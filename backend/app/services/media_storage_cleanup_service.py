"""Filesystem and setting cleanup helpers for deleted media and collections."""

from __future__ import annotations

import errno
import logging
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import or_
from sqlmodel import Session, delete, select

from app.media_paths import (
    audio_filename_candidates,
    logical_audio_media_path,
    logical_photo_media_path,
    media_root,
    normalize_media_relative_path,
    preview_basename,
    preview_relative_candidates,
    resolve_media_storage_collection_id,
)
from app.models import AudioSetting, Media, MediaCollection, PhotoSetting, Preview
from app.services import collection_bundle_export_service
from app.services import detail_cache_service as detail_cache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MediaCleanupSnapshot:
    """Immutable metadata captured before a media row is deleted from the database."""

    media_id: int
    media_type: str
    directory: int | None
    filename: str | None
    storage_collection_id: int | None
    collection_ids: tuple[int, ...]
    previews: tuple[tuple[str | None, str], ...]
    audio_setting_id: int | None
    photo_setting_id: int | None


@dataclass(frozen=True)
class _DirectoryReferences:
    audio_filenames: frozenset[str]
    audio_stems: frozenset[str]
    photo_filenames: frozenset[str]
    photo_stems: frozenset[str]
    preview_filenames: frozenset[str]


def build_media_cleanup_snapshot(
    media: Media,
    *,
    collection_ids: Iterable[int] | None = None,
    previews: Iterable[Preview] | None = None,
) -> MediaCleanupSnapshot:
    """Capture media file and preview coordinates before database deletion."""
    resolved_collection_ids = (
        tuple(sorted({cid for cid in collection_ids if cid is not None}))
        if collection_ids is not None
        else tuple(sorted({mc.collection_id for mc in (media.media_collections or [])}))
    )
    preview_rows = list(previews) if previews is not None else list(media.previews or [])
    resolved_previews = tuple(
        (preview.type, preview.filename)
        for preview in preview_rows
        if preview.filename
    )
    return MediaCleanupSnapshot(
        media_id=media.media_id,
        media_type=media.media_type,
        directory=media.directory,
        filename=media.filename,
        storage_collection_id=media.storage_collection_id,
        collection_ids=resolved_collection_ids,
        previews=resolved_previews,
        audio_setting_id=media.audio_setting_id,
        photo_setting_id=media.photo_setting_id,
    )


def delete_unreferenced_media_settings(
    session: Session,
    *,
    audio_setting_ids: Iterable[int | None] = (),
    photo_setting_ids: Iterable[int | None] = (),
) -> None:
    """Delete AudioSetting and PhotoSetting rows no longer referenced by any Media."""
    unique_audio_ids = {sid for sid in audio_setting_ids if sid is not None}
    if unique_audio_ids:
        referenced_audio_ids = set(
            session.exec(
                select(Media.audio_setting_id).where(
                    Media.audio_setting_id.in_(unique_audio_ids)
                )
            ).all()
        )
        orphan_audio_ids = unique_audio_ids - referenced_audio_ids
        if orphan_audio_ids:
            session.exec(
                delete(AudioSetting).where(AudioSetting.audio_setting_id.in_(orphan_audio_ids))
            )

    unique_photo_ids = {sid for sid in photo_setting_ids if sid is not None}
    if unique_photo_ids:
        referenced_photo_ids = set(
            session.exec(
                select(Media.photo_setting_id).where(
                    Media.photo_setting_id.in_(unique_photo_ids)
                )
            ).all()
        )
        orphan_photo_ids = unique_photo_ids - referenced_photo_ids
        if orphan_photo_ids:
            session.exec(
                delete(PhotoSetting).where(PhotoSetting.photo_setting_id.in_(orphan_photo_ids))
            )


def _is_safe_basename(filename: str | None) -> bool:
    if not filename:
        return False
    stripped = filename.strip()
    if not stripped or stripped in {".", ".."}:
        return False
    return "/" not in stripped and "\\" not in stripped


def _has_symlink_component(path: Path, boundary: Path) -> bool:
    current = path
    resolved_boundary = boundary.resolve()
    while True:
        if current.is_symlink():
            return True
        if current == boundary or current.resolve() == resolved_boundary:
            return False
        parent = current.parent
        if parent == current:
            return True
        current = parent


def _safe_storage_file(relative_path: Path) -> Path | None:
    """Return an existing regular file strictly contained under media_root()."""
    try:
        normalized = normalize_media_relative_path(relative_path)
    except ValueError:
        return None
    if normalized is None or str(normalized).startswith("http"):
        return None

    root = media_root()
    candidate = root / normalized
    try:
        if not candidate.exists() or candidate.is_symlink() or not candidate.is_file():
            return None
        if _has_symlink_component(candidate, root):
            return None
        if not candidate.resolve().is_relative_to(root.resolve()):
            return None
    except OSError:
        return None
    return candidate


def _unlink_file_safe(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        logger.warning("Could not delete media storage file: %s", path, exc_info=True)
        return False


def _prune_empty_dirs(start_dir: Path, stop_at: Path) -> None:
    """Remove empty parent directories upward without removing stop_at itself."""
    if not stop_at.exists() or not detail_cache.safe_directory(stop_at, media_root()):
        return

    resolved_stop = stop_at.resolve()
    current = start_dir
    while True:
        if not current.exists() or not detail_cache.safe_directory(current, stop_at):
            return
        if current.resolve() == resolved_stop:
            return
        try:
            current.rmdir()
        except OSError as exc:
            if exc.errno not in (errno.ENOTEMPTY, errno.ENOENT):
                logger.warning("Could not prune empty media directory: %s", current, exc_info=True)
            return
        parent = current.parent
        if parent == current:
            return
        current = parent


def _remove_collection_root_dir(
    category: Literal["sounds", "images"],
    collection_id: int,
) -> None:
    """Safely remove sounds/<collection_id> or images/<collection_id>."""
    category_root = media_root() / category
    if not category_root.exists() or not detail_cache.safe_directory(category_root, media_root()):
        return
    target = category_root / str(collection_id)
    if not target.exists() or not detail_cache.safe_directory(target, category_root):
        return
    try:
        shutil.rmtree(target)
    except OSError:
        logger.warning("Could not remove collection directory: %s", target, exc_info=True)


def _directory_filter_clause(directory: int | None):
    if directory:
        return Media.directory == directory
    return or_(Media.directory.is_(None), Media.directory == 0)


def _collect_remaining_directory_references(
    session: Session,
    storage_collection_id: int,
    directory: int | None,
) -> _DirectoryReferences:
    """Collect filenames still referenced by surviving media in the same storage directory."""
    fallback_media_subquery = select(MediaCollection.media_id).where(
        MediaCollection.collection_id == storage_collection_id
    )
    remaining_rows = session.exec(
        select(Media.media_id, Media.media_type, Media.filename).where(
            _directory_filter_clause(directory),
            or_(
                Media.storage_collection_id == storage_collection_id,
                (Media.storage_collection_id.is_(None))
                & (Media.media_id.in_(fallback_media_subquery)),
            ),
        )
    ).all()

    if not remaining_rows:
        return _DirectoryReferences(
            audio_filenames=frozenset(),
            audio_stems=frozenset(),
            photo_filenames=frozenset(),
            photo_stems=frozenset(),
            preview_filenames=frozenset(),
        )

    remaining_media_ids: list[int] = []
    audio_filenames: set[str] = set()
    audio_stems: set[str] = set()
    photo_filenames: set[str] = set()
    photo_stems: set[str] = set()

    for media_id, media_type, filename in remaining_rows:
        remaining_media_ids.append(media_id)
        if not filename:
            continue
        if media_type == "audio":
            audio_filenames.update(audio_filename_candidates(filename))
            audio_stems.add(Path(filename).stem)
        elif media_type == "photo":
            photo_filenames.add(filename)
            photo_stems.add(Path(filename).stem)

    preview_rows = session.exec(
        select(Preview.filename).where(Preview.media_id.in_(remaining_media_ids))
    ).all()
    preview_filenames = {
        name for raw in preview_rows if (name := preview_basename(raw)) is not None
    }

    return _DirectoryReferences(
        audio_filenames=frozenset(audio_filenames),
        audio_stems=frozenset(audio_stems),
        photo_filenames=frozenset(photo_filenames),
        photo_stems=frozenset(photo_stems),
        preview_filenames=frozenset(preview_filenames),
    )


def _cleanup_snapshot_in_bucket(
    session: Session,
    snapshot: MediaCleanupSnapshot,
    bucket_id: int,
) -> int:
    refs = _collect_remaining_directory_references(session, bucket_id, snapshot.directory)
    dir_token = str(snapshot.directory or "")
    deleted_files = 0
    seen_targets: set[Path] = set()

    def _delete_relative(relative: Path) -> None:
        nonlocal deleted_files
        safe_path = _safe_storage_file(relative)
        if safe_path is None or safe_path in seen_targets:
            return
        seen_targets.add(safe_path)
        if _unlink_file_safe(safe_path):
            deleted_files += 1

    # 1. Primary media binary file(s)
    if _is_safe_basename(snapshot.filename):
        assert snapshot.filename is not None
        if snapshot.media_type == "audio":
            for candidate in audio_filename_candidates(snapshot.filename):
                if candidate in refs.audio_filenames or not _is_safe_basename(candidate):
                    continue
                _delete_relative(logical_audio_media_path(bucket_id, dir_token, candidate))
        elif snapshot.media_type == "photo":
            if snapshot.filename not in refs.photo_filenames:
                _delete_relative(logical_photo_media_path(bucket_id, dir_token, snapshot.filename))

    # 2. Explicit Preview records captured before deletion
    for preview_type, raw_preview_name in snapshot.previews:
        name = preview_basename(raw_preview_name)
        if not _is_safe_basename(name) or name in refs.preview_filenames:
            continue
        assert name is not None
        candidate_paths = list(
            preview_relative_candidates(
                collection_id=bucket_id,
                directory=snapshot.directory,
                media_type=snapshot.media_type,
                preview_type=preview_type,
                filename=name,
            )
        )
        for category in ("sounds", "images"):
            alt = Path(category) / str(bucket_id) / dir_token / name
            if alt not in candidate_paths:
                candidate_paths.append(alt)
        for candidate_path in candidate_paths:
            if candidate_path.parts[0] == "sounds" and name in refs.audio_filenames:
                continue
            if candidate_path.parts[0] == "images" and name in refs.photo_filenames:
                continue
            _delete_relative(candidate_path)

    # 3. Standard derived preview filenames in case Preview DB rows were absent
    if _is_safe_basename(snapshot.filename):
        assert snapshot.filename is not None
        stem = Path(snapshot.filename).stem
        if snapshot.media_type == "audio" and stem not in refs.audio_stems:
            thumb_name = f"{stem}_thumbnail.png"
            if thumb_name not in refs.preview_filenames and thumb_name not in refs.audio_filenames:
                _delete_relative(Path("sounds") / str(bucket_id) / dir_token / thumb_name)
            player_name = f"{stem}_player_s.png"
            if player_name not in refs.preview_filenames and player_name not in refs.photo_filenames:
                _delete_relative(Path("images") / str(bucket_id) / dir_token / player_name)
        elif snapshot.media_type == "photo" and stem not in refs.photo_stems:
            thumb_name = f"{stem}_thumbnail.png"
            if thumb_name not in refs.preview_filenames and thumb_name not in refs.photo_filenames:
                _delete_relative(Path("images") / str(bucket_id) / dir_token / thumb_name)

    # 4. Prune empty directories upward (keeping sounds/ and images/ roots intact)
    sounds_root = media_root() / "sounds"
    images_root = media_root() / "images"
    sounds_dir = sounds_root / str(bucket_id) / dir_token if dir_token else sounds_root / str(bucket_id)
    images_dir = images_root / str(bucket_id) / dir_token if dir_token else images_root / str(bucket_id)
    _prune_empty_dirs(sounds_dir, sounds_root)
    _prune_empty_dirs(images_dir, images_root)

    return deleted_files


def cleanup_deleted_media_files(
    session: Session,
    snapshot: MediaCleanupSnapshot,
) -> int:
    """Clean up physical media files, previews, empty dirs, and detail cache after commit."""
    bucket_ids: list[int]
    if snapshot.storage_collection_id is not None:
        bucket_ids = [snapshot.storage_collection_id]
    else:
        bucket_ids = sorted(set(snapshot.collection_ids))

    deleted_files = 0
    for bucket_id in bucket_ids:
        deleted_files += _cleanup_snapshot_in_bucket(session, snapshot, bucket_id)

    detail_cache.remove_media_cache(snapshot.media_id)
    if deleted_files:
        logger.info(
            "Cleaned up %d storage file(s) for deleted media_id=%s",
            deleted_files,
            snapshot.media_id,
        )
    return deleted_files


def cleanup_deleted_collection_storage(
    session: Session,
    collection_id: int,
    exclusive_snapshots: Sequence[MediaCleanupSnapshot],
    export_paths: Iterable[str | None] = (),
) -> None:
    """Clean up files and export bundles after a collection and its exclusive media are committed deleted."""
    for export_path in export_paths:
        try:
            collection_bundle_export_service.remove_artifact_path(export_path)
        except OSError:
            logger.warning(
                "Could not remove collection bundle export artifact %s for collection_id=%s",
                export_path,
                collection_id,
                exc_info=True,
            )

    has_remaining_storage_refs = (
        session.exec(
            select(Media.media_id)
            .where(Media.storage_collection_id == collection_id)
            .limit(1)
        ).first()
        is not None
    )

    if has_remaining_storage_refs:
        # Surviving shared media still reads from sounds/<collection_id> and images/<collection_id>.
        # Remove only the deleted exclusive media files and prune empty subdirectories.
        for snapshot in exclusive_snapshots:
            cleanup_deleted_media_files(session, snapshot)
        return

    for snapshot in exclusive_snapshots:
        resolved_bucket = resolve_media_storage_collection_id(
            snapshot.storage_collection_id,
            snapshot.collection_ids,
        )
        if resolved_bucket is not None and resolved_bucket != collection_id:
            cleanup_deleted_media_files(session, snapshot)
        else:
            detail_cache.remove_media_cache(snapshot.media_id)

    _remove_collection_root_dir("sounds", collection_id)
    _remove_collection_root_dir("images", collection_id)
