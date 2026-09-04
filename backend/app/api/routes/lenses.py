"""镜头 API 路由（管理员 CRUD + 公开选项）。 / Lenses: admin CRUD and public options."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.models import Lens
from app.schemas.device import (
    LensCreate,
    LensListItem,
    LensOption,
    LensPublic,
    LensUpdate,
    DeviceImportResponse,
)
from app.schemas.response import (
    ApiResponse,
    PagedApiResponse,
    api_page,
    api_success,
)
from app.services import device_service
from app.csv_import import attach_import_metadata, parse_import_upload
from app.utils import parse_uuid

router = APIRouter(prefix="/lenses", tags=["镜头 / lenses"])
router_views = APIRouter(tags=["镜头 / lenses"])


@router_views.get(
    "/lens-options",
    response_model=ApiResponse[list[LensOption]],
    summary="获取镜头选项 / Get Lens Options",
)
def get_lens_options(session: SessionDep, _: CurrentUser) -> Any:
    """
    获取下拉菜单的镜头选项。 / Get lens options for dropdown menus.

    返回包含 ID 和名称的所有镜头列表。 / Returns list of all lenses with id and name.
    需要登录。 / Login required.
    """
    stmt = select(Lens.lens_id, Lens.name).order_by(Lens.name)
    results = session.exec(stmt).all()
    data = [{"lens_id": r[0], "name": r[1] or ""} for r in results]
    return api_success(data=data)


@router.get(
    "",
    response_model=PagedApiResponse[list[LensListItem]],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取镜头列表 / List Lenses",
)
def list_lenses(
    session: SessionDep,
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数 / Page size"),
    lens_id: Optional[int] = Query(default=None, description="镜头 ID 精确筛选 / Filter by lens ID (exact)"),
    uuid: Optional[str] = Query(default=None, description="UUID 精确筛选 / Filter by UUID (exact)"),
    name: Optional[str] = Query(default=None, description="名称模糊搜索 / Fuzzy search by name"),
    focal_length: Optional[str] = Query(default=None, description="焦距模糊搜索 / Fuzzy search by focal length"),
    max_aperture: Optional[str] = Query(default=None, description="最大光圈模糊搜索 / Fuzzy search by max aperture"),
    brand: Optional[str] = Query(default=None, description="品牌模糊搜索 / Fuzzy search by brand"),
    order_by: str = Query(default="lens_id", description="排序字段：lens_id, uuid, name, focal_length, max_aperture, brand / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    """
    获取所有镜头列表（分页，支持筛选和排序）。
    Get paginated list of lenses with filter and sort support.

    仅管理员可访问。 / Admin only.
    """
    filters = {
        "lens_id": lens_id,
        "uuid": parse_uuid(uuid),
        "name": name,
        "focal_length": focal_length,
        "max_aperture": max_aperture,
        "brand": brand,
    }
    items, total = device_service.list_lenses(session, page, page_size, filters, order_by, order_dir)
    return api_page(data=items, total=total, page=page, page_size=page_size)


@router.get(
    "/exports",
    dependencies=[Depends(get_current_active_superuser)],
    summary="导出镜头列表 / Export Lenses",
)
def export_lenses(
    session: SessionDep,
    lens_id: Optional[int] = Query(default=None, description="镜头 ID 精确筛选 / Filter by lens ID (exact)"),
    uuid: Optional[str] = Query(default=None, description="UUID 精确筛选 / Filter by UUID (exact)"),
    name: Optional[str] = Query(default=None, description="名称模糊搜索 / Fuzzy search by name"),
    focal_length: Optional[str] = Query(default=None, description="焦距模糊搜索 / Fuzzy search by focal length"),
    max_aperture: Optional[str] = Query(default=None, description="最大光圈模糊搜索 / Fuzzy search by max aperture"),
    brand: Optional[str] = Query(default=None, description="品牌模糊搜索 / Fuzzy search by brand"),
    order_by: str = Query(default="lens_id", description="排序字段：lens_id, uuid, name, focal_length, max_aperture, brand / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    from app.api.responses import csv_response

    filters = {
        "lens_id": lens_id,
        "uuid": parse_uuid(uuid),
        "name": name,
        "focal_length": focal_length,
        "max_aperture": max_aperture,
        "brand": brand,
    }
    csv_content = device_service.export_lenses_csv(session, filters, order_by, order_dir)
    return csv_response(csv_content, "lenses.csv")


@router.post("/imports", response_model=ApiResponse[DeviceImportResponse], dependencies=[Depends(get_current_active_superuser)], summary="导入镜头 / Import Lenses")
async def import_lenses(session: SessionDep, file: UploadFile = File(...), dry_run: bool = Form(True)) -> Any:
    """使用固定字段模板导入镜头。 / Import lenses using the fixed field template."""
    parsed = parse_import_upload(file.filename or "", await file.read())
    report = device_service.import_lenses_csv(session, parsed.text, dry_run=dry_run)
    return api_success(message="Import validation completed" if dry_run else "Import completed", data=attach_import_metadata(report, parsed, dry_run=dry_run))


@router.post(
    "",
    response_model=ApiResponse[None],
    dependencies=[Depends(get_current_active_superuser)],
    summary="创建镜头 / Create Lens",
)
def create_lens(session: SessionDep, body: LensCreate) -> Any:
    """
    创建新镜头。 / Create a new lens.

    仅管理员可访问。 / Admin only.
    """
    device_service.create_lens(
        session, body.name, body.focal_length, body.max_aperture, body.brand
    )
    return api_success()


@router.get(
    "/{lens_id}",
    response_model=ApiResponse[LensPublic],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取镜头详情 / Get Lens",
)
def get_lens(session: SessionDep, lens_id: int) -> Any:
    """
    根据 ID 获取镜头详情。
    Get lens detail by ID.

    仅管理员可访问。 / Admin only.
    """
    result = device_service.get_lens(session, lens_id)
    return api_success(data=result)


@router.put(
    "/{lens_id}",
    response_model=ApiResponse[None],
    dependencies=[Depends(get_current_active_superuser)],
    summary="更新镜头 / Update Lens",
)
def update_lens(session: SessionDep, lens_id: int, body: LensUpdate) -> Any:
    """
    更新镜头信息。 / Update lens information.

    仅管理员可访问。 / Admin only.
    """
    device_service.update_lens(session, lens_id, body)
    return api_success()


@router.delete(
    "/{lens_id}",
    response_model=ApiResponse,
    dependencies=[Depends(get_current_active_superuser)],
    summary="删除镜头 / Delete Lens",
)
def delete_lens(session: SessionDep, lens_id: int) -> Any:
    """
    删除镜头。如果被传感器引用则拒绝删除。
    Delete a lens. Rejected if referenced by sensor records.

    仅管理员可访问。 / Admin only.
    """
    device_service.delete_lens(session, lens_id)
    return ApiResponse()
