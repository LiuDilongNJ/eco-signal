"""任务分配 API 路由。 / Task assignment API routes."""
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, SessionDep
from app.api.responses import csv_response
from app.enums import MediaType
from app.schemas.response import ApiResponse, PagedApiResponse, api_page, api_success
from app.schemas.task import (
    AssignableUserPublic,
    TaskAssignmentRequest,
    TaskAssignmentResult,
    TaskListItem,
    TaskPublic,
)
from app.services import task_service

router = APIRouter(prefix="/media", tags=["任务 / tasks"])

logger = logging.getLogger(__name__)


@router.get(
    "/{media_id}/task-assignee-options",
    response_model=ApiResponse[list[AssignableUserPublic]],
    summary="获取符合任务分配条件的用户列表 / Get Assignable Users",
)
def get_assignable_users(
    session: SessionDep,
    media_id: int,
    current_user: CurrentUser,
) -> Any:
    """
    获取有权访问包含指定媒体集合的用户列表。 / Get a list of users who have access to the collection containing the specified media.

    每个用户包含一个 `task_count`（已为该媒体分配给他们的任务数量），前端可以使用它来预勾选复选框。 / Each user includes a `task_count` (how many tasks for this media are already assigned to them), which the frontend can use to pre-check checkboxes.

    - 仅限管理员或对该媒体所属集合拥有 'write' 权限的用户访问。 / Accessible only by Admins or users with 'write' permission on the media's collection.
    """
    users = task_service.get_assignable_users(session, media_id, current_user)
    result = [AssignableUserPublic(**u) for u in users]
    return api_success(data=result)


@router.get(
    "/{media_id}/tasks",
    response_model=ApiResponse[list[TaskPublic]],
    summary="获取媒体的所有已分配任务 / Get Media Tasks",
)
def get_media_tasks(
    session: SessionDep,
    media_id: int,
    current_user: CurrentUser,
) -> Any:
    """
    获取指定媒体的所有已创建任务。 / Get all created tasks for the specified media.

    返回包含分配者/受分配者姓名、状态、评论和时间戳的详细信息。 / Returns details including assigner/assignee names, status, comments, and timestamps.

    - 仅限管理员或对该媒体拥有 'write' 权限的用户访问。 / Accessible only by Admins or users with 'write' permission on the media.
    """
    tasks = task_service.get_media_tasks(session, media_id, current_user)
    result = [TaskPublic(**t) for t in tasks]
    return api_success(data=result)


@router.put(
    "/{media_id}/tasks",
    response_model=ApiResponse[TaskAssignmentResult],
    summary="批量为用户分配任务 / Batch Assign Tasks",
)
def assign_tasks(
    session: SessionDep,
    media_id: int,
    current_user: CurrentUser,
    body: TaskAssignmentRequest,
) -> Any:
    """
    使用 upsert 逻辑为特定媒体批量分配任务给用户。 / Batch assign tasks to users for a specific media_id using upsert logic.

    - 如果用户/媒体已存在任务：更新评论和分配者。 / If a task already exists for a user/media: update the comment and assigner.
    - 如果不存在任务：创建一个状态为 'assigned' 的新任务。 / If no task exists: create a new task with status 'assigned'.

    请求体示例： / Request body example:
    ```json
    {
      "type": "media",
      "assignments": [
        {"user_id": 1, "comment": "Please review this media"},
        {"user_id": 2, "comment": ""}
      ]
    }
    ```

    - 仅限管理员或对该媒体拥有 'write' 权限的用户访问。 / Accessible only by Admins or users with 'write' permission on the media.
    """
    assignments_data = [
        {"user_id": item.user_id, "comment": item.comment}
        for item in body.assignments
    ]

    result = task_service.assign_tasks(
        session=session,
        media_id=media_id,
        current_user=current_user,
        task_type=body.type,
        assignments=assignments_data,
        annotation_ids=body.annotation_ids,
    )
    return api_success(data=result)

router_tasks = APIRouter(prefix="/tasks", tags=["任务列表 / task management"])

@router_tasks.get(
    "",
    response_model=PagedApiResponse[list[TaskListItem]],
    summary="获取任务列表 / Get task list",
)
def list_tasks(
    session: SessionDep,
    current_user: CurrentUser,
    page: int = Query(1, ge=1, description="页码 / Page number"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量 / Page size"),
    task_id: int | None = Query(None, description="任务 ID / Task ID"),
    type: str | None = Query(None, description="任务类型模糊筛选 / Fuzzy filter by task type"),
    media_name: str | None = Query(None, description="媒体名称 / Media name"),
    media_type: MediaType | None = Query(None, description="媒体类型精确筛选 / Exact media type filter"),
    annotation_id: int | None = Query(None, description="标注 ID / Annotation ID"),
    assigner_id: int | None = Query(None, description="分配者 ID / Assigner ID"),
    assigner_name: str | None = Query(None, description="分配者名称模糊筛选（大小写不敏感） / Fuzzy filter by assigner name (case-insensitive)"),
    assignee_id: int | None = Query(None, description="受分配者 ID / Assignee ID"),
    assignee_name: str | None = Query(None, description="受分配者名称模糊筛选（大小写不敏感） / Fuzzy filter by assignee name (case-insensitive)"),
    project_id: int | None = Query(None, description="项目 ID / Project ID"),
    collection_id: int | None = Query(None, description="集合 ID / Collection ID"),
    status: str | None = Query(None, description="状态模糊筛选 / Fuzzy filter by status"),
    comment: str | None = Query(None, description="备注 / Comment"),
    datetime_from: datetime | None = Query(None, description="创建时间起 / Creation datetime from"),
    datetime_to:   datetime | None = Query(None, description="创建时间止 / Creation datetime to"),
    order_by:  str | None = Query(None,   description="排序字段 / Sort field"),
    order_dir: str        = Query("asc", description="排序方向 asc/desc / Sort direction"),
) -> Any:
    """
    获取分页的任务列表，支持多条件筛选和排序。 / Get paginated task list with filtering and sorting support.
    
    只有超级管理员、集合管理员能够查看所有相关任务，普通用户只能查看自己分配或被分配的任务。 / Only superusers and collection admins can view all related tasks, normal users can only view tasks assigned by/to them.
    """
    skip = (page - 1) * page_size
    total, items = task_service.list_tasks(
        session=session,
        current_user=current_user,
        skip=skip,
        limit=page_size,
        task_id=task_id,
        type=type,
        media_name=media_name,
        media_type=media_type,
        annotation_id=annotation_id,
        assigner_id=assigner_id,
        assigner_name=assigner_name,
        assignee_id=assignee_id,
        assignee_name=assignee_name,
        project_id=project_id,
        collection_id=collection_id,
        status=status,
        comment=comment,
        datetime_from=datetime_from,
        datetime_to=datetime_to,
        order_by=order_by,
        order_dir=order_dir,
    )
    
    return api_page(data=items, total=total, page=page, page_size=page_size)


@router_tasks.get(
    "/exports",
    summary="导出任务列表 / Export task list",
)
def export_tasks(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int = Query(..., description="项目 ID（必填） / Project ID (required)"),
    collection_id: int | None = Query(None, description="集合 ID / Collection ID"),
    order_by:  str | None = Query("task_id",   description="排序字段 / Sort field"),
    order_dir: str        = Query("asc", pattern="^(asc|desc)$", description="排序方向 asc/desc / Sort direction"),
):
    """
    导出任务列表为 CSV 文件。 / Export task list as CSV file.
    """
    csv_data = task_service.export_tasks(
        session=session,
        current_user=current_user,
        project_id=project_id,
        collection_id=collection_id,
        order_by=order_by,
        order_dir=order_dir,
    )

    return csv_response(csv_data, "tasks.csv")


@router_tasks.get(
    "/{task_id}",
    response_model=ApiResponse[TaskListItem],
    summary="获取任务详情 / Get task details",
)
def get_task(
    task_id: int,
    session: SessionDep,
    current_user: CurrentUser
) -> Any:
    """
    获取指定ID的任务详情。 / Get task details by ID.
    """
    task_dict = task_service.get_task(
        session=session,
        current_user=current_user,
        task_id=task_id
    )
    return api_success(data=task_dict)


@router_tasks.delete(
    "/{task_id}",
    response_model=ApiResponse[dict],
    summary="删除任务 / Delete task",
)
def delete_task(
    task_id: int,
    session: SessionDep,
    current_user: CurrentUser
) -> Any:
    """
    删除任务。仅限超级管理员、相关集合管理员或该任务的分配者执行。 / Delete a task. Only superusers, collection admins or the task assigner can perform this.
    """
    task_service.delete_task(
        session=session,
        current_user=current_user,
        task_id=task_id
    )
    return api_success(data={"message": "Task deleted successfully"})
