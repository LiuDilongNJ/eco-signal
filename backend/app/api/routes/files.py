"""文件 API 路由（分块与批量上传路径约定）。 / Files API (chunked and batch upload path layout)."""
import logging
import random
import uuid
import zlib
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, File, UploadFile, HTTPException, Form
from sqlmodel import select

from app.api.deps import CurrentUser, RedisDep, SessionDep, TaskPublisherDep
from app.enums import QueueStatus, WorkerTaskType
from app.media_paths import logical_category_media_path
from app.models import FileUpload, Queue
from app.repositories import file_upload_repository
from app.schemas.file_upload import FileUploadCreate
from app.schemas.response import ApiResponse, api_success
from app.services import permission_service
from app.services.data_import_service import data_import_service
from app.services.file_service import file_service
from app.services.upload_validation_service import (
    validate_audio_filename,
    validate_filename,
    validate_photo_filename,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["文件 / files"])

@router.post("/file-upload-batches", response_model=ApiResponse[dict], summary="初始化上传批次 / Init Upload Batch")
def init_batch():
    """
    生成用于批量上传的新批次 ID。 / Generate a new batch ID for bulk upload.

    此 ID 应包含在后续的 POST /media 请求中，以便将文件分组并确保目录局部性。 / This ID should be included in subsequent POST /media requests to group files together and ensure directory locality.
    """
    return api_success(data={"batch_id": str(uuid.uuid4())})


@router.put("/projects/{project_id}/picture", response_model=ApiResponse[dict], summary="上传项目图片 / Upload Project Picture")
async def upload_project_picture(
    project_id: int,
    session: SessionDep,
    current_user: CurrentUser,
    file: UploadFile = File(..., description="图像文件 (png, jpg, jpeg, gif, webp) / Image file (png, jpg, jpeg, gif, webp)")
) -> ApiResponse[dict]:
    """
    上传项目图片。 / Upload a project picture.

    - 管理员或拥有 project:write 权限的用户可以上传 / Admins or users with project:write permission can upload
    - 文件保存在 sounds/projects/{project_uuid_without_hyphens}.{extension} / File is saved to sounds/projects/{project_uuid_without_hyphens}.{extension}
    - 上传成功后自动更新项目图片 / The project picture is updated automatically after a successful upload

    Returns:
        {"picture_id": "550e8400e29b41d4a716446655440000.png", "path": "projects/550e8400e29b41d4a716446655440000.png"}
    """

    data = await file_service.upload_project_picture(session, project_id, current_user, file)
    return api_success(data=data)


@router.post("/file-images/{category}", response_model=ApiResponse[dict], summary="上传图片 / Upload Image")
async def upload_image(
    category: str,
    _current_user: CurrentUser,
    file: UploadFile = File(..., description="图像文件 (png, jpg, jpeg, gif, webp) / Image file (png, jpg, jpeg, gif, webp)"),
    filename: str | None = None
) -> ApiResponse[dict]:
    """
    上传通用图像文件。 / Upload a general image file.

    这是一个通用的上传接口。文件保存在 sounds/{category}/{filename}.{ext} / This is a generic upload endpoint. The file is saved to sounds/{category}/{filename}.{ext}

    Args:
        category: 子目录名称（例如 "projects", "collections", "temp"） / Subdirectory name (e.g., "projects", "collections", "temp")
        filename: 可选的自定义文件名（不带扩展名）。如果未提供，则生成一个。 / Optional custom filename (without extension). If not provided, generates one.

    Returns:
        {"filename": "xxx.png", "path": "sounds/{category}/xxx.png"}
    """

    # Validate category (prevent path traversal)
    if ".." in category or "/" in category or "\\" in category:
        raise HTTPException(status_code=400, detail="Invalid category")

    # Generate filename if not provided
    if not filename:
        filename = str(uuid.uuid4())[:8]

    saved_filename = await file_service.upload_image(file, category, filename)

    return api_success(data={
        "filename": saved_filename,
        "path": logical_category_media_path(category, saved_filename).as_posix()
    })


@router.delete("/file-images/{category}/{filename}", response_model=ApiResponse, summary="删除文件 / Delete File")
async def delete_file(
    category: str,
    filename: str,
    current_user: CurrentUser
) -> ApiResponse:
    """
    删除已上传的文件。 / Delete an uploaded file.

    需要管理员权限。 / Requires admin permission.
    """
    if not permission_service.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin only")

    # Validate inputs
    if ".." in category or "/" in category or "\\" in category:
        raise HTTPException(status_code=400, detail="Invalid category")
    validate_filename(filename)

    deleted = file_service.delete_file(category, filename)

    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")

    return ApiResponse(message="File deleted successfully")


@router.post("/file-upload-batches/{batch_id}/chunks", response_model=ApiResponse[dict], summary="上传分块 / Upload Chunk")
async def upload_chunk(
    batch_id: str,
    current_user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
    publisher: TaskPublisherDep,
    filename: str = Form(..., description="原始文件名 / Original filename"),
    media_type: Literal["audio", "photo"] = Form(
        "audio", description="媒体类型 / Media type"
    ),
    chunk_index: int = Form(..., ge=0, description="分块索引（从 0 开始） / Chunk index (0-based)"),
    total_chunks: int = Form(..., ge=1, description="分块总数 / Total number of chunks"),
    file: UploadFile = File(..., description="分块数据 / Chunk data"),
    collection_id: int | None = Form(default=None, description="目标收藏集 ID / Target collection ID"),
) -> ApiResponse[dict]:
    """
    上传文件分块。 / Upload a file chunk.

    分块保存在 sounds/tmp/chunks/{batch_id}/{filename}/{chunk_index}。 / Chunks are saved to sounds/tmp/chunks/{batch_id}/{filename}/{chunk_index}.
    普通媒体的最后一个分块只创建暂存记录，提交媒体表单后统一处理。 / The final chunk of standard media only creates a staging record; processing starts when the media form is submitted.
    离线导入批次仍会在合并完成后自动触发后台导入。 / Offline import batches still trigger the background import after merging.

    Returns:
        {filename, uploaded_chunks, total_chunks, is_complete, file_upload_id}
        file_upload_id 仅在 is_complete=True 时存在。 / file_upload_id is only present when is_complete=True.
    """
    # Validate filename and batch_id (prevent path traversal)
    validate_filename(filename)
    if ".." in batch_id or "/" in batch_id or "\\" in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id")

    data_import = await data_import_service.get_context(redis, batch_id)
    if data_import is not None:
        if not filename.lower().endswith(".zip"):
            raise HTTPException(
                status_code=400,
                detail="Offline import batches only accept .zip files",
            )
        if data_import["file_upload_id"] is not None:
            raise HTTPException(
                status_code=409,
                detail="Offline import batch already has an uploaded bundle",
            )
    else:
        if media_type == "photo":
            validate_photo_filename(filename)
        else:
            validate_audio_filename(filename)

    result = await file_service.save_chunk(
        file=file,
        filename=filename,
        chunk_index=chunk_index,
        total_chunks=total_chunks,
        batch_id=batch_id,
        allowed_extensions={"zip"} if data_import is not None else None,
        media_type=media_type,
    )

    if result["is_complete"]:
        stmt = select(FileUpload).where(
            FileUpload.batch_id == batch_id,
            FileUpload.filename == filename,
        )
        if session.exec(stmt).first():
            raise HTTPException(
                status_code=409,
                detail="File already exists in this batch",
            )
            
        directory = (zlib.crc32(batch_id.encode()) % 100) + 1 if batch_id else random.randint(1, 100)
        
        file_upload_data = FileUploadCreate(
            path="",
            filename=filename,
            name=filename,
            directory=directory,
            uploader_id=current_user.user_id,
            status=1,  # pending
            batch_id=batch_id,
        )
        file_upload = file_upload_repository.create(session, obj_in=file_upload_data)

        if data_import is None:
            result["file_upload_id"] = file_upload.file_upload_id
            return api_success(data=result)

        merge_queue = Queue(
            type="file_upload",
            user_id=current_user.user_id,
            total=1,
            status=QueueStatus.PENDING,
        )
        session.add(merge_queue)
        session.commit()
        session.refresh(merge_queue)
        
        try:
            logger.info(f"Attempting to enqueue MERGE_FILE_CHUNKS for file_upload_id={file_upload.file_upload_id}")
            await publisher.enqueue_task(
                WorkerTaskType.MERGE_FILE_CHUNKS,
                file_upload_id=file_upload.file_upload_id,
                filename=filename,
                user_id=current_user.user_id,
                batch_id=batch_id,
                queue_id=merge_queue.queue_id,
            )
            logger.info(f"Successfully enqueued MERGE_FILE_CHUNKS for file_upload_id={file_upload.file_upload_id}")
        except Exception as e:
            logger.error(f"Failed to enqueue MERGE_FILE_CHUNKS: {e}")
            merge_queue.status = QueueStatus.ERROR
            merge_queue.error = "Failed to enqueue file validation job"
            merge_queue.stop_time = datetime.now(UTC).replace(tzinfo=None)
            file_upload.status = 4
            file_upload.error = merge_queue.error
            session.add(file_upload)
            session.add(merge_queue)
            session.commit()
        
        result["file_upload_id"] = file_upload.file_upload_id
        result["queue_id"] = merge_queue.queue_id

    return api_success(data=result)


@router.get("/file-upload-batches/{batch_id}/files/{filename}", response_model=ApiResponse[dict], summary="获取上传状态 / Get Upload Status")
def get_upload_status(
    batch_id: str,
    filename: str,
    _current_user: CurrentUser,
) -> ApiResponse[dict]:
    """获取文件的上传状态。 / Get the upload status for a file."""
    validate_filename(filename)
    if ".." in batch_id or "/" in batch_id or "\\" in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id")

    data = file_service.get_chunk_status(filename, batch_id=batch_id)
    return api_success(data=data)
