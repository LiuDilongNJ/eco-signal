"""
Hybrid media storage: an S3-compatible bucket as the source of truth with a
per-service local cache.

Each service (backend, worker, worker-analysis) keeps its own local cache under
``MEDIA_ROOT``. Files are read through :func:`ensure_local` (cache-miss fetches
from S3) and written locally first (so ffmpeg/sox/mutagen/atomic ``replace``
keep working unchanged) then pushed to S3 via :func:`upload`.

When ``MEDIA_S3_MODE`` is ``local`` (the default), every operation is a
no-op passthrough and the service behaves exactly as before.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any
import os

from app.core.config import settings
from app.media_paths import media_root

# See https://stackoverflow.com/a/79501762/9943464
logging.basicConfig()

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

# Sidecar directory (hidden) that stores per-file S3 metadata (etag + mtime).
# Kept out of the media tree's normal listings so chunk counting and globs are
# unaffected.
_META_DIRNAME = ".s3meta"


def _s3_enabled() -> bool:
    return settings.media_storage_is_s3


def _client() -> Any:
    """Lazily build a boto3 S3 client. Imported here so boto3 is only needed
    when S3 mode is actually enabled."""
    import boto3  # type: ignore[import-untyped]

    kwargs: dict[str, object] = {
        "region_name": settings.S3_REGION or None,
    }
    if settings.S3_ENDPOINT:
        kwargs["endpoint_url"] = settings.S3_ENDPOINT
    if settings.S3_ACCESS_KEY and settings.S3_SECRET_KEY:
        kwargs["aws_access_key_id"] = settings.S3_ACCESS_KEY
        kwargs["aws_secret_access_key"] = settings.S3_SECRET_KEY
    return boto3.client("s3", **kwargs)


def _root() -> Path:
    """Resolved media root, used as the base for S3 keys and meta paths so the
    math works whether ``MEDIA_ROOT`` is absolute or relative."""
    return media_root().resolve()


def _meta_path(local_path: Path) -> Path:
    return (
        _root()
        / _META_DIRNAME
        / (str(local_path.resolve().relative_to(_root())) + ".json")
    )


def _read_meta(local_path: Path) -> dict[str, object] | None:
    meta = _meta_path(local_path)
    if not meta.is_file():
        return None
    try:
        return json.loads(meta.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError):
        return None


def _write_meta(local_path: Path, etag: str) -> None:
    meta = _meta_path(local_path)
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(json.dumps({"etag": etag, "mtime": time.time()}), encoding="utf-8")


def _delete_meta(local_path: Path) -> None:
    _meta_path(local_path).unlink(missing_ok=True)


def _key_for(local_path: Path) -> str:
    return local_path.resolve().relative_to(_root()).as_posix()


def _is_fresh(local_path: Path) -> bool:
    """A local file is fresh if it has no S3 metadata (written locally, not yet
    synced) or its recorded etag/mtime is within the cache TTL."""
    meta = _read_meta(local_path)
    if meta is None:
        return True
    ttl = settings.MEDIA_CACHE_TTL
    if ttl <= 0:
        return False
    mtime = meta.get("mtime")
    if not isinstance(mtime, (int, float)):
        return True
    return (time.time() - mtime) < ttl


def ensure_local(local_path: Path) -> Path:
    """Make sure ``local_path`` (a file or directory under MEDIA_ROOT) reflects
    the current S3 state, fetching any missing/stale entries into the local
    cache. Returns the local path.

    - File: if missing or stale, download from S3. If absent in S3, leave the
      local file as-is (it may be a pending local write).
    - Directory: download every S3 object under the prefix that is missing
      locally, and remove local files that no longer exist in S3.
    """
    if not _s3_enabled():
        return local_path

    local_path = local_path.resolve()
    if local_path.is_dir():
        _ensure_dir(local_path)
        return local_path
    _ensure_file(local_path)
    return local_path


def ensure_local_dir(local_path: Path) -> Path:
    """Make sure a directory and all objects under its S3 prefix are cached locally."""
    if not _s3_enabled():
        return local_path

    local_path = local_path.resolve()
    _ensure_dir(local_path)
    return local_path


def _s3_object_missing(exc: Exception) -> bool:
    """True when the S3 error means the object does not exist (404/NoSuchKey),
    as opposed to a transient network/auth error."""
    try:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover - boto3 is a hard dep in s3 mode
        return False
    if not isinstance(exc, ClientError):
        return False
    code = str(exc.response.get("Error", {}).get("Code", ""))
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"404", "NoSuchKey"} or status == 404


def _ensure_file(local_path: Path) -> None:
    if local_path.is_file() and _is_fresh(local_path):
        return
    client = _client()
    key = _key_for(local_path)
    try:
        head = client.head_object(Bucket=settings.S3_BUCKET, Key=key)
    except Exception as exc:  # noqa: BLE001
        if _s3_object_missing(exc) and local_path.is_file():
            # Another service deleted the object; drop the stale local copy so
            # it is not served. Transient errors keep the local state.
            logger.debug(
                "S3 object %s deleted remotely; dropping stale local copy", key
            )
            local_path.unlink(missing_ok=True)
            _delete_meta(local_path)
        else:
            logger.debug("S3 lookup failed for %s; keeping local state", key)
        return
    etag = str(head.get("ETag", "")).strip('"')
    meta = _read_meta(local_path)
    if local_path.is_file() and etag and meta and meta.get("etag") == etag:
        # Same content already cached; just refresh the freshness marker.
        _write_meta(local_path, etag)
        return
    local_path.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(settings.S3_BUCKET, key, str(local_path))
    _write_meta(local_path, etag)


def _ensure_dir(local_path: Path) -> None:
    logger.debug("Ensuring local directory %s is up-to-date with S3", local_path)
    client = _client()
    prefix = _key_for(local_path) + "/"
    logger.debug("Listing S3 objects under prefix %s", prefix)
    remote_keys: set[str] = set()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            logger.debug("Found S3 object %s", key)
            if key.endswith("/"):
                continue
            remote_keys.add(key)
            rel = key[len(prefix) :]
            logger.debug(
                "Ensuring local file %s is up-to-date with S3", local_path / rel
            )
            _ensure_file(local_path / rel)
    # Remove local files that no longer exist in S3 (best-effort cleanup).
    logger.debug(
        "Cleaning up local files under %s that no longer exist in S3", local_path
    )
    for local_file in local_path.rglob("*"):
        if local_file.is_file():
            key = _key_for(local_file)
            if key not in remote_keys:
                local_file.unlink(missing_ok=True)
                _delete_meta(local_file)


def upload(local_path: Path) -> None:
    """Upload a local file to S3 and record its etag in the local cache."""
    if not _s3_enabled():
        return
    local_path = local_path.resolve()
    if not local_path.is_file():
        return
    client = _client()
    key = _key_for(local_path)
    client.upload_file(str(local_path), settings.S3_BUCKET, key)
    try:
        head = client.head_object(Bucket=settings.S3_BUCKET, Key=key)
        etag = str(head.get("ETag", "")).strip('"')
    except Exception:  # noqa: BLE001
        etag = ""
    _write_meta(local_path, etag)


def delete(local_path: Path) -> None:
    """Delete a local file and its S3 object."""
    if not _s3_enabled():
        return
    local_path = local_path.resolve()
    client = _client()
    key = _key_for(local_path)
    try:
        client.delete_object(Bucket=settings.S3_BUCKET, Key=key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to delete S3 object %s: %s", key, exc)
    local_path.unlink(missing_ok=True)
    _delete_meta(local_path)


def delete_dir(local_path: Path) -> None:
    """Delete a local directory tree and all S3 objects under its prefix."""
    if not _s3_enabled():
        return
    local_path = local_path.resolve()
    client = _client()
    prefix = _key_for(local_path) + "/"
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=settings.S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    for i in range(0, len(keys), 1000):
        batch = [{"Key": k} for k in keys[i : i + 1000]]
        try:
            client.delete_objects(Bucket=settings.S3_BUCKET, Delete={"Objects": batch})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to delete S3 objects under %s: %s", prefix, exc)
    for local_file in local_path.rglob("*"):
        if local_file.is_file():
            _delete_meta(local_file)


def invalidate_local(local_path: Path) -> None:
    """Drop the local cache entry (and its metadata) so the next read re-fetches
    from S3. Used after a local rewrite that should not be re-uploaded."""
    if not _s3_enabled():
        return
    local_path = local_path.resolve()
    if local_path.is_file():
        local_path.unlink(missing_ok=True)
        _delete_meta(local_path)
