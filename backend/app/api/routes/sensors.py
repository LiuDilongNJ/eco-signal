"""传感器 API 路由（管理员 CRUD + 公开选项）。 / Sensors: admin CRUD and public options."""
from datetime import UTC, date, datetime, time
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import select

from app.api.deps import SessionDep, get_current_active_superuser
from app.api.responses import csv_response
from app.models import Sensor
from app.schemas.device import SensorCreate, SensorOption, SensorPublic, SensorUpdate
from app.schemas.response import PagedApiResponse, ApiResponse, api_page, api_success
from app.services import device_service
from app.utils import parse_uuid

router = APIRouter(prefix="/sensors", tags=["传感器 / sensors"])
router_views = APIRouter(tags=["传感器 / sensors"])


def _date_start(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.min, UTC)


def _date_end(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.max, UTC)


@router_views.get(
    "/sensor-options",
    response_model=ApiResponse[list[SensorOption]],
    summary="获取传感器选项 / Get Sensor Options",
)
def get_sensor_options(session: SessionDep) -> Any:
    """
    获取下拉菜单的传感器选项。 / Get sensor options for dropdown menus.

    返回包含 ID 和名称的所有传感器列表。 / Returns list of all sensors with id and name.
    无需身份验证。 / No authentication required.
    """
    stmt = select(Sensor.sensor_id, Sensor.name, Sensor.sensor_type).order_by(Sensor.name)
    results = session.exec(stmt).all()
    data = [{"sensor_id": r[0], "name": r[1] or "", "sensor_type": r[2]} for r in results]
    return api_success(data=data)


@router.get(
    "",
    response_model=PagedApiResponse[list[SensorPublic]],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取传感器列表 / List Sensors",
)
def list_sensors(
    session: SessionDep,
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数 / Page size"),
    sensor_id: Optional[int] = Query(default=None, description="传感器 ID 精确筛选 / Filter by sensor ID (exact)"),
    uuid: Optional[str] = Query(default=None, description="UUID 精确筛选 / Filter by UUID (exact)"),
    name: Optional[str] = Query(default=None, description="名称模糊搜索 / Fuzzy search by name"),
    description: Optional[str] = Query(default=None, description="描述模糊搜索 / Fuzzy search by description"),
    sensor_type: Optional[str] = Query(default=None, description="传感器类型模糊搜索 / Fuzzy search by sensor type"),
    recorder_id: Optional[int] = Query(default=None, description="通过录音机 ID 筛选 / Filter by recorder ID"),
    microphone_id: Optional[int] = Query(default=None, description="通过麦克风 ID 筛选 / Filter by microphone ID"),
    camera_id: Optional[int] = Query(default=None, description="通过相机 ID 筛选 / Filter by camera ID"),
    lens_id: Optional[int] = Query(default=None, description="通过镜头 ID 筛选 / Filter by lens ID"),
    recorder_name: Optional[str] = Query(default=None, description="录音机名称模糊搜索 / Fuzzy search by recorder name"),
    microphone_name: Optional[str] = Query(default=None, description="麦克风名称模糊搜索 / Fuzzy search by microphone name"),
    camera_name: Optional[str] = Query(default=None, description="相机名称模糊搜索 / Fuzzy search by camera name"),
    lens_name: Optional[str] = Query(default=None, description="镜头名称模糊搜索 / Fuzzy search by lens name"),
    creation_date_from: Optional[date] = Query(default=None, description="创建日期起始（含）YYYY-MM-DD / Creation date from"),
    creation_date_to: Optional[date] = Query(default=None, description="创建日期截止（含）YYYY-MM-DD / Creation date to"),
    order_by: str = Query(default="sensor_id", description="排序字段：sensor_id, uuid, name, sensor_type, recorder_name, microphone_name, camera_name, lens_name, creation_date / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    """
    获取所有传感器列表（分页，支持筛选和排序），含关联设备名称。
    Get paginated list of sensors with filter and sort support, including associated device names.

    仅管理员可访问。 / Admin only.
    """
    filters = {
        "sensor_id": sensor_id,
        "uuid": parse_uuid(uuid),
        "name": name,
        "description": description,
        "sensor_type": sensor_type,
        "recorder_id": recorder_id,
        "microphone_id": microphone_id,
        "camera_id": camera_id,
        "lens_id": lens_id,
        "recorder_name": recorder_name,
        "microphone_name": microphone_name,
        "camera_name": camera_name,
        "lens_name": lens_name,
        "creation_date_from": _date_start(creation_date_from),
        "creation_date_to": _date_end(creation_date_to),
    }
    items, total = device_service.list_sensors(session, page, page_size, filters, order_by, order_dir)
    return api_page(data=items, total=total, page=page, page_size=page_size)


@router.get(
    "/exports",
    dependencies=[Depends(get_current_active_superuser)],
    summary="导出传感器列表 / Export Sensors",
)
def export_sensors(
    session: SessionDep,
    sensor_id: Optional[int] = Query(default=None, description="传感器 ID 精确筛选 / Filter by sensor ID (exact)"),
    uuid: Optional[str] = Query(default=None, description="UUID 精确筛选 / Filter by UUID (exact)"),
    name: Optional[str] = Query(default=None, description="名称模糊搜索 / Fuzzy search by name"),
    description: Optional[str] = Query(default=None, description="描述模糊搜索 / Fuzzy search by description"),
    sensor_type: Optional[str] = Query(default=None, description="传感器类型模糊搜索 / Fuzzy search by sensor type"),
    recorder_id: Optional[int] = Query(default=None, description="通过录音机 ID 筛选 / Filter by recorder ID"),
    microphone_id: Optional[int] = Query(default=None, description="通过麦克风 ID 筛选 / Filter by microphone ID"),
    camera_id: Optional[int] = Query(default=None, description="通过相机 ID 筛选 / Filter by camera ID"),
    lens_id: Optional[int] = Query(default=None, description="通过镜头 ID 筛选 / Filter by lens ID"),
    recorder_name: Optional[str] = Query(default=None, description="录音机名称模糊搜索 / Fuzzy search by recorder name"),
    microphone_name: Optional[str] = Query(default=None, description="麦克风名称模糊搜索 / Fuzzy search by microphone name"),
    camera_name: Optional[str] = Query(default=None, description="相机名称模糊搜索 / Fuzzy search by camera name"),
    lens_name: Optional[str] = Query(default=None, description="镜头名称模糊搜索 / Fuzzy search by lens name"),
    creation_date_from: Optional[date] = Query(default=None, description="创建日期起始（含）YYYY-MM-DD / Creation date from"),
    creation_date_to: Optional[date] = Query(default=None, description="创建日期截止（含）YYYY-MM-DD / Creation date to"),
    order_by: str = Query(default="sensor_id", description="排序字段：sensor_id, uuid, name, sensor_type, recorder_name, microphone_name, camera_name, lens_name, creation_date / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    filters = {
        "sensor_id": sensor_id,
        "uuid": parse_uuid(uuid),
        "name": name,
        "description": description,
        "sensor_type": sensor_type,
        "recorder_id": recorder_id,
        "microphone_id": microphone_id,
        "camera_id": camera_id,
        "lens_id": lens_id,
        "recorder_name": recorder_name,
        "microphone_name": microphone_name,
        "camera_name": camera_name,
        "lens_name": lens_name,
        "creation_date_from": _date_start(creation_date_from),
        "creation_date_to": _date_end(creation_date_to),
    }
    csv_content = device_service.export_sensors_csv(session, filters, order_by, order_dir)
    return csv_response(csv_content, "sensors.csv")


@router.post(
    "",
    response_model=ApiResponse[None],
    dependencies=[Depends(get_current_active_superuser)],
    summary="创建传感器 / Create Sensor",
)
def create_sensor(session: SessionDep, body: SensorCreate) -> Any:
    """
    创建新传感器。 / Create a new sensor.

    仅管理员可访问。 / Admin only.
    """
    device_service.create_sensor(
        session, body.name, body.sensor_type,
        body.recorder_id, body.microphone_id, body.camera_id, body.lens_id,
        body.camera_lens_is_default,
        body.description,
        body.recorder_microphone_is_default,
    )
    return api_success()


@router.get(
    "/{sensor_id}",
    response_model=ApiResponse[SensorPublic],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取传感器详情 / Get Sensor",
)
def get_sensor(session: SessionDep, sensor_id: int) -> Any:
    """
    根据 ID 获取传感器详情，含关联设备名称。
    Get sensor detail by ID, including associated device names.

    仅管理员可访问。 / Admin only.
    """
    result = device_service.get_sensor(session, sensor_id)
    return api_success(data=result)


@router.put(
    "/{sensor_id}",
    response_model=ApiResponse[None],
    dependencies=[Depends(get_current_active_superuser)],
    summary="更新传感器 / Update Sensor",
)
def update_sensor(session: SessionDep, sensor_id: int, body: SensorUpdate) -> Any:
    """
    更新传感器信息。 / Update sensor information.

    仅管理员可访问。 / Admin only.
    """
    device_service.update_sensor(session, sensor_id, body)
    return api_success()


@router.delete(
    "/{sensor_id}",
    response_model=ApiResponse,
    dependencies=[Depends(get_current_active_superuser)],
    summary="删除传感器 / Delete Sensor",
)
def delete_sensor(session: SessionDep, sensor_id: int) -> Any:
    """
    删除传感器。如果被媒体引用则拒绝删除。
    Delete a sensor. Rejected if referenced by media records.

    仅管理员可访问。 / Admin only.
    """
    device_service.delete_sensor(session, sensor_id)
    return ApiResponse()
