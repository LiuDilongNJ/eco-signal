"""分类群 API 路由。 / Taxons API routes."""
from datetime import date, datetime, time
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.api.deps import SessionDep, get_current_active_superuser
from app.api.responses import csv_response
from app.repositories.taxon_repository import RemoteTaxonLookupError, taxon_repository
from app.schemas.response import ApiResponse, PagedApiResponse, api_page, api_success
from app.schemas.taxon import (
    SoundClassificationPublic,
    TaxonCreate,
    TaxonImportResponse,
    TaxonListItem,
    TaxonOption,
    TaxonPublic,
    TaxonRank,
    TaxonSoundTypePublic,
    TaxonUpdate,
)
from app.services import taxon_service
from app.services.upload_validation_service import extension_for, validate_csv_content

router = APIRouter(prefix="/taxons", tags=["分类群 / taxons"])
router_views = APIRouter(tags=["分类群 / taxons"])


def _date_start(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.min)


def _date_end(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.max)


@router.get("/suggestions", response_model=ApiResponse[list[TaxonPublic]], summary="搜索分类群 / Search Taxons")
def list_taxon_suggestions(
    session: SessionDep,
    q: str | None = Query(None, description="科学名称或常用名称的搜索关键字 / Search keyword for scientific or common name"),
    limit: int = Query(10, ge=1, le=100, description="要返回的最大结果数 / Max number of results to return"),
    offset: int = Query(0, ge=0, description="跳过的结果数 / Number of results to skip"),
) -> Any:
    """
    根据科学名称或常用名称搜索本地分类群字典。 / Search local taxon dictionary by scientific or common name.
    """
    taxons = taxon_repository.search(session, q=q, limit=limit, offset=offset)
    return api_success(data=[TaxonPublic.model_validate(t) for t in taxons])


@router_views.get(
    "/sound-classifications",
    response_model=ApiResponse[list[SoundClassificationPublic]],
    summary="获取声景分类列表 / Get Sound Classification List",
)
def get_sound_classifications(session: SessionDep) -> Any:
    """
    返回所有声景分类选项，用于标注表单「Soundscape」和「Sound Type」下拉。
    前端先按 soundscape_component 分组渲染第一个下拉，再按选中值过滤得到第二个下拉，
    最终取 sound_id 作为创建标注时的提交值。

    / Return all sound classification options for annotation form dropdowns.
    Group by soundscape_component for the first selector, filter for the second,
    and submit sound_id when creating an annotation.
    """
    items = taxon_repository.get_all_sound_classifications(session)
    return api_success(data=[SoundClassificationPublic.model_validate(item) for item in items])


@router_views.get(
    "/animal-sound-types",
    response_model=ApiResponse[list[TaxonSoundTypePublic]],
    summary="获取动物发声类型列表 / Get Animal Sound Type List",
)
def get_animal_sound_types(
    session: SessionDep,
    taxon_class: Optional[str] = Query(None, description="按分类纲过滤，如 AVES / Filter by taxon class, e.g. AVES"),
    taxon_order: Optional[str] = Query(None, description="按分类目过滤（优先于 taxon_class）/ Filter by taxon order (takes priority over taxon_class)"),
) -> Any:
    """
    返回动物发声类型，用于标注表单「Animal Sound」下拉。
    选定 Taxon 后，将其 col_class_id / col_order_id 作为过滤条件传入，获取匹配的发声类型列表。
    不传参数则返回全部。提交时取 name 字段作为 animal_sound_type 值。

    / Return animal sound types for the annotation form "Animal Sound" dropdown.
    Pass the taxon's class/order to filter; omit params to get all.
    Submit the name field as animal_sound_type.
    """
    items = taxon_repository.get_taxon_sound_types(
        session, taxon_class=taxon_class, taxon_order=taxon_order
    )
    return api_success(data=[TaxonSoundTypePublic.model_validate(i) for i in items])



@router.get(
    "/options",
    response_model=PagedApiResponse[list[TaxonOption]],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取分类层级选项 / Get Taxon Hierarchy Options",
)
def list_taxon_options(
    session: SessionDep,
    rank: TaxonRank = Query(..., description="层级：class|order|family|genus|species / Rank: class|order|family|genus|species"),
    class_id: Optional[str] = Query(None, description="按纲 ID 过滤 / Filter by class ID"),
    order_id: Optional[str] = Query(None, description="按目 ID 过滤 / Filter by order ID"),
    family_id: Optional[str] = Query(None, description="按科 ID 过滤 / Filter by family ID"),
    genus_id: Optional[str] = Query(None, description="按属 ID 过滤 / Filter by genus ID"),
    q: Optional[str] = Query(None, description="按名称模糊搜索 / Fuzzy search by name"),
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数 / Page size"),
) -> Any:
    """
    获取 taxon 管理表单的层级下拉选项，仅返回 id 和 name。

    / Get hierarchy dropdown options for taxon admin form. Returns id and name only.
    """
    try:
        items, total = taxon_repository.get_hierarchy_options(
            session=session,
            rank=rank,
            class_id=class_id,
            order_id=order_id,
            family_id=family_id,
            genus_id=genus_id,
            q=q,
            page=page,
            page_size=page_size,
        )
    except RemoteTaxonLookupError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return api_page(data=[TaxonOption.model_validate(item) for item in items], total=total, page=page, page_size=page_size)


@router.get(
    "",
    response_model=PagedApiResponse[list[TaxonListItem]],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取分类群列表 / List Taxons",
)
def list_taxons(
    session: SessionDep,
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数 / Page size"),
    taxon_id: Optional[int] = Query(default=None, description="按 taxon_id 精确筛选 / Filter by taxon_id (exact)"),
    q: Optional[str] = Query(default=None, description="按学名或俗名关键字搜索 / Keyword search on scientific or common name"),
    cached_scientific_name: Optional[str] = Query(default=None, description="按学名模糊筛选 / Fuzzy filter by scientific name"),
    cached_common_name: Optional[str] = Query(default=None, description="按俗名模糊筛选 / Fuzzy filter by common name"),
    taxonomy_source: Optional[str] = Query(default=None, description="来源精确筛选，如 CatalogueOfLife / Filter by taxonomy source"),
    col_class_id: Optional[str] = Query(default=None, description="按 COL 纲 ID 筛选 / Filter by COL class ID"),
    col_order_id: Optional[str] = Query(default=None, description="按 COL 目 ID 筛选 / Filter by COL order ID"),
    col_genus_name: Optional[str] = Query(default=None, description="按属名称筛选 / Filter by genus name"),
    col_species_name: Optional[str] = Query(default=None, description="按种名称筛选 / Filter by species name"),
    col_family_name: Optional[str] = Query(default=None, description="按科名称筛选 / Filter by family name"),
    col_order_name: Optional[str] = Query(default=None, description="按目名称筛选 / Filter by order name"),
    col_class_name: Optional[str] = Query(default=None, description="按纲名称筛选 / Filter by class name"),
    creation_date_from: Optional[date] = Query(default=None, description="创建日期起始 YYYY-MM-DD / Creation date from"),
    creation_date_to: Optional[date] = Query(default=None, description="创建日期截止 YYYY-MM-DD / Creation date to"),
    last_synced_from: Optional[date] = Query(default=None, description="最后同步时间起始 YYYY-MM-DD / Last synced from"),
    last_synced_to: Optional[date] = Query(default=None, description="最后同步时间截止 YYYY-MM-DD / Last synced to"),
    order_by: str = Query(default="taxon_id", description="排序字段：taxon_id, scientific_name, common_name, col_species_name, col_genus_name, col_family_name, col_order_name, col_class_name, taxonomy_source, creation_date, last_synced / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    """
    获取分类群列表（分页，支持多字段筛选和排序）。
    Get paginated taxon list with multi-field filter and sort support.

    仅管理员可访问。 / Admin only.
    """
    filters = {
        "taxon_id": taxon_id,
        "q": q,
        "cached_scientific_name": cached_scientific_name,
        "cached_common_name": cached_common_name,
        "taxonomy_source": taxonomy_source,
        "col_class_id": col_class_id,
        "col_order_id": col_order_id,
        "col_genus_name": col_genus_name,
        "col_species_name": col_species_name,
        "col_family_name": col_family_name,
        "col_order_name": col_order_name,
        "col_class_name": col_class_name,
        "creation_date_from": _date_start(creation_date_from),
        "creation_date_to": _date_end(creation_date_to),
        "last_synced_from": _date_start(last_synced_from),
        "last_synced_to": _date_end(last_synced_to),
    }
    try:
        items, total = taxon_repository.list_taxons(
            session, page, page_size, filters, order_by, order_dir
        )
    except RemoteTaxonLookupError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return api_page(data=[TaxonListItem.model_validate(t) for t in items], total=total, page=page, page_size=page_size)


@router.get(
    "/exports",
    dependencies=[Depends(get_current_active_superuser)],
    summary="导出分类群列表 / Export Taxons",
)
def export_taxons(
    session: SessionDep,
    order_by: str = Query(default="taxon_id", description="排序字段：taxon_id, scientific_name, common_name, col_species_name, col_genus_name, col_family_name, col_order_name, col_class_name, taxonomy_source, creation_date, last_synced / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向 / Sort direction"),
) -> Any:
    csv_content = taxon_service.export_taxons_csv(session, {}, order_by, order_dir)
    return csv_response(csv_content, "taxons.csv")


@router.post("/imports", response_model=ApiResponse[TaxonImportResponse], dependencies=[Depends(get_current_active_superuser)], summary="导入分类群 / Import Taxons")
async def import_taxons(session: SessionDep, file: UploadFile = File(...)) -> Any:
    """使用固定 CSV 模板原子导入分类群。 / Atomically import taxons from the fixed CSV template."""
    extension_for(file.filename or "", {"csv"})
    return api_success(data=taxon_service.import_taxons_csv(session, validate_csv_content(await file.read())))


@router.post(
    "",
    response_model=ApiResponse[TaxonListItem],
    dependencies=[Depends(get_current_active_superuser)],
    summary="创建分类群 / Create Taxon",
)
def create_taxon(session: SessionDep, body: TaxonCreate) -> Any:
    """
    创建新的分类群记录。 / Create a new taxon record.

    仅管理员可访问。 / Admin only.
    """
    try:
        taxon = taxon_repository.create(session, body)
    except RemoteTaxonLookupError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    detail = taxon_repository.get_detail_by_id(session, taxon.taxon_id)
    return api_success(data=TaxonListItem.model_validate(detail))


@router.get(
    "/{taxon_id}",
    response_model=ApiResponse[TaxonListItem],
    dependencies=[Depends(get_current_active_superuser)],
    summary="获取分类群详情 / Get Taxon",
)
def get_taxon(session: SessionDep, taxon_id: int) -> Any:
    """
    根据 ID 获取分类群详情。 / Get taxon detail by ID.

    仅管理员可访问。 / Admin only.
    """
    taxon = taxon_repository.get_detail_by_id(session, taxon_id)
    if taxon is None:
        raise HTTPException(status_code=404, detail="Taxon not found")
    return api_success(data=TaxonListItem.model_validate(taxon))


@router.put(
    "/{taxon_id}",
    response_model=ApiResponse[TaxonListItem],
    dependencies=[Depends(get_current_active_superuser)],
    summary="更新分类群 / Update Taxon",
)
def update_taxon(session: SessionDep, taxon_id: int, body: TaxonUpdate) -> Any:
    """
    更新分类群信息。 / Update taxon information.

    仅管理员可访问。 / Admin only.
    """
    taxon = taxon_repository.get_by_id(session, taxon_id)
    if not taxon:
        raise HTTPException(status_code=404, detail="Taxon not found")
    try:
        taxon = taxon_repository.update(session, taxon, body)
    except RemoteTaxonLookupError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    detail = taxon_repository.get_detail_by_id(session, taxon.taxon_id)
    return api_success(data=TaxonListItem.model_validate(detail))


@router.delete(
    "/{taxon_id}",
    response_model=ApiResponse,
    dependencies=[Depends(get_current_active_superuser)],
    summary="删除分类群 / Delete Taxon",
)
def delete_taxon(session: SessionDep, taxon_id: int) -> Any:
    """
    删除分类群。若被标注引用则拒绝删除。
    Delete a taxon. Rejected if referenced by annotation records.

    仅管理员可访问。 / Admin only.
    """
    taxon = taxon_repository.get_by_id(session, taxon_id)
    if not taxon:
        raise HTTPException(status_code=404, detail="Taxon not found")
    if taxon_repository.is_referenced(session, taxon_id):
        raise HTTPException(status_code=400, detail="Cannot delete taxon: it is referenced by annotation records")
    taxon_repository.delete(session, taxon)
    return ApiResponse()
