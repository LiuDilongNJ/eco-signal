from datetime import datetime
from typing import Any

from fastapi import APIRouter, Path, Query

from app.api.deps import CurrentUser, SessionDep
from app.api.responses import csv_response
from app.enums import MediaType
from app.schemas.response import ApiResponse, PagedApiResponse, api_page, api_success
from app.schemas.review import ReviewCreate, ReviewRead, ReviewUpdate
from app.services import review_service

router = APIRouter(prefix="/reviews", tags=["评审 / reviews"])
router_views = APIRouter(tags=["评审 / reviews"])


@router.get("", response_model=PagedApiResponse[list[ReviewRead]], summary="获取评审列表 | Get reviews list")
def read_reviews(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int | None = Query(None, description="项目 ID 筛选 | Filter by project ID"),
    collection_id: int | None = Query(None, description="集合 ID 筛选 | Filter by collection ID"),
    page: int = Query(1, ge=1, description="页码 | Page number"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量 | Items per page"),
    annotation_id: int | None = Query(None, description="注释 ID 筛选 | Filter by annotation ID"),
    media_name: str | None = Query(None, description="媒体名称筛选 | Filter by media name"),
    media_type: MediaType | None = Query(None, description="媒体类型精确筛选 | Exact media type filter"),
    reviewer_id: int | None = Query(None, description="评审者 ID 筛选 | Filter by reviewer ID"),
    reviewer_name: str | None = Query(None, description="评审者名称模糊筛选（大小写不敏感） | Fuzzy filter by reviewer name (case-insensitive)"),
    status_id: int | None = Query(None, description="状态 ID 筛选 | Filter by status ID"),
    status_name: str | None = Query(None, description="状态名称模糊筛选（大小写不敏感） | Fuzzy filter by status name (case-insensitive)"),
    taxon_id: int | None = Query(None, description="物种 ID 筛选 | Filter by taxon ID"),
    taxon_name: str | None = Query(None, description="物种名称模糊筛选（大小写不敏感） | Fuzzy filter by taxon name (case-insensitive)"),
    note: str | None = Query(None, description="备注筛选 | Filter by note content"),
    creation_date_from: datetime | None = Query(None, description="创建时间起 | Creation date from"),
    creation_date_to: datetime | None = Query(None, description="创建时间止 | Creation date to"),
    order_by:  str = Query("creation_date", description="排序字段 | Sort by field"),
    order_dir: str = Query("desc", description="排序方向 asc/desc | Sort direction"),
) -> Any:
    """
    获取满足条件的评审列表，按权限过滤数据。
    
    Get a paginated list of reviews matching the criteria, masked by read permissions.
    """
    filters = {
        k: v for k, v in {
            "annotation_id": annotation_id,
            "media_name": media_name,
            "media_type": media_type,
            "reviewer_id": reviewer_id,
            "reviewer_name": reviewer_name,
            "status_id": status_id,
            "status_name": status_name,
            "taxon_id": taxon_id,
            "taxon_name": taxon_name,
            "note": note,
            "creation_date_from": creation_date_from,
            "creation_date_to": creation_date_to,
            "project_id": project_id,
            "collection_id": collection_id,
        }.items() if v is not None
    }

    items, total = review_service.list_reviews(
        session=session,
        user=current_user,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
        **filters
    )
    
    return api_page(data=items, total=total, page=page, page_size=page_size)


@router.get("/exports", summary="导出评审数据 | Export reviews data")
def export_reviews(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int | None = Query(None, description="项目 ID 筛选 | Filter by project ID"),
    collection_id: int | None = Query(None, description="集合 ID 筛选 | Filter by collection ID"),
    annotation_id: int | None = Query(None, description="注释 ID 筛选 | Filter by annotation ID"),
    media_name: str | None = Query(None, description="媒体名称筛选 | Filter by media name"),
    reviewer_id: int | None = Query(None, description="评审者 ID 筛选 | Filter by reviewer ID"),
    status_id: int | None = Query(None, description="状态 ID 筛选 | Filter by status ID"),
    taxon_id: int | None = Query(None, description="物种 ID 筛选 | Filter by taxon ID"),
    note: str | None = Query(None, description="备注筛选 | Filter by note content"),
    creation_date_from: datetime | None = Query(None, description="创建时间起 | Creation date from"),
    creation_date_to: datetime | None = Query(None, description="创建时间止 | Creation date to"),
    order_by:  str = Query("creation_date", description="排序字段 | Sort by field"),
    order_dir: str = Query("desc", description="排序方向 asc/desc | Sort direction"),
):
    """
    导出满足条件的评审数据为 CSV 格式文件。
    
    Export matching reviews to a CSV file.
    """
    filters = {
        k: v for k, v in {
            "project_id": project_id,
            "collection_id": collection_id,
        }.items() if v is not None
    }

    csv_content = review_service.export_review_csv(
        session=session,
        user=current_user,
        order_by=order_by,
        order_dir=order_dir,
        **filters,
    )
    
    return csv_response(csv_content, "reviews.csv")


@router.post(
    "",
    response_model=ApiResponse[None],
    status_code=201,
    summary="创建评审 | Create review",
)
def create_review(
    session: SessionDep,
    current_user: CurrentUser,
    data: ReviewCreate,
) -> Any:
    """
    为指定标注创建评审记录，评审者为当前登录用户。创建成功后自动标记对应的 annotation 任务为 reviewed。

    Create a review for an annotation. The reviewer is the current user. On api_success the corresponding annotation task is marked as reviewed.
    """
    review_service.create_review(
        session=session,
        user=current_user,
        data=data,
    )
    return api_success()


@router_views.put("/annotations/{annotation_id}/reviews/{reviewer_id}", response_model=ApiResponse[None], summary="更新评审信息 | Update review information")
def update_review(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int = Query(..., description="项目 ID | Project ID"),
    annotation_id: int = Path(..., description="注释 ID | Annotation ID"),
    reviewer_id: int = Path(..., description="评审者 ID | Reviewer ID"),
    review_update: ReviewUpdate,
) -> Any:
    """
    修改评审信息，需要所在集合的 review:write 权限。
    
    Update review data, requires review:write permission on the collection.
    """
    update_data = review_update.model_dump(exclude_unset=True)
    review_service.update_review(
        session=session,
        user=current_user,
        project_id=project_id,
        annotation_id=annotation_id,
        reviewer_id=reviewer_id,
        update_data=update_data
    )
    return api_success()


@router_views.delete(
    "/annotations/{annotation_id}/reviews/{reviewer_id}",
    response_model=ApiResponse[dict],
    summary="删除评审 | Delete review",
)
def delete_review(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int = Query(..., description="项目 ID | Project ID"),
    annotation_id: int = Path(..., description="注释 ID | Annotation ID"),
    reviewer_id: int = Path(..., description="评审者 ID | Reviewer ID"),
) -> Any:
    """
    删除评审记录。删除后自动将对应的 annotation 任务状态回退为 assigned。仅限管理员、集合管理者或评审者本人操作。

    Delete a review. Reverts the corresponding annotation task to assigned. Only admins, collection managers or the reviewer can delete.
    """
    review_service.delete_review(
        session=session,
        user=current_user,
        project_id=project_id,
        annotation_id=annotation_id,
        reviewer_id=reviewer_id,
    )
    return api_success(data={"message": "Review deleted successfully"})
