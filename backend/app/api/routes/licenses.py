"""许可证 API 路由（管理员 CRUD + 公开选项）。 / Licenses: admin CRUD and public options."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import select

from app.api.deps import SessionDep, get_current_active_superuser
from app.api.responses import csv_response
from app.models import License
from app.schemas.device import LicenseCreate, LicenseOption, LicensePublic, LicenseUpdate
from app.schemas.response import PagedApiResponse, ApiResponse, api_page, api_success
from app.services import device_service

router = APIRouter(prefix="/licenses", tags=["许可证 / licenses"])
router_views = APIRouter(tags=["许可证 / licenses"])


@router_views.get("/license-options", response_model=ApiResponse[list[LicenseOption]], summary="获取许可证选项 / Get License Options")
def get_license_options(session: SessionDep) -> Any:
    """
    获取下拉菜单的许可证选项。 / Get license options for dropdown menus.

    返回包含 ID 和名称的所有许可证列表。 / Returns list of all licenses with id and name.
    无需身份验证。 / No authentication required.
    """
    stmt = select(License.license_id, License.name).order_by(License.name)
    results = session.exec(stmt).all()
    data = [{"license_id": r[0], "name": r[1] or ""} for r in results]
    return api_success(data=data)


@router.get(
    "",
    response_model=PagedApiResponse[list[LicensePublic]],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取许可证列表 / List Licenses",
)
def list_licenses(
    session: SessionDep,
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数 / Page size"),
    license_id: Optional[int] = Query(default=None, description="许可证 ID 精确筛选 / Filter by license ID (exact)"),
    name: Optional[str] = Query(default=None, description="名称模糊搜索 / Fuzzy search by name"),
    link: Optional[str] = Query(default=None, description="链接模糊搜索 / Fuzzy search by link"),
    order_by: str = Query(default="license_id", description="排序字段：license_id, name, link / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    """
    获取所有许可证列表（分页，支持筛选和排序）。 / Get paginated list of licenses with filter and sort support.

    仅管理员可访问。 / Admin only.
    """
    filters = {"license_id": license_id, "name": name, "link": link}
    items, total = device_service.list_licenses(session, page, page_size, filters, order_by, order_dir)
    return api_page(data=items, total=total, page=page, page_size=page_size)


@router.get(
    "/exports",
    dependencies=[Depends(get_current_active_superuser)],
    summary="导出许可证列表 / Export Licenses",
)
def export_licenses(
    session: SessionDep,
    license_id: Optional[int] = Query(default=None, description="许可证 ID 精确筛选 / Filter by license ID (exact)"),
    name: Optional[str] = Query(default=None, description="名称模糊搜索 / Fuzzy search by name"),
    link: Optional[str] = Query(default=None, description="链接模糊搜索 / Fuzzy search by link"),
    order_by: str = Query(default="license_id", description="排序字段：license_id, name, link / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    filters = {"license_id": license_id, "name": name, "link": link}
    csv_content = device_service.export_licenses_csv(session, filters, order_by, order_dir)
    return csv_response(csv_content, "licenses.csv")


@router.post(
    "",
    response_model=ApiResponse[LicensePublic],
    dependencies=[Depends(get_current_active_superuser)],
    summary="创建许可证 / Create License",
)
def create_license(
    session: SessionDep,
    body: LicenseCreate,
) -> Any:
    """
    创建新许可证。 / Create a new license.

    仅管理员可访问。 / Admin only.
    """
    result = device_service.create_license(session, body.name, body.link)
    return api_success(data=result)


@router.get(
    "/{license_id}",
    response_model=ApiResponse[LicensePublic],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取许可证详情 / Get License",
)
def get_license(session: SessionDep, license_id: int) -> Any:
    """
    根据 ID 获取许可证详情。 / Get license detail by ID.

    仅管理员可访问。 / Admin only.
    """
    result = device_service.get_license(session, license_id)
    return api_success(data=result)


@router.put(
    "/{license_id}",
    response_model=ApiResponse[LicensePublic],
    dependencies=[Depends(get_current_active_superuser)],
    summary="更新许可证 / Update License",
)
def update_license(
    session: SessionDep,
    license_id: int,
    body: LicenseUpdate,
) -> Any:
    """
    更新许可证信息。 / Update license information.

    仅管理员可访问。 / Admin only.
    """
    result = device_service.update_license(session, license_id, body.name, body.link)
    return api_success(data=result)


@router.delete(
    "/{license_id}",
    response_model=ApiResponse,
    dependencies=[Depends(get_current_active_superuser)],
    summary="删除许可证 / Delete License",
)
def delete_license(session: SessionDep, license_id: int) -> Any:
    """
    删除许可证。如果有媒体正在使用该许可证，则拒绝删除。
    Delete a license. Rejected if the license is referenced by media records.

    仅管理员可访问。 / Admin only.
    """
    device_service.delete_license(session, license_id)
    return ApiResponse()
