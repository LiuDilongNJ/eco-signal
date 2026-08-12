import logging
import shutil
import subprocess
from pathlib import Path
from typing import Literal

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

    def normalize_audio_filename_to_flac(self, filename: str) -> str:
        """Normalize any audio filename to a lowercase .flac extension."""
        return f"{Path(filename).stem}.flac"
    
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

    def ensure_audio_is_flac(
        self,
        source_path: Path,
        *,
        source_filename: str,
    ) -> tuple[Path, str]:
        """
        Normalize an uploaded audio file to FLAC on disk.

        Returns:
            The normalized FLAC path and filename.

        Raises:
            FileNotFoundError: Source file is missing.
            RuntimeError: ffmpeg is unavailable or conversion fails.
        """
        if not source_path.is_file():
            raise FileNotFoundError(f"File not found or is a directory: {source_path}")

        target_filename = self.normalize_audio_filename_to_flac(source_filename)
        target_path = source_path.with_name(target_filename)
        source_suffix = source_path.suffix.lower()

        if source_suffix == ".flac":
            if source_path.name != target_filename:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.replace(target_path)
                logger.info("Normalized FLAC filename from %s to %s", source_path.name, target_filename)
            return target_path, target_filename

        command = [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-i",
            str(source_path),
            "-map",
            "0:a",
            "-vn",
            "-sn",
            "-dn",
            "-map_metadata",
            "-1",
            "-c:a",
            "flac",
            str(target_path),
        ]
        try:
            subprocess.run(command, capture_output=True, text=True, check=True)
        except FileNotFoundError as exc:
            raise RuntimeError("ffmpeg is not installed") from exc
        except subprocess.CalledProcessError as exc:
            if target_path.exists():
                target_path.unlink()
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(f"ffmpeg conversion failed: {detail}") from exc

        source_path.unlink()
        return target_path, target_filename
    
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
