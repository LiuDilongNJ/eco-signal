"""声景分类 API 路由。 / Sound classification API routes."""

from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.api.deps import SessionDep, get_current_active_superuser
from app.api.responses import csv_response
from app.schemas.response import ApiResponse, PagedApiResponse, api_page, api_success
from app.schemas.sound_classification import (
    SoundClassificationCreate,
    SoundClassificationImportResponse,
    SoundClassificationPublic,
    SoundClassificationUpdate,
)
from app.services import sound_classification_service
from app.csv_import import attach_import_metadata, parse_import_upload

router = APIRouter(prefix="/sound-classification-records", tags=["声景分类 / sound classifications"])


@router.get(
    "",
    response_model=PagedApiResponse[list[SoundClassificationPublic]],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取声景分类列表 / List Sound Classifications",
)
def list_sound_classifications(
    session: SessionDep,
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数 / Page size"),
    sound_id: int | None = Query(default=None, description="声音分类 ID / Sound classification ID"),
    soundscape_component: str | None = Query(default=None, description="声景组成成分 / Soundscape component"),
    sound_type: str | None = Query(default=None, description="声音类型 / Sound type"),
    order_by: str = Query(default="sound_id", pattern="^(sound_id|soundscape_component|sound_type)$", description="排序字段 / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    """获取管理员声景分类列表。 / Get the administrator sound classification list."""
    items, total = sound_classification_service.list_sound_classifications(
        session,
        page,
        page_size,
        {
            "sound_id": sound_id,
            "soundscape_component": soundscape_component,
            "sound_type": sound_type,
        },
        order_by,
        order_dir,
    )
    return api_page(data=items, total=total, page=page, page_size=page_size)


@router.get(
    "/exports",
    dependencies=[Depends(get_current_active_superuser)],
    summary="导出声景分类 / Export Sound Classifications",
)
def export_sound_classifications(
    session: SessionDep,
    order_by: str = Query(default="sound_id", pattern="^(sound_id|soundscape_component|sound_type)$", description="排序字段 / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    """导出全部声景分类。 / Export all sound classifications."""
    content = sound_classification_service.export_sound_classifications_csv(session, order_by, order_dir)
    return csv_response(content, "sound-classifications.csv")


@router.post(
    "/imports",
    response_model=ApiResponse[SoundClassificationImportResponse],
    dependencies=[Depends(get_current_active_superuser)],
    summary="导入声景分类 / Import Sound Classifications",
)
async def import_sound_classifications(
    session: SessionDep,
    file: UploadFile = File(..., description="声景分类 CSV 文件 / Sound classification CSV file"),
    dry_run: bool = Form(True),
) -> Any:
    """使用固定两列模板导入声景分类。 / Import sound classifications using the two-column template."""
    parsed = parse_import_upload(file.filename or "", await file.read())
    result = sound_classification_service.import_sound_classifications_csv(session, parsed.text, dry_run=dry_run)
    return api_success(message="Import validation completed" if dry_run else "Import completed", data=attach_import_metadata(result, parsed, dry_run=dry_run))


@router.post(
    "",
    response_model=ApiResponse[SoundClassificationPublic],
    dependencies=[Depends(get_current_active_superuser)],
    summary="创建声景分类 / Create Sound Classification",
)
def create_sound_classification(session: SessionDep, body: SoundClassificationCreate) -> Any:
    """创建声景分类。 / Create a sound classification."""
    return api_success(data=sound_classification_service.create_sound_classification(session, body))


@router.get(
    "/{sound_id}",
    response_model=ApiResponse[SoundClassificationPublic],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取声景分类详情 / Get Sound Classification",
)
def get_sound_classification(session: SessionDep, sound_id: int) -> Any:
    """获取声景分类详情。 / Get sound classification detail."""
    return api_success(data=sound_classification_service.get_sound_classification(session, sound_id))


@router.put(
    "/{sound_id}",
    response_model=ApiResponse[SoundClassificationPublic],
    dependencies=[Depends(get_current_active_superuser)],
    summary="更新声景分类 / Update Sound Classification",
)
def update_sound_classification(
    session: SessionDep,
    sound_id: int,
    body: SoundClassificationUpdate,
) -> Any:
    """替换声景分类字段。 / Replace sound classification fields."""
    return api_success(data=sound_classification_service.update_sound_classification(session, sound_id, body))


@router.delete(
    "/{sound_id}",
    response_model=ApiResponse[None],
    dependencies=[Depends(get_current_active_superuser)],
    summary="删除声景分类 / Delete Sound Classification",
)
def delete_sound_classification(session: SessionDep, sound_id: int) -> Any:
    """删除未被标注引用的声景分类。 / Delete an unreferenced sound classification."""
    sound_classification_service.delete_sound_classification(session, sound_id)
    return api_success()
