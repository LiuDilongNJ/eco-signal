"""录音机 API 路由（管理员 CRUD、录音机-麦克风关联、公开选项）。 / Recorders: admin CRUD, recorder-mic links, public options."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlmodel import select

from app.api.deps import SessionDep, get_current_active_superuser
from app.models import Recorder
from app.schemas.device import (
    RecorderCreate,
    RecorderListItem,
    RecorderMicrophoneCreate,
    RecorderOption,
    RecorderPublic,
    RecorderUpdate,
    DeviceImportResponse,
)
from app.schemas.response import ApiResponse, PagedApiResponse, api_page, api_success
from app.services import device_service
from app.services.upload_validation_service import extension_for, validate_csv_content
from app.utils import parse_uuid

router = APIRouter(prefix="/recorders", tags=["录音机 / recorders"])
router_views = APIRouter(tags=["录音机 / recorders"])


@router_views.get(
    "/recorder-options",
    response_model=ApiResponse[list[RecorderOption]],
    summary="获取录音机选项 / Get Recorder Options",
)
def get_recorder_options(session: SessionDep) -> Any:
    """
    获取下拉菜单的录音机选项。 / Get recorder options for dropdown menus.

    返回包含 ID 和名称的所有录音机列表。 / Returns list of all recorders with id and name.
    无需身份验证。 / No authentication required.
    """
    stmt = select(Recorder.recorder_id, Recorder.name).order_by(Recorder.name)
    results = session.exec(stmt).all()
    data = [{"recorder_id": r[0], "name": r[1] or ""} for r in results]
    return api_success(data=data)


@router.get(
    "",
    response_model=PagedApiResponse[list[RecorderListItem]],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取录音机列表 / List Recorders",
)
def list_recorders(
    session: SessionDep,
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数 / Page size"),
    recorder_id: Optional[int] = Query(default=None, description="录音机 ID 精确筛选 / Filter by recorder ID (exact)"),
    uuid: Optional[str] = Query(default=None, description="UUID 精确筛选 / Filter by UUID (exact)"),
    name: Optional[str] = Query(default=None, description="名称模糊搜索 / Fuzzy search by name"),
    version: Optional[str] = Query(default=None, description="型号模糊搜索 / Fuzzy search by version"),
    brand: Optional[str] = Query(default=None, description="品牌模糊搜索 / Fuzzy search by brand"),
    microphone_count: Optional[int] = Query(default=None, description="麦克风数量精确筛选 / Filter by microphone count (exact)"),
    order_by: str = Query(default="recorder_id", description="排序字段：recorder_id, uuid, name, version, brand, microphone_count / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    """
    获取所有录音机列表（分页，支持筛选和排序），含关联麦克风数量。
    Get paginated list of recorders with filter and sort support, including associated microphone count.

    仅管理员可访问。 / Admin only.
    """
    filters = {
        "recorder_id": recorder_id,
        "uuid": parse_uuid(uuid),
        "name": name,
        "version": version,
        "brand": brand,
        "microphone_count": microphone_count,
    }
    items, total = device_service.list_recorders(session, page, page_size, filters, order_by, order_dir)
    return api_page(data=items, total=total, page=page, page_size=page_size)


@router.get(
    "/exports",
    dependencies=[Depends(get_current_active_superuser)],
    summary="导出录音机列表 / Export Recorders",
)
def export_recorders(
    session: SessionDep,
    recorder_id: Optional[int] = Query(default=None, description="录音机 ID 精确筛选 / Filter by recorder ID (exact)"),
    uuid: Optional[str] = Query(default=None, description="UUID 精确筛选 / Filter by UUID (exact)"),
    name: Optional[str] = Query(default=None, description="名称模糊搜索 / Fuzzy search by name"),
    version: Optional[str] = Query(default=None, description="型号模糊搜索 / Fuzzy search by version"),
    brand: Optional[str] = Query(default=None, description="品牌模糊搜索 / Fuzzy search by brand"),
    microphone_count: Optional[int] = Query(default=None, description="麦克风数量精确筛选 / Filter by microphone count (exact)"),
    order_by: str = Query(default="recorder_id", description="排序字段：recorder_id, uuid, name, version, brand, microphone_count / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    from app.api.responses import csv_response

    filters = {
        "recorder_id": recorder_id,
        "uuid": parse_uuid(uuid),
        "name": name,
        "version": version,
        "brand": brand,
        "microphone_count": microphone_count,
    }
    csv_content = device_service.export_recorders_csv(session, filters, order_by, order_dir)
    return csv_response(csv_content, "recorders.csv")


@router.post("/imports", response_model=ApiResponse[DeviceImportResponse], dependencies=[Depends(get_current_active_superuser)], summary="导入录音机 / Import Recorders")
async def import_recorders(session: SessionDep, file: UploadFile = File(...)) -> Any:
    """使用固定 CSV 模板原子导入录音机。 / Atomically import recorders from the fixed CSV template."""
    extension_for(file.filename or "", {"csv"})
    return api_success(data=device_service.import_recorders_csv(session, validate_csv_content(await file.read())))


@router.post(
    "",
    response_model=ApiResponse[None],
    dependencies=[Depends(get_current_active_superuser)],
    summary="创建录音机 / Create Recorder",
)
def create_recorder(session: SessionDep, body: RecorderCreate) -> Any:
    """
    创建新录音机。 / Create a new recorder.

    仅管理员可访问。 / Admin only.
    """
    device_service.create_recorder(session, body.name, body.version, body.brand)
    return api_success()


@router.get(
    "/{recorder_id}",
    response_model=ApiResponse[RecorderPublic],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取录音机详情 / Get Recorder",
)
def get_recorder(session: SessionDep, recorder_id: int) -> Any:
    """
    根据 ID 获取录音机详情，含关联的麦克风列表。
    Get recorder detail by ID, including associated microphones.

    仅管理员可访问。 / Admin only.
    """
    result = device_service.get_recorder(session, recorder_id)
    return api_success(data=result)


@router.put(
    "/{recorder_id}",
    response_model=ApiResponse[None],
    dependencies=[Depends(get_current_active_superuser)],
    summary="更新录音机 / Update Recorder",
)
def update_recorder(session: SessionDep, recorder_id: int, body: RecorderUpdate) -> Any:
    """
    更新录音机信息。 / Update recorder information.

    仅管理员可访问。 / Admin only.
    """
    device_service.update_recorder(session, recorder_id, body)
    return api_success()


@router.delete(
    "/{recorder_id}",
    response_model=ApiResponse,
    dependencies=[Depends(get_current_active_superuser)],
    summary="删除录音机 / Delete Recorder",
)
def delete_recorder(session: SessionDep, recorder_id: int) -> Any:
    """
    删除录音机。如果被传感器引用则拒绝删除。
    Delete a recorder. Rejected if referenced by sensor records.

    仅管理员可访问。 / Admin only.
    """
    device_service.delete_recorder(session, recorder_id)
    return ApiResponse()


@router.post(
    "/{recorder_id}/microphones",
    response_model=ApiResponse[None],
    dependencies=[Depends(get_current_active_superuser)],
    summary="添加录音机麦克风关联 / Add Recorder-Microphone Association",
)
def add_recorder_microphone(
    session: SessionDep, recorder_id: int, body: RecorderMicrophoneCreate
) -> Any:
    """
    为录音机添加兼容麦克风关联。 / Add a compatible microphone association for a recorder.

    仅管理员可访问。 / Admin only.
    """
    device_service.add_recorder_microphone(session, recorder_id, body)
    return api_success()


@router.delete(
    "/{recorder_id}/microphones/{microphone_id}",
    response_model=ApiResponse,
    dependencies=[Depends(get_current_active_superuser)],
    summary="移除录音机麦克风关联 / Remove Recorder-Microphone Association",
)
def remove_recorder_microphone(
    session: SessionDep, recorder_id: int, microphone_id: int
) -> Any:
    """
    移除录音机与麦克风的关联。 / Remove a recorder-microphone association.

    仅管理员可访问。 / Admin only.
    """
    device_service.remove_recorder_microphone(session, recorder_id, microphone_id)
    return ApiResponse()
