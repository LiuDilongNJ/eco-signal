from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.csv_export import CsvColumn, export_columns_csv
from app.enums.task import AssignmentTaskType
from app.models import User
from app.models.annotation import Annotation
from app.models.media import Media, MediaCollection
from app.repositories import permission_repository, task_repository
from app.services import permission_service

_TASK_EXPORT_COLUMNS = [
    CsvColumn("task_id"), CsvColumn("type"), CsvColumn("media_name"), CsvColumn("media_type"),
    CsvColumn("annotation_id"), CsvColumn("assigner_name"),
    CsvColumn("assigner_id"), CsvColumn("assignee_name"),
    CsvColumn("assignee_id"), CsvColumn("status"), CsvColumn("comment"),
    CsvColumn(
        "creation_date",
        lambda row: row.get("datetime") or "",
    ),
]


def _format_task_datetime(value) -> str | None:
    """Format task timestamps using the project-wide response convention."""
    if value is None:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")


def require_media_write_access(
    session: Session,
    media_id: int,
    current_user: User,
) -> Media:
    """Verify media exists and current user has write permission on at least
    one of its collections (or is admin)."""
    media = session.get(Media, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    if not permission_service.is_admin(current_user):
        mc_list = session.exec(
            select(MediaCollection).where(MediaCollection.media_id == media_id)
        ).all()

        if not mc_list:
            raise HTTPException(
                status_code=403,
                detail="No write permission on this media's collection",
            )

        has_access = permission_service.has_resource_permission_on_any_collection_path(
            session,
            current_user,
            [mc.collection_id for mc in mc_list],
            "collection",
            "write",
        )
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="No write permission on this media's collection",
            )
    return media


def get_assignable_users(session: Session, media_id: int, current_user: User) -> list[dict]:
    """Get users assignable to tasks for the given media."""
    require_media_write_access(session, media_id, current_user)
    return task_repository.get_assignable_users(session, media_id)


def get_media_tasks(session: Session, media_id: int, current_user: User) -> list[dict]:
    """Get all tasks for the given media."""
    require_media_write_access(session, media_id, current_user)
    return task_repository.get_tasks_by_media(session, media_id)


def assign_tasks(
    session: Session,
    media_id: int,
    current_user: User,
    task_type: str,
    assignments: list[dict],
    annotation_ids: list[int] | None = None,
    *,
    commit: bool = True,
) -> dict:
    """Batch assign tasks to users for a specific media."""
    require_media_write_access(session, media_id, current_user)

    if not assignments:
        raise HTTPException(status_code=400, detail="assignments list cannot be empty")

    if task_type not in {task.value for task in AssignmentTaskType}:
        raise HTTPException(status_code=400, detail="task_type must be 'media' or 'annotation'")

    total_count = 0

    if task_type == AssignmentTaskType.ANNOTATION.value:
        if not annotation_ids:
            raise HTTPException(
                status_code=400,
                detail="annotation_ids is required for annotation-type tasks",
            )
        for ann_id in annotation_ids:
            ann = session.get(Annotation, ann_id)
            if not ann or ann.media_id != media_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Annotation {ann_id} does not belong to media {media_id}",
                )

        for ann_id in annotation_ids:
            count = task_repository.upsert_assignments(
                session=session,
                media_id=media_id,
                assigner_id=current_user.user_id,
                task_type=AssignmentTaskType.ANNOTATION.value,
                assignments=assignments,
                annotation_id=ann_id,
                commit=False,
            )
            total_count += count
    else:
        total_count = task_repository.upsert_assignments(
            session=session,
            media_id=media_id,
            assigner_id=current_user.user_id,
            task_type=task_type,
            assignments=assignments,
            commit=False,
        )

    if commit:
        session.commit()
    else:
        session.flush()

    return {"assigned_count": total_count}


def list_tasks(
    session: Session,
    current_user: User,
    skip: int = 0,
    limit: int = 10,
    task_id: Optional[int] = None,
    type: Optional[str] = None,
    media_name: Optional[str] = None,
    media_type: Optional[str] = None,
    annotation_id: Optional[int] = None,
    assigner_id: Optional[int] = None,
    assigner_name: Optional[str] = None,
    assignee_id: Optional[int] = None,
    assignee_name: Optional[str] = None,
    status: Optional[str] = None,
    comment: Optional[str] = None,
    datetime_from: Optional[object] = None,
    datetime_to: Optional[object] = None,
    project_id: Optional[int] = None,
    collection_id: Optional[int] = None,
    order_by: Optional[str] = None,
    order_dir: str = "asc",
) -> tuple[int, list[dict]]:

    is_admin = permission_service.is_admin(current_user)
    # Get collections where the user has collection:write access
    accessible_collection_scopes = None
    if not is_admin:
        accessible_collection_scopes = permission_repository.get_accessible_collection_scopes(
            session,
            user_id=current_user.user_id,
            resource_type="collection",
            action="write" # user must have collection:write to see all tasks in collection
        )

    return task_repository.list_tasks(
        session=session,
        user_id=current_user.user_id,
        is_admin=is_admin,
        accessible_collection_ids=None,
        accessible_collection_scopes=accessible_collection_scopes,
        skip=skip,
        limit=limit,
        order_by=order_by,
        order_dir=order_dir,
        **{k: v for k, v in {
            "task_id": task_id, "type": type, "media_name": media_name, "media_type": media_type,
            "annotation_id": annotation_id, "assigner_id": assigner_id,
            "assigner_name": assigner_name, "assignee_id": assignee_id,
            "assignee_name": assignee_name, "status": status, "comment": comment,
            "datetime_from": datetime_from,
            "datetime_to": datetime_to,
            "project_id": project_id,
            "collection_id": collection_id,
        }.items() if v is not None}
    )


def export_tasks(
    session: Session,
    current_user: User,
    project_id: int,
    collection_id: int | None = None,
    order_by: str | None = "task_id",
    order_dir: str = "asc",
) -> str:
    if collection_id is not None:
        permission_service.resolve_collection_project_id(
            session,
            collection_id,
            project_id,
        )

    _, items = list_tasks(
        session=session,
        current_user=current_user,
        skip=0,
        limit=1_000_000,
        project_id=project_id,
        collection_id=collection_id,
        order_by=order_by,
        order_dir=order_dir,
    )
    return export_columns_csv(_TASK_EXPORT_COLUMNS, items)


def get_task(
    session: Session,
    current_user: User,
    task_id: int
) -> dict:
    task = task_repository.get(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    is_admin = permission_service.is_admin(current_user)
    
    if not is_admin:
        # Check if user is assigner or assignee
        if task.assigner_id != current_user.user_id and task.assignee_id != current_user.user_id:
            if task.media_id:
                media_cols = session.exec(select(MediaCollection.collection_id).where(MediaCollection.media_id == task.media_id)).all()
                if not permission_service.has_resource_permission_on_any_collection_path(
                    session,
                    current_user,
                    list(media_cols),
                    "collection",
                    "write",
                ):
                    raise HTTPException(status_code=403, detail="You do not have permission to view this task.")
            else:
                 raise HTTPException(status_code=403, detail="You do not have permission to view this task.")
                 
    # Resolve display names required by TaskListItem.
    assigner = session.get(User, task.assigner_id)
    assignee = session.get(User, task.assignee_id)
    
    media_name = None
    media_type = None
    if task.media_id:
        media = session.get(Media, task.media_id)
        if media:
            media_name = media.name
            media_type = media.media_type
            
    task_dict = task.model_dump()
    task_dict["datetime"] = _format_task_datetime(task.datetime)
    task_dict["assigner_name"] = (assigner.name or assigner.username) if assigner else None
    task_dict["assignee_name"] = (assignee.name or assignee.username) if assignee else None
    task_dict["media_name"] = media_name
    task_dict["media_type"] = media_type

    return task_dict


def delete_task(session: Session, current_user: User, task_id: int):
    task = task_repository.get(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    is_admin = permission_service.is_admin(current_user)
    
    # Only admin, collection:write, OR assigner can delete
    if not is_admin and task.assigner_id != current_user.user_id:
        if task.media_id:
            media_cols = session.exec(select(MediaCollection.collection_id).where(MediaCollection.media_id == task.media_id)).all()
            if not permission_service.has_resource_permission_on_any_collection_path(
                session,
                current_user,
                list(media_cols),
                "collection",
                "write",
            ):
                raise HTTPException(status_code=403, detail="You do not have permission to delete this task.")
        else:
            raise HTTPException(status_code=403, detail="You do not have permission to delete this task.")
            
    deleted = task_repository.delete(session, id=task_id)
    if not deleted:
         # This should technically not happen if we found the task above
         raise HTTPException(status_code=404, detail="Task not found or already deleted")
    
    return True
