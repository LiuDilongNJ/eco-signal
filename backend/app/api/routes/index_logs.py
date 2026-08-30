"""指数日志 API 路由；声学指数结果的查询、导出与删除。 / Index logs: query, export, delete."""
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Body, File, Form, Query, UploadFile

from app.api.deps import CurrentUser, SessionDep
from app.api.responses import csv_response
from app.csv_import import attach_import_metadata, parse_import_upload
from app.schemas.index_log import (
    IndexLogCreateRequest,
    IndexLogCreateResponse,
    IndexLogDeleteItem,
    IndexLogRead,
)
from app.schemas.response import ApiResponse, PagedApiResponse, api_page, api_success
from app.services import index_log_service, permission_service, tabular_import_service
from app.services.analysis_service import analysis_service

router = APIRouter(prefix="/index-logs", tags=["指数日志 / index-logs"])


@router.post("/imports", summary="导入指数日志 / Import Index Logs")
async def import_index_logs(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int = Form(...),
    collection_id: int = Form(...),
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
) -> Any:
    """校验或原子导入指数日志。 / Validate or atomically import index logs."""
    permission_service.require_collection_resource_permission(
        session,
        collection_id=collection_id,
        project_id=project_id,
        user=current_user,
        resource_type="audio",
        action="write",
        denied_detail="No audio:write permission on collection",
    )
    parsed = parse_import_upload(file.filename or "", await file.read())
    report = tabular_import_service.import_index_logs(
        session,
        parsed.text,
        current_user,
        project_id,
        collection_id,
        dry_run=dry_run,
    )
    return api_success(message="Import validation completed" if dry_run else "Import completed", data=attach_import_metadata(report, parsed, dry_run=dry_run))


@router.post(
    "",
    response_model=ApiResponse[IndexLogCreateResponse],
    summary="保存指数日志 / Save index log",
)
def create_index_log(
    request: IndexLogCreateRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """
    保存已确认的声学指数结果。 / Save a confirmed acoustic index result.
    """
    result = analysis_service.save_acoustic_index_preview(
        session=session,
        request=request,
        current_user=current_user,
    )
    return api_success(data=result)


@router.get(
    "/exports",
    summary="导出指数日志 CSV / Export index logs to CSV",
)
def export_index_logs(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: Optional[int] = Query(None, description="项目 ID / Project ID"),
    collection_id: Optional[int] = Query(None, description="集合 ID / Collection ID"),
    order_by:  Optional[str] = Query(None,   description="排序字段 / Field to sort by"),
    order_dir: str           = Query("asc", description="排序方向 asc/desc / Sort direction"),
):
    """
    导出指数日志数据为 CSV 文件。 / Export index log data as a CSV file.
    只导出模型字段，遵循 BaseRepository 导出规范。
    """
    filters = {
        k: v for k, v in {
            "project_id": project_id,
            "collection_id": collection_id,
        }.items() if v is not None
    }
    
    csv_content = index_log_service.export_index_logs(
        session=session,
        current_user=current_user,
        order_by=order_by,
        order_dir=order_dir,
        **filters,
    )
    
    return csv_response(csv_content, "index-logs.csv")


@router.get(
    "",
    response_model=PagedApiResponse[list[IndexLogRead]],
    summary="获取指数日志列表 / Get index logs list",
)
def get_index_logs(
    session: SessionDep,
    current_user: CurrentUser,
    page: int = Query(1, ge=1, description="页码 / Page number"),
    page_size: int = Query(15, ge=1, le=100, description="每页数量 / Items per page"),
    project_id: Optional[int] = Query(None, description="项目 ID / Project ID"),
    collection_id: Optional[int] = Query(None, description="集合 ID / Collection ID"),
    media_id: Optional[int] = Query(None, description="媒体 ID / Media ID"),
    log_id: Optional[int] = Query(None, description="日志 ID / Log ID"),
    version: Optional[str] = Query(None, description="计算版本 / Version"),
    min_t_min: Optional[float] = Query(None, description="最小时间下限 / Min Time lower bound"),
    min_t_max: Optional[float] = Query(None, description="最小时间上限 / Min Time upper bound"),
    max_t_min: Optional[float] = Query(None, description="最大时间下限 / Max Time lower bound"),
    max_t_max: Optional[float] = Query(None, description="最大时间上限 / Max Time upper bound"),
    min_f_min: Optional[float] = Query(None, description="最小频率下限 / Min Frequency lower bound"),
    min_f_max: Optional[float] = Query(None, description="最小频率上限 / Min Frequency upper bound"),
    max_f_min: Optional[float] = Query(None, description="最大频率下限 / Max Frequency lower bound"),
    max_f_max: Optional[float] = Query(None, description="最大频率上限 / Max Frequency upper bound"),
    var_type: Optional[str] = Query(None, description="变量类型模糊筛选 / Fuzzy filter by variable type"),
    var_order_min: Optional[int] = Query(None, description="变量顺序下限 / Variable Order lower bound"),
    var_order_max: Optional[int] = Query(None, description="变量顺序上限 / Variable Order upper bound"),
    var_name: Optional[str] = Query(None, description="变量名 / Variable Name"),
    var_value_min: Optional[float] = Query(None, description="变量值下限 / Variable Value lower bound"),
    var_value_max: Optional[float] = Query(None, description="变量值上限 / Variable Value upper bound"),
    media_name: Optional[str] = Query(None, description="媒体名称 / Media Name"),
    user: Optional[str] = Query(None, description="用户名模糊筛选 / Fuzzy filter by user name"),
    index_type: Optional[str] = Query(None, description="指数名称模糊筛选 / Fuzzy filter by index name"),
    creation_date_from: Optional[datetime] = Query(None, description="创建时间起 / Created from"),
    creation_date_to: Optional[datetime] = Query(None, description="创建时间止 / Created to"),
    order_by:  Optional[str] = Query(None,   description="排序字段 / Field to sort by"),
    order_dir: str           = Query("asc", description="排序方向 asc/desc / Sort direction"),
) -> Any:
    """
    获取分页的指数日志列表。 / Get paginated list of index logs.
    """
    filters = {
        k: v for k, v in {
            "project_id": project_id,
            "collection_id": collection_id,
            "media_id": media_id,
            "log_id": log_id, "version": version,
            "min_t_min": min_t_min, "min_t_max": min_t_max,
            "max_t_min": max_t_min, "max_t_max": max_t_max,
            "min_f_min": min_f_min, "min_f_max": min_f_max,
            "max_f_min": max_f_min, "max_f_max": max_f_max,
            "var_type": var_type,
            "var_order_min": var_order_min, "var_order_max": var_order_max,
            "var_name": var_name,
            "var_value_min": var_value_min, "var_value_max": var_value_max,
            "media_name": media_name, "user": user, "index_type": index_type,
            "creation_date_from": creation_date_from,
            "creation_date_to": creation_date_to,
        }.items() if v is not None
    }
    
    items, total = index_log_service.list_index_logs(
        session=session,
        current_user=current_user,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
        **filters
    )
    
    return api_page(items, total, page, page_size)


@router.delete(
    "",
    response_model=ApiResponse[int],
    summary="批量删除指数日志 / Batch delete index logs",
)
def delete_index_logs(
    session: SessionDep,
    current_user: CurrentUser,
    delete_items: list[IndexLogDeleteItem] = Body(..., description="要删除的日志三元组列表 / List of index log identity tuples"),
    project_id: int = Query(..., description="项目 ID / Project ID"),
) -> Any:
    """
    批量删除指数日志。 / Batch delete index logs.
    """
    deleted_count = index_log_service.delete_index_logs(
        session=session,
        current_user=current_user,
        delete_items=delete_items,
        project_id=project_id,
    )
    return api_success(deleted_count, message=f"Successfully deleted {deleted_count} log groups")
