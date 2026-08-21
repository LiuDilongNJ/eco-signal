import fcntl
import hashlib
import itertools
import json
import logging
import math
import os
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import soundfile as sf
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.csv_export import CsvColumn, export_columns_csv
from app.csv_import import (
    CsvImportResult,
    CsvImportRowResult,
    effective_header_width,
    ensure_row_width,
    parse_csv,
    read_cell,
    resolve_header_positions,
)
from app.enums import MediaType, QueueStatus, WorkerTaskType
from app.media_paths import (
    build_media_public_url,
    logical_photo_media_path,
    media_root,
    resolve_existing_audio_media_path,
    resolve_existing_media_path,
)
from app.models import (
    AudioSetting,
    Collection,
    FileUpload,
    License,
    Media,
    MediaCollection,
    PhotoSetting,
    ProjectCollection,
    Queue,
    Sensor,
    Setting,
    Site,
    User,
    UserPreference,
)
from app.models.media import Preview
from app.models.project import Project
from app.repositories import media_repository, permission_repository, project_repository, user_repository
from app.repositories.collection_scope import resolve_project_collection_scope
from app.schemas.media import (
    MediaBatchFailedItem,
    MediaBatchOperationResponse,
    MediaBrowseGalleryItem,
    MediaBrowseListItem,
    MediaCollectionLinkOptionsResponse,
    MediaCreate,
    MediaCreateFailedItem,
    MediaCreateResponse,
    MediaListPublic,
    MediaNavigation,
    MediaNavigationItem,
    MediaOption,
    MediaPublic,
    MediaTimelineItem,
    MediaTimelineRange,
    MediaTimelineResponse,
    MediaUpdate,
    PhotoSettingPublic,
    PreviewPublic,
)
from app.schemas.response import ApiResponse, PagedApiResponse, api_page
from app.services import permission_service
from app.spectrogram import (
    DETAIL_DEFAULT_FFT_SIZE,
    DETAIL_DEFAULT_MIN_FREQ,
    build_sox_sinc_frequency_spec,
    generate_spectrogram_png,
)
from app.workers.publisher import TaskPublisher

logger = logging.getLogger(__name__)

PLAYER_SPECTROGRAM_TYPE = "spectrogram"
PLAYER_SPECTROGRAM_SUFFIX = "_player_s.png"
_DETAIL_ASSET_DIR = Path("tmp") / "detail"
_DETAIL_ASSET_TTL = timedelta(hours=12)
_DETAIL_ASSET_LOCK_TIMEOUT_SECONDS = 60.0
_DETAIL_ASSET_LOCK_SHARDS = 1024
_DETAIL_ASSET_MANIFEST_VERSION = 3
_DETAIL_ASSET_MANIFEST_FILENAME = "manifest.json"
_DETAIL_ASSET_ACCESS_FILENAME = ".last_access"
_DETAIL_PARAM_PRECISION = 4
_SOX_TIMEOUT_SECONDS = 300


def _media_source_csv_value(media: Any) -> str:
    return "metadata" if media.is_metadata else "file"


# Importable fields share the same headers as the metadata import template so
# an exported file can be re-imported directly.
_AUDIO_EXPORT_COLUMNS = [
    CsvColumn("media_id"), CsvColumn("uuid"), CsvColumn("media_type"),
    CsvColumn("type", _media_source_csv_value), CsvColumn("name"), CsvColumn("filename"),
    CsvColumn("site_name"), CsvColumn("sensor_name"), CsvColumn("medium"),
    CsvColumn("sampling_rate_hz", "audio_setting.sampling_rate_hz"), CsvColumn("bit_depth", "audio_setting.bit_depth"),
    CsvColumn("channel_num", "audio_setting.channel_num"), CsvColumn("duration_s", "audio_setting.duration_s"),
    CsvColumn("size_b"), CsvColumn("recording_gain_db", "audio_setting.recording_gain_db"),
    CsvColumn("duty_cycle_recording"), CsvColumn("duty_cycle_period"),
    CsvColumn("license_name"), CsvColumn("doi"), CsvColumn("note"),
    CsvColumn("uploader_name"), CsvColumn("uploader_id"),
    CsvColumn("creator_name"), CsvColumn("creator_id"),
    CsvColumn("date_time"),
]

_PHOTO_EXPORT_COLUMNS = [
    CsvColumn("media_id"), CsvColumn("uuid"), CsvColumn("type", _media_source_csv_value),
    CsvColumn("name"), CsvColumn("filename"), CsvColumn("site_name"),
    CsvColumn("sensor_name"), CsvColumn("medium"), CsvColumn("image_width"),
    CsvColumn("image_height"), CsvColumn("exposure_ms", "photo_setting.exposure_ms"),
    CsvColumn("aperture", "photo_setting.aperture"), CsvColumn("iso", "photo_setting.iso"), CsvColumn("size_b"),
    CsvColumn("license_name"), CsvColumn("doi"), CsvColumn("note"),
    CsvColumn("uploader_name"), CsvColumn("uploader_id"),
    CsvColumn("creator_name"), CsvColumn("creator_id"), CsvColumn("date_time"),
]

# Metadata import columns: internal field key -> CSV header (matches the export
# headers above so exported files re-import without editing).
_AUDIO_METADATA_CSV_FIELD_HEADERS: dict[str, str] = {
    "date_time": "date_time", "duration_s": "duration_s", "sampling_rate": "sampling_rate_hz",
    "name": "name", "bit_depth": "bit_depth", "channel_num": "channel_num",
    "duty_cycle_recording": "duty_cycle_recording", "duty_cycle_period": "duty_cycle_period",
}

_AUDIO_METADATA_CSV_REQUIRED_FIELDS: tuple[str, ...] = (
    "date_time",
    "duration_s",
    "sampling_rate",
)

_PHOTO_METADATA_CSV_FIELD_HEADERS: dict[str, str] = {
    "date_time": "date_time", "name": "name", "exposure_ms": "exposure_ms",
    "aperture": "aperture", "iso": "iso",
}

_PHOTO_METADATA_CSV_REQUIRED_FIELDS: tuple[str, ...] = ("date_time",)

# Extra display columns from the export sets, tolerated (ignored) on import so
# exported CSV files can be re-imported without manual editing.
_AUDIO_METADATA_CSV_IGNORED_KEYS: frozenset[str] = frozenset(
    column.header.lower() for column in _AUDIO_EXPORT_COLUMNS
) - {header.lower() for header in _AUDIO_METADATA_CSV_FIELD_HEADERS.values()}

_PHOTO_METADATA_CSV_IGNORED_KEYS: frozenset[str] = frozenset(
    column.header.lower() for column in _PHOTO_EXPORT_COLUMNS
) - {header.lower() for header in _PHOTO_METADATA_CSV_FIELD_HEADERS.values()}

_METADATA_RECORDING_START_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y/%m/%dT%H:%M:%S",
    "%Y/%m/%dT%H:%M",
)
_METADATA_RECORDING_START_FORMAT_HELP = (
    "YYYY-MM-DD HH:MM[:SS], YYYY/MM/DD HH:MM[:SS], "
    "YYYY-MM-DDTHH:MM[:SS], YYYY/MM/DDTHH:MM[:SS]"
)
_LEGACY_FILENAME_DATETIME_FALLBACK = "1970-01-01 00:00:00"


def _filename_datetime_warning(filenames: list[str]) -> str | None:
    if not filenames:
        return None
    joined_filenames = ", ".join(filenames)
    return (
        "Date/time could not be extracted from the filename for: "
        f"{joined_filenames}. Default date/time {_LEGACY_FILENAME_DATETIME_FALLBACK} was used."
    )


def _build_display_filename(original_name: str, filename_prefix: str) -> str:
    """Build the logical stored filename using the current naming rules."""
    base_name = original_name.strip()
    if not base_name:
        return filename_prefix
    if not filename_prefix:
        return base_name
    return f"{filename_prefix}{base_name}"


def _metadata_csv_row_error_message(
    row: int,
    col_key: str | None,
    col_one: int | None,
    detail: str,
) -> str:
    if col_one is not None and col_key:
        msg = f"Row {row}, column {col_one} ({col_key}): {detail}"
    elif col_one is not None:
        msg = f"Row {row}, column {col_one}: {detail}"
    else:
        msg = f"Row {row}: {detail}"
    return msg


def _parse_metadata_recording_start(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    for fmt in _METADATA_RECORDING_START_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def parse_timeline_site_ids(site_ids: str | None) -> list[int] | None:
    """Parse comma-separated site IDs for timeline filtering."""
    if not site_ids:
        return None

    parsed_ids: list[int] = []
    for raw in site_ids.split(","):
        token = raw.strip()
        if not token:
            continue
        if not token.isdigit():
            raise HTTPException(
                status_code=400,
                detail="site_ids must be a comma-separated list of integers",
            )
        parsed_ids.append(int(token))

    return parsed_ids or None


def _preview_basename(filename: str | None) -> str | None:
    """Return the preview basename using the current storage rules."""
    if not filename:
        return None
    raw = str(filename).replace("\\", "/").strip()
    if not raw:
        return None
    name = Path(raw).name.strip()
    return name or None


def _preview_relative_candidates(
    *,
    collection_id: int,
    directory: int | None,
    media_type: str | None,
    preview_type: str | None,
    filename: str,
) -> list[Path]:
    dir_token = str(directory or "")
    normalized_type = (preview_type or "").strip().lower()
    # Audio thumbnails remain alongside recordings; photo thumbnails live with image media.
    if normalized_type in {"spectrogram", "waveform", PLAYER_SPECTROGRAM_TYPE}:
        category = "images"
    elif normalized_type == "thumbnail":
        category = "images" if media_type == "photo" else "sounds"
    else:
        category = "images"
    return [Path(category) / str(collection_id) / dir_token / filename]


def _build_preview_public_url(media: Media, preview) -> str | None:
    """
    Build a preview URL from the stored preview metadata.

    Stored preview.filename keeps basename only; actual access path derives from
    collection + directory with type-based category priority.
    """
    filename = _preview_basename(preview.filename)
    if not filename:
        logger.warning(
            "Preview URL resolution failed: empty filename",
            extra={
                "media_id": media.media_id,
                "preview_id": preview.preview_id,
                "filename": preview.filename,
                "tried_paths": [],
            },
        )
        return None

    collection_ids = sorted({mc.collection_id for mc in (media.media_collections or [])})
    if not collection_ids:
        logger.warning(
            "Preview URL resolution failed: media has no collection links",
            extra={
                "media_id": media.media_id,
                "preview_id": preview.preview_id,
                "filename": preview.filename,
                "tried_paths": [],
            },
        )
        return None

    rel = _preview_relative_candidates(
        collection_id=collection_ids[0],
        directory=media.directory,
        media_type=media.media_type,
        preview_type=preview.type,
        filename=filename,
    )[0]
    return build_media_public_url(rel)


def _resolve_preview_file_path(media: Media, preview: Preview) -> Path | None:
    """Resolve a preview record to a physical file path."""
    filename = _preview_basename(preview.filename)
    if not filename:
        return None

    collection_ids = sorted({mc.collection_id for mc in (media.media_collections or [])})
    if not collection_ids:
        return None

    for candidate in _preview_relative_candidates(
        collection_id=collection_ids[0],
        directory=media.directory,
        media_type=media.media_type,
        preview_type=preview.type,
        filename=filename,
    ):
        resolved = resolve_existing_media_path(candidate)
        if resolved is not None:
            return resolved
    return None


def _is_player_spectrogram_preview(preview: Preview) -> bool:
    filename = _preview_basename(preview.filename)
    return bool(filename and filename.endswith(PLAYER_SPECTROGRAM_SUFFIX))


def _preview_priority(preview: Preview) -> tuple[int, int]:
    if _is_player_spectrogram_preview(preview):
        return (0, preview.preview_id or 0)
    normalized_type = (preview.type or "").strip().lower()
    order = {
        "thumbnail": 1,
        "spectrogram": 2,
        "waveform": 3,
    }
    return (order.get(normalized_type, 99), preview.preview_id or 0)


def _get_preview_url(media: Media) -> str | None:
    """Build a normalized site-root-relative URL for the preferred preview."""
    if not media.previews:
        return None
    for preview in sorted(media.previews, key=_preview_priority):
        static_url = _build_preview_public_url(media, preview)
        if static_url:
            return static_url
    return None


def _get_primary_media_collection(
    media: Media,
    *,
    preferred_collection_id: int | None = None,
) -> MediaCollection | None:
    """Pick a stable collection context for response fields without changing API shape."""
    media_collections = list(media.media_collections or [])
    if not media_collections:
        return None

    if preferred_collection_id is not None:
        for media_collection in media_collections:
            if media_collection.collection_id == preferred_collection_id:
                return media_collection

    return min(
        media_collections, key=lambda media_collection: media_collection.collection_id
    )


def _get_audio_path_for_media(media: Media) -> Path | None:
    """Resolve the physical audio file for a media record."""
    if media.media_type != "audio" or not media.filename:
        return None

    media_collection = _get_primary_media_collection(media)
    if not media_collection:
        return None

    return resolve_existing_audio_media_path(
        media_collection.collection_id,
        media.directory or "",
        media.filename,
    )


def resolve_spectrogram_fft_size(session: Session, user: User | None) -> int:
    """Resolve the default FFT size: user preference first, then global setting."""
    if user is not None:
        preference = session.get(UserPreference, user.user_id)
        if preference is not None and preference.fft:
            return int(preference.fft)

    setting = session.get(Setting, "fft_window_size")
    if setting is not None:
        try:
            return int(setting.value)
        except (TypeError, ValueError):
            logger.warning("Invalid fft_window_size setting: %r", setting.value)

    return DETAIL_DEFAULT_FFT_SIZE


def require_media_resource_write(
    session: Session,
    user: User,
    media_id: int,
    *,
    project_id: int | None,
    denied_detail: str = "No write permission on this media's collection",
) -> list[MediaCollection]:
    """Require audio:write on at least one project-local collection linked to a media record."""
    media = session.get(Media, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    media_collections = list(
        session.exec(
            select(MediaCollection).where(MediaCollection.media_id == media_id)
        ).all()
    )
    if permission_service.is_admin(user):
        return media_collections

    has_access = permission_service.has_resource_permission_on_any_collection_path(
        session,
        user,
        [media_collection.collection_id for media_collection in media_collections],
        "audio",
        "write",
        project_id=project_id,
    )
    if not has_access:
        raise HTTPException(status_code=403, detail=denied_detail)
    return media_collections


def _get_primary_collection_sphere(
    media: Media,
    *,
    preferred_collection_id: int | None = None,
) -> str | None:
    media_collection = _get_primary_media_collection(
        media,
        preferred_collection_id=preferred_collection_id,
    )
    if not media_collection or not media_collection.collection:
        return None
    return media_collection.collection.sphere


@dataclass(frozen=True)
class DetailAssetBundle:
    """Cached detail-view artifacts derived from one viewport selection."""

    source_audio_path: Path
    spectrogram_audio_path: Path
    playback_audio_path: Path
    playback_format: str
    download_basename: str
    key: str


def _resolve_creator_id(
    session: Session,
    requested_creator_id: int | None,
    current_user: User,
    collection_ids: list[int],
    project_id: int | None,
) -> int:
    """Resolve the selected creator and ensure it belongs to the upload scope."""
    if requested_creator_id is None or requested_creator_id == current_user.user_id:
        return current_user.user_id

    creator = session.get(User, requested_creator_id)
    if creator is None:
        raise HTTPException(status_code=404, detail="Creator user not found")
    if permission_service.is_admin(creator):
        return creator.user_id
    if permission_service.is_admin(current_user):
        return creator.user_id

    project_write_ids = permission_repository.get_project_ids_with_write_permission(
        session, current_user.user_id
    )
    project_write_set = set(project_write_ids)
    collection_write_scopes = [
        scope
        for scope in permission_repository.get_effective_collection_scopes(
            session,
            current_user.user_id,
            resource_type="collection",
            action="write",
        )
        if scope[0] not in project_write_set
    ]
    for collection_id in collection_ids:
        resolved_project_id = permission_service.resolve_collection_project_id(
            session, collection_id, project_id
        )
        allowed_user_condition = user_repository.build_manager_scope_user_condition(
            [resolved_project_id] if resolved_project_id in project_write_set else [],
            [(resolved_project_id, collection_id)]
            if (resolved_project_id, collection_id) in collection_write_scopes
            else [],
        )
        target_is_allowed = session.exec(
            select(User.user_id).where(
                User.user_id == creator.user_id,
                allowed_user_condition,
            )
        ).first()
        if target_is_allowed is not None:
            return creator.user_id

    raise HTTPException(
        status_code=403,
        detail="Creator is not available in the current project or collection",
    )


async def create_media(
    session: Session,
    request: MediaCreate,
    current_user: User,
    publisher: TaskPublisher,
    project_id: int | None = None,
) -> MediaCreateResponse:
    """
    Create media from a batch of uploaded files.

    Each file must have been uploaded via chunk upload (which creates the
    FileUpload record automatically on completion).

    This function:
    1. For each file_upload_id: validates the record exists and is pending
    2. Processes photos synchronously and enqueues audio for asynchronous processing

    Args:
        session: Database session
        request: Batch media creation request
        current_user: Current authenticated user
        publisher: RabbitMQ task publisher

    Returns:
        MediaCreateResponse with queued and failed lists
    """
    valid_items: list[tuple[int, str | None, str | None, str]] = []
    failed: list[MediaCreateFailedItem] = []
    filename_datetime_warnings: list[str] = []
    filename_prefix = request.filename_prefix or ""

    creator_id = _resolve_creator_id(
        session,
        request.creator_id,
        current_user,
        [request.collection_id],
        project_id,
    )
    shared_date_time_parts: tuple[str | None, str | None] = (None, None)
    if request.date_from_filename:
        fallback_date_time = request.date_time or _LEGACY_FILENAME_DATETIME_FALLBACK
        date_parts = fallback_date_time.split(" ")
        shared_date_time_parts = (date_parts[0], date_parts[1])
    elif request.date_time:
        date_parts = request.date_time.split(" ")
        shared_date_time_parts = (date_parts[0], date_parts[1])

    # Validate shared foreign key IDs once for batch-level payload.
    if request.sensor_id:
        sensor = session.get(Sensor, request.sensor_id)
        if sensor is None:
            failed.extend(
                MediaCreateFailedItem(
                    file_upload_id=fid,
                    reason=f"Sensor with id={request.sensor_id} not found",
                )
                for fid in request.file_upload_ids
            )
            return MediaCreateResponse(queued=[], failed=failed)
        _validate_sensor_matches_media_type(
            sensor,
            request.media_type or MediaType.AUDIO,
        )

    if request.site_id and not session.get(Site, request.site_id):
        failed.extend(
            MediaCreateFailedItem(
                file_upload_id=fid,
                reason=f"Site with id={request.site_id} not found",
            )
            for fid in request.file_upload_ids
        )
        return MediaCreateResponse(queued=[], failed=failed)

    if request.license_id and not session.get(License, request.license_id):
        failed.extend(
            MediaCreateFailedItem(
                file_upload_id=fid,
                reason=f"License with id={request.license_id} not found",
            )
            for fid in request.file_upload_ids
        )
        return MediaCreateResponse(queued=[], failed=failed)

    for fid in request.file_upload_ids:
        # Validate FileUpload record exists
        file_upload = session.get(FileUpload, fid)
        if not file_upload:
            failed.append(MediaCreateFailedItem(file_upload_id=fid, reason="FileUpload not found"))
            continue

        # Validate status is pending (1)
        if file_upload.status != 1:
            failed.append(
                MediaCreateFailedItem(
                    file_upload_id=fid,
                    reason=f"FileUpload status is not pending (current status={file_upload.status})",
                )
            )
            continue

        # Parse date from filename if requested
        file_date = None
        file_time = None
        if request.date_from_filename:
            file_date, file_time = shared_date_time_parts
            pattern = (
                r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})[-_T](\d{2})[-_:]?(\d{2})[-_:]?(\d{2})"
            )
            match = re.search(pattern, file_upload.filename)
            if match:
                file_date = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
                file_time = f"{match.group(4)}:{match.group(5)}:{match.group(6)}"
            elif request.date_time is None:
                filename_datetime_warnings.append(file_upload.name or file_upload.filename)
        else:
            file_date, file_time = shared_date_time_parts

        original_name = (file_upload.name or file_upload.filename or "").strip()
        display_filename = _build_display_filename(original_name, filename_prefix)
        if not Path(display_filename).name == display_filename:
            failed.append(
                MediaCreateFailedItem(
                    file_upload_id=fid,
                    reason="display filename contains invalid path characters",
                )
            )
            continue

        valid_items.append((fid, file_date, file_time, display_filename))

    if failed:
        return MediaCreateResponse(queued=[], failed=failed)

    batch_queue = Queue(
        type="upload",
        user_id=current_user.user_id,
        total=len(valid_items),
        status=QueueStatus.PENDING,
        warning=_filename_datetime_warning(filename_datetime_warnings),
    )
    session.add(batch_queue)
    session.commit()
    session.refresh(batch_queue)

    try:
        await publisher.enqueue_task(
            WorkerTaskType.PROCESS_MEDIA_BATCH,
            queue_id=batch_queue.queue_id,
            collection_id=request.collection_id,
            items=[
                {
                    "file_upload_id": fid,
                    "file_date": file_date,
                    "file_time": file_time,
                    "display_filename": display_filename,
                }
                for fid, file_date, file_time, display_filename in valid_items
            ],
            site_id=request.site_id,
            sensor_id=request.sensor_id,
            license_id=request.license_id,
            creator_id=creator_id,
            medium=request.medium,
            media_type=request.media_type,
            recording_gain_db=request.recording_gain_db,
            duty_cycle_recording=request.duty_cycle_recording,
            duty_cycle_period=request.duty_cycle_period,
            note=request.note,
            doi=request.doi,
        )
    except Exception:
        logger.exception("Failed to enqueue media batch queue_id=%s", batch_queue.queue_id)
        batch_queue.status = QueueStatus.ERROR
        batch_queue.error = "Failed to enqueue media processing job"
        batch_queue.stop_time = datetime.now().replace(tzinfo=None)
        session.add(batch_queue)
        session.commit()
        return MediaCreateResponse(
            queue_id=batch_queue.queue_id,
            queued=[],
            failed=[
                MediaCreateFailedItem(
                    file_upload_id=fid,
                    reason="Failed to enqueue media processing job",
                )
                for fid, *_ in valid_items
            ],
        )

    return MediaCreateResponse(
        queue_id=batch_queue.queue_id,
        queued=[fid for fid, *_ in valid_items],
    )


def _parse_metadata_optional_int(
    row: list[str],
    positions: dict[str, int],
    row_num: int,
    field: str,
    label: str,
) -> int | None:
    raw = read_cell(row, positions, field)
    if not raw:
        return None

    try:
        return int(raw)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=_metadata_csv_row_error_message(
                row_num,
                label,
                positions[field] + 1,
                f"expected integer, got {raw!r}",
            ),
        )


def _parse_metadata_optional_float(
    row: list[str],
    positions: dict[str, int],
    row_num: int,
    field: str,
    label: str,
) -> float | None:
    raw = read_cell(row, positions, field)
    if not raw:
        return None

    try:
        return float(raw)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=_metadata_csv_row_error_message(
                row_num,
                label,
                positions[field] + 1,
                f"expected float, got {raw!r}",
            ),
        )


def _parse_metadata_required_datetime(
    row: list[str],
    positions: dict[str, int],
    row_num: int,
    field: str,
    label: str,
) -> datetime:
    raw = read_cell(row, positions, field)
    date_time = _parse_metadata_recording_start(raw)
    if date_time is None:
        snippet = raw if len(raw) <= 120 else raw[:117] + "..."
        raise HTTPException(
            status_code=422,
            detail=_metadata_csv_row_error_message(
                row_num,
                label,
                positions[field] + 1,
                f"expected date/time in supported formats ({_METADATA_RECORDING_START_FORMAT_HELP}), got {snippet!r}",
            ),
        )
    return date_time


def _parse_metadata_required_float(
    row: list[str],
    positions: dict[str, int],
    row_num: int,
    field: str,
    label: str,
) -> float:
    raw = read_cell(row, positions, field)
    try:
        return float(raw)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=_metadata_csv_row_error_message(
                row_num,
                label,
                positions[field] + 1,
                f"expected float, got {raw!r}",
            ),
        )


def _parse_audio_metadata_csv_rows(
    text: str, report: CsvImportResult
) -> list[dict[str, Any]]:
    rows = parse_csv(text)
    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty")
    header, *data_rows = rows
    width = effective_header_width(header)

    positions = resolve_header_positions(
        header,
        _AUDIO_METADATA_CSV_FIELD_HEADERS,
        _AUDIO_METADATA_CSV_REQUIRED_FIELDS,
        _AUDIO_METADATA_CSV_IGNORED_KEYS,
    )
    labels = _AUDIO_METADATA_CSV_FIELD_HEADERS

    rows_data: list[dict[str, Any]] = []
    for i, row in enumerate(data_rows, start=2):
        if not row or not any(cell.strip() for cell in row):
            report.rows.append(CsvImportRowResult(row_number=i, status="skipped", reason="Blank row"))
            continue
        try:
            ensure_row_width(row, i, width)
            data = {
                "_row_number": i,
                "date_time": _parse_metadata_required_datetime(
                    row, positions, i, "date_time", labels["date_time"]
                ),
                "duration_s": _parse_metadata_required_float(
                    row, positions, i, "duration_s", labels["duration_s"]
                ),
                "sampling_rate": int(
                    _parse_metadata_required_float(
                        row, positions, i, "sampling_rate", labels["sampling_rate"]
                    )
                ),
                "name": read_cell(row, positions, "name") or None,
                "bit_depth": _parse_metadata_optional_int(
                    row, positions, i, "bit_depth", labels["bit_depth"]
                ),
                "channel_num": _parse_metadata_optional_int(
                    row, positions, i, "channel_num", labels["channel_num"]
                ),
                "duty_cycle_recording": _parse_metadata_optional_int(
                    row, positions, i, "duty_cycle_recording", labels["duty_cycle_recording"]
                ),
                "duty_cycle_period": _parse_metadata_optional_int(
                    row, positions, i, "duty_cycle_period", labels["duty_cycle_period"]
                ),
            }
        except HTTPException as exc:
            reason = str(exc.detail)
            report.global_errors.append(reason)
            report.rows.append(CsvImportRowResult(row_number=i, status="failed", reason=reason))
            continue
        rows_data.append(data)
        report.rows.append(CsvImportRowResult(row_number=i, status="succeeded"))
    return rows_data


def _naive_datetime(value: datetime | None) -> datetime | None:
    """Drop tzinfo so timestamptz values compare against naive CSV datetimes."""
    if value is None or value.tzinfo is None:
        return value
    return value.replace(tzinfo=None)


def _audio_metadata_row_key(data: dict[str, Any]) -> tuple[Any, ...]:
    # Normalize values the same way _persist_audio_metadata_media_rows stores them,
    # so keys built from CSV rows match keys built from persisted records.
    # Blank bit_depth/channel_num end up as the AudioSetting column defaults (16/1),
    # not NULL, so apply the same fallbacks here.
    return (
        data["date_time"],
        data["name"],
        data["duration_s"] or 0.0,
        data["sampling_rate"] or 44100,
        data["bit_depth"] if data["bit_depth"] is not None else 16,
        data["channel_num"] if data["channel_num"] is not None else 1,
        data["duty_cycle_recording"],
        data["duty_cycle_period"],
    )


# Keep IN-clause bind params well under the PostgreSQL wire-protocol limit (65535).
_METADATA_IN_CLAUSE_BATCH = 30_000


def _existing_audio_metadata_keys(
    session: Session,
    date_times: set[datetime],
) -> dict[tuple[Any, ...], int]:
    """
    Map dedup keys of metadata-only audio records to media_id (global dedup).

    Only records whose date_time appears in the CSV are candidates (date_time
    is part of the dedup key), so the scan stays proportional to the CSV size
    instead of the whole media table. Queried in chunks to stay under the
    driver's bind-parameter limit for very large files.
    """
    result: dict[tuple[Any, ...], int] = {}
    for batch in itertools.batched(date_times, _METADATA_IN_CLAUSE_BATCH):
        stmt = (
            select(
                Media.media_id,
                Media.date_time,
                Media.name,
                AudioSetting.duration_s,
                AudioSetting.sampling_rate_hz,
                AudioSetting.bit_depth,
                AudioSetting.channel_num,
                Media.duty_cycle_recording,
                Media.duty_cycle_period,
            )
            .join(AudioSetting, AudioSetting.audio_setting_id == Media.audio_setting_id)
            .where(
                Media.is_metadata.is_(True),
                Media.media_type == "audio",
                Media.date_time.in_(batch),
            )
        )
        # Later media_id wins is irrelevant; any existing record with the key is a valid reuse target.
        for row in session.exec(stmt).all():
            result[(_naive_datetime(row[1]), *row[2:])] = row[0]
    return result


def _linked_media_ids(
    session: Session, collection_id: int, media_ids: set[int]
) -> set[int]:
    """Subset of candidate media_ids already linked to the target collection."""
    linked: set[int] = set()
    for batch in itertools.batched(media_ids, _METADATA_IN_CLAUSE_BATCH):
        linked.update(
            session.exec(
                select(MediaCollection.media_id).where(
                    MediaCollection.collection_id == collection_id,
                    MediaCollection.media_id.in_(batch),
                )
            ).all()
        )
    return linked


def _persist_audio_metadata_media_rows(
    session: Session,
    rows_data: list[dict[str, Any]],
    *,
    collection_id: int,
    user: User,
) -> tuple[int, int]:
    """
    Persist parsed rows with global dedup; returns (created, linked).

    A row whose key matches an existing metadata record reuses that Media:
    if it is not yet in the target collection a MediaCollection link is added
    (linked), otherwise the row is skipped. Unknown keys create a new Media.
    """
    key_to_media_id = _existing_audio_metadata_keys(
        session, {data["date_time"] for data in rows_data}
    )
    linked_ids = _linked_media_ids(
        session, collection_id, set(key_to_media_id.values())
    )
    # Keys created earlier in this file; identical later rows are skipped.
    created_keys: set[tuple[Any, ...]] = set()
    created = 0
    linked = 0
    for data in rows_data:
        key = _audio_metadata_row_key(data)
        if key in created_keys:
            continue
        existing_media_id = key_to_media_id.get(key)
        if existing_media_id is not None:
            # Already present in this collection -> skip.
            if existing_media_id in linked_ids:
                continue
            session.add(MediaCollection(
                media_id=existing_media_id, collection_id=collection_id, added_by=user.user_id
            ))
            linked_ids.add(existing_media_id)
            linked += 1
            continue

        # Relationship wiring lets a single commit batch-insert all rows
        # instead of flushing per row for FK ids.
        session.add(Media(
            media_type="audio",
            is_metadata=True,
            name=data["name"],
            date_time=data["date_time"],
            duty_cycle_recording=data["duty_cycle_recording"],
            duty_cycle_period=data["duty_cycle_period"],
            uploader_id=user.user_id,
            creator_id=user.user_id,
            audio_setting=AudioSetting(
                duration_s=data["duration_s"] or 0.0,
                sampling_rate_hz=data["sampling_rate"] or 44100,
                bit_depth=data["bit_depth"],
                channel_num=data["channel_num"],
            ),
            media_collections=[
                MediaCollection(collection_id=collection_id, added_by=user.user_id)
            ],
        ))
        created_keys.add(key)
        created += 1

    session.commit()
    return created, linked


def _parse_photo_metadata_csv_rows(
    text: str, report: CsvImportResult
) -> list[dict[str, Any]]:
    rows = parse_csv(text)
    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty")
    header, *data_rows = rows
    width = effective_header_width(header)

    positions = resolve_header_positions(
        header,
        _PHOTO_METADATA_CSV_FIELD_HEADERS,
        _PHOTO_METADATA_CSV_REQUIRED_FIELDS,
        _PHOTO_METADATA_CSV_IGNORED_KEYS,
    )
    labels = _PHOTO_METADATA_CSV_FIELD_HEADERS

    rows_data: list[dict[str, Any]] = []
    for i, row in enumerate(data_rows, start=2):
        if not row or not any(cell.strip() for cell in row):
            report.rows.append(CsvImportRowResult(row_number=i, status="skipped", reason="Blank row"))
            continue
        try:
            ensure_row_width(row, i, width)
            data = {
                "_row_number": i,
                "date_time": _parse_metadata_required_datetime(
                    row, positions, i, "date_time", labels["date_time"]
                ),
                "name": read_cell(row, positions, "name") or None,
                "exposure_ms": _parse_metadata_optional_float(
                    row, positions, i, "exposure_ms", labels["exposure_ms"]
                ),
                "aperture": _parse_metadata_optional_float(
                    row, positions, i, "aperture", labels["aperture"]
                ),
                "iso": _parse_metadata_optional_int(
                    row, positions, i, "iso", labels["iso"]
                ),
            }
        except HTTPException as exc:
            reason = str(exc.detail)
            report.global_errors.append(reason)
            report.rows.append(CsvImportRowResult(row_number=i, status="failed", reason=reason))
            continue
        rows_data.append(data)
        report.rows.append(CsvImportRowResult(row_number=i, status="succeeded"))
    return rows_data


def _photo_metadata_row_key(data: dict[str, Any]) -> tuple[Any, ...]:
    return (
        data["date_time"],
        data["name"],
        data["exposure_ms"],
        data["aperture"],
        data["iso"],
    )


def _existing_photo_metadata_keys(
    session: Session,
    date_times: set[datetime],
) -> dict[tuple[Any, ...], int]:
    """
    Map dedup keys of metadata-only photo records to media_id (global dedup).

    Only records whose date_time appears in the CSV are candidates (date_time
    is part of the dedup key), so the scan stays proportional to the CSV size
    instead of the whole media table.
    """
    if not date_times:
        return {}
    stmt = (
        select(
            Media.media_id,
            Media.date_time,
            Media.name,
            PhotoSetting.exposure_ms,
            PhotoSetting.aperture,
            PhotoSetting.iso,
        )
        .join(PhotoSetting, PhotoSetting.photo_setting_id == Media.photo_setting_id)
        .where(
            Media.is_metadata.is_(True),
            Media.media_type == "photo",
            Media.date_time.in_(date_times),
        )
    )
    return {
        (_naive_datetime(row[1]), *row[2:]): row[0]
        for row in session.exec(stmt).all()
    }


def _persist_photo_metadata_media_rows(
    session: Session,
    rows_data: list[dict[str, Any]],
    *,
    collection_id: int,
    user: User,
) -> tuple[int, int]:
    """
    Persist parsed rows with global dedup; returns (created, linked).

    A row whose key matches an existing metadata record reuses that Media:
    if it is not yet in the target collection a MediaCollection link is added
    (linked), otherwise the row is skipped. Unknown keys create a new Media.
    """
    key_to_media_id = _existing_photo_metadata_keys(
        session, {data["date_time"] for data in rows_data}
    )
    linked_ids = _linked_media_ids(
        session, collection_id, set(key_to_media_id.values())
    )
    # Keys created earlier in this file; identical later rows are skipped.
    created_keys: set[tuple[Any, ...]] = set()
    created = 0
    linked = 0
    for data in rows_data:
        key = _photo_metadata_row_key(data)
        if key in created_keys:
            continue
        existing_media_id = key_to_media_id.get(key)
        if existing_media_id is not None:
            # Already present in this collection -> skip.
            if existing_media_id in linked_ids:
                continue
            session.add(MediaCollection(
                media_id=existing_media_id, collection_id=collection_id, added_by=user.user_id
            ))
            linked_ids.add(existing_media_id)
            linked += 1
            continue

        # Relationship wiring lets a single commit batch-insert all rows
        # instead of flushing per row for FK ids.
        session.add(Media(
            media_type="photo",
            is_metadata=True,
            name=data["name"],
            date_time=data["date_time"],
            uploader_id=user.user_id,
            creator_id=user.user_id,
            photo_setting=PhotoSetting(
                exposure_ms=data["exposure_ms"],
                aperture=data["aperture"],
                iso=data["iso"],
            ),
            media_collections=[
                MediaCollection(collection_id=collection_id, added_by=user.user_id)
            ],
        ))
        created_keys.add(key)
        created += 1

    session.commit()
    return created, linked


def import_metadata_csv(
    session: Session,
    text: str,
    collection_id: int,
    user: User,
    media_type: Literal["audio", "photo"] = "audio",
) -> CsvImportResult:
    """
    Import media metadata from decoded CSV text.

    Validates rows and fails fast on the first invalid row.
    Deduplication is global across collections: a row identical to an existing
    metadata record reuses that Media (a MediaCollection link is added when the
    record is not yet in the target collection, otherwise the row is skipped),
    so the media table never holds duplicate metadata rows across collections.
    `media_type` selects the CSV column schema (audio vs photo) and the
    resulting Media.media_type / setting table used.
    """
    report = CsvImportResult()
    try:
        if media_type == "photo":
            rows_data = _parse_photo_metadata_csv_rows(text, report)
        else:
            rows_data = _parse_audio_metadata_csv_rows(text, report)
    except HTTPException as exc:
        report.global_errors.append(str(exc.detail))
        try:
            parsed = parse_csv(text)
        except HTTPException:
            parsed = []
        if parsed:
            report.reject_data_rows(parsed[1:], str(exc.detail))
        return report.finalize()

    seen: set[tuple[Any, ...]] = set()
    results = {item.row_number: item for item in report.rows}
    for data in rows_data:
        key = _photo_metadata_row_key(data) if media_type == "photo" else _audio_metadata_row_key(data)
        row = results[data["_row_number"]]
        if key in seen:
            row.status, row.field, row.reason = "skipped", "metadata", "Duplicate metadata row in file"
        seen.add(key)

    # Existing-record reuse is a successful write when it creates a collection link;
    # a record already linked to the target collection is skipped.
    if media_type == "photo":
        existing = _existing_photo_metadata_keys(session, {data["date_time"] for data in rows_data})
    else:
        existing = _existing_audio_metadata_keys(session, {data["date_time"] for data in rows_data})
    linked_ids = _linked_media_ids(session, collection_id, set(existing.values()))
    for data in rows_data:
        row = results[data["_row_number"]]
        if row.status != "succeeded":
            continue
        key = _photo_metadata_row_key(data) if media_type == "photo" else _audio_metadata_row_key(data)
        if existing.get(key) in linked_ids:
            row.status, row.field, row.reason = "skipped", "metadata", "Metadata already exists in this collection"

    report.finalize()
    if report.failed:
        report.reject_candidates()
        return report
    if media_type == "photo":
        created, linked = _persist_photo_metadata_media_rows(
            session,
            rows_data,
            collection_id=collection_id,
            user=user,
        )
    else:
        created, linked = _persist_audio_metadata_media_rows(
            session,
            rows_data,
            collection_id=collection_id,
            user=user,
        )

    report.committed = True
    return report.finalize()


def _media_visibility(
    user: User | None,
) -> tuple[Literal["all", "public", "accessible"], int | None]:
    if user is None:
        return "public", None
    if permission_service.is_admin(user):
        return "all", None
    return "accessible", user.user_id


def _resolve_visible_media_collection_ids(
    session: Session,
    user: User | None,
    *,
    project_id: int,
    collection_id: int | None,
) -> list[int]:
    """Resolve browse/list collection scope once so list and count reuse it."""
    visibility, user_id = _media_visibility(user)
    if visibility == "all":
        return resolve_project_collection_scope(
            session,
            project_id=project_id,
            collection_id=collection_id,
            is_admin=True,
            include_public=False,
        )

    return resolve_project_collection_scope(
        session,
        project_id=project_id,
        collection_id=collection_id,
        user_id=user_id,
        resource_type="audio",
        action="read",
        include_public=True,
    )


def _query_visible_media(
    session: Session,
    user: User | None,
    *,
    filters: dict,
    page: int = 1,
    page_size: int | None = 20,
    order_by: str = "media_id",
    order_dir: str = "asc",
    relation_profile: str | None = None,
    include_total: bool = True,
) -> tuple[list[Media], int]:
    """Run the shared list/count queries; callers must pre-resolve
    filters["scoped_collection_ids"] so both queries share one permission scope."""
    visibility, user_id = _media_visibility(user)
    skip = (page - 1) * page_size if page_size is not None else 0

    records = media_repository.list_filtered(
        session,
        visibility=visibility,
        user_id=user_id,
        skip=skip,
        limit=page_size,
        order_by=order_by,
        order_dir=order_dir,
        relation_profile=relation_profile,
        **filters,
    )
    total = (
        media_repository.count_filtered(
            session,
            visibility=visibility,
            user_id=user_id,
            **filters,
        )
        if include_total
        else len(records)
    )
    return records, total


def get_media_list(
    session: Session,
    user: User | None,
    *,
    project_id: int,
    page: int = 1,
    page_size: int = 20,
    order_by: str = "media_id",
    order_dir: str = "asc",
    **filters,
) -> PagedApiResponse[list[MediaListPublic]]:
    scoped_collection_ids = _resolve_visible_media_collection_ids(
        session,
        user,
        project_id=project_id,
        collection_id=filters.get("collection_id"),
    )
    media_list, count = _query_visible_media(
        session,
        user,
        filters={
            **filters,
            "scoped_collection_ids": scoped_collection_ids,
            **(
                {"label_user_id": user.user_id}
                if user is not None and filters.get("label_id")
                else {}
            ),
        },
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
        relation_profile="detail",
    )
    scope_set = set(scoped_collection_ids)
    data = [
        MediaListPublic.model_validate(
            _build_media_public(
                session,
                media,
                user,
                project_id=project_id,
                include_image_dimensions=False,
                scoped_collection_ids=scope_set,
            )
        )
        for media in media_list
    ]
    return api_page(data=data, total=count, page=page, page_size=page_size)


def _build_gallery_item(
    media: Media, collection_id: int | None, user: User | None
) -> MediaBrowseGalleryItem:
    return MediaBrowseGalleryItem(
        media_id=media.media_id,
        name=media.name,
        filename=media.filename,
        media_type=media.media_type,
        is_metadata=media.is_metadata,
        date_time=media.date_time,
        size_b=media.size_b,
        duration_s=(media.audio_setting.duration_s if media.audio_setting else None),
        sampling_rate_hz=(
            media.audio_setting.sampling_rate_hz if media.audio_setting else None
        ),
        bit_depth=(media.audio_setting.bit_depth if media.audio_setting else None),
        channel_num=(media.audio_setting.channel_num if media.audio_setting else None),
        duty_cycle_period=media.duty_cycle_period,
        duty_cycle_recording=media.duty_cycle_recording,
        label=_get_browse_label(media, user),
        preview_url=_get_preview_url(media),
        sphere=_get_primary_collection_sphere(
            media, preferred_collection_id=collection_id
        ),
        realm_name=(media.site.realm.name if media.site and media.site.realm else None),
    )


def _build_list_item(
    media: Media, collection_id: int | None, user: User | None
) -> MediaBrowseListItem:
    return MediaBrowseListItem(
        media_id=media.media_id,
        name=media.name,
        filename=media.filename,
        media_type=media.media_type,
        is_metadata=media.is_metadata,
        site_id=media.site_id,
        site_name=(media.site.name if media.site else None),
        sensor_id=media.sensor_id,
        sensor_name=(media.sensor.name if media.sensor else None),
        license_id=media.license_id,
        license_name=(media.license.name if media.license else None),
        medium=media.medium,
        date_time=media.date_time,
        duration_s=(media.audio_setting.duration_s if media.audio_setting else None),
        sampling_rate_hz=(
            media.audio_setting.sampling_rate_hz if media.audio_setting else None
        ),
        bit_depth=(media.audio_setting.bit_depth if media.audio_setting else None),
        channel_num=(media.audio_setting.channel_num if media.audio_setting else None),
        duty_cycle_period=media.duty_cycle_period,
        duty_cycle_recording=media.duty_cycle_recording,
        label=_get_browse_label(media, user),
        preview_url=_get_preview_url(media),
        size_b=media.size_b,
        uploader_name=media.uploader_name,
        creator_name=media.creator_name,
        note=media.note,
        doi=media.doi,
        sphere=_get_primary_collection_sphere(
            media, preferred_collection_id=collection_id
        ),
        topography_m=(media.site.topography_m if media.site else None),
        freshwater_depth_m=(media.site.freshwater_depth_m if media.site else None),
        realm_name=(media.site.realm.name if media.site and media.site.realm else None),
        biome_name=(media.site.biome.name if media.site and media.site.biome else None),
        functional_type_name=(
            media.site.functional_type.name
            if media.site and media.site.functional_type
            else None
        ),
        hierarchy=[
            name
            for name in [
                media.site.realm.name if media.site and media.site.realm else None,
                media.site.biome.name if media.site and media.site.biome else None,
                media.site.functional_type.name
                if media.site and media.site.functional_type
                else None,
            ]
            if name
        ],
    )


def browse_media_list(
    session: Session,
    user: User | None,
    *,
    project_id: int,
    view_type: Literal["gallery", "list"],
    page: int = 1,
    page_size: int = 20,
    collection_id: int | None = None,
    site_id: int | None = None,
    name: str | None = None,
    media_type: str = "all",
    order_by: str = "media_id",
    order_dir: str = "asc",
) -> PagedApiResponse[list[MediaBrowseGalleryItem | MediaBrowseListItem]]:
    scoped_collection_ids = _resolve_visible_media_collection_ids(
        session,
        user,
        project_id=project_id,
        collection_id=collection_id,
    )
    filters = {
        "site_id": site_id,
        "browse_view_type": view_type,
        "scoped_collection_ids": scoped_collection_ids,
    }
    if media_type != "all":
        filters["media_type"] = media_type
    if name:
        filters["browse_search"] = name
        if user is not None:
            filters["browse_label_user_id"] = user.user_id

    media_list, count = _query_visible_media(
        session,
        user,
        filters=filters,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
        relation_profile=view_type,
    )

    item_builder = _build_gallery_item if view_type == "gallery" else _build_list_item
    items = [item_builder(media, collection_id, user) for media in media_list]
    return api_page(data=items, total=count, page=page, page_size=page_size)


def _get_browse_label(media: Media, user: User | None) -> str:
    """Return the current user's browse label, defaulting to not analysed."""
    if user is None:
        return "not analysed"
    label_names = sorted(
        {
            lm.label.name
            for lm in media.label_media
            if lm.user_id == user.user_id and lm.label and lm.label.name
        }
    )
    return label_names[0] if label_names else "not analysed"


def _get_project_public_collection_ids(session: Session, project_id: int) -> list[int]:
    """Return public-access collection IDs under a project."""
    stmt = (
        select(Collection.collection_id)
        .join(
            ProjectCollection,
            ProjectCollection.collection_id == Collection.collection_id,
        )
        .where(
            ProjectCollection.project_id == project_id,
            Collection.public_access.is_(True),
        )
    )
    return list(session.exec(stmt).all())


def build_media_timeline_data(
    session: Session,
    *,
    current_user: User | None,
    project_id: int,
    collection_id: int | None = None,
    site_ids: list[int] | None = None,
    include_metadata: bool = True,
    response_mode: Literal["overview", "detail"] = "overview",
    site_key: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    detail_limit: int = 5000,
    media_type: str = "all",
) -> MediaTimelineResponse:
    """Build media timeline payload using project-scoped collection visibility."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_collection_ids = set(
        permission_repository.get_project_collection_ids(session, project_id)
    )
    if collection_id is not None and collection_id not in project_collection_ids:
        raise HTTPException(
            status_code=400,
            detail="collection_id does not belong to the given project_id",
        )

    if collection_id is not None:
        collection = session.get(Collection, collection_id)
        if collection is None:
            raise HTTPException(status_code=404, detail="Collection not found")

        is_public_scope = bool(project.public and collection.public_access)
        if not is_public_scope:
            if current_user is None:
                raise HTTPException(status_code=403, detail="Access denied")
            if not permission_service.has_resource_permission(
                session,
                current_user,
                "audio",
                "read",
                project_id=project_id,
                collection_id=collection_id,
            ):
                raise HTTPException(status_code=403, detail="Access denied")
        visible_collection_ids = None
    else:
        if current_user is None:
            if not project.public:
                raise HTTPException(status_code=403, detail="Access denied")
            visible_collection_ids = sorted(
                _get_project_public_collection_ids(session, project_id)
            )
        elif permission_service.is_admin(current_user):
            visible_collection_ids = sorted(project_collection_ids)
        else:
            accessible_collection_ids = set(
                permission_repository.get_accessible_collection_ids(
                    session,
                    current_user.user_id,
                    resource_type="audio",
                    action="read",
                    project_id=project_id,
                )
            )

            visible_collection_ids = accessible_collection_ids & project_collection_ids
            if project.public:
                visible_collection_ids |= set(
                    _get_project_public_collection_ids(session, project_id)
                )
            visible_collection_ids = sorted(visible_collection_ids)
            if not project.public and not visible_collection_ids:
                raise HTTPException(status_code=403, detail="Access denied")

    has_more = False
    if response_mode == "detail":
        if not site_key or start_date is None or end_date is None:
            raise HTTPException(
                status_code=400,
                detail="site_key, start_date and end_date are required in detail mode",
            )
        if site_key != "nogeo":
            if not site_key.startswith("site:"):
                raise HTTPException(status_code=400, detail="Invalid site_key")
            try:
                int(site_key.removeprefix("site:"))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid site_key") from exc
        if end_date <= start_date:
            raise HTTPException(status_code=400, detail="end_date must be after start_date")
        media_list, has_more = media_repository.get_media_timeline_detail_media(
            session,
            project_id=project_id,
            collection_id=collection_id,
            visible_collection_ids=visible_collection_ids,
            site_key=site_key,
            start_date=start_date,
            end_date=end_date,
            include_metadata=include_metadata,
            limit=detail_limit,
            media_types=None if media_type == "all" else [media_type],
        )
    else:
        media_list = media_repository.get_media_timeline_media(
            session,
            project_id=project_id,
            collection_id=collection_id,
            visible_collection_ids=visible_collection_ids,
            site_ids=site_ids,
            include_metadata=include_metadata,
            media_types=None if media_type == "all" else [media_type],
        )

    items: list[MediaTimelineItem] = []
    min_start: datetime | None = None
    max_end: datetime | None = None

    for media in media_list:
        start_date = media.date_time

        if media.end_time is not None:
            end_date = media.end_time
        else:
            duration_seconds = float(media.duration_s or 0.0)
            if duration_seconds < 0:
                duration_seconds = 0.0
            end_date = start_date + timedelta(seconds=duration_seconds)

        site_name = media.site_name or "not geo-referenced"
        creator_name = media.creator_name or ""
        item_name = media.name or media.filename or f"media_{media.media_id}"
        realm_name = media.realm_name

        items.append(
            MediaTimelineItem(
                media_id=media.media_id,
                media_type=media.media_type,
                name=item_name,
                start_date=start_date,
                end_date=end_date,
                duration_s=media.duration_s,
                site_id=media.site_id,
                site_key=media.site_key,
                site_name=site_name,
                duty_cycle_period=media.duty_cycle_period,
                duty_cycle_recording=media.duty_cycle_recording,
                is_metadata=media.is_metadata,
                creator_name=creator_name,
                realm=realm_name,
                item_count=media.item_count,
            )
        )

        min_start = start_date if min_start is None else min(min_start, start_date)
        max_end = end_date if max_end is None else max(max_end, end_date)

    if min_start is not None and max_end is not None:
        time_range = MediaTimelineRange(
            min=min_start - timedelta(days=1),
            max=max_end + timedelta(days=1),
        )
    else:
        time_range = MediaTimelineRange(min=None, max=None)

    return MediaTimelineResponse(
        project_id=project_id,
        collection_id=collection_id,
        items=items,
        time_range=time_range,
        has_more=has_more,
    )


def get_media(
    session: Session, project_id: int, media_id: int, user: User | None
) -> MediaPublic:
    """
    Get a media record by ID with full detail including previews, related names, and user labels.

    Anonymous users can only access media linked to public collections.
    Authenticated users need read permission on the media's collection.

    Args:
        session: Database session
        media_id: Media ID
        user: Current user

    Returns:
        Enriched MediaPublic response

    Raises:
        HTTPException: If not found or no permission
    """
    media = media_repository.get_with_detail_relations(session, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    # Permission check
    stmt = (
        select(MediaCollection)
        .join(
            ProjectCollection,
            ProjectCollection.collection_id == MediaCollection.collection_id,
        )
        .where(
            MediaCollection.media_id == media_id,
            ProjectCollection.project_id == project_id,
        )
    )
    media_collections = session.exec(stmt).all()

    if not media_collections:
        raise HTTPException(status_code=403, detail="Access denied")

    if user is None:
        allowed = any(
            permission_repository.is_public_project_collection(
                session, project_id, mc.collection_id
            )
            for mc in media_collections
        )
        if not allowed:
            raise HTTPException(status_code=403, detail="Access denied")
        return _build_media_public(session, media, None, project_id=project_id)

    if not permission_service.is_admin(user):
        allowed = False
        for mc in media_collections:
            collection = session.get(Collection, mc.collection_id)
            if collection and permission_repository.is_public_project_collection(
                session, project_id, mc.collection_id
            ):
                allowed = True
                break
            if permission_service.has_resource_permission(
                session,
                user,
                "audio",
                "read",
                project_id=project_id,
                collection_id=mc.collection_id,
            ):
                allowed = True
                break

        if not allowed:
            raise HTTPException(status_code=403, detail="Access denied")

    return _build_media_public(session, media, user, project_id=project_id)


def _detail_asset_root() -> Path:
    return media_root() / _DETAIL_ASSET_DIR


class _DetailAssetLockTimeoutError(TimeoutError):
    pass


def _detail_asset_lock_path(key: str) -> Path:
    shard = int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16) % _DETAIL_ASSET_LOCK_SHARDS
    return _detail_asset_root() / ".locks" / f"{shard:04d}.lock"


@contextmanager
def _detail_asset_lock(
    key: str,
    *,
    timeout_seconds: float | None = None,
) -> Iterator[float]:
    effective_timeout = (
        _DETAIL_ASSET_LOCK_TIMEOUT_SECONDS
        if timeout_seconds is None
        else timeout_seconds
    )
    lock_path = _detail_asset_lock_path(key)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = time.monotonic()
    with lock_path.open("a+b") as lock_file:
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() - started_at >= effective_timeout:
                    raise _DetailAssetLockTimeoutError(key)
                time.sleep(min(0.05, max(0.0, effective_timeout)))

        waited_seconds = time.monotonic() - started_at
        try:
            yield waited_seconds
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _detail_asset_modified_at(bundle_dir: Path) -> datetime | None:
    manifest_path = bundle_dir / _DETAIL_ASSET_MANIFEST_FILENAME
    access_path = bundle_dir / _DETAIL_ASSET_ACCESS_FILENAME
    candidate = access_path if access_path.exists() else manifest_path
    if not candidate.exists():
        candidate = bundle_dir
    try:
        return datetime.fromtimestamp(candidate.stat().st_mtime)
    except OSError:
        return None


def _touch_detail_asset(bundle_dir: Path) -> None:
    access_path = bundle_dir / _DETAIL_ASSET_ACCESS_FILENAME
    access_path.touch(exist_ok=True)


def _cleanup_stale_detail_assets() -> None:
    root = _detail_asset_root()
    if not root.exists():
        return

    cutoff = datetime.now() - _DETAIL_ASSET_TTL
    for media_dir in root.iterdir():
        if media_dir.name == ".locks" or not media_dir.is_dir():
            continue
        for bundle_dir in media_dir.iterdir():
            if not bundle_dir.is_dir():
                continue
            modified_at = _detail_asset_modified_at(bundle_dir)
            if modified_at is None or modified_at >= cutoff:
                continue
            try:
                with _detail_asset_lock(bundle_dir.name, timeout_seconds=0.0):
                    modified_at = _detail_asset_modified_at(bundle_dir)
                    if modified_at is not None and modified_at < cutoff:
                        shutil.rmtree(bundle_dir, ignore_errors=True)
            except _DetailAssetLockTimeoutError:
                continue


def _detail_asset_parameters(
    *,
    media_id: int,
    start_time: float,
    end_time: float | None,
    min_freq: float,
    max_freq: float | None,
    channel: int,
    filter_enabled: bool,
    fft_size: int,
) -> dict[str, Any]:
    return {
        "media_id": media_id,
        "start_time": round(float(start_time), _DETAIL_PARAM_PRECISION),
        "end_time": round(float(end_time), _DETAIL_PARAM_PRECISION) if end_time is not None else None,
        "min_freq": round(float(min_freq), _DETAIL_PARAM_PRECISION),
        "max_freq": round(float(max_freq), _DETAIL_PARAM_PRECISION) if max_freq is not None else None,
        "channel": int(channel),
        "filter": bool(filter_enabled),
        "fft_size": int(fft_size),
    }


def _detail_asset_key(
    *,
    media_id: int,
    start_time: float,
    end_time: float | None,
    min_freq: float,
    max_freq: float | None,
    channel: int,
    filter_enabled: bool,
    fft_size: int,
) -> str:
    payload = _detail_asset_parameters(
        media_id=media_id,
        start_time=start_time,
        end_time=end_time,
        min_freq=min_freq,
        max_freq=max_freq,
        channel=channel,
        filter_enabled=filter_enabled,
        fft_size=fft_size,
    )
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _detail_output_format(*, sample_rate: int, source_path: Path) -> str:
    if sample_rate <= 44_100:
        return "mp3"
    if sample_rate <= 192_000:
        return "ogg"
    return source_path.suffix.lower().lstrip(".") or "wav"


def _normalize_detail_freq_band(
    sample_rate: int,
    min_freq: float,
    max_freq: float | None,
) -> tuple[float, float]:
    nyquist = float(max(1, sample_rate // 2))
    lo = max(0.0, float(min_freq))
    hi = nyquist if max_freq is None else min(float(max_freq), nyquist)
    if hi < lo:
        hi = lo
    return (
        round(lo, _DETAIL_PARAM_PRECISION),
        round(hi, _DETAIL_PARAM_PRECISION),
    )


def _run_audio_command(command: list[str], *, executable_name: str) -> None:
    """Run one bounded external audio operation without buffering audio in Python."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_SOX_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"{executable_name} is required for audio selection processing"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        logger.error(
            "%s timed out after %ss: %s",
            executable_name,
            _SOX_TIMEOUT_SECONDS,
            command,
        )
        raise RuntimeError(f"{executable_name} audio processing timed out") from exc
    if result.returncode != 0:
        detail = (
            result.stderr
            or result.stdout
            or f"unknown {executable_name} error"
        ).strip()
        logger.error(
            "%s failed with exit %s: %s",
            executable_name,
            result.returncode,
            detail,
        )
        raise RuntimeError(f"{executable_name} audio processing failed: {detail}")


def _run_sox(command: list[str]) -> None:
    _run_audio_command(command, executable_name="SoX")


def _run_lame(command: list[str]) -> None:
    _run_audio_command(command, executable_name="LAME")


def _round_sample_half_up(value: float) -> int:
    return int(math.floor(max(0.0, float(value)) + 0.5))


def _sox_selection_command(
    audio_path: Path,
    output_path: Path,
    *,
    start_sample: int,
    duration_sample: int | None,
) -> list[str]:
    command = ["sox", str(audio_path), str(output_path)]
    if start_sample > 0 or duration_sample is not None:
        command.extend(["trim", f"{max(0, int(start_sample))}s"])
        if duration_sample is not None:
            command.append(f"{max(0, int(duration_sample))}s")
    return command


def _sox_filter_command(
    source_path: Path,
    output_path: Path,
    *,
    sample_rate: int,
    min_freq: float,
    max_freq: float,
) -> list[str]:
    frequency_spec = build_sox_sinc_frequency_spec(sample_rate, min_freq, max_freq)
    return ["sox", str(source_path), str(output_path), "sinc", frequency_spec]


def _detail_asset_temp_path(target_path: Path) -> Path:
    return target_path.with_name(
        f".{target_path.stem}.{uuid.uuid4().hex}.tmp{target_path.suffix}"
    )


def _validate_cached_audio(path: Path, expected_size: int | None = None) -> bool:
    try:
        stat = path.stat()
        if not path.is_file() or stat.st_size <= 0:
            return False
        if expected_size is not None and stat.st_size != expected_size:
            return False
        sf.info(str(path))
        return True
    except (OSError, RuntimeError, sf.LibsndfileError):
        return False


def _read_source_audio_info(audio_path: Path) -> Any:
    try:
        return sf.info(str(audio_path))
    except (OSError, RuntimeError, sf.LibsndfileError) as exc:
        raise HTTPException(
            status_code=415,
            detail="Unsupported audio format",
        ) from exc


def _validate_cached_playback(path: Path, manifest_path: Path) -> bool:
    if not _validate_cached_audio(path):
        return False
    try:
        return path.stat().st_mtime_ns >= manifest_path.stat().st_mtime_ns
    except OSError:
        return False


def _source_audio_fingerprint(audio_path: Path, sample_rate: int) -> dict[str, Any]:
    stat = audio_path.stat()
    return {
        "path": str(audio_path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sample_rate": int(sample_rate),
    }


def _read_valid_detail_manifest(
    bundle_dir: Path,
    *,
    parameters: dict[str, Any],
    source: dict[str, Any],
    filter_enabled: bool,
) -> tuple[dict[str, Any] | None, str]:
    manifest_path = bundle_dir / _DETAIL_ASSET_MANIFEST_FILENAME
    try:
        with manifest_path.open(encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
    except (OSError, json.JSONDecodeError, TypeError):
        return None, "manifest_missing_or_invalid"

    if not isinstance(manifest, dict):
        return None, "manifest_invalid"
    if manifest.get("version") != _DETAIL_ASSET_MANIFEST_VERSION:
        return None, "manifest_version_changed"
    if manifest.get("parameters") != parameters:
        return None, "parameters_changed"
    if manifest.get("source") != source:
        return None, "source_changed"

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return None, "artifact_metadata_invalid"
    if not artifacts:
        return None, "artifact_metadata_invalid"
    for required_artifact in ("zoomed_audio", "spectrogram_wav"):
        if required_artifact not in artifacts:
            return None, f"artifact_metadata_invalid:{required_artifact}"
    if filter_enabled and "filtered_audio" not in artifacts:
        return None, "artifact_metadata_invalid:filtered_audio"
    for artifact_name, metadata in artifacts.items():
        if not isinstance(metadata, dict) or not isinstance(metadata.get("size"), int):
            return None, f"artifact_metadata_invalid:{artifact_name}"
        filename = metadata.get("filename")
        if not isinstance(filename, str) or not filename:
            return None, f"artifact_metadata_invalid:{artifact_name}"
        if not _validate_cached_audio(bundle_dir / filename, metadata["size"]):
            return None, f"artifact_invalid:{artifact_name}"
    return manifest, "hit"


def _write_detail_manifest_temp(
    manifest_path: Path,
    manifest: dict[str, Any],
) -> Path:
    temp_path = _detail_asset_temp_path(manifest_path)
    try:
        with temp_path.open("w", encoding="utf-8") as manifest_file:
            json.dump(manifest, manifest_file, sort_keys=True, separators=(",", ":"))
            manifest_file.flush()
            os.fsync(manifest_file.fileno())
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _publish_detail_selection(
    replacements: list[tuple[Path, Path]],
) -> None:
    backups: dict[Path, Path | None] = {}
    published_targets: list[Path] = []
    try:
        for _temp_path, target_path in replacements:
            if target_path.exists():
                backup_path = _detail_asset_temp_path(target_path)
                os.link(target_path, backup_path)
                backups[target_path] = backup_path
            else:
                backups[target_path] = None

        for temp_path, target_path in replacements:
            os.replace(temp_path, target_path)
            published_targets.append(target_path)
    except Exception:
        for target_path in reversed(published_targets):
            restore_path = backups[target_path]
            if restore_path is None:
                target_path.unlink(missing_ok=True)
            else:
                os.replace(restore_path, target_path)
        raise
    finally:
        for stale_backup_path in backups.values():
            if stale_backup_path is not None:
                stale_backup_path.unlink(missing_ok=True)


def _rebuild_detail_selection(
    *,
    bundle_dir: Path,
    audio_path: Path,
    start_sample: int,
    duration_sample: int,
    total_frames: int,
    source_suffix: str,
    filter_enabled: bool,
    min_freq: float,
    max_freq: float,
    sample_rate: int,
    parameters: dict[str, Any],
    source: dict[str, Any],
) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    zoomed_audio_path = bundle_dir / f"zoomed{source_suffix}"
    filtered_audio_path = bundle_dir / f"zoomed_filtered{source_suffix}"
    spectrogram_wav_path = bundle_dir / "spectrogram.wav"
    render_audio_path = filtered_audio_path if filter_enabled else zoomed_audio_path
    source_temp_path = _detail_asset_temp_path(zoomed_audio_path)
    filtered_temp_path = _detail_asset_temp_path(filtered_audio_path)
    spectrogram_temp_path = _detail_asset_temp_path(spectrogram_wav_path)
    manifest_path = bundle_dir / _DETAIL_ASSET_MANIFEST_FILENAME
    manifest_temp_path: Path | None = None
    temp_paths = [source_temp_path, filtered_temp_path, spectrogram_temp_path]

    try:
        should_trim = start_sample != 0 or duration_sample != total_frames
        if should_trim:
            _run_sox(
                _sox_selection_command(
                    audio_path,
                    source_temp_path,
                    start_sample=start_sample,
                    duration_sample=duration_sample,
                )
            )
        else:
            shutil.copyfile(audio_path, source_temp_path)
        if not _validate_cached_audio(source_temp_path):
            raise RuntimeError("Generated detail selection is invalid")

        artifacts = {
            "zoomed_audio": {
                "filename": zoomed_audio_path.name,
                "size": source_temp_path.stat().st_size,
            }
        }
        if filter_enabled:
            filter_command = _sox_filter_command(
                source_temp_path if should_trim else audio_path,
                filtered_temp_path,
                sample_rate=sample_rate,
                min_freq=min_freq,
                max_freq=max_freq,
            )
            _run_sox(filter_command)
            if not _validate_cached_audio(filtered_temp_path):
                raise RuntimeError("Generated filtered detail selection is invalid")
            artifacts["filtered_audio"] = {
                "filename": filtered_audio_path.name,
                "size": filtered_temp_path.stat().st_size,
            }

        if render_audio_path.suffix.lower() == ".wav":
            shutil.copyfile(
                filtered_temp_path if filter_enabled else source_temp_path,
                spectrogram_temp_path,
            )
        else:
            _run_sox(
                [
                    "sox",
                    str(filtered_temp_path if filter_enabled else source_temp_path),
                    str(spectrogram_temp_path),
                ]
            )
        if not _validate_cached_audio(spectrogram_temp_path):
            raise RuntimeError("Generated spectrogram WAV is invalid")
        render_input_artifact = "filtered_audio" if filter_enabled else "zoomed_audio"
        artifacts["spectrogram_wav"] = {
            "filename": spectrogram_wav_path.name,
            "size": spectrogram_temp_path.stat().st_size,
            "format": "wav",
            "input_artifact": render_input_artifact,
            "input_format": render_audio_path.suffix.lower().lstrip(".") or "wav",
        }

        manifest = {
            "version": _DETAIL_ASSET_MANIFEST_VERSION,
            "parameters": parameters,
            "source": source,
            "selection_sample_rate": int(sample_rate),
            "artifacts": artifacts,
        }
        manifest_temp_path = _write_detail_manifest_temp(manifest_path, manifest)
        temp_paths.append(manifest_temp_path)
        replacements = [
            (source_temp_path, zoomed_audio_path),
            (spectrogram_temp_path, spectrogram_wav_path),
        ]
        if filter_enabled:
            replacements.append((filtered_temp_path, filtered_audio_path))
        replacements.append((manifest_temp_path, manifest_path))
        _publish_detail_selection(replacements)
    finally:
        for temp_path in temp_paths:
            temp_path.unlink(missing_ok=True)


def _write_playback_atomically(
    source_path: Path,
    target_path: Path,
    output_format: str,
) -> None:
    temp_path = _detail_asset_temp_path(target_path)
    try:
        if output_format == "mp3":
            _run_lame(
                [
                    "lame",
                    "--noreplaygain",
                    "-f",
                    "-b",
                    "128",
                    str(source_path),
                    str(temp_path),
                ]
            )
        elif output_format == "ogg":
            _run_sox(["sox", str(source_path), "-C", "10", str(temp_path)])
        elif output_format == "wav" and source_path.suffix.lower() != ".wav":
            _run_sox(["sox", str(source_path), str(temp_path)])
        else:
            shutil.copyfile(source_path, temp_path)
        if not _validate_cached_audio(temp_path):
            raise RuntimeError(f"Generated {output_format} playback is invalid")
        os.replace(temp_path, target_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _guess_audio_mimetype(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".aif": "audio/aiff",
        ".aiff": "audio/aiff",
    }.get(ext, "audio/octet-stream")


def _format_detail_time_token(value: float) -> str:
    text = f"{round(float(value), _DETAIL_PARAM_PRECISION):.{_DETAIL_PARAM_PRECISION}f}"
    return text.rstrip("0").rstrip(".") or "0"


def _format_detail_freq_token(value: float) -> str:
    text = f"{round(float(value), _DETAIL_PARAM_PRECISION):.{_DETAIL_PARAM_PRECISION}f}"
    return text.rstrip("0").rstrip(".") or "0"


def _build_detail_download_basename(
    *,
    filename: str,
    min_freq: float,
    max_freq: float,
    start_time: float,
    end_time: float,
    fft_size: int,
    channel: int,
    filter_enabled: bool,
) -> str:
    stem = Path(filename or "media").stem or "media"
    suffix = "_filtered" if filter_enabled else ""
    return (
        f"{stem}_{_format_detail_freq_token(min_freq)}-{_format_detail_freq_token(max_freq)}"
        f"_{_format_detail_time_token(start_time)}-{_format_detail_time_token(end_time)}"
        f"_{int(fft_size)}_{int(channel)}{suffix}"
    )


def get_or_create_detail_asset_bundle(
    session: Session,
    media_id: int,
    *,
    start_time: float,
    end_time: float | None,
    min_freq: float,
    max_freq: float | None,
    channel: int,
    filter_enabled: bool,
    fft_size: int,
    build_playback: bool = True,
) -> DetailAssetBundle:
    """Build or reuse detail-view assets for one viewport selection."""
    media = media_repository.get_with_detail_relations(session, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    audio_path = _get_audio_path_for_media(media)
    if audio_path is None:
        raise HTTPException(status_code=404, detail="Audio media not found on server")

    audio_info = _read_source_audio_info(audio_path)
    sample_rate = (
        int(media.audio_setting.sampling_rate_hz)
        if media.audio_setting is not None and media.audio_setting.sampling_rate_hz
        else int(audio_info.samplerate)
    )
    total_duration = (
        float(audio_info.frames) / float(audio_info.samplerate)
        if audio_info.samplerate
        else 0.0
    )
    actual_start_time = round(
        min(max(0.0, float(start_time)), total_duration),
        _DETAIL_PARAM_PRECISION,
    )
    requested_end_time = total_duration if end_time is None else max(float(end_time), actual_start_time)
    actual_end_time = round(
        min(requested_end_time, total_duration),
        _DETAIL_PARAM_PRECISION,
    )
    if actual_end_time < actual_start_time:
        actual_end_time = actual_start_time
    normalized_end_time = None if end_time is None else actual_end_time
    total_frames = int(audio_info.frames)
    start_sample = min(
        total_frames,
        _round_sample_half_up(actual_start_time * sample_rate),
    )
    duration_sample = min(
        max(0, total_frames - start_sample),
        _round_sample_half_up((actual_end_time - actual_start_time) * sample_rate),
    )
    source_suffix = audio_path.suffix.lower() or ".wav"
    freq_lo, freq_hi = _normalize_detail_freq_band(sample_rate, min_freq, max_freq)
    download_basename = _build_detail_download_basename(
        filename=media.filename or f"media-{media.media_id}",
        min_freq=freq_lo,
        max_freq=freq_hi,
        start_time=actual_start_time,
        end_time=actual_end_time,
        fft_size=fft_size,
        channel=channel,
        filter_enabled=filter_enabled,
    )
    key = _detail_asset_key(
        media_id=media_id,
        start_time=actual_start_time,
        end_time=normalized_end_time,
        min_freq=freq_lo,
        max_freq=freq_hi,
        channel=channel,
        filter_enabled=filter_enabled,
        fft_size=fft_size,
    )
    output_format = _detail_output_format(
        sample_rate=sample_rate,
        source_path=audio_path,
    )
    bundle_dir = _detail_asset_root() / str(media_id) / key
    source_audio_path = bundle_dir / f"zoomed{source_suffix}"
    filtered_audio_path = bundle_dir / f"zoomed_filtered{source_suffix}"
    spectrogram_wav_path = bundle_dir / "spectrogram.wav"
    parameters = _detail_asset_parameters(
        media_id=media_id,
        start_time=actual_start_time,
        end_time=normalized_end_time,
        min_freq=freq_lo,
        max_freq=freq_hi,
        channel=channel,
        filter_enabled=filter_enabled,
        fft_size=fft_size,
    )
    _cleanup_stale_detail_assets()
    try:
        with _detail_asset_lock(key) as waited_seconds:
            current_audio_info = _read_source_audio_info(audio_path)
            source = _source_audio_fingerprint(
                audio_path,
                current_audio_info.samplerate,
            )
            manifest, cache_status = _read_valid_detail_manifest(
                bundle_dir,
                parameters=parameters,
                source=source,
                filter_enabled=filter_enabled,
            )
            if manifest is None:
                logger.info(
                    "Rebuilding detail asset cache",
                    extra={
                        "media_id": media_id,
                        "cache_key": key,
                        "cache_reason": cache_status,
                        "lock_wait_seconds": round(waited_seconds, 6),
                    },
                )
                _rebuild_detail_selection(
                    bundle_dir=bundle_dir,
                    audio_path=audio_path,
                    start_sample=start_sample,
                    duration_sample=duration_sample,
                    total_frames=total_frames,
                    source_suffix=source_suffix,
                    filter_enabled=filter_enabled,
                    min_freq=freq_lo,
                    max_freq=freq_hi,
                    sample_rate=sample_rate,
                    parameters=parameters,
                    source=source,
                )
                manifest, cache_status = _read_valid_detail_manifest(
                    bundle_dir,
                    parameters=parameters,
                    source=source,
                    filter_enabled=filter_enabled,
                )
                if manifest is None:
                    raise RuntimeError(
                        f"Detail asset cache validation failed after rebuild: {cache_status}"
                    )
            else:
                logger.debug(
                    "Detail asset cache hit",
                    extra={
                        "media_id": media_id,
                        "cache_key": key,
                        "lock_wait_seconds": round(waited_seconds, 6),
                    },
                )

            render_source_path = filtered_audio_path if filter_enabled else source_audio_path
            manifest_path = bundle_dir / _DETAIL_ASSET_MANIFEST_FILENAME
            if not build_playback:
                playback_path = render_source_path
                output_format = render_source_path.suffix.lower().lstrip(".") or "wav"
            elif output_format == render_source_path.suffix.lower().lstrip("."):
                playback_path = render_source_path
            else:
                playback_path = bundle_dir / f"playback.{output_format}"
                if not _validate_cached_playback(playback_path, manifest_path):
                    _write_playback_atomically(
                        render_source_path,
                        playback_path,
                        output_format,
                    )
            _touch_detail_asset(bundle_dir)
    except _DetailAssetLockTimeoutError:
        logger.warning(
            "Timed out waiting for detail asset cache lock",
            extra={
                "media_id": media_id,
                "cache_key": key,
                "lock_timeout_seconds": _DETAIL_ASSET_LOCK_TIMEOUT_SECONDS,
            },
        )
        raise HTTPException(
            status_code=503,
            detail="Spectrogram audio cache is busy",
            headers={"Retry-After": "1"},
        )

    return DetailAssetBundle(
        source_audio_path=render_source_path,
        spectrogram_audio_path=spectrogram_wav_path,
        playback_audio_path=playback_path,
        playback_format=output_format,
        download_basename=download_basename,
        key=key,
    )


def get_audio_stream_payload(
    session: Session,
    media_id: int,
    *,
    start_time: float | None,
    end_time: float | None,
    min_freq: float | None,
    max_freq: float | None,
    channel: int | None,
    filter_enabled: bool,
    fft_size: int,
) -> tuple[Path, str, str | None]:
    """Return a direct file path for both original and processed audio."""
    media = media_repository.get_with_detail_relations(session, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    audio_path = _get_audio_path_for_media(media)
    if audio_path is None:
        raise HTTPException(status_code=404, detail="Audio media not found on server")

    if (
        start_time is None
        and end_time is None
        and min_freq is None
        and max_freq is None
        and not filter_enabled
    ):
        return audio_path, _guess_audio_mimetype(str(audio_path)), None

    bundle = get_or_create_detail_asset_bundle(
        session,
        media_id,
        start_time=float(start_time or 0.0),
        end_time=end_time,
        min_freq=float(min_freq or 0.0),
        max_freq=max_freq,
        channel=int(channel or 0),
        filter_enabled=filter_enabled,
        fft_size=fft_size,
    )
    return (
        bundle.playback_audio_path,
        _guess_audio_mimetype(str(bundle.playback_audio_path)),
        f"{bundle.download_basename}.{bundle.playback_format}",
    )


def render_dynamic_spectrogram(
    session: Session,
    media_id: int,
    *,
    start_time: float,
    end_time: float | None,
    min_freq: float,
    max_freq: float | None,
    fft_size: int,
    window: str,
    channel: int,
    width_px: int,
    height_px: int,
    apply_frequency_filter: bool,
) -> bytes:
    """Render a spectrogram PNG from the shared detail-view selection bundle."""
    # Match legacy svt.py / ImageService default lower bound (f_min=1).
    render_min_freq = DETAIL_DEFAULT_MIN_FREQ if float(min_freq) <= 0 else float(min_freq)
    bundle = get_or_create_detail_asset_bundle(
        session,
        media_id,
        start_time=start_time,
        end_time=end_time,
        min_freq=render_min_freq,
        max_freq=max_freq,
        channel=channel,
        filter_enabled=apply_frequency_filter,
        fft_size=fft_size,
        build_playback=False,
    )
    return generate_spectrogram_png(
        audio_path=str(bundle.spectrogram_audio_path),
        start_time=0.0,
        end_time=None,
        min_freq=render_min_freq,
        max_freq=max_freq,
        fft_size=fft_size,
        window=window,
        channel=channel,
        width_px=width_px,
        height_px=height_px,
        apply_frequency_filter=False,
    )


def get_spectrogram_download_filename(
    session: Session,
    media_id: int,
    *,
    start_time: float,
    end_time: float | None,
    min_freq: float,
    max_freq: float | None,
    fft_size: int,
    channel: int,
    apply_frequency_filter: bool,
) -> str:
    """Return the spectrogram download filename for one viewport selection."""
    bundle = get_or_create_detail_asset_bundle(
        session,
        media_id,
        start_time=start_time,
        end_time=end_time,
        min_freq=min_freq,
        max_freq=max_freq,
        channel=channel,
        filter_enabled=apply_frequency_filter,
        fft_size=fft_size,
        build_playback=False,
    )
    return f"{bundle.download_basename}.png"


def get_spectrogram(
    session: Session,
    media_id: int,
    *,
    start_time: float,
    end_time: float | None,
    min_freq: float,
    max_freq: float | None,
    fft_size: int,
    window: str,
    channel: int,
    width_px: int,
    height_px: int,
    apply_frequency_filter: bool = False,
) -> bytes:
    """Render a detail-view spectrogram PNG for the current request."""
    media = media_repository.get_with_detail_relations(session, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    return render_dynamic_spectrogram(
        session,
        media_id,
        start_time=start_time,
        end_time=end_time,
        min_freq=min_freq,
        max_freq=max_freq,
        fft_size=fft_size,
        window=window,
        channel=channel,
        width_px=width_px,
        height_px=height_px,
        apply_frequency_filter=apply_frequency_filter,
    )


def get_preview_file_path(session: Session, media_id: int, preview_id: int) -> Path:
    """Resolve the physical preview file path for a media preview."""
    media = media_repository.get_with_detail_relations(session, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media file not found")

    preview = session.get(Preview, preview_id)
    if not preview or preview.media_id != media_id:
        raise HTTPException(status_code=404, detail="Preview not found")

    file_path = _resolve_preview_file_path(media, preview)
    if file_path is None:
        raise HTTPException(status_code=404, detail="Preview file not found on server")
    return file_path


def get_media_content_path(session: Session, media_id: int) -> Path:
    """Resolve an original photo file after the route has completed access checks."""
    media = media_repository.get_with_detail_relations(session, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media file not found")
    if media.media_type != "photo" or not media.filename:
        raise HTTPException(status_code=404, detail="Photo content is not available for this media")
    primary_collection = _get_primary_media_collection(media)
    if not primary_collection:
        raise HTTPException(status_code=404, detail="Media collection not found")
    path = resolve_existing_media_path(
        logical_photo_media_path(primary_collection.collection_id, media.directory or "", media.filename)
    )
    if path is None:
        raise HTTPException(status_code=404, detail="Photo file not found on server")
    return path


def get_media_collection_link_options(
    session: Session,
    media_id: int,
    user: User,
    *,
    project_id: int,
    name: str | None = None,
    other_project_name: str | None = None,
) -> MediaCollectionLinkOptionsResponse:
    """Get grouped collection-link options for a media record."""
    media = media_repository.get(session, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    project = project_repository.get(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    selected_collection_ids = sorted(
        {mc.collection_id for mc in (media.media_collections or [])}
    )
    current_collection_ids = set(
        project_repository.get_project_collection_ids(session, project_id)
    )

    manageable_user_id = None if permission_service.is_admin(user) else user.user_id

    current_rows = project_repository.get_manageable_project_collection_rows(
        session,
        user_id=manageable_user_id,
        exclude_project_id=None,
        collection_name=name,
        project_name=None,
    )
    current_collections: list[dict] = []
    for pid, _project_name, cid, cname in current_rows:
        if pid != project_id:
            continue
        current_collections.append(
            {
                "collection_id": cid,
                "name": cname,
                "selected": cid in selected_collection_ids,
            }
        )

    other_rows = project_repository.get_manageable_project_collection_rows(
        session,
        user_id=manageable_user_id,
        exclude_project_id=project_id,
        collection_name=name,
        project_name=other_project_name,
    )

    duplicates_map: dict[int, set[int]] = {}
    for pid, _project_name, cid, _collection_name in other_rows:
        if cid in current_collection_ids:
            continue
        duplicates_map.setdefault(cid, set()).add(pid)

    other_projects_map: dict[int, dict] = {}
    for pid, pname, cid, cname in other_rows:
        if cid in current_collection_ids:
            continue
        if pid not in other_projects_map:
            other_projects_map[pid] = {
                "project_id": pid,
                "project_name": pname,
                "collections": [],
            }
        other_projects_map[pid]["collections"].append(
            {
                "collection_id": cid,
                "name": cname,
                "selected": cid in selected_collection_ids,
                "duplicate_project_ids": sorted(duplicates_map.get(cid, set())),
            }
        )
    other_projects = list(other_projects_map.values())

    manageable_collection_ids: list[int] | None = None
    if not permission_service.is_admin(user):
        manageable_collection_ids = permission_repository.get_accessible_collection_ids(
            session,
            user.user_id,
            resource_type="collection",
            action="write",
        )
    unassigned = project_repository.get_unassigned_collections(
        session,
        collection_ids=manageable_collection_ids,
        name=name,
    )
    unassigned_collections = [
        {
            "collection_id": collection.collection_id,
            "name": collection.name,
            "selected": collection.collection_id in selected_collection_ids,
        }
        for collection in unassigned
        if collection.collection_id not in current_collection_ids
    ]

    return MediaCollectionLinkOptionsResponse.model_validate(
        {
            "current_project": {
                "project_id": project.project_id,
                "project_name": project.name,
                "collections": current_collections,
            },
            "other_projects": other_projects,
            "unassigned_collections": unassigned_collections,
            "selected_collection_ids": selected_collection_ids,
        }
    )


def sync_media_collections(
    session: Session,
    media_id: int,
    user: User,
    collection_ids: list[int],
    *,
    project_id: int,
) -> None:
    """Fully sync collection bindings for a media record."""
    media = media_repository.get(session, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    requested_collection_ids = sorted(set(collection_ids))

    require_media_resource_write(session, user, media_id, project_id=project_id)
    if not permission_service.is_admin(user):
        requested_scopes = [
            (project_id, collection_id) for collection_id in requested_collection_ids
        ]
        if not permission_repository.has_all_effective_collection_scopes(
            session,
            user.user_id,
            requested_scopes,
            "audio",
            "write",
        ):
            allowed_collection_ids = set(
                permission_repository.get_accessible_project_collection_ids(
                    session,
                    user.user_id,
                    project_id,
                    "audio",
                    "write",
                )
            )
            disallowed_collection_ids = [
                collection_id
                for collection_id in requested_collection_ids
                if collection_id not in allowed_collection_ids
            ]
            raise HTTPException(
                status_code=403,
                detail=f"No write permission on collection(s): {disallowed_collection_ids}",
            )

    existing_collection_ids = set(
        session.exec(
            select(Collection.collection_id).where(
                Collection.collection_id.in_(requested_collection_ids)
            )
        ).all()
    )
    missing_collection_ids = sorted(
        set(requested_collection_ids) - existing_collection_ids
    )
    if missing_collection_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Collection(s) not found: {missing_collection_ids}",
        )

    media_repository.bind_to_collections(
        session,
        media_id=media_id,
        collection_ids=requested_collection_ids,
        added_by=user.user_id,
    )


def sync_media_collection_links(
    session: Session,
    user: User,
    media_ids: list[int],
    collection_ids: list[int],
    *,
    project_id: int,
) -> MediaBatchOperationResponse:
    """Fully sync the same collection bindings across multiple media records."""
    succeeded: list[int] = []
    failed: list[MediaBatchFailedItem] = []

    for media_id in sorted(set(media_ids)):
        try:
            sync_media_collections(
                session,
                media_id,
                user,
                collection_ids,
                project_id=project_id,
            )
            succeeded.append(media_id)
        except HTTPException as exc:
            failed.append(
                MediaBatchFailedItem(
                    media_id=media_id,
                    status_code=exc.status_code,
                    message=str(exc.detail),
                )
            )

    return MediaBatchOperationResponse(succeeded=succeeded, failed=failed)


def _build_media_public(
    session: Session,
    media: Media,
    user: User | None,
    *,
    project_id: int,
    include_image_dimensions: bool = True,
    scoped_collection_ids: set[int] | None = None,
) -> MediaPublic:
    # Per-user labels are returned as-is; empty means no explicit label.
    user_labels = [
        lm.label.name
        for lm in media.label_media
        if user and lm.user_id == user.user_id and lm.label
    ]
    labels = user_labels

    # Previews: return normalized static URLs (same strategy as browse preview_url).
    previews: list[PreviewPublic] = []
    for p in sorted(media.previews, key=_preview_priority):
        static_url = _build_preview_public_url(media, p)
        if not static_url:
            continue
        previews.append(
            PreviewPublic(
                preview_id=p.preview_id,
                media_id=p.media_id,
                type=p.type,
                url=static_url,
            )
        )

    # Collection and project info use a stable collection selection to keep the
    # response deterministic when a media is linked to multiple collections.
    collection_id = None
    collection_name = None
    collection_sphere = None
    response_project_id = None
    project_name = None

    media_collections = list(media.media_collections or [])
    # List/export callers pass the pre-resolved scope so row building stays
    # free of per-row queries; single-media callers fall back to one lookup.
    if scoped_collection_ids is None:
        scoped_collection_ids = set(
            session.exec(
                select(ProjectCollection.collection_id).where(
                    ProjectCollection.project_id == project_id
                )
            ).all()
        )
    media_collections = [
        mc for mc in media_collections if mc.collection_id in scoped_collection_ids
    ]

    media_collection = (
        sorted(media_collections, key=lambda mc: mc.collection_id)[0]
        if media_collections
        else None
    )
    if media_collection:
        col = media_collection.collection or session.get(
            Collection, media_collection.collection_id
        )
        if col:
            collection_id = col.collection_id
            collection_name = col.name
            collection_sphere = col.sphere
            # Collection membership in the project is already guaranteed by
            # the scope filter above; session.get hits the identity map
            # after the first row.
            proj = session.get(Project, project_id)
            if proj:
                response_project_id = proj.project_id
                project_name = proj.name

    audio_url = None
    if media.media_type == "audio" and not media.is_metadata:
        audio_url = f"{settings.API_V1_STR}/media/{media.media_id}/audio?project_id={project_id}"

    media_url = None
    image_width = None
    image_height = None
    if media.media_type == "photo" and not media.is_metadata:
        media_url = f"{settings.API_V1_STR}/media/{media.media_id}/content?project_id={project_id}"
        if include_image_dimensions:
            try:
                from PIL import Image
                photo_path = get_media_content_path(session, media.media_id)
                with Image.open(photo_path) as image:
                    image_width, image_height = image.size
            except (HTTPException, OSError):
                pass

    site_realm_name = media.site.realm.name if media.site and media.site.realm else None
    theme_value = site_realm_name or collection_sphere
    theme_source = (
        "site_realm"
        if site_realm_name
        else ("collection_sphere" if collection_sphere else None)
    )

    return MediaPublic(
        media_id=media.media_id,
        uuid=media.uuid,
        media_type=media.media_type,
        is_metadata=media.is_metadata,
        filename=media.filename,
        name=media.name,
        medium=media.medium,
        note=media.note,
        doi=media.doi,
        date_time=media.date_time,
        size_b=media.size_b,
        md5_hash=media.md5_hash,
        duty_cycle_recording=media.duty_cycle_recording,
        duty_cycle_period=media.duty_cycle_period,
        creation_date=media.creation_date,
        uploader_id=media.uploader_id,
        uploader_name=media.uploader_name,
        creator_id=media.creator_id,
        creator_name=media.creator_name,
        site_id=media.site_id,
        site_name=(media.site.name if media.site else None),
        theme_value=theme_value,
        theme_source=theme_source,
        sensor_id=media.sensor_id,
        sensor_name=(media.sensor.name if media.sensor else None),
        license_id=media.license_id,
        license_name=(media.license.name if media.license else None),
        collection_id=collection_id,
        collection_name=collection_name,
        project_id=response_project_id,
        project_name=project_name,
        audio_url=audio_url,
        media_url=media_url,
        image_width=image_width,
        image_height=image_height,
        previews=previews,
        audio_setting=media.audio_setting,
        photo_setting=PhotoSettingPublic.model_validate(media.photo_setting) if media.photo_setting else None,
        labels=labels,
    )


def update_media(
    session: Session,
    media_id: int,
    media_in: MediaUpdate,
    current_user: User | None = None,
    project_id: int | None = None,
) -> None:
    """
    Update a media record.

    Requires write permission on the media's collection.

    Args:
        session: Database session
        media_id: Media ID
        media_in: MediaUpdate data
    Returns:
        None
    """
    media = media_repository.get(session, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    # Permission check handled by PermissionChecker dependency in route

    raw_payload = media_in.model_dump(exclude_unset=True)

    # Extract audio setting fields from the raw payload BEFORE sanitization,
    # because _sanitize_media_update_payload only allows Media-table columns and
    # would strip these fields, making audio_update_data always empty.
    audio_setting_fields = {
        "recording_gain_db",
        "sampling_rate_hz",
        "bit_depth",
        "channel_num",
        "duration_s",
    }
    audio_update_data = {k: raw_payload[k] for k in raw_payload if k in audio_setting_fields}

    audio_only_fields = audio_setting_fields | {
        "duty_cycle_recording",
        "duty_cycle_period",
    }
    forbidden_fields = sorted(set(raw_payload) & audio_only_fields)
    # Photo media (including photo metadata) has no audio-only fields; audio
    # metadata keeps its manually-entered technical settings, so it is allowed.
    if media.media_type == MediaType.PHOTO.value and forbidden_fields:
        raise HTTPException(
            status_code=422,
            detail=(
                "Photo media must not include audio-only fields: "
                + ", ".join(forbidden_fields)
            ),
        )

    if audio_update_data and media.media_type != MediaType.AUDIO.value:
        raise HTTPException(
            status_code=422,
            detail="Audio setting fields can only be updated for audio media",
        )

    update_data = _sanitize_media_update_payload(media, raw_payload)
    if "creator_id" in raw_payload:
        if raw_payload["creator_id"] is None:
            update_data["creator_id"] = None
        else:
            if current_user is None or project_id is None:
                raise HTTPException(status_code=400, detail="Creator update requires project context")
            collection_ids = list(session.exec(
                select(MediaCollection.collection_id)
                .join(
                    ProjectCollection,
                    ProjectCollection.collection_id == MediaCollection.collection_id,
                )
                .where(
                    MediaCollection.media_id == media_id,
                    ProjectCollection.project_id == project_id,
                )
            ).all())
            if not collection_ids:
                raise HTTPException(
                    status_code=403,
                    detail="Media is not linked to the current project",
                )
            update_data["creator_id"] = _resolve_creator_id(
                session,
                raw_payload["creator_id"],
                current_user,
                collection_ids,
                project_id,
            )
    if "date_time" in update_data and update_data["date_time"]:
        update_data["date_time"] = datetime.strptime(
            update_data["date_time"], "%Y-%m-%d %H:%M:%S"
        )

    if "sensor_id" in update_data and update_data["sensor_id"] is not None:
        sensor = session.get(Sensor, update_data["sensor_id"])
        if sensor is None:
            raise HTTPException(status_code=422, detail=f"Sensor with id={update_data['sensor_id']} not found")
        _validate_sensor_matches_media_type(sensor, media.media_type)

    try:
        # Do not use media_repository.update here: it commits independently and would
        # make a later settings failure leave a partially persisted PATCH behind.
        media.sqlmodel_update(update_data)
        session.add(media)

        if audio_update_data:
            audio_setting = media.audio_setting
            if audio_setting is None:
                # Metadata records may lack technical settings; create one so the
                # user-provided values can be persisted. Real audio media always
                # has settings extracted from its source file.
                if media.is_metadata:
                    audio_setting = AudioSetting(duration_s=0.0)
                    media.audio_setting = audio_setting
                else:
                    raise HTTPException(
                        status_code=409,
                        detail="Audio media has no associated audio settings",
                    )
            audio_setting.sqlmodel_update(audio_update_data)
            session.add(audio_setting)

        session.commit()
        session.refresh(media)
    except Exception:
        session.rollback()
        raise


def _validate_sensor_matches_media_type(sensor: Sensor, media_type: MediaType | str) -> None:
    """Reject audio/photo media paired with a sensor of the other type."""
    normalized_media_type = (
        media_type.value if isinstance(media_type, MediaType) else str(media_type).lower()
    )
    if normalized_media_type not in {MediaType.AUDIO.value, MediaType.PHOTO.value}:
        return
    if sensor.sensor_type.lower() != normalized_media_type:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Sensor with id={sensor.sensor_id} has type '{sensor.sensor_type}'; "
                f"it cannot be used for {normalized_media_type} media"
            ),
        )


def _sanitize_media_update_payload(media: Media, update_data: dict[str, Any]) -> dict[str, Any]:
    """Keep media updates aligned with the current media/settings split."""
    allowed_fields = {
        "name",
        "medium",
        "note",
        "doi",
        "date_time",
        "site_id",
        "sensor_id",
        "license_id",
        "creator_id",
        "duty_cycle_recording",
        "duty_cycle_period",
    }
    sanitized = {key: value for key, value in update_data.items() if key in allowed_fields}

    dropped_fields = sorted(set(update_data) - set(sanitized))
    if dropped_fields:
        logger.warning(
            "Dropped unsupported media update fields for media_id=%s media_type=%s: %s",
            media.media_id,
            media.media_type,
            ", ".join(dropped_fields),
        )

    return sanitized


def delete_media(
    session: Session, media_id: int, user: User, project_id: int | None = None
):
    """
    Delete a media record.

    Requires audio:write on at least one project-local collection path.

    Args:
        session: Database session
        media_id: Media ID
        user: Current user

    Returns:
        Success response
    """
    require_media_resource_write(
        session,
        user,
        media_id,
        project_id=project_id,
        denied_detail="No audio:write permission on this media",
    )

    media_repository.delete(session, id=media_id)
    return ApiResponse(message="Media deleted successfully")


def export_media_csv(
    session: Session,
    user: User,
    project_id: int,
    media_type: Literal["audio", "photo"],
    collection_id: int | None = None,
    order_by: str = "media_id",
    order_dir: str = "asc",
) -> str:
    """
    Export media to CSV format based on user permissions.

    Args:
        session: Database session
        user: Current user
        project_id: Filter by project ID
        collection_id: Optional filter by collection ID

    Returns:
        CSV content string
    """
    scoped_collection_ids = _resolve_visible_media_collection_ids(
        session,
        user,
        project_id=project_id,
        collection_id=collection_id,
    )
    media_list, _ = _query_visible_media(
        session,
        user,
        filters={
            "media_type": media_type,
            "scoped_collection_ids": scoped_collection_ids,
        },
        page_size=None,
        order_by=order_by,
        order_dir=order_dir,
        relation_profile="detail",
        include_total=False,
    )
    scope_set = set(scoped_collection_ids)
    data = [
        _build_media_public(
            session,
            media,
            user,
            project_id=project_id,
            scoped_collection_ids=scope_set,
        )
        for media in media_list
    ]
    columns = _PHOTO_EXPORT_COLUMNS if media_type == "photo" else _AUDIO_EXPORT_COLUMNS
    return export_columns_csv(columns, data)


def get_media_options(
    session: Session,
    user: User | None,
    project_id: int,
    collection_id: int | None = None,
    name: str | None = None,
) -> list[MediaOption]:
    """
    获取媒体下拉选项列表，仅返回 media_id 和 name 字段。 / Get media dropdown options.

    - 匿名用户 (Anonymous)：仅返回该项目下公开集合中的媒体
    - 管理员 (Admin)：返回该项目下全部媒体
    - 普通用户 (Regular user)：仅返回可访问集合内的媒体

    支持按 name / filename 进行模糊筛选。 / Supports fuzzy filter by name / filename.

    Args:
        session: Database session
        user: Current authenticated user (or None for anonymous)
        project_id: Filter by project ID (required)
        collection_id: Optional filter by collection ID
        name: Optional fuzzy filter applied to both name and filename fields

    Returns:
        List of MediaOption instances
    """
    filters: dict = {}
    if collection_id is not None:
        filters["collection_id"] = collection_id
    if name:
        filters["search"] = name

    visibility, user_id = _media_visibility(user)
    rows = media_repository.list_options_filtered(
        session,
        visibility=visibility,
        user_id=user_id,
        project_id=project_id,
        **filters,
    )
    return [
        MediaOption(media_id=row.media_id, name=row.name or row.filename, media_type=row.media_type)
        for row in rows
    ]


def get_media_navigation(
    session: Session, media_id: int, collection_id: int, _user: User
) -> MediaNavigation:
    # Verify the media belongs to the given collection
    mc_check = session.exec(
        select(MediaCollection).where(
            MediaCollection.media_id == media_id,
            MediaCollection.collection_id == collection_id,
        )
    ).first()
    if not mc_check:
        raise HTTPException(
            status_code=404, detail="Media not found in specified collection"
        )

    # Adjacent rows only; avoids loading the whole collection into memory.
    base = (
        select(Media.media_id, Media.name)
        .join(MediaCollection, Media.media_id == MediaCollection.media_id)
        .where(MediaCollection.collection_id == collection_id)
    )
    prev_row = session.exec(
        base.where(Media.media_id < media_id)
        .order_by(Media.media_id.desc())
        .limit(1)
    ).first()
    next_row = session.exec(
        base.where(Media.media_id > media_id)
        .order_by(Media.media_id.asc())
        .limit(1)
    ).first()

    prev_item = (
        MediaNavigationItem(media_id=prev_row[0], name=prev_row[1])
        if prev_row
        else None
    )
    next_item = (
        MediaNavigationItem(media_id=next_row[0], name=next_row[1])
        if next_row
        else None
    )

    return MediaNavigation(prev=prev_item, next=next_item)
