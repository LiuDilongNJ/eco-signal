"""标注 API 路由。 / Annotations API routes."""
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, File, Form, Query, UploadFile

from app.api.deps import CurrentUser, CurrentUserOptional, SessionDep
from app.api.responses import csv_response
from app.csv_import import attach_import_metadata, parse_import_upload
from app.enums import MediaType
from app.schemas.annotation import (
    AnnotationCreate,
    AnnotationNavigation,
    AnnotationUpdate,
    AnnotationWithReviews,
)
from app.schemas.response import ApiResponse, PagedApiResponse, api_page, api_success
from app.services import annotation_service, permission_service, tabular_import_service
from app.utils import parse_range, parse_uuid

router = APIRouter(prefix="/annotations", tags=["标注 / annotations"])


@router.post("/imports", summary="导入标注 / Import Annotations")
async def import_annotations(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int = Form(...),
    collection_id: int = Form(...),
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
    media_type: Literal["audio", "photo"] | None = Form(None),
) -> Any:
    """校验或原子导入标注。 / Validate or atomically import annotations."""
    permission_service.require_collection_resource_permission(
        session,
        collection_id=collection_id,
        project_id=project_id,
        user=current_user,
        resource_type="annotation",
        action="write",
        denied_detail="No annotation:write permission on collection",
    )
    parsed = parse_import_upload(file.filename or "", await file.read())
    report = tabular_import_service.import_annotations(
        session,
        parsed.text,
        current_user,
        project_id,
        collection_id,
        dry_run=dry_run,
        expected_media_type=media_type,
    )
    return api_success(message="Import validation completed" if dry_run else "Import completed", data=attach_import_metadata(report, parsed, dry_run=dry_run))



@router.get(
    "/exports",
    summary="导出标注 CSV / Export annotations to CSV",
)
def export_annotations(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: Optional[int] = Query(None, description="项目 ID / Project ID"),
    collection_id: Optional[int] = Query(None, description="集合 ID / Collection ID"),
    media_id: Optional[int] = Query(None, description="媒体 ID / Media ID"),
    taxon_id: Optional[int] = Query(None, description="物种 ID / Taxon ID"),
    creator_id: Optional[int] = Query(None, description="创建者 ID / Creator ID"),
    creator_type: Optional[str] = Query(None, description="创建者类型 / Creator Type (e.g. user, model)"),
    sound_id: Optional[int] = Query(None, description="声音类型 ID / Sound Type ID"),
    creation_date_from: Optional[datetime] = Query(None),
    creation_date_to: Optional[datetime] = Query(None),
    view_time_start: Optional[float] = Query(None, description="视窗时间起点 (s)，与 view_time_end 等成对用于导出当前声谱可见范围 / Viewport time start (s)"),
    view_time_end: Optional[float] = Query(None, description="视窗时间终点 (s) / Viewport time end (s)"),
    view_freq_min: Optional[float] = Query(None, description="视窗频率下限 (Hz) / Viewport min frequency (Hz)"),
    view_freq_max: Optional[float] = Query(None, description="视窗频率上限 (Hz) / Viewport max frequency (Hz)"),
    order_by: str = Query(default="annotation_id", description="排序字段 / Sort field"),
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$", description="排序方向：asc 或 desc / Sort direction"),
):
    """
    导出标注数据为 CSV 文件。 / Export annotation data as a CSV file.
    """
    filters = {
        k: v for k, v in {
            "project_id": project_id,
            "collection_id": collection_id,
            "media_id": media_id,
            "taxon_id": taxon_id,
            "creator_id": creator_id,
            "creator_type": creator_type,
            "sound_id": sound_id,
            "creation_date_from": creation_date_from,
            "creation_date_to": creation_date_to,
            "viewport_time_start": view_time_start,
            "viewport_time_end": view_time_end,
            "viewport_freq_min": view_freq_min,
            "viewport_freq_max": view_freq_max,
        }.items() if v is not None
    }

    csv_content = annotation_service.export_annotation_csv(
        session,
        current_user,
        order_by=order_by,
        order_dir=order_dir,
        **filters,
    )

    return csv_response(csv_content, "annotations.csv")


@router.get(
    "",
    response_model=PagedApiResponse[list[AnnotationWithReviews]],
    summary="获取标注列表 / List Annotations",
)
def list_annotations(
    session: SessionDep,
    current_user: CurrentUserOptional,
    project_id: int = Query(..., description="项目 ID（必传） / Project ID (required)"),
    collection_id: Optional[int] = Query(None, description="集合 ID / Collection ID"),
    media_id: Optional[int] = Query(None, description="媒体 ID / Media ID"),
    taxon_id: Optional[int] = Query(None, description="物种 ID / Taxon ID"),
    taxon_name: Optional[str] = Query(None, description="物种名称模糊筛选（大小写不敏感） / Fuzzy filter by taxon name (case-insensitive)"),
    creator_id: Optional[int] = Query(None, description="创建者 ID / Creator ID"),
    creator_name: Optional[str] = Query(None, description="创建者名称模糊筛选（大小写不敏感） / Fuzzy filter by creator name (case-insensitive)"),
    creator_type: Optional[str] = Query(None, description="创建者类型模糊筛选 / Fuzzy filter by creator type"),
    sound_id: Optional[int] = Query(None, description="声音类型 ID / Sound Type ID"),
    sound_type: Optional[str] = Query(None, description="声音类型名称模糊筛选（大小写不敏感） / Fuzzy filter by sound type name (case-insensitive)"),
    creation_date_from: Optional[datetime] = Query(None),
    creation_date_to: Optional[datetime] = Query(None),
    # Per-column filters
    soundscape_component: Optional[str] = Query(None, description="声景组分模糊筛选 / Fuzzy filter by soundscape component"),
    uncertain: Optional[bool] = Query(None, description="是否不确定 / Uncertain flag"),
    annotation_id: Optional[int] = Query(None, description="标注 ID（精确） / Annotation ID (exact)"),
    uuid: Optional[str] = Query(None, description="UUID 筛选（精确，非法值忽略） / UUID filter (exact, invalid ignored)"),
    media_name: Optional[str] = Query(None, description="媒体文件名模糊筛选 / Media filename fuzzy filter"),
    media_type: Optional[MediaType] = Query(None, description="媒体类型精确筛选 / Exact media type filter"),
    animal_sound_type: Optional[str] = Query(None, description="动物声音类型模糊筛选 / Fuzzy filter by animal sound type"),
    confidence: Optional[str] = Query(None, description="置信度区间，格式 min,max / Confidence range, format min,max"),
    sound_distance_m: Optional[str] = Query(None, description="声源距离区间（m），格式 min,max / Sound distance range (m), format min,max"),
    distance_not_estimable: Optional[bool] = Query(None, description="距离不可估 / Distance not estimable"),
    individual_num: Optional[str] = Query(None, description="个体数量区间，格式 min,max / Individual count range, format min,max"),
    reference: Optional[bool] = Query(None, description="是否参考标注 / Reference annotation flag"),
    comments: Optional[str] = Query(None, description="备注模糊筛选 / Comments fuzzy filter"),
    min_x: Optional[str] = Query(None, description="时间起点区间（s），格式 min,max / Min-x range (s), format min,max"),
    max_x: Optional[str] = Query(None, description="时间终点区间（s），格式 min,max / Max-x range (s), format min,max"),
    min_y: Optional[str] = Query(None, description="频率下界区间（Hz），格式 min,max / Min-y range (Hz), format min,max"),
    max_y: Optional[str] = Query(None, description="频率上界区间（Hz），格式 min,max / Max-y range (Hz), format min,max"),
    view_time_start: Optional[float] = Query(None, description="当前声谱可见时间窗起点（s），与 view_time_end 组合为重叠过滤 / Visible spectrogram time-window start (s)"),
    view_time_end: Optional[float] = Query(None, description="当前声谱可见时间窗终点（s） / Visible spectrogram time-window end (s)"),
    view_freq_min: Optional[float] = Query(None, description="当前声谱可见频率窗下界（Hz） / Visible spectrogram frequency-window min (Hz)"),
    view_freq_max: Optional[float] = Query(None, description="当前声谱可见频率窗上界（Hz） / Visible spectrogram frequency-window max (Hz)"),
    order_by: str = Query(default="annotation_id", description="排序字段 / Order by field"),
    order_dir: str = Query(default="asc", description="排序方向 asc/desc / Order direction"),
    page: int = Query(default=1, ge=1, description="页码 / Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数 / Page size"),
) -> Any:
    """
    获取标注分页列表。支持多种筛选和排序。 / Get paginated list of annotations.

    坐标列区间参数（min_x 等）筛选字段值落在指定范围内的标注。
    Coordinate range params filter by field value range.
    """
    # Parse range params into (min, max) pairs
    confidence_min, confidence_max = parse_range(confidence)
    distance_m_min, distance_m_max = parse_range(sound_distance_m)
    individual_num_min, individual_num_max = parse_range(individual_num)
    min_x_min, min_x_max = parse_range(min_x)
    max_x_min, max_x_max = parse_range(max_x)
    min_y_min, min_y_max = parse_range(min_y)
    max_y_min, max_y_max = parse_range(max_y)

    filters = {
        k: v for k, v in {
            "project_id": project_id, "collection_id": collection_id,
            "media_id": media_id, "taxon_id": taxon_id,
            "taxon_name": taxon_name,
            "creator_id": creator_id, "creator_name": creator_name, "creator_type": creator_type,
            "sound_id": sound_id, "sound_type": sound_type,
            "creation_date_from": creation_date_from,
            "creation_date_to": creation_date_to,
            "soundscape_component": soundscape_component,
            "uncertain": uncertain,
            "annotation_id": annotation_id,
            "uuid": parse_uuid(uuid),
            "media_name": media_name,
            "media_type": media_type,
            "animal_sound_type": animal_sound_type,
            "distance_not_estimable": distance_not_estimable,
            "reference": reference,
            "comments": comments,
            "confidence_min": confidence_min, "confidence_max": confidence_max,
            "sound_distance_m_min": distance_m_min, "sound_distance_m_max": distance_m_max,
            "individual_num_min": individual_num_min, "individual_num_max": individual_num_max,
            "min_x_min": min_x_min, "min_x_max": min_x_max,
            "max_x_min": max_x_min, "max_x_max": max_x_max,
            "min_y_min": min_y_min, "min_y_max": min_y_max,
            "max_y_min": max_y_min, "max_y_max": max_y_max,
            "viewport_time_start": view_time_start,
            "viewport_time_end": view_time_end,
            "viewport_freq_min": view_freq_min,
            "viewport_freq_max": view_freq_max,
        }.items() if v is not None
    }

    result = annotation_service.list_annotations(
        session, current_user,
        page=page, page_size=page_size,
        order_by=order_by, order_dir=order_dir,
        **filters,
    )
    return api_page(data=result.data, total=result.count, page=page, page_size=page_size)


@router.get(
    "/all",
    response_model=ApiResponse[list[AnnotationWithReviews]],
    summary="获取不分页标注列表 / List Annotations without pagination",
)
def list_all_annotations(
    session: SessionDep,
    current_user: CurrentUserOptional,
    project_id: int = Query(..., description="项目 ID（必传） / Project ID (required)"),
    collection_id: Optional[int] = Query(None, description="集合 ID / Collection ID"),
    media_id: Optional[int] = Query(None, description="媒体 ID / Media ID"),
    taxon_id: Optional[int] = Query(None, description="物种 ID / Taxon ID"),
    taxon_name: Optional[str] = Query(None, description="物种名称模糊筛选（大小写不敏感） / Fuzzy filter by taxon name (case-insensitive)"),
    creator_id: Optional[int] = Query(None, description="创建者 ID / Creator ID"),
    creator_name: Optional[str] = Query(None, description="创建者名称模糊筛选（大小写不敏感） / Fuzzy filter by creator name (case-insensitive)"),
    creator_type: Optional[str] = Query(None, description="创建者类型模糊筛选 / Fuzzy filter by creator type"),
    sound_id: Optional[int] = Query(None, description="声音类型 ID / Sound Type ID"),
    sound_type: Optional[str] = Query(None, description="声音类型名称模糊筛选（大小写不敏感） / Fuzzy filter by sound type name (case-insensitive)"),
    creation_date_from: Optional[datetime] = Query(None),
    creation_date_to: Optional[datetime] = Query(None),
    soundscape_component: Optional[str] = Query(None, description="声景组分模糊筛选 / Fuzzy filter by soundscape component"),
    uncertain: Optional[bool] = Query(None, description="是否不确定 / Uncertain flag"),
    annotation_id: Optional[int] = Query(None, description="标注 ID（精确） / Annotation ID (exact)"),
    uuid: Optional[str] = Query(None, description="UUID 筛选（精确，非法值忽略） / UUID filter (exact, invalid ignored)"),
    media_name: Optional[str] = Query(None, description="媒体文件名模糊筛选 / Media filename fuzzy filter"),
    media_type: Optional[MediaType] = Query(None, description="媒体类型精确筛选 / Exact media type filter"),
    animal_sound_type: Optional[str] = Query(None, description="动物声音类型模糊筛选 / Fuzzy filter by animal sound type"),
    confidence: Optional[str] = Query(None, description="置信度区间，格式 min,max / Confidence range, format min,max"),
    sound_distance_m: Optional[str] = Query(None, description="声源距离区间（m），格式 min,max / Sound distance range (m), format min,max"),
    distance_not_estimable: Optional[bool] = Query(None, description="距离不可估 / Distance not estimable"),
    individual_num: Optional[str] = Query(None, description="个体数量区间，格式 min,max / Individual count range, format min,max"),
    reference: Optional[bool] = Query(None, description="是否参考标注 / Reference annotation flag"),
    comments: Optional[str] = Query(None, description="备注模糊筛选 / Comments fuzzy filter"),
    min_x: Optional[str] = Query(None, description="时间起点区间（s），格式 min,max / Min-x range (s)"),
    max_x: Optional[str] = Query(None, description="时间终点区间（s），格式 min,max / Max-x range (s)"),
    min_y: Optional[str] = Query(None, description="频率下界区间（Hz），格式 min,max / Min-y range (Hz)"),
    max_y: Optional[str] = Query(None, description="频率上界区间（Hz），格式 min,max / Max-y range (Hz)"),
    view_time_start: Optional[float] = Query(None, description="当前声谱可见时间窗起点（s） / Visible spectrogram time-window start (s)"),
    view_time_end: Optional[float] = Query(None, description="当前声谱可见时间窗终点（s） / Visible spectrogram time-window end (s)"),
    view_freq_min: Optional[float] = Query(None, description="当前声谱可见频率窗下界（Hz） / Visible spectrogram frequency-window min"),
    view_freq_max: Optional[float] = Query(None, description="当前声谱可见频率窗上界（Hz） / Visible spectrogram frequency-window max"),
    order_by: str = Query(default="annotation_id", description="排序字段 / Order by field"),
    order_dir: str = Query(default="asc", description="排序方向 asc/desc / Order direction"),
) -> Any:
    """获取不分页标注列表，供媒体详情页使用。 / Unpaged annotations for media detail views."""
    confidence_min, confidence_max = parse_range(confidence)
    distance_m_min, distance_m_max = parse_range(sound_distance_m)
    individual_num_min, individual_num_max = parse_range(individual_num)
    min_x_min, min_x_max = parse_range(min_x)
    max_x_min, max_x_max = parse_range(max_x)
    min_y_min, min_y_max = parse_range(min_y)
    max_y_min, max_y_max = parse_range(max_y)

    filters = {
        k: v for k, v in {
            "project_id": project_id, "collection_id": collection_id,
            "media_id": media_id, "taxon_id": taxon_id,
            "taxon_name": taxon_name,
            "creator_id": creator_id, "creator_name": creator_name, "creator_type": creator_type,
            "sound_id": sound_id, "sound_type": sound_type,
            "creation_date_from": creation_date_from,
            "creation_date_to": creation_date_to,
            "soundscape_component": soundscape_component,
            "uncertain": uncertain,
            "annotation_id": annotation_id,
            "uuid": parse_uuid(uuid),
            "media_name": media_name,
            "media_type": media_type,
            "animal_sound_type": animal_sound_type,
            "distance_not_estimable": distance_not_estimable,
            "reference": reference,
            "comments": comments,
            "confidence_min": confidence_min, "confidence_max": confidence_max,
            "sound_distance_m_min": distance_m_min, "sound_distance_m_max": distance_m_max,
            "individual_num_min": individual_num_min, "individual_num_max": individual_num_max,
            "min_x_min": min_x_min, "min_x_max": min_x_max,
            "max_x_min": max_x_min, "max_x_max": max_x_max,
            "min_y_min": min_y_min, "min_y_max": min_y_max,
            "max_y_min": max_y_min, "max_y_max": max_y_max,
            "viewport_time_start": view_time_start,
            "viewport_time_end": view_time_end,
            "viewport_freq_min": view_freq_min,
            "viewport_freq_max": view_freq_max,
        }.items() if v is not None
    }

    result = annotation_service.list_annotations(
        session, current_user,
        page=1, page_size=1_000_000,
        order_by=order_by, order_dir=order_dir,
        **filters,
    )
    return api_success(data=result.data)


@router.get(
    "/{annotation_id}",
    response_model=ApiResponse[AnnotationWithReviews],
    summary="获取标注详情（含审阅列表） / Get Annotation Detail with Reviews",
)
def get_annotation(
    session: SessionDep,
    current_user: CurrentUser,
    annotation_id: int,
    project_id: int = Query(..., description="项目 ID / Project ID"),
) -> Any:
    """
    获取单条标注的完整详情，包含内嵌的 reviews 列表。
    Get full detail of a single annotation, including embedded reviews list.

    权限：同标注列表权限逻辑（管理员全量，有 annotation:read 或 public_tags 的集合，或自己的标注）。
    Permission: same as list (admin / annotation:read / public_tags / own annotation).
    """
    ann = annotation_service.get_annotation(
        session, current_user, annotation_id, project_id=project_id
    )
    return api_success(data=ann)


@router.get(
    "/{annotation_id}/navigation-items",
    response_model=ApiResponse[AnnotationNavigation],
    summary="获取标注上下导航 / Get Annotation Navigation",
)
def get_annotation_navigation(
    session: SessionDep,
    current_user: CurrentUser,
    annotation_id: int,
    media_id: int = Query(..., description="媒体 ID（必传） / Media ID (required)"),
) -> Any:
    """
    返回同一媒体中当前标注的上一条和下一条（按 annotation_id 排序）。
    Return prev/next annotation IDs within the same media (ordered by annotation_id).
    """
    nav = annotation_service.get_annotation_navigation(
        session, current_user, annotation_id=annotation_id, media_id=media_id
    )
    return api_success(data=nav)



@router.post(
    "",
    response_model=ApiResponse[None],
    status_code=201,
    summary="创建标注 / Create an Annotation",
)
def create_annotation(
    session: SessionDep,
    current_user: CurrentUser,
    data: AnnotationCreate,
) -> Any:
    """
    为指定媒体创建新的标注。 / Create a new annotation for a specific media.
    需要目标媒体所在集合的 annotation:write 权限。
    Requires annotation:write permission on the target media's collection.
    """
    annotation_service.create_annotation(session, current_user=current_user, data=data)
    return api_success()


@router.patch(
    "/{annotation_id}",
    response_model=ApiResponse[None],
    summary="修改/修复标注 / Update or repair an Annotation",
)
def update_annotation(
    session: SessionDep,
    current_user: CurrentUser,
    annotation_id: int,
    data: AnnotationUpdate,
    project_id: int = Query(..., description="项目 ID / Project ID"),
) -> Any:
    """
    更新现有标注。 / Update an existing annotation.
    仅创建者(且拥有集合 read 权限) 或 拥有集合 annotation:write 权限的管理者 可修改。
    Only the creator (with read access) or managers with annotation:write can update.
    """
    annotation_service.update_annotation(
        session,
        current_user=current_user,
        project_id=project_id,
        annotation_id=annotation_id,
        data=data,
    )
    return api_success()


@router.delete(
    "/{annotation_id}",
    response_model=ApiResponse[dict],
    summary="删除标注 / Delete Annotation",
)
def delete_annotation(
    session: SessionDep,
    current_user: CurrentUser,
    annotation_id: int,
    project_id: int = Query(..., description="项目 ID / Project ID"),
) -> Any:
    """
    删除标注记录。 / Delete an annotation record.
    仅创建者(且拥有集合 read 权限) 或 拥有集合 annotation:write 权限的管理者 可删除。
    Only creator or manager can delete.
    """
    annotation_service.delete_annotation(
        session,
        current_user=current_user,
        project_id=project_id,
        annotation_id=annotation_id,
    )
    return api_success(data={"annotation_id": annotation_id})
