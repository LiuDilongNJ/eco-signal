"""Maintenance tasks for system cleanup."""
import asyncio
import logging
import shutil
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from app.api.deps import get_redis_client
from app.core.config import settings
from app.core.db import engine
from app.media_paths import logical_chunk_dir_path, media_root
from app.models import FileUpload
from app.repositories import collection_bundle_export_repository
from app.repositories.file_upload_repository import file_upload_repository
from app.services import detail_cache_service as detail_cache
from app.services.data_import_service import data_import_service

logger = logging.getLogger(__name__)


async def cleanup_expired_chunks(
        ctx: dict[str, Any],
        max_age_hours: int = 24,
) -> dict[str, Any]:
    """
    定时清理过期的上传 chunks。
    
    Args:
        ctx: ARQ context
        max_age_hours: 文件最大保留时间（小时），默认24小时
    
    Returns:
        清理结果
    """
    del ctx
    chunks_dir = media_root() / logical_chunk_dir_path("placeholder").parent
    if not chunks_dir.exists():
        logger.info("No chunks directory found, skipping cleanup")
        return {"deleted": 0}
    
    now = time.time()
    max_age_seconds = max_age_hours * 3600
    deleted_count = 0
    
    # 遍历 batch_id 目录
    for batch_dir in chunks_dir.iterdir():
        if batch_dir.is_dir():
            for file_dir in batch_dir.iterdir():
                if file_dir.is_dir():
                    # 检查目录修改时间
                    mtime = file_dir.stat().st_mtime
                    if now - mtime > max_age_seconds:
                        shutil.rmtree(file_dir)
                        deleted_count += 1
                        logger.info(f"Deleted expired chunk directory: {file_dir}")
            
            # 清理空的 batch 目录
            if batch_dir.exists() and not any(batch_dir.iterdir()):
                batch_dir.rmdir()
                logger.info(f"Deleted empty batch directory: {batch_dir}")
    
    logger.info(f"Cleanup completed: deleted {deleted_count} expired chunk directories")
    return {"deleted": deleted_count}


async def cleanup_expired_offline_imports(ctx: dict[str, Any]) -> dict[str, Any]:
    """Delete expired failed offline bundle zip files."""
    del ctx
    deleted = 0
    async for redis in get_redis_client():
        keys = await data_import_service.list_context_keys(redis)
        with Session(engine) as session:
            for key in keys:
                batch_id = key.rsplit(":", 1)[-1]
                context = await data_import_service.get_context(redis, batch_id)
                if context is None or context.get("status") != "failed" or not context.get("cleanup_after"):
                    continue
                cleanup_after = datetime.strptime(
                    context["cleanup_after"],
                    "%Y-%m-%d %H:%M:%S",
                ).replace(tzinfo=UTC)
                if cleanup_after > datetime.now(UTC):
                    continue
                file_upload_id = context.get("file_upload_id")
                if file_upload_id:
                    file_upload = session.get(FileUpload, file_upload_id)
                    if file_upload and file_upload.path:
                        bundle_path = media_root() / file_upload.path
                        if bundle_path.exists():
                            bundle_path.unlink()
                            deleted += 1
                        file_upload.path = ""
                        session.add(file_upload)
                        session.commit()
                await redis.delete(key)
        break
    logger.info("Offline import cleanup completed: deleted=%d", deleted)
    return {"deleted": deleted}


async def cleanup_expired_collection_bundle_exports(ctx: dict[str, Any]) -> dict[str, Any]:
    """Delete expired collection bundle files while retaining their audit records."""
    del ctx
    now = datetime.now(UTC).replace(tzinfo=None)
    deleted = 0
    with Session(engine) as session:
        records = collection_bundle_export_repository.list_expired(session, now)
        for record in records:
            if record.path:
                target = (media_root() / record.path).resolve()
                root = media_root().resolve()
                if target.is_relative_to(root) and target.is_file():
                    target.unlink()
                    deleted += 1
            record.status = "expired"
            record.path = None
            session.add(record)
        session.commit()
    logger.info("Collection bundle export cleanup completed: deleted=%d", deleted)
    return {"deleted": deleted}


async def sync_network_nodes(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Daily sync: if this instance is a child node (host_url is configured),
    fetch the full node list from HOST and update the local network_node table.

    Runs daily at 2:00 AM (registered in workers/config.py).
    If this instance is the HOST (no host_url configured), exits silently.
    """
    del ctx
    from app.services import network_service

    with Session(engine) as session:
        result = network_service.sync_from_host(session)

    logger.info(
        "Network sync completed: synced=%d message=%s",
        result.synced,
        result.message,
    )
    return {"synced": result.synced, "message": result.message}


async def startup_sync_network_nodes(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Startup sync: run once when worker starts.

    Reuses the same child-node sync logic as the scheduled task, but logs
    trigger=startup for easier operational tracing.
    """
    del ctx
    from app.services import network_service

    logger.info("Network sync started: trigger=startup")
    try:
        with Session(engine) as session:
            result = network_service.sync_from_host(session)
    except Exception:  # noqa: BLE001
        logger.exception("Network sync failed: trigger=startup")
        return {"synced": 0, "message": "startup sync failed"}

    logger.info(
        "Network sync completed: trigger=startup synced=%d message=%s",
        result.synced,
        result.message,
    )
    return {"synced": result.synced, "message": result.message}


def _cleanup_pending_files() -> dict[str, int]:
    pending = media_root() / "tmp" / "pending"
    result = {"deleted": 0, "freed_bytes": 0, "skipped_locked": 0, "errors": 0}
    if not detail_cache.safe_directory(pending, media_root()):
        return result
    cutoff = time.time() - settings.PENDING_FILE_TTL_SECONDS
    try:
        with Session(engine) as session:
            for user_dir in pending.iterdir():
                if not detail_cache.safe_directory(user_dir, pending):
                    continue
                for path in user_dir.iterdir():
                    try:
                        if path.is_symlink() or not path.is_file() or path.stat().st_mtime >= cutoff:
                            continue
                        with detail_cache.pending_lock(path, timeout=0):
                            relative = path.relative_to(media_root()).as_posix()
                            if file_upload_repository.is_path_referenced(session, relative):
                                continue
                            if path.stat().st_mtime >= cutoff:
                                continue
                            size = path.stat().st_size
                            path.unlink()
                            result["deleted"] += 1
                            result["freed_bytes"] += size
                    except detail_cache.CacheLockTimeout:
                        result["skipped_locked"] += 1
                    except FileNotFoundError:
                        continue
                    except OSError:
                        result["errors"] += 1
                        logger.exception("Could not remove pending upload: %s", path)
    except Exception:
        result["errors"] += 1
        logger.exception("Pending upload cleanup unavailable")
    logger.info("Pending upload cleanup completed: %s", result)
    return result


async def cleanup_audio_assets(ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    cache_result = await asyncio.to_thread(detail_cache.cleanup)
    pending_result = await asyncio.to_thread(_cleanup_pending_files)
    return {"detail": asdict(cache_result), "pending": pending_result}
