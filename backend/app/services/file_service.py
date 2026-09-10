import logging
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

import mutagen

from fastapi import UploadFile, HTTPException
from sqlmodel import Session

from app.core.config import settings
from app.media_paths import (
    logical_chunk_dir_path,
    logical_project_media_path,
    media_root,
    normalize_media_relative_path,
)
from app.models import User
from app.repositories import project_repository
from app.services.upload_validation_service import (
    sanitize_image,
    validate_audio_file,
    validate_audio_filename,
    validate_filename,
    validate_photo_file,
    validate_photo_filename,
    validate_zip_file,
)

logger = logging.getLogger(__name__)
_STREAM_CHUNK_SIZE = 1024 * 1024


def _as_int(value: object) -> int | None:
    try:
        return int(str(value)) if value not in (None, "N/A", "") else None
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    try:
        return float(str(value)) if value not in (None, "N/A", "") else None
    except (TypeError, ValueError):
        return None


def _json_tag_value(value: object) -> str | int | float | bool:
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return f"binary:{len(value)} bytes"
    return str(value)


_NON_CONTENT_AUDIO_TAG_KEYS = {"encoder", "tsse"}


def _missing_audio_tag_names(
    source_tags: dict[str, dict[str, list[str | int | float | bool]]],
    stored_tags: dict[str, dict[str, list[str | int | float | bool]]],
) -> list[str]:
    """Return source tag names whose values are absent after a format conversion."""
    stored_values = {
        str(value).casefold()
        for namespace in stored_tags.values()
        for values in namespace.values()
        for value in values
    }
    missing: list[str] = []
    for namespace in source_tags.values():
        for name, values in namespace.items():
            if name.casefold() in _NON_CONTENT_AUDIO_TAG_KEYS:
                continue
            if any(str(value).casefold() not in stored_values for value in values):
                missing.append(name)
    return list(dict.fromkeys(missing))


# Allowed file types by category
ALLOWED_EXTENSIONS = {
    "image": {"png", "jpg", "jpeg", "gif", "webp"},
    "audio": {"wav", "mp3", "flac", "ogg"},
}


class FileService:
    """
    Common file upload service.
    
    Handles file uploads for various entities like projects, collections, etc.
    Storage paths follow the established sounds/ chunk layout used by the upload API.
    """
    
    def __init__(self, base_dir: str | None = None):
        """
        Initialize file service.
        
        Args:
            base_dir: Base directory for file storage (relative to app root)
        """
        self.base_dir = Path(base_dir) if base_dir else media_root()
    
    def _ensure_directory(self, directory: Path) -> None:
        """Ensure directory exists, create if not."""
        directory.mkdir(parents=True, exist_ok=True)
    
    def _get_extension(self, filename: str) -> str:
        """Extract file extension from filename."""
        return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    def _probe_audio(self, path: Path) -> dict[str, Any]:
        """Read the actual container and stream properties, never trusting its suffix."""
        command = ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=True)
            payload = json.loads(completed.stdout)
        except FileNotFoundError as exc:
            raise RuntimeError("ffprobe is not installed") from exc
        except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            raise RuntimeError("Unable to read audio file format") from exc
        stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "audio"), None)
        if not stream:
            raise ValueError("Uploaded file does not contain an audio stream")
        fmt = payload.get("format") or {}
        container = str(fmt.get("format_name") or "").split(",")[0].lower()
        return {
            "container": container,
            "codec": str(stream.get("codec_name") or "").lower(),
            "bit_rate_bps": _as_int(stream.get("bit_rate") or fmt.get("bit_rate")),
            "sampling_rate_hz": _as_int(stream.get("sample_rate")),
            "bit_depth": _as_int(stream.get("bits_per_raw_sample") or stream.get("bits_per_sample")),
            "channel_num": _as_int(stream.get("channels")),
            "duration_s": _as_float(stream.get("duration") or fmt.get("duration")),
        }

    def _extract_audio_tags(self, path: Path) -> tuple[dict[str, dict[str, list[str | int | float | bool]]], list[str]]:
        """Extract embedded tags and normalize their values for JSON storage."""
        tags: dict[str, dict[str, list[str | int | float | bool]]] = {
            "id3v2": {}, "vorbis_comment": {}, "riff_info": {}, "other": {},
        }
        warnings: list[str] = []
        try:
            audio = mutagen.File(path, easy=False)
            raw_tags = getattr(audio, "tags", None)
            if not raw_tags:
                return {}, warnings
            tag_class = raw_tags.__class__.__module__.lower()
            namespace = "id3v2" if "id3" in tag_class else "vorbis_comment" if "vorbis" in tag_class or "flac" in tag_class else "riff_info" if "wave" in tag_class else "other"
            for key, value in raw_tags.items():
                values = value if isinstance(value, (list, tuple)) else [value]
                normalized = [_json_tag_value(item) for item in values]
                tags[namespace][str(key)] = normalized
        except Exception as exc:
            logger.warning("Could not read embedded audio tags from %s: %s", path, exc)
            warnings.append("Embedded metadata could not be fully read")
        return {key: value for key, value in tags.items() if value}, warnings

    def prepare_audio_for_storage(
        self,
        source_path: Path,
        *,
        source_filename: str,
        target_sampling_rate_hz: int | None = None,
    ) -> tuple[Path, str, dict[str, Any]]:
        """Validate audio, convert PCM to FLAC, and apply the requested downsampling."""
        if not source_path.is_file():
            raise FileNotFoundError(f"File not found or is a directory: {source_path}")

        source = self._probe_audio(source_path)
        codec = source["codec"]
        container = source["container"]
        supported = {"pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "flac", "mp3", "vorbis", "opus"}
        if codec not in supported:
            raise ValueError(f"Unsupported audio codec: {codec or 'unknown'}")
        source_rate = source["sampling_rate_hz"]
        if not source_rate:
            raise ValueError("Audio sampling rate is unavailable")
        if target_sampling_rate_hz and target_sampling_rate_hz > source_rate:
            raise ValueError("Target sampling rate must not exceed the source sampling rate")

        tags, warnings = self._extract_audio_tags(source_path)
        target_codec = "flac" if codec.startswith("pcm_") else codec
        target_container = "flac" if target_codec == "flac" else "mp3" if target_codec == "mp3" else "ogg"
        extension = ".flac" if target_codec == "flac" else ".mp3" if target_codec == "mp3" else ".ogg"
        target_filename = f"{Path(source_filename).stem}{extension}"
        target_path = source_path.with_name(target_filename)
        must_convert = codec.startswith("pcm_") or (target_sampling_rate_hz is not None and target_sampling_rate_hz < source_rate)
        if must_convert:
            temporary_path = target_path.with_name(f".{target_path.stem}.processing{target_path.suffix}")
            command = ["ffmpeg", "-y", "-nostdin", "-i", str(source_path), "-map", "0:a:0", "-vn", "-sn", "-dn", "-map_metadata", "0"]
            if target_sampling_rate_hz:
                command.extend(["-ar", str(target_sampling_rate_hz)])
            encoder = {"flac": "flac", "mp3": "libmp3lame", "vorbis": "libvorbis", "opus": "libopus"}[target_codec]
            command.extend(["-c:a", encoder, str(temporary_path)])
            try:
                subprocess.run(command, capture_output=True, text=True, check=True)
                stored = self._probe_audio(temporary_path)
                if target_sampling_rate_hz and stored["sampling_rate_hz"] != target_sampling_rate_hz:
                    raise RuntimeError("Converted file has an unexpected sampling rate")
                temporary_path.replace(target_path)
                if source_path != target_path:
                    source_path.unlink(missing_ok=True)
            except FileNotFoundError as exc:
                raise RuntimeError("ffmpeg is not installed") from exc
            except Exception:
                temporary_path.unlink(missing_ok=True)
                raise
        else:
            stored = source
            if source_path.name != target_filename:
                source_path.replace(target_path)

        stored = self._probe_audio(target_path)
        metadata = {
            "schema_version": 1,
            "source": {"filename": source_filename, **source},
            "stored": {"filename": target_filename, "container": target_container, **stored},
            "tags": tags,
            "warnings": warnings,
        }
        if must_convert and tags:
            stored_tags, _ = self._extract_audio_tags(target_path)
            missing_tag_names = _missing_audio_tag_names(tags, stored_tags)
            if missing_tag_names:
                metadata["warnings"].append(
                    "Embedded metadata was not retained for: " + ", ".join(missing_tag_names)
                )
        return target_path, target_filename, metadata

    def resample_stored_audio(
        self,
        source_path: Path,
        *,
        target_sampling_rate_hz: int,
        file_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically replace a stored audio file with a lower-rate equivalent."""
        current = self._probe_audio(source_path)
        current_rate = current["sampling_rate_hz"]
        if not current_rate or target_sampling_rate_hz > current_rate:
            raise ValueError("Target sampling rate must not exceed the current sampling rate")
        if target_sampling_rate_hz == current_rate:
            updated = dict(file_metadata)
            updated.setdefault("warnings", []).append("Resampling skipped because the target rate already matches the stored file")
            return updated
        codec = current["codec"]
        encoder = {"flac": "flac", "mp3": "libmp3lame", "vorbis": "libvorbis", "opus": "libopus"}.get(codec)
        if not encoder:
            raise ValueError(f"Unsupported audio codec: {codec or 'unknown'}")
        temporary_path = source_path.with_name(f".{source_path.stem}.resampling{source_path.suffix}")
        command = [
            "ffmpeg", "-y", "-nostdin", "-i", str(source_path), "-map", "0:a:0",
            "-vn", "-sn", "-dn", "-map_metadata", "0", "-ar", str(target_sampling_rate_hz),
            "-c:a", encoder, str(temporary_path),
        ]
        try:
            subprocess.run(command, capture_output=True, text=True, check=True)
            stored = self._probe_audio(temporary_path)
            if stored["sampling_rate_hz"] != target_sampling_rate_hz:
                raise RuntimeError("Converted file has an unexpected sampling rate")
            temporary_path.replace(source_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        updated = dict(file_metadata)
        updated["stored"] = {"filename": source_path.name, **stored}
        warnings = list(updated.get("warnings") or [])
        if codec in {"mp3", "vorbis", "opus"}:
            warnings.append("Lossy audio was re-encoded during resampling and may have lower quality")
        updated["warnings"] = warnings
        return updated
    
    def _validate_file_type(
        self, 
        filename: str, 
        file_type: Literal["image", "audio"]
    ) -> str:
        """
        Validate file extension against allowed types.
        
        Returns:
            The validated extension
            
        Raises:
            HTTPException: If file type is not allowed
        """
        ext = self._get_extension(filename)
        allowed = ALLOWED_EXTENSIONS.get(file_type, set())
        
        if ext not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"File type '.{ext}' not allowed. Allowed types: {', '.join(allowed)}"
            )
        return ext
    
    async def _write_upload_stream(
        self,
        file: UploadFile,
        target_path: Path,
        *,
        max_size: int,
        label: str,
    ) -> None:
        """Write an upload incrementally and publish it only after validation."""
        temp_path = target_path.with_name(f".{target_path.name}.uploading")
        written = 0
        try:
            with temp_path.open("wb") as output:
                while chunk := await file.read(_STREAM_CHUNK_SIZE):
                    written += len(chunk)
                    if written > max_size:
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                f"{label} exceeds maximum allowed size "
                                f"({max_size // (1024 * 1024)} MB)"
                            ),
                        )
                    output.write(chunk)
            temp_path.replace(target_path)
        finally:
            temp_path.unlink(missing_ok=True)

    async def upload_image(
        self,
        file: UploadFile,
        directory: str,
        filename: str
    ) -> str:
        """
        Upload an image file.
        
        Args:
            file: The uploaded file
            directory: Subdirectory under base_dir (e.g., "projects")
            filename: Target filename without extension (e.g., "123")
            
        Returns:
            The saved filename with extension (e.g., "123.png")
            
        Example:
            # Upload project picture
            saved_name = await file_service.upload_image(
                file, "projects", str(project_id)
            )
            # File saved to: sounds/projects/123.png
        """
        # Validate the user supplied name before it reaches the filesystem.
        original_filename = validate_filename(file.filename or "")
        ext = self._validate_file_type(original_filename, "image")
        
        # Prepare target path
        target_dir = self.base_dir / directory
        self._ensure_directory(target_dir)
        
        # Build full filename
        full_filename = validate_filename(f"{filename}.{ext}")
        target_path = target_dir / full_filename
        
        await self._write_upload_stream(
            file,
            target_path,
            max_size=settings.MAX_IMAGE_SIZE,
            label="Image file",
        )
        try:
            sanitize_image(target_path, original_filename, file.content_type)
        except Exception:
            target_path.unlink(missing_ok=True)
            raise
        for old_file in target_dir.glob(f"{filename}.*"):
            if old_file != target_path:
                old_file.unlink()
        
        return full_filename

    async def upload_project_picture(
        self,
        session: Session,
        project_id: int,
        current_user: User,
        file: UploadFile,
    ) -> dict[str, str]:
        """Upload a project picture and persist the project's picture_id."""
        from app.services import permission_service

        project = project_repository.get(session, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        if not permission_service.is_admin(current_user):
            has_perm = permission_service.has_resource_permission(
                session,
                current_user,
                "project",
                "write",
                project_id=project_id,
            )
            if not has_perm:
                raise HTTPException(status_code=403, detail="No permission to upload")

        original_filename = validate_filename(file.filename or "")
        ext = self._validate_file_type(original_filename, "image")
        picture_id = f"{project.uuid.hex}.{ext}"
        target_dir = self.base_dir / "projects"
        self._ensure_directory(target_dir)
        target_path = target_dir / picture_id
        staging_path = target_path.with_name(f".{target_path.name}.new")
        backup_path = target_path.with_name(f".{target_path.name}.backup")
        previous_picture_id = project.picture_id
        published = False

        try:
            await self._write_upload_stream(
                file,
                staging_path,
                max_size=settings.MAX_IMAGE_SIZE,
                label="Image file",
            )
            sanitize_image(staging_path, original_filename, file.content_type)

            if target_path.exists():
                backup_path.unlink(missing_ok=True)
                target_path.replace(backup_path)
            staging_path.replace(target_path)
            published = True

            project.picture_id = picture_id
            session.add(project)
            session.commit()
        except Exception:
            session.rollback()
            project.picture_id = previous_picture_id
            staging_path.unlink(missing_ok=True)
            if backup_path.exists():
                target_path.unlink(missing_ok=True)
                backup_path.replace(target_path)
            elif published:
                target_path.unlink(missing_ok=True)
            raise

        backup_path.unlink(missing_ok=True)
        if previous_picture_id and previous_picture_id != picture_id:
            try:
                previous_filename = validate_filename(previous_picture_id)
                (target_dir / previous_filename).unlink(missing_ok=True)
            except HTTPException:
                logger.warning("Skipped unsafe previous project picture filename for project %s", project_id)

        return {
            "picture_id": picture_id,
            "path": logical_project_media_path(picture_id).as_posix(),
        }
    
    def delete_file(self, directory: str, filename: str) -> bool:
        """
        Delete a file.
        
        Args:
            directory: Subdirectory under base_dir
            filename: The filename to delete (with extension)
            
        Returns:
            True if file was deleted, False if not found
        """
        file_path = self.base_dir / directory / filename
        if file_path.exists():
            file_path.unlink()
            return True
        return False
    
    # Chunk Upload Methods

    def get_chunk_dir(self, filename: str, batch_id: str | None = None) -> Path:
        """Get the directory for storing chunks of a file."""
        return self.base_dir / logical_chunk_dir_path(filename, batch_id)

    
    async def save_chunk(
        self,
        file: UploadFile,
        filename: str,
        chunk_index: int,
        total_chunks: int,
        batch_id: str | None = None,
        *,
        allowed_extensions: set[str] | None = None,
        media_type: Literal["audio", "photo"] = "audio",
    ) -> dict:
        """
        Save a file chunk.
        
        Args:
            file: The chunk data
            filename: Original filename (used as folder name)
            chunk_index: Chunk index (0-based)
            total_chunks: Total number of chunks
            batch_id: Optional batch ID for isolation
            
        Returns:
            {filename, uploaded_chunks, total_chunks, is_complete}
        """
        validate_filename(filename)
        if allowed_extensions is not None:
            ext = self._get_extension(filename)
            if ext not in allowed_extensions:
                raise HTTPException(status_code=400, detail="unsupported_file_type")
        elif media_type == "audio":
            validate_audio_filename(filename)
        else:
            validate_photo_filename(filename)
        chunk_dir = self.get_chunk_dir(filename, batch_id)
        self._ensure_directory(chunk_dir)
        
        # Save chunk file
        chunk_path = chunk_dir / f"{chunk_index:05d}"
        await self._write_upload_stream(
            file,
            chunk_path,
            max_size=settings.MAX_CHUNK_SIZE,
            label="Chunk",
        )
        
        # Count uploaded chunks
        uploaded_chunks = len(list(chunk_dir.glob("*")))
        is_complete = uploaded_chunks >= total_chunks
        
        return {
            "filename": filename,
            "uploaded_chunks": uploaded_chunks,
            "total_chunks": total_chunks,
            "is_complete": is_complete
        }
    
    def merge_chunks(self, filename: str, target_dir: str, batch_id: str | None = None) -> Path:
        """
        Merge all chunks into a single file.
        
        Args:
            filename: Original filename
            target_dir: Target directory under base_dir
            batch_id: Optional batch ID for isolation
            
        Returns:
            Path to the merged file
        """
        chunk_dir = self.get_chunk_dir(filename, batch_id)
        
        if not chunk_dir.exists():
            raise FileNotFoundError(f"No chunks found for {filename}")
        
        # Prepare target path
        target_relative = normalize_media_relative_path(target_dir)
        if target_relative is None:
            raise FileNotFoundError("Target directory cannot be empty")
        target_path_dir = self.base_dir / target_relative
        self._ensure_directory(target_path_dir)
        target_path = target_path_dir / filename
        
        # Get sorted chunk files
        chunk_files = sorted(chunk_dir.glob("*"))
        
        if not chunk_files:
            raise FileNotFoundError(f"No chunks found for {filename}")
        
        # Merge chunks
        with target_path.open("wb") as output:
            for chunk_file in chunk_files:
                with chunk_file.open("rb") as source:
                    shutil.copyfileobj(source, output, length=_STREAM_CHUNK_SIZE)
        
        # Cleanup chunk directory
        shutil.rmtree(chunk_dir)
        
        # Cleanup empty batch_id parent directory if exists
        if batch_id:
            batch_dir = chunk_dir.parent
            if batch_dir.exists() and not any(batch_dir.iterdir()):
                batch_dir.rmdir()
        
        return target_path

    def merge_and_validate_chunks(
        self,
        *,
        filename: str,
        user_id: int,
        batch_id: str | None,
        media_type: Literal["audio", "photo", "zip"],
    ) -> Path:
        """Merge an upload into quarantine and validate its actual content."""
        merged_path = self.merge_chunks(
            filename,
            f"tmp/pending/{user_id}",
            batch_id=batch_id,
        )
        try:
            if media_type == "zip":
                validate_zip_file(merged_path, filename)
            elif media_type == "photo":
                validate_photo_file(merged_path, filename)
            else:
                validate_audio_file(merged_path, filename)
        except Exception:
            merged_path.unlink(missing_ok=True)
            raise
        return merged_path
    
    def get_chunk_status(self, filename: str, batch_id: str | None = None) -> dict:
        """Get the upload status for a file."""
        chunk_dir = self.get_chunk_dir(filename, batch_id)
        
        if not chunk_dir.exists():
            return {
                "filename": filename, 
                "uploaded_chunks": 0, 
                "uploaded_indices": [],
                "exists": False
            }
        
        chunk_files = [int(f.name) for f in chunk_dir.glob("*") if f.is_file() and f.name.isdigit()]
        return {
            "filename": filename,
            "uploaded_chunks": len(chunk_files),
            "uploaded_indices": sorted(chunk_files),
            "exists": True
        }
    
# Singleton instance
file_service = FileService()
