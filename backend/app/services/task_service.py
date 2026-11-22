from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.csv_export import CsvColumn, export_columns_csv
from app.enums.task import AssignmentTaskType
from app.models import User
from app.models.annotation import Annotation
from app.models.media import Media, MediaCollection
from app.repositories import permission_repository, task_repository
from app.repositories.annotation_repository import annotation_repository
from app.repositories.media_repository import media_repository
from app.repositories.task_repository import TaskNavigationAccess
from app.schemas.task import TaskNavigationResponse
from app.services import access_scope_service, authorization_service, permission_service
from app.services.authorization_policy import AuthorizationAction

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


def get_navigation_items(
    session: Session, access: TaskNavigationAccess,
    media_id: int, annotation: Annotation | None,
) -> TaskNavigationResponse:
    previous, following = task_repository.get_navigation_items(session, access, media_id, annotation)
    return TaskNavigationResponse(previous=previous, next=following)


def get_navigation_anchor(
    session: Session, project_id: int, collection_id: int | None,
    media_id: int, annotation_id: int | None,
) -> tuple[Annotation | None, set[int]]:
    if collection_id is not None:
        access_scope_service.resolve_collection_project_id(session, collection_id, project_id)
    media = media_repository.get(session, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media not found")
    paths = authorization_service.media_collection_map(session, {media_id}, project_id).get(media_id, set())
    if collection_id is not None:
        paths &= {collection_id}
    if not paths:
        raise HTTPException(status_code=400, detail="Media does not belong to the requested scope")
    annotation = None
    if annotation_id is not None:
        annotation = annotation_repository.get(session, annotation_id)
        if annotation is None:
            raise HTTPException(status_code=404, detail="Annotation not found")
        if annotation.media_id != media_id:
            raise HTTPException(status_code=400, detail="Annotation does not belong to the requested media")
    return annotation, paths


def navigation_anchor_visible(session: Session, annotation_id: int, access: TaskNavigationAccess) -> bool:
    return task_repository.navigation_anchor_visible(session, annotation_id, access)


def _format_task_datetime(value) -> str | None:
    """Format task timestamps using the project-wide response convention."""
    if value is None:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")


def require_media_write_access(
    session: Session,
    media_id: int,
    current_user: User,
    project_id: int | None = None,
) -> Media:
    """Verify media exists and current user has write permission on at least
    one of its collections (or is admin)."""
    media = session.get(Media, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    mc_list = session.exec(
        select(MediaCollection).where(MediaCollection.media_id == media_id)
    ).all()
    authorization_service.evaluator(session, current_user, project_id).require(
        AuthorizationAction.MEDIA_ASSIGN,
        authorization_service.AuthorizationSubject(frozenset(mc.collection_id for mc in mc_list)),
        detail="No write permission on this media's collection",
    )
    return media


_MAX_BATCH_MEDIA_OPTIONS_IDS = 500


def parse_media_ids(raw: str) -> list[int]:
    """Parse a comma-separated list of positive media IDs."""
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        raise HTTPException(status_code=400, detail="media_ids cannot be empty")
    parsed: list[int] = []
    for part in parts:
        try:
            value = int(part)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="media_ids must be comma-separated positive integers") from exc
        if value <= 0:
            raise HTTPException(status_code=400, detail="media_ids must be comma-separated positive integers")
        parsed.append(value)
    unique_ids = list(dict.fromkeys(parsed))
    if len(unique_ids) > _MAX_BATCH_MEDIA_OPTIONS_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"At most {_MAX_BATCH_MEDIA_OPTIONS_IDS} media_ids are supported per request",
        )
    return unique_ids


def _require_assignees_exist(session: Session, assignments: list[dict]) -> None:
    assignee_ids = list(dict.fromkeys(item.get("user_id") for item in assignments))
    if any(uid is None for uid in assignee_ids):
        raise HTTPException(status_code=404, detail="Assignee not found")
    existing_ids = set(
        session.exec(select(User.user_id).where(User.user_id.in_(assignee_ids))).all()
    )
    if len(existing_ids) != len(assignee_ids):
        raise HTTPException(status_code=404, detail="Assignee not found")


def _require_project_media_assign_access(
    session: Session,
    media_ids: list[int],
    current_user: User,
    project_id: int,
    action: AuthorizationAction,
) -> dict[int, set[int]]:
    """Verify all media belong to project_id and current_user can assign tasks on every media."""
    media_collections = authorization_service.media_collection_map(
        session, set(media_ids), project_id
    )
    authz = authorization_service.evaluator(session, current_user, project_id)
    for media_id in media_ids:
        collection_ids = media_collections.get(media_id, set())
        if not collection_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Media {media_id} does not belong to the given project",
            )
        authz.require(
            action,
            authorization_service.AuthorizationSubject(frozenset(collection_ids)),
            detail="No write permission on this media's collection",
        )
    return media_collections


def get_assignable_users(session: Session, media_id: int, current_user: User, project_id: int | None = None) -> list[dict]:
    """Get users assignable to tasks for the given media."""
    require_media_write_access(session, media_id, current_user, project_id)
    return task_repository.get_assignable_users(session, media_id)


def get_batch_assignable_users(
    session: Session,
    media_ids: list[int],
    current_user: User,
    project_id: int,
) -> list[dict]:
    """Get users assignable across all specified media within a project."""
    unique_media_ids = list(dict.fromkeys(media_ids))
    if not unique_media_ids:
        raise HTTPException(status_code=400, detail="media_ids cannot be empty")

    existing_media_ids = set(
        session.exec(select(Media.media_id).where(Media.media_id.in_(unique_media_ids))).all()
    )
    if len(existing_media_ids) != len(unique_media_ids):
        raise HTTPException(status_code=404, detail="Media not found")

    media_collections = _require_project_media_assign_access(
        session, unique_media_ids, current_user, project_id, AuthorizationAction.MEDIA_ASSIGN
    )
    return task_repository.get_assignable_users_for_media_collections(
        session, media_collections, project_id
    )


def get_media_tasks(session: Session, media_id: int, current_user: User, project_id: int | None = None) -> list[dict]:
    """Get all tasks for the given media."""
    require_media_write_access(session, media_id, current_user, project_id)
    return task_repository.get_tasks_by_media(session, media_id)


def assign_tasks(
    session: Session,
    media_id: int,
    current_user: User,
    task_type: str,
    assignments: list[dict],
    annotation_ids: list[int] | None = None,
    project_id: int | None = None,
    *,
    commit: bool = True,
) -> dict:
    """Batch assign tasks to users for a specific media."""
    validate_task_assignments(session, media_id, current_user, task_type, assignments, annotation_ids, project_id)

    if task_type == AssignmentTaskType.ANNOTATION.value:
        unique_ann_ids = list(dict.fromkeys(annotation_ids or []))
        targets = [(media_id, ann_id) for ann_id in unique_ann_ids]
    else:
        targets = [(media_id, None)]

    total_count = task_repository.upsert_batch_assignments(
        session=session,
        targets=targets,
        assigner_id=current_user.user_id,
        task_type=task_type,
        assignments=assignments,
        commit=commit,
    )

    return {"assigned_count": total_count}


def assign_tasks_batch(
    session: Session,
    current_user: User,
    project_id: int,
    task_type: str,
    assignments: list[dict],
    *,
    media_ids: list[int] | None = None,
    annotation_ids: list[int] | None = None,
    commit: bool = True,
) -> dict:
    """Atomically batch assign tasks across multiple media or annotations in a project."""
    if not assignments:
        raise HTTPException(status_code=400, detail="assignments list cannot be empty")
    if task_type not in {task.value for task in AssignmentTaskType}:
        raise HTTPException(status_code=400, detail="task_type must be 'media' or 'annotation'")

    _require_assignees_exist(session, assignments)

    if task_type == AssignmentTaskType.ANNOTATION.value:
        unique_ann_ids = list(dict.fromkeys(annotation_ids or []))
        if not unique_ann_ids:
            raise HTTPException(
                status_code=400,
                detail="annotation_ids is required for annotation-type tasks",
            )
        ann_rows = session.exec(
            select(Annotation).where(Annotation.annotation_id.in_(unique_ann_ids))
        ).all()
        ann_map = {ann.annotation_id: ann for ann in ann_rows if ann.annotation_id is not None}
        for ann_id in unique_ann_ids:
            if ann_id not in ann_map:
                raise HTTPException(status_code=404, detail=f"Annotation {ann_id} not found")

        unique_media_ids = list(dict.fromkeys(ann_map[ann_id].media_id for ann_id in unique_ann_ids))
        _require_project_media_assign_access(
            session, unique_media_ids, current_user, project_id, AuthorizationAction.ANNOTATION_ASSIGN
        )
        targets = [(ann_map[ann_id].media_id, ann_id) for ann_id in unique_ann_ids]
    else:
        unique_media_ids = list(dict.fromkeys(media_ids or []))
        if not unique_media_ids:
            raise HTTPException(
                status_code=400,
                detail="media_ids is required for media-type tasks",
            )
        existing_media_ids = set(
            session.exec(select(Media.media_id).where(Media.media_id.in_(unique_media_ids))).all()
        )
        if len(existing_media_ids) != len(unique_media_ids):
            raise HTTPException(status_code=404, detail="Media not found")
        _require_project_media_assign_access(
            session, unique_media_ids, current_user, project_id, AuthorizationAction.MEDIA_ASSIGN
        )
        targets = [(media_id, None) for media_id in unique_media_ids]

    total_count = task_repository.upsert_batch_assignments(
        session=session,
        targets=targets,
        assigner_id=current_user.user_id,
        task_type=task_type,
        assignments=assignments,
        commit=commit,
    )
    return {"assigned_count": total_count}


def validate_task_assignments(
    session: Session, media_id: int, current_user: User, task_type: str,
    assignments: list[dict], annotation_ids: list[int] | None = None,
    project_id: int | None = None,
) -> None:
    """Validate task assignments without creating or updating tasks."""
    require_media_write_access(session, media_id, current_user, project_id)

    if not assignments:
        raise HTTPException(status_code=400, detail="assignments list cannot be empty")

    if task_type not in {task.value for task in AssignmentTaskType}:
        raise HTTPException(status_code=400, detail="task_type must be 'media' or 'annotation'")

    _require_assignees_exist(session, assignments)

    if task_type == AssignmentTaskType.ANNOTATION.value:
        if not annotation_ids:
            raise HTTPException(
                status_code=400,
                detail="annotation_ids is required for annotation-type tasks",
            )
        unique_ann_ids = list(dict.fromkeys(annotation_ids))
        ann_rows = session.exec(
            select(Annotation.annotation_id, Annotation.media_id).where(
                Annotation.annotation_id.in_(unique_ann_ids)
            )
        ).all()
        ann_media_map = {ann_id: ann_media_id for ann_id, ann_media_id in ann_rows}
        for ann_id in unique_ann_ids:
            if ann_media_map.get(ann_id) != media_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Annotation {ann_id} does not belong to media {media_id}",
                )



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

    total, items = task_repository.list_tasks(
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
    media_ids = {int(item["media_id"]) for item in items if item.get("media_id") is not None}
    media_collections = authorization_service.media_collection_map(
        session, media_ids, project_id
    )
    authz = authorization_service.evaluator(session, current_user, project_id)
    for item in items:
        linked_ids = media_collections.get(item.get("media_id"), set())
        item["capabilities"] = authz.task_capabilities(
            linked_ids, assigner_id=item.get("assigner_id")
        )
    return total, items


def export_tasks(
    session: Session,
    current_user: User,
    project_id: int,
    collection_id: int | None = None,
    order_by: str | None = "task_id",
    order_dir: str = "asc",
) -> str:
    if collection_id is not None:
        access_scope_service.resolve_collection_project_id(
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
        
    if task.assigner_id != current_user.user_id and task.assignee_id != current_user.user_id:
        media_cols = (
            session.exec(select(MediaCollection.collection_id).where(MediaCollection.media_id == task.media_id)).all()
            if task.media_id else []
        )
        authorization_service.evaluator(session, current_user, None).require(
            AuthorizationAction.TASK_VIEW,
            authorization_service.AuthorizationSubject(frozenset(media_cols)),
            detail="You do not have permission to view this task.",
        )
                 
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


def delete_task(session: Session, current_user: User, task_id: int, project_id: int | None = None):
    task = task_repository.get(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    media_cols = (
        session.exec(select(MediaCollection.collection_id).where(MediaCollection.media_id == task.media_id)).all()
        if task.media_id else []
    )
    authorization_service.evaluator(session, current_user, project_id).require(
        AuthorizationAction.TASK_DELETE,
        authorization_service.AuthorizationSubject(
            frozenset(media_cols), owner_id=task.assigner_id
        ),
        detail="You do not have permission to delete this task.",
    )
            
    deleted = task_repository.delete(session, id=task_id)
    if not deleted:
         # This should technically not happen if we found the task above
         raise HTTPException(status_code=404, detail="Task not found or already deleted")
    
    return True
