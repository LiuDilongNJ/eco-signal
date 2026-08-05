"""集合离线包导出 API。 / Collection bundle export API."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, SessionDep, TaskPublisherDep
from app.models import Collection, Project
from app.schemas.collection_bundle_export import (
    CollectionBundleExportCreate,
    CollectionBundleExportPublic,
)
from app.schemas.response import ApiResponse, api_success
from app.services import collection_bundle_export_service, permission_service

router = APIRouter(
    prefix="/collection-bundle-exports",
    tags=["集合离线包导出 / collection bundle exports"],
)


def _require_project_write(session: SessionDep, current_user: CurrentUser, project_id: int) -> None:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not permission_service.has_resource_permission(
        session,
        current_user,
        "project",
        "write",
        project_id=project_id,
    ):
        raise HTTPException(
            status_code=403,
            detail="No project:write permission on target project",
        )


def _require_record_access(current_user: CurrentUser, record) -> None:
    if not permission_service.is_admin(current_user) and record.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")


@router.post(
    "",
    response_model=ApiResponse[CollectionBundleExportPublic],
    summary="创建集合离线包导出 / Create Collection Bundle Export",
)
async def create_collection_bundle_export(
    payload: CollectionBundleExportCreate,
    session: SessionDep,
    current_user: CurrentUser,
    publisher: TaskPublisherDep,
) -> ApiResponse[CollectionBundleExportPublic]:
    """
    创建包含全部音频和图片原文件的后台导出任务。 /
    Create a background export containing every audio and photo source file.
    """
    _require_project_write(session, current_user, payload.project_id)
    if session.get(Collection, payload.collection_id) is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    permission_service.resolve_collection_project_id(
        session,
        payload.collection_id,
        payload.project_id,
    )
    data = await collection_bundle_export_service.create_export(
        session,
        project_id=payload.project_id,
        collection_id=payload.collection_id,
        current_user=current_user,
        publisher=publisher,
    )
    return api_success(data=data, message="Collection bundle export queued")


@router.get(
    "",
    response_model=ApiResponse[list[CollectionBundleExportPublic]],
    summary="列出集合离线包导出 / List Collection Bundle Exports",
)
def list_collection_bundle_exports(
    session: SessionDep,
    current_user: CurrentUser,
    project_id: int = Query(..., description="项目 ID / Project ID"),
) -> ApiResponse[list[CollectionBundleExportPublic]]:
    """
    列出当前项目下尚未过期的导出。 /
    List non-expired exports for the current project.
    """
    _require_project_write(session, current_user, project_id)
    return api_success(
        data=collection_bundle_export_service.list_exports(
            session,
            project_id=project_id,
            current_user=current_user,
            is_admin=permission_service.is_admin(current_user),
        )
    )


@router.get(
    "/{export_id}",
    response_model=ApiResponse[CollectionBundleExportPublic],
    summary="获取集合离线包导出 / Get Collection Bundle Export",
)
def get_collection_bundle_export(
    export_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> ApiResponse[CollectionBundleExportPublic]:
    """查询导出状态。 / Get export status."""
    record = collection_bundle_export_service.get_export(session, export_id)
    _require_record_access(current_user, record)
    _require_project_write(session, current_user, record.project_id)
    return api_success(
        data=CollectionBundleExportPublic.model_validate(record, from_attributes=True)
    )


@router.get(
    "/{export_id}/file",
    summary="下载集合离线包 / Download Collection Bundle Export",
)
def download_collection_bundle_export(
    export_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> FileResponse:
    """下载已完成且未过期的离线包。 / Download a completed, non-expired bundle."""
    record = collection_bundle_export_service.get_export(session, export_id)
    _require_record_access(current_user, record)
    _require_project_write(session, current_user, record.project_id)
    path = collection_bundle_export_service.get_download_path(record)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=record.filename,
    )
