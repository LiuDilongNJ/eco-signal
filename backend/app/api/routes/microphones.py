"""麦克风 API 路由（管理员 CRUD + 公开选项）。 / Microphones: admin CRUD and public options."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlmodel import select

from app.api.deps import SessionDep, get_current_active_superuser
from app.api.responses import csv_response
from app.models import Microphone, RecorderMicrophone
from app.schemas.device import (
    MicrophoneCreate,
    MicrophoneListItem,
    MicrophoneOption,
    MicrophonePublic,
    MicrophoneUpdate,
    DeviceImportResponse,
)
from app.schemas.response import ApiResponse, PagedApiResponse, api_page, api_success
from app.services import device_service
from app.services.upload_validation_service import extension_for, validate_csv_content
from app.utils import parse_range, parse_uuid

router = APIRouter(prefix="/microphones", tags=["麦克风 / microphones"])
router_views = APIRouter(tags=["麦克风 / microphones"])


@router_views.get(
    "/microphone-options",
    response_model=ApiResponse[list[MicrophoneOption]],
    summary="获取麦克风选项 / Get Microphone Options",
)
def get_microphone_options(
    session: SessionDep,
    recorder_id: Optional[int] = Query(default=None, description="通过录音机 ID 筛选 / Filter by recorder ID"),
) -> Any:
    """
    获取下拉菜单的麦克风选项。 / Get microphone options for dropdown menus.

    返回包含 ID 和名称的麦克风列表。 / Returns list of microphones with id and name.
    可选地通过 recorder_id 筛选（通过 recorder_microphone table 关联）。 / Optionally filtered by recorder_id (linked via recorder_microphone table).
    无需身份验证。 / No authentication required.
    """
    if recorder_id:
        stmt = (
            select(Microphone.microphone_id, Microphone.name)
            .join(RecorderMicrophone)
            .where(RecorderMicrophone.recorder_id == recorder_id)
            .order_by(Microphone.name)
        )
    else:
        stmt = select(Microphone.microphone_id, Microphone.name).order_by(Microphone.name)

    results = session.exec(stmt).all()
    data = [{"microphone_id": r[0], "name": r[1] or ""} for r in results]
    return api_success(data=data)


@router.get(
    "",
    response_model=PagedApiResponse[list[MicrophoneListItem]],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取麦克风列表 / List Microphones",
)
def list_microphones(
    session: SessionDep,
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数 / Page size"),
    microphone_id: Optional[int] = Query(default=None, description="麦克风 ID 精确筛选 / Filter by microphone ID (exact)"),
    uuid: Optional[str] = Query(default=None, description="UUID 精确筛选 / Filter by UUID (exact)"),
    name: Optional[str] = Query(default=None, description="名称模糊搜索 / Fuzzy search by name"),
    microphone_element: Optional[str] = Query(default=None, description="振膜类型模糊搜索 / Fuzzy search by microphone element"),
    sensitivity: Optional[str] = Query(default=None, description="灵敏度区间，格式：min,max / Sensitivity range: min,max"),
    signal_to_noise_ratio: Optional[str] = Query(default=None, description="信噪比区间，格式：min,max / SNR range: min,max"),
    recorder_id: Optional[int] = Query(default=None, description="通过录音机 ID 筛选 / Filter by recorder ID"),
    recorder_count: Optional[int] = Query(default=None, ge=0, description="录音机数量精确筛选 / Filter by recorder count (exact)"),
    order_by: str = Query(default="microphone_id", description="排序字段：microphone_id, uuid, name, microphone_element, sensitivity, signal_to_noise_ratio, recorder_count / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    """
    获取所有麦克风列表（分页，支持筛选和排序），含关联录音机数量。
    Get paginated list of microphones with filter and sort support, including associated recorder count.

    仅管理员可访问。 / Admin only.
    """
    sens_min, sens_max = parse_range(sensitivity)
    snr_min, snr_max = parse_range(signal_to_noise_ratio)
    filters = {
        "microphone_id": microphone_id,
        "uuid": parse_uuid(uuid),
        "name": name,
        "microphone_element": microphone_element,
        "sensitivity_min": sens_min,
        "sensitivity_max": sens_max,
        "signal_to_noise_ratio_min": snr_min,
        "signal_to_noise_ratio_max": snr_max,
        "recorder_id": recorder_id,
        "recorder_count": recorder_count,
    }
    items, total = device_service.list_microphones(session, page, page_size, filters, order_by, order_dir)
    return api_page(data=items, total=total, page=page, page_size=page_size)


@router.get(
    "/exports",
    dependencies=[Depends(get_current_active_superuser)],
    summary="导出麦克风列表 / Export Microphones",
)
def export_microphones(
    session: SessionDep,
    microphone_id: Optional[int] = Query(default=None, description="麦克风 ID 精确筛选 / Filter by microphone ID (exact)"),
    uuid: Optional[str] = Query(default=None, description="UUID 精确筛选 / Filter by UUID (exact)"),
    name: Optional[str] = Query(default=None, description="名称模糊搜索 / Fuzzy search by name"),
    microphone_element: Optional[str] = Query(default=None, description="拾音器类型模糊搜索 / Fuzzy search by microphone element"),
    sensitivity: Optional[str] = Query(default=None, description="灵敏度区间，格式：min,max / Sensitivity range: min,max"),
    signal_to_noise_ratio: Optional[str] = Query(default=None, description="信噪比区间，格式：min,max / SNR range: min,max"),
    recorder_id: Optional[int] = Query(default=None, description="按关联的录音机筛选 / Filter by associated recorder ID"),
    order_by: str = Query(default="microphone_id", description="排序字段：microphone_id, uuid, name, microphone_element, sensitivity, signal_to_noise_ratio, recorder_count / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    sens_min, sens_max = parse_range(sensitivity)
    snr_min, snr_max = parse_range(signal_to_noise_ratio)

    filters = {
        "microphone_id": microphone_id,
        "uuid": parse_uuid(uuid),
        "name": name,
        "microphone_element": microphone_element,
        "sensitivity_min": sens_min,
        "sensitivity_max": sens_max,
        "signal_to_noise_ratio_min": snr_min,
        "signal_to_noise_ratio_max": snr_max,
        "recorder_id": recorder_id,
    }
    csv_content = device_service.export_microphones_csv(session, filters, order_by, order_dir)
    return csv_response(csv_content, "microphones.csv")


@router.post("/imports", response_model=ApiResponse[DeviceImportResponse], dependencies=[Depends(get_current_active_superuser)], summary="导入麦克风 / Import Microphones")
async def import_microphones(session: SessionDep, file: UploadFile = File(...)) -> Any:
    """使用固定 CSV 模板原子导入麦克风。 / Atomically import microphones from the fixed CSV template."""
    extension_for(file.filename or "", {"csv"})
    return api_success(data=device_service.import_microphones_csv(session, validate_csv_content(await file.read())))


@router.post(
    "",
    response_model=ApiResponse[None],
    dependencies=[Depends(get_current_active_superuser)],
    summary="创建麦克风 / Create Microphone",
)
def create_microphone(session: SessionDep, body: MicrophoneCreate) -> Any:
    """
    创建新麦克风。 / Create a new microphone.

    仅管理员可访问。 / Admin only.
    """
    device_service.create_microphone(
        session, body.name, body.microphone_element, body.sensitivity, body.signal_to_noise_ratio
    )
    return api_success()


@router.get(
    "/{microphone_id}",
    response_model=ApiResponse[MicrophonePublic],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取麦克风详情 / Get Microphone",
)
def get_microphone(session: SessionDep, microphone_id: int) -> Any:
    """
    根据 ID 获取麦克风详情，含关联的录音机列表。
    Get microphone detail by ID, including associated recorders.

    仅管理员可访问。 / Admin only.
    """
    result = device_service.get_microphone(session, microphone_id)
    return api_success(data=result)


@router.put(
    "/{microphone_id}",
    response_model=ApiResponse[None],
    dependencies=[Depends(get_current_active_superuser)],
    summary="更新麦克风 / Update Microphone",
)
def update_microphone(session: SessionDep, microphone_id: int, body: MicrophoneUpdate) -> Any:
    """
    更新麦克风信息。 / Update microphone information.

    仅管理员可访问。 / Admin only.
    """
    device_service.update_microphone(session, microphone_id, body)
    return api_success()


@router.delete(
    "/{microphone_id}",
    response_model=ApiResponse,
    dependencies=[Depends(get_current_active_superuser)],
    summary="删除麦克风 / Delete Microphone",
)
def delete_microphone(session: SessionDep, microphone_id: int) -> Any:
    """
    删除麦克风。如果被传感器引用则拒绝删除。
    Delete a microphone. Rejected if referenced by sensor records.

    仅管理员可访问。 / Admin only.
    """
    device_service.delete_microphone(session, microphone_id)
    return ApiResponse()
