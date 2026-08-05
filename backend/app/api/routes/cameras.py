"""相机 API 路由（管理员 CRUD、相机-镜头关联）。 / Cameras: admin CRUD and camera-lens links."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.api.deps import SessionDep, get_current_active_superuser
from app.schemas.device import (
    CameraCreate,
    CameraLensCreate,
    CameraListItem,
    CameraPublic,
    CameraUpdate,
    DeviceImportResponse,
)
from app.schemas.response import ApiResponse, PagedApiResponse, api_page, api_success
from app.services import device_service
from app.services.upload_validation_service import extension_for, validate_csv_content
from app.utils import parse_uuid

router = APIRouter(prefix="/cameras", tags=["相机 / cameras"])


@router.get(
    "",
    response_model=PagedApiResponse[list[CameraListItem]],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取相机列表 / List Cameras",
)
def list_cameras(
    session: SessionDep,
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数 / Page size"),
    camera_id: Optional[int] = Query(default=None, description="相机 ID 精确筛选 / Filter by camera ID (exact)"),
    uuid: Optional[str] = Query(default=None, description="UUID 精确筛选 / Filter by UUID (exact)"),
    name: Optional[str] = Query(default=None, description="名称模糊搜索 / Fuzzy search by name"),
    version: Optional[str] = Query(default=None, description="型号模糊搜索 / Fuzzy search by version"),
    brand: Optional[str] = Query(default=None, description="品牌模糊搜索 / Fuzzy search by brand"),
    lens_count: Optional[int] = Query(default=None, description="镜头数量精确筛选 / Filter by lens count (exact)"),
    order_by: str = Query(default="camera_id", description="排序字段：camera_id, uuid, name, version, brand, lens_count / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    """
    获取所有相机列表（分页，支持筛选和排序），含关联镜头数量。
    Get paginated list of cameras with filter and sort support, including associated lens count.

    仅管理员可访问。 / Admin only.
    """
    filters = {
        "camera_id": camera_id,
        "uuid": parse_uuid(uuid),
        "name": name,
        "version": version,
        "brand": brand,
        "lens_count": lens_count,
    }
    items, total = device_service.list_cameras(session, page, page_size, filters, order_by, order_dir)
    return api_page(data=items, total=total, page=page, page_size=page_size)


@router.get(
    "/exports",
    dependencies=[Depends(get_current_active_superuser)],
    summary="导出相机列表 / Export Cameras",
)
def export_cameras(
    session: SessionDep,
    camera_id: Optional[int] = Query(default=None, description="相机 ID 精确筛选 / Filter by camera ID (exact)"),
    uuid: Optional[str] = Query(default=None, description="UUID 精确筛选 / Filter by UUID (exact)"),
    name: Optional[str] = Query(default=None, description="名称模糊搜索 / Fuzzy search by name"),
    version: Optional[str] = Query(default=None, description="型号模糊搜索 / Fuzzy search by version"),
    brand: Optional[str] = Query(default=None, description="品牌模糊搜索 / Fuzzy search by brand"),
    lens_count: Optional[int] = Query(default=None, description="镜头数量精确筛选 / Filter by lens count (exact)"),
    order_by: str = Query(default="camera_id", description="排序字段：camera_id, uuid, name, version, brand, lens_count / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    """
    导出相机列表。 / Export cameras to CSV.

    仅管理员可访问。 / Admin only.
    """
    from app.api.responses import csv_response

    filters = {
        "camera_id": camera_id,
        "uuid": parse_uuid(uuid),
        "name": name,
        "version": version,
        "brand": brand,
        "lens_count": lens_count,
    }
    csv_content = device_service.export_cameras_csv(session, filters, order_by, order_dir)
    return csv_response(csv_content, "cameras.csv")


@router.post("/imports", response_model=ApiResponse[DeviceImportResponse], dependencies=[Depends(get_current_active_superuser)], summary="导入相机 / Import Cameras")
async def import_cameras(session: SessionDep, file: UploadFile = File(...)) -> Any:
    """使用固定 CSV 模板原子导入相机。 / Atomically import cameras from the fixed CSV template."""
    extension_for(file.filename or "", {"csv"})
    return api_success(data=device_service.import_cameras_csv(session, validate_csv_content(await file.read())))


@router.post(
    "",
    response_model=ApiResponse[None],
    dependencies=[Depends(get_current_active_superuser)],
    summary="创建相机 / Create Camera",
)
def create_camera(session: SessionDep, body: CameraCreate) -> Any:
    """
    创建新相机。 / Create a new camera.

    仅管理员可访问。 / Admin only.
    """
    device_service.create_camera(session, body.name, body.version, body.brand)
    return api_success()


@router.get(
    "/{camera_id}",
    response_model=ApiResponse[CameraPublic],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取相机详情 / Get Camera",
)
def get_camera(session: SessionDep, camera_id: int) -> Any:
    """
    根据 ID 获取相机详情，含关联的镜头列表。
    Get camera detail by ID, including associated lenses.

    仅管理员可访问。 / Admin only.
    """
    result = device_service.get_camera(session, camera_id)
    return api_success(data=result)


@router.put(
    "/{camera_id}",
    response_model=ApiResponse[None],
    dependencies=[Depends(get_current_active_superuser)],
    summary="更新相机 / Update Camera",
)
def update_camera(session: SessionDep, camera_id: int, body: CameraUpdate) -> Any:
    """
    更新相机信息。 / Update camera information.

    仅管理员可访问。 / Admin only.
    """
    device_service.update_camera(session, camera_id, body)
    return api_success()


@router.delete(
    "/{camera_id}",
    response_model=ApiResponse,
    dependencies=[Depends(get_current_active_superuser)],
    summary="删除相机 / Delete Camera",
)
def delete_camera(session: SessionDep, camera_id: int) -> Any:
    """
    删除相机。如果被传感器引用则拒绝删除。
    Delete a camera. Rejected if referenced by sensor records.

    仅管理员可访问。 / Admin only.
    """
    device_service.delete_camera(session, camera_id)
    return ApiResponse()


@router.post(
    "/{camera_id}/lenses",
    response_model=ApiResponse[None],
    dependencies=[Depends(get_current_active_superuser)],
    summary="添加相机镜头关联 / Add Camera-Lens Association",
)
def add_camera_lens(session: SessionDep, camera_id: int, body: CameraLensCreate) -> Any:
    """
    为相机添加兼容镜头关联。 / Add a compatible lens association for a camera.

    仅管理员可访问。 / Admin only.
    """
    device_service.add_camera_lens(session, camera_id, body)
    return api_success()


@router.delete(
    "/{camera_id}/lenses/{lens_id}",
    response_model=ApiResponse,
    dependencies=[Depends(get_current_active_superuser)],
    summary="移除相机镜头关联 / Remove Camera-Lens Association",
)
def remove_camera_lens(session: SessionDep, camera_id: int, lens_id: int) -> Any:
    """
    移除相机与镜头的关联。 / Remove a camera-lens association.

    仅管理员可访问。 / Admin only.
    """
    device_service.remove_camera_lens(session, camera_id, lens_id)
    return ApiResponse()
