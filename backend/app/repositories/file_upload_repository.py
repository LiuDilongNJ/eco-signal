from sqlmodel import Session, select

from app.models import FileUpload
from app.repositories.base import BaseRepository
from app.schemas.file_upload import FileUploadCreate, FileUploadUpdate


class FileUploadRepository(BaseRepository[FileUpload, FileUploadCreate, FileUploadUpdate]):
    """
    Repository for FileUpload entity operations.
    """
    
    def __init__(self):
        super().__init__(FileUpload)

    def is_path_referenced(self, session: Session, path: str) -> bool:
        return session.exec(select(FileUpload.file_upload_id).where(FileUpload.path == path).limit(1)).first() is not None


# Singleton instance
file_upload_repository = FileUploadRepository()
