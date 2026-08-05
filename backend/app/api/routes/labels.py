"""标签 API 路由。 / Labels API routes."""
from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, CurrentUserOptional, SessionDep
from app.schemas.label import LabelCreateRequest, LabelPublic, MediaSetLabelsRequest
from app.schemas.media import MediaBatchOperationResponse
from app.schemas.response import ApiResponse, api_success
from app.services import label_service

router = APIRouter(prefix="/labels", tags=["标签 / labels"])
router_media = APIRouter(tags=["标签 / labels"])


@router.post("", response_model=ApiResponse[None], summary="创建标签 / Create Label")
def create_label(
    session: SessionDep,
    request: LabelCreateRequest,
    current_user: CurrentUser
) -> Any:
    """
    创建一个新的标签。 / Create a new label.
    新建标签默认仅创建者可见。 / Newly created labels are private to the creator by default.
    """
    label_service.create_label(session, request, current_user)
    return api_success()


@router.get("", response_model=ApiResponse[list[LabelPublic]], summary="获取标签列表 / List Labels")
def list_labels(
    session: SessionDep,
    current_user: CurrentUserOptional
) -> Any:
    """
    获取当前用户可访问的所有标签。 / Get labels accessible to the current user.
    匿名仅返回 public 标签；登录用户返回“自己标签 + public 标签”。
    / Anonymous users only get public labels; authenticated users get own labels + public labels.
    """
    labels = label_service.get_user_labels(session, current_user)
    return api_success(data=[LabelPublic.model_validate(l) for l in labels])


@router.delete("/{label_id}", response_model=ApiResponse[None], summary="删除标签 / Delete Label")
def delete_label(
    session: SessionDep,
    label_id: int,
    current_user: CurrentUser,
) -> Any:
    """
    删除指定标签。 / Delete the specified label.
    系统标签（ID=1,2,3）不可删除。 / System labels (ID=1,2,3) cannot be deleted.
    用户只能删除自己创建的标签。 / Users can only delete labels they created.
    """
    label_service.delete_label(session, label_id, current_user)
    return api_success(data=None)


@router_media.put("/media-labels", response_model=ApiResponse[MediaBatchOperationResponse], summary="批量设置媒体标签 / Set Media Labels")
def set_media_labels(
    session: SessionDep,
    request: MediaSetLabelsRequest,
    current_user: CurrentUser,
    project_id: int = Query(..., description="项目 ID（必填） / Project ID (required)"),
) -> Any:
    """
    为多个媒体设置同一个标签（每位用户对每个媒体至多一条）。 / Set one label across multiple media records.
    传 `label_id: null` 可清除该用户此前设置的标签。 / Pass `label_id: null` to clear this user's label on the media.

    需要对每个媒体所属集合拥有读取权限。 / Requires read permission on each media's collection.
    """
    data = label_service.set_media_labels(
        session,
        request.media_ids,
        request.label_id,
        current_user,
        project_id=project_id,
    )
    return api_success(data=data)
