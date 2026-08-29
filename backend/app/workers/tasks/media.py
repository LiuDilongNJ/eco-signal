"""Media processing tasks."""
import datetime
import hashlib
import logging
import shutil
from datetime import datetime as dt
from pathlib import Path
from time import monotonic
from typing import Any

import mutagen
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlmodel import Session, select

from app.core.db import engine
from app.enums import QueueStatus
from app.core.task_cancellation import CancellationToken
from app.media_paths import (
    logical_audio_media_path,
    logical_photo_media_path,
    media_root,
    normalize_media_relative_path,
    primary_media_path,
)
from app.models import FileUpload, Media, AudioSetting, MediaCollection, Queue, PhotoSetting
from app.services.file_service import file_service
from app.services.media_preview_service import (
    generate_media_previews,
    generate_photo_thumbnail,
)
from app.services.upload_validation_service import format_validation_error
from app.spectrogram import generate_player_spectrogram, generate_thumbnail

logger = logging.getLogger(__name__)

PLAYER_SPECTROGRAM_TYPE = "spectrogram"
_HASH_CHUNK_SIZE = 1024 * 1024
_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
_PHOTO_FORMATS = {"JPEG", "MPO", "PNG", "TIFF"}


def _md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_duplicate_media(
    session: Session,
    md5_hash: str | None,
    collection_id: int,
) -> int | None:
    """Return an existing media_id in the collection with the same MD5, if any."""
    if not md5_hash:
        return None
    return session.exec(
        select(Media.media_id)
        .join(MediaCollection, MediaCollection.media_id == Media.media_id)
        .where(
            Media.md5_hash == md5_hash,
            MediaCollection.collection_id == collection_id,
        )
        .limit(1)
    ).first()


def _logical_media_storage_path(
    *,
    media_type: str,
    collection_id: int,
    directory: int | str | None,
    filename: str,
) -> Path:
    if media_type == "photo":
        return logical_photo_media_path(collection_id, directory or "", filename)
    return logical_audio_media_path(collection_id, directory or "", filename)


def _player_spectrogram_filename(filename: str) -> str:
    return f"{Path(filename).stem}_player_s.png"


def _exif_float(value: object) -> float | None:
    try:
        if hasattr(value, "numerator") and hasattr(value, "denominator"):
            denominator = getattr(value, "denominator")
            return float(getattr(value, "numerator")) / float(denominator) if denominator else None
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, ZeroDivisionError):
        return None


_EXIF_IFD_TAG = 0x8769
_TAG_EXPOSURE_TIME = 33434
_TAG_F_NUMBER = 33437
_TAG_ISO = 34855
_TAG_DATETIME_ORIGINAL = 36867
_TAG_DATETIME = 306


def _exif_tag(exif: object, tag_id: int) -> object | None:
    if not exif:
        return None
    try:
        get_ifd = exif.get_ifd  # type: ignore[attr-defined]
        get_tag = exif.get  # type: ignore[attr-defined]
    except AttributeError:
        return None
    try:
        exif_ifd = get_ifd(_EXIF_IFD_TAG)
        if tag_id in exif_ifd:
            return exif_ifd.get(tag_id)
    except (KeyError, TypeError, ValueError):
        pass
    return get_tag(tag_id)


def _exif_iso(value: object | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        parsed = _exif_float(value)
        return int(parsed) if parsed is not None else None


def _photo_metadata(path: Path) -> tuple[dict[str, float | int | None], dt | None, tuple[int, int]]:
    """Verify an uploaded image and return the EXIF values used by the media record."""
    if path.suffix.lower() not in _PHOTO_EXTENSIONS:
        raise ValueError("Unsupported photo format; use JPEG, PNG, or TIFF")
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.format not in _PHOTO_FORMATS:
                raise ValueError("Unsupported photo format; use JPEG, PNG, or TIFF")
            image.seek(0)
            exif = image.getexif()
            exposure_s = _exif_float(_exif_tag(exif, _TAG_EXPOSURE_TIME))
            aperture = _exif_float(_exif_tag(exif, _TAG_F_NUMBER))
            iso = _exif_iso(_exif_tag(exif, _TAG_ISO))
            captured_at = None
            raw_datetime = _exif_tag(exif, _TAG_DATETIME_ORIGINAL) or _exif_tag(exif, _TAG_DATETIME)
            if raw_datetime:
                try:
                    captured_at = dt.strptime(str(raw_datetime), "%Y:%m:%d %H:%M:%S")
                except ValueError:
                    pass
            return (
                {"exposure_ms": exposure_s * 1000 if exposure_s is not None else None, "aperture": aperture, "iso": iso},
                captured_at,
                image.size,
            )
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Uploaded file is not a valid image") from exc


def _generate_photo_thumbnail(source: Path, target: Path) -> None:
    generate_photo_thumbnail(source, target)


async def process_media(
        ctx: dict[str, Any],
        file_upload_id: int,
        collection_id: int,
        creator_id: int | None = None,
        site_id: int | None = None,
        sensor_id: int | None = None,
        license_id: int | None = None,
        medium: str | None = None,
        media_type: str | None = None,
        recording_gain_db: int | None = None,
        file_date: str | None = None,
        file_time: str | None = None,
        duty_cycle_recording: int | None = None,
        duty_cycle_period: int | None = None,
        note: str | None = None,
        doi: str | None = None,
        display_filename: str | None = None,
) -> dict[str, Any]:
    """
    Process uploaded media file.

    This task:
    1. Normalizes audio uploads to FLAC when needed (physical storage)
    2. Extracts audio metadata (duration, sample rate, channels, bit depth)
    3. Creates media record where filename reflects normalized storage filename
    4. Moves file to permanent location
    5. Generates spectrogram/thumbnail previews for audio

    Args:
        ctx: ARQ context
        file_upload_id: FileUpload record ID
        collection_id: Target collection ID
        Other args: Media metadata

    Returns:
        Task execution result
    """
    cancellation_token: CancellationToken | None = ctx.get("cancellation_token")
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()

    with Session(engine) as session:
        file_upload = session.get(FileUpload, file_upload_id)
        if not file_upload:
            logger.error(f"FileUpload {file_upload_id} not found")
            return {"error": "FileUpload not found"}
            
        if not file_upload.path:
            if media_type == "photo":
                file_upload.status = 4
                file_upload.error = "Photo upload is incomplete"
                session.commit()
                return {"error": file_upload.error}
            logger.info(f"FileUpload {file_upload_id} has no path (likely merging). Retrying in 5 seconds...")
            from app.workers.exceptions import TaskRetryError
            raise TaskRetryError("FileUpload is still waiting for chunk merge", defer=5)

        try:
            # Update status to processing
            file_upload.status = 2  # processing
            session.commit()

            logger.info(f"Processing media file: {file_upload.filename}")

            actual_media_type = media_type or "audio"
            file_path = primary_media_path(file_upload.path)
            if not file_path.is_file():
                raise FileNotFoundError(f"File not found or is a directory: {file_path}")

            storage_filename = file_upload.filename
            media_filename = file_upload.filename
            media_name = file_upload.name
            if actual_media_type == "audio":
                resolved_display_filename = display_filename or file_upload.filename
                source_suffix = file_path.suffix.lower()
                started_at = monotonic()
                file_path, normalized_filename = file_service.ensure_audio_is_flac(
                    file_path,
                    source_filename=resolved_display_filename,
                )
                storage_filename = normalized_filename
                media_filename = normalized_filename
                media_name = file_upload.name or file_upload.filename
                file_upload.filename = normalized_filename
                file_upload.path = str(normalize_media_relative_path(file_path))
                logger.info(
                    "Normalized upload %s from %s to %s (display=%s) in %.3fs",
                    file_upload_id,
                    source_suffix or "<no_ext>",
                    normalized_filename,
                    resolved_display_filename,
                    monotonic() - started_at,
                )

            file_size = file_path.stat().st_size

            # Calculate MD5 hash and skip duplicates within the same collection
            md5_hash = _md5_file(file_path)
            duplicate_media_id = _find_duplicate_media(session, md5_hash, collection_id)
            if duplicate_media_id is not None:
                logger.info(
                    "Skipping duplicate media %s (matches media_id=%s in collection %s)",
                    file_upload.filename,
                    duplicate_media_id,
                    collection_id,
                )
                file_path.unlink(missing_ok=True)
                file_upload.status = 5  # duplicate/skipped
                file_upload.media_id = duplicate_media_id
                session.commit()
                processing_warning = (
                    f"File {media_name or media_filename} already exists in the collection."
                )
                return {
                    "status": "duplicate",
                    "file_upload_id": file_upload_id,
                    "filename": media_name or media_filename,
                    "existing_media_id": duplicate_media_id,
                }

            audio_setting_id: int | None = None
            photo_setting_id: int | None = None
            sampling_rate = 44100
            channel_num = 1
            if actual_media_type == "audio":
                # Extract audio metadata using mutagen or similar
                duration = 0.0
                bit_depth = 16
                try:
                    audio = mutagen.File(str(file_path))

                    if audio is None:
                        logger.info("mutagen returned None for file %s", file_path)
                    else:
                        info = getattr(audio, "info", None)
                        if info:
                            duration = getattr(info, "length", 0.0)
                            sampling_rate = getattr(info, "sample_rate", 44100)
                            channel_num = getattr(info, "channels", 1)
                            bit_depth = getattr(info, "bits_per_sample", 16)
                        else:
                            logger.warning("mutagen info is None for file %s", file_path)
                except Exception as e:
                    logger.warning(f"Could not extract audio metadata: {e}")

                audio_setting = AudioSetting(
                    recording_gain_db=recording_gain_db,
                    sampling_rate_hz=sampling_rate,
                    bit_depth=bit_depth,
                    channel_num=channel_num,
                    duration_s=duration,
                )
                session.add(audio_setting)
                session.flush()
                audio_setting_id = audio_setting.audio_setting_id
            elif actual_media_type == "photo":
                photo_values, photo_date_time, _ = _photo_metadata(file_path)
                photo_setting = PhotoSetting(**photo_values)
                session.add(photo_setting)
                session.flush()
                photo_setting_id = photo_setting.photo_setting_id

            # Parse datetime
            date_time = None
            if file_date and file_time:
                try:
                    date_time = dt.strptime(f"{file_date} {file_time}", "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
            elif actual_media_type == "photo":
                date_time = photo_date_time

            # Create media record
            media = Media(
                media_type=actual_media_type,
                directory=file_upload.directory,
                filename=media_filename,
                name=media_name,
                uploader_id=file_upload.uploader_id,
                creator_id=creator_id or file_upload.uploader_id,
                audio_setting_id=audio_setting_id,
                photo_setting_id=photo_setting_id,
                medium=medium,
                duty_cycle_recording=(duty_cycle_recording if actual_media_type == "audio" else None),
                duty_cycle_period=(duty_cycle_period if actual_media_type == "audio" else None),
                note=note,
                date_time=date_time,
                size_b=file_size,
                md5_hash=md5_hash,
                doi=doi,
            )

            # Only set foreign key fields if they have valid values (not None or 0)
            if site_id:
                media.site_id = site_id
            if sensor_id:
                media.sensor_id = sensor_id
            if license_id:
                media.license_id = license_id

            session.add(media)
            session.flush()

            # Create media_collection link
            media_collection = MediaCollection(
                media_id=media.media_id,
                collection_id=collection_id,
                added_by=file_upload.uploader_id,
            )
            session.add(media_collection)

            # Move file to permanent location by media type.
            target_dir = media_root() / _logical_media_storage_path(
                media_type=actual_media_type,
                collection_id=collection_id,
                directory=file_upload.directory,
                filename=storage_filename,
            ).parent
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / storage_filename

            shutil.move(str(file_path), str(target_path))

            preview_result = generate_media_previews(
                session,
                media=media,
                collection_id=collection_id,
                source_path=target_path,
                thumbnail_generator=generate_thumbnail,
                player_generator=generate_player_spectrogram,
                photo_generator=_generate_photo_thumbnail,
                atomic=False,
            )
            for preview_warning in preview_result.warnings:
                logger.warning("Preview generation failed for media %s: %s", media.media_id, preview_warning)

            # Update file_upload record
            file_upload.status = 3  # completed
            file_upload.media_id = media.media_id

            session.commit()

            logger.info(f"Media processed successfully: media_id={media.media_id}")

            return {
                "file_upload_id": file_upload_id,
                "media_id": media.media_id,
                "status": "completed",
            }

        except Exception as e:
            logger.exception(f"Failed to process media: {file_upload_id}")
            file_upload.status = 4  # error
            file_upload.error = str(e)
            session.commit()
            return {"error": str(e)}


def _mark_batch_queue_running(queue_id: int) -> None:
    with Session(engine) as session:
        queue = session.get(Queue, queue_id)
        if queue is None:
            return
        if queue.status == QueueStatus.PENDING:
            queue.status = QueueStatus.RUNNING
            queue.start_time = dt.now(datetime.UTC)
            session.add(queue)
            session.commit()


def _sync_batch_completed(queue_id: int, item_ids: list[int]) -> None:
    with Session(engine) as session:
        queue = session.exec(
            select(Queue).where(Queue.queue_id == queue_id).with_for_update()
        ).first()
        if queue is None or queue.status != QueueStatus.RUNNING:
            return
        queue.completed = sum(
            1
            for file_upload_id in item_ids
            if (file_upload := session.get(FileUpload, file_upload_id)) is not None
            and file_upload.status == 3
        )
        session.add(queue)
        session.commit()


def _batch_file_failure_message(file_upload: FileUpload | None) -> str:
    filename = file_upload.name if file_upload and file_upload.name else "unknown"
    error = file_upload.error.strip() if file_upload and file_upload.error else "unknown processing error"
    return f"File {filename} failed to process: {format_validation_error(error)}"


def _resolve_batch_queue_status(
    *,
    has_failures: bool,
    has_warning: bool,
) -> tuple[QueueStatus, str]:
    if has_failures:
        return QueueStatus.ERROR, "error"
    if has_warning:
        return QueueStatus.WARNING, "warning"
    return QueueStatus.COMPLETED, "completed"


def _merge_batch_file(
    file_upload_id: int,
    media_type: str,
) -> dict[str, Any]:
    with Session(engine) as session:
        file_upload = session.get(FileUpload, file_upload_id)
        if file_upload is None:
            return {"error": "FileUpload not found"}
        if file_upload.path:
            return {"status": "ready"}
        try:
            merged_path = file_service.merge_and_validate_chunks(
                filename=file_upload.filename,
                user_id=file_upload.uploader_id,
                batch_id=str(file_upload.batch_id) if file_upload.batch_id else None,
                media_type=media_type,
            )
        except HTTPException as exc:
            reason = str(exc.detail) if isinstance(exc.detail, str) else "invalid_file_content"
            file_upload.status = 4
            file_upload.error = reason
            session.add(file_upload)
            session.commit()
            return {"error": reason}
        except Exception:
            logger.exception("Failed to merge uploaded file %s", file_upload_id)
            file_upload.status = 4
            file_upload.error = "invalid_file_content"
            session.add(file_upload)
            session.commit()
            return {"error": file_upload.error}

        file_upload.path = str(normalize_media_relative_path(merged_path))
        file_upload.status = 1
        file_upload.error = None
        session.add(file_upload)
        session.commit()
        return {"status": "ready"}


async def process_media_batch(
    ctx: dict[str, Any],
    queue_id: int,
    collection_id: int,
    items: list[dict[str, Any]],
    creator_id: int | None = None,
    site_id: int | None = None,
    sensor_id: int | None = None,
    license_id: int | None = None,
    medium: str | None = None,
    media_type: str | None = None,
    recording_gain_db: int | None = None,
    duty_cycle_recording: int | None = None,
    duty_cycle_period: int | None = None,
    note: str | None = None,
    doi: str | None = None,
) -> dict[str, Any]:
    """Process one submitted media batch and settle its queue once all files are terminal."""
    cancellation_token: CancellationToken | None = ctx.get("cancellation_token")
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()

    _mark_batch_queue_running(queue_id)
    actual_media_type = media_type or "audio"
    item_ids = [int(item["file_upload_id"]) for item in items]

    for item in items:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        file_upload_id = int(item["file_upload_id"])
        with Session(engine) as session:
            file_upload = session.get(FileUpload, file_upload_id)
            if file_upload is None or file_upload.status in {3, 4, 5}:
                continue
            if file_upload.status == 2:
                file_upload.status = 1
                session.add(file_upload)
                session.commit()

        merged = _merge_batch_file(file_upload_id, actual_media_type)
        if merged.get("error"):
            _sync_batch_completed(queue_id, item_ids)
            continue

        await process_media(
            ctx=ctx,
            file_upload_id=file_upload_id,
            collection_id=collection_id,
            creator_id=creator_id,
            site_id=site_id,
            sensor_id=sensor_id,
            license_id=license_id,
            medium=medium,
            media_type=actual_media_type,
            recording_gain_db=recording_gain_db,
            file_date=item.get("file_date"),
            file_time=item.get("file_time"),
            duty_cycle_recording=duty_cycle_recording,
            duty_cycle_period=duty_cycle_period,
            note=note,
            doi=doi,
            display_filename=item.get("display_filename"),
        )
        _sync_batch_completed(queue_id, item_ids)

    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()

    with Session(engine) as session:
        queue = session.exec(
            select(Queue).where(Queue.queue_id == queue_id).with_for_update()
        ).first()
        if queue is None:
            return {"error": "Queue not found"}
        file_uploads = [session.get(FileUpload, file_upload_id) for file_upload_id in item_ids]
        successes = [item for item in file_uploads if item and item.status == 3]
        duplicates = [item for item in file_uploads if item and item.status == 5]
        failures = [item for item in file_uploads if item is None or item.status == 4]

        queue.completed = len(successes)
        queue.error = None
        if duplicates:
            duplicate_warning = "; ".join(
                f"File {item.name or item.filename} already exists in the collection"
                for item in duplicates
            )
            queue.warning = "; ".join(
                warning for warning in (queue.warning, duplicate_warning) if warning
            )
        queue_status, result_status = _resolve_batch_queue_status(
            has_failures=bool(failures),
            has_warning=bool(queue.warning),
        )
        if failures:
            queue.error = "; ".join(
                _batch_file_failure_message(item)
                for item in failures
            )
        queue.status = queue_status
        queue.stop_time = dt.now(datetime.UTC)
        session.add(queue)
        session.commit()

    return {
        "queue_id": queue_id,
        "completed": len(successes),
        "total": len(item_ids),
        "status": result_status,
    }
