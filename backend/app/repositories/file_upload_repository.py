from app.models import FileUpload
from app.repositories.base import BaseRepository
from app.schemas.file_upload import FileUploadCreate, FileUploadUpdate


class FileUploadRepository(BaseRepository[FileUpload, FileUploadCreate, FileUploadUpdate]):
    """
    Repository for FileUpload entity operations.
    """
    
    def __init__(self):
        super().__init__(FileUpload)


# Singleton instance
file_upload_repository = FileUploadRepository()
