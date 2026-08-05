from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import aliased
from sqlmodel import Session, func, or_, select

from app.core.config import settings
from app.enums.task import AssignmentTaskType, TaskStatus
from app.models import Media, MediaCollection, Role, Task, User
from app.models.effective_permission import UserEffectivePermission
from app.models.project import ProjectCollection
from app.repositories.base import BaseRepository
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
)

# Module-level aliases for multi-join on User (assigner and assignee).
# Using the same alias objects in both JOIN and ORDER BY keeps SQL consistent.
_AssignerUser = aliased(User)
_AssigneeUser = aliased(User)

_FILTER_SPECS: list[FilterSpec] = [
    ("task_id",       Task.task_id,       FilterOp.EQ),
    ("annotation_id", Task.annotation_id, FilterOp.EQ),
    ("assigner_id",   Task.assigner_id,   FilterOp.EQ),
    ("assignee_id",   Task.assignee_id,   FilterOp.EQ),
    ("type",          Task.type,          FilterOp.LIKE),
    ("media_name",    Media.name,         FilterOp.LIKE),
    ("media_type",    Media.media_type,   FilterOp.EQ),
    ("status",        Task.status,        FilterOp.LIKE),
    ("comment",       Task.comment,       FilterOp.LIKE),
    # datetime_from / datetime_to → filters Task.datetime
    ("datetime",      Task.datetime,      FilterOp.DATE_RANGE),
]

_SORT_FIELDS: dict[str, Any] = {
    "task_id":       Task.task_id,
    "type":          Task.type,
    "media_name":    Media.name,
    "media_type":    Media.media_type,
    "annotation_id": Task.annotation_id,
    "assigner_name": _AssignerUser.name,
    "assignee_name": _AssigneeUser.name,
    "status":        Task.status,
    "comment":       Task.comment,
    "datetime":      Task.datetime,
}


def _format_task_datetime(value: datetime | None) -> str | None:
    """Format task timestamps using the project-wide response convention."""
    if value is None:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")


class TaskRepository(BaseRepository[Task, Any, Any]):
    """
    Repository for Task entity operations covering the assignment workflow.
    """

    def __init__(self):
        super().__init__(Task)

    def get_assignable_users(
        self,
        session: Session,
        media_id: int,
    ) -> list[dict]:
        """
        Get all users who can be assigned a task for the given media.

        Logic:
        - A user is assignable if they are an admin or have effective access
          to a project-local collection path containing this media.
        - Each user also gets a `task_count` indicating how many tasks for
          this media have already been assigned to them (used to pre-check
          checkboxes in the UI).

        Args:
            session: Database session
            media_id: ID of the media

        Returns:
            List of dicts with keys: user_id, name, username, task_count
        """
        # Sub-query: task counts per assignee for this media
        task_count_subq = (
            select(Task.assignee_id, func.count(Task.task_id).label("task_count"))
            .where(Task.media_id == media_id)
            .group_by(Task.assignee_id)
            .subquery()
        )

        # Get collection IDs that contain this media
        collection_ids_stmt = select(MediaCollection.collection_id).where(
            MediaCollection.media_id == media_id
        )
        collection_ids = list(session.exec(collection_ids_stmt).all())

        # Users with effective permissions on those collections
        permitted_user_ids_stmt = (
            select(UserEffectivePermission.user_id)
            .where(
                UserEffectivePermission.scope_type == "project_collection",
                UserEffectivePermission.collection_id.in_(collection_ids),
            )
            .distinct()
        )
        permitted_user_ids = list(session.exec(permitted_user_ids_stmt).all())

        # Combine: superusers OR permitted users
        stmt = (
            select(
                User.user_id,
                User.name,
                User.username,
                func.coalesce(task_count_subq.c.task_count, 0).label("task_count"),
            )
            .outerjoin(task_count_subq, task_count_subq.c.assignee_id == User.user_id)
            .where(
                User.role_id.in_(select(Role.role_id).where(Role.name == settings.ADMIN_ROLE_NAME))
                | (User.user_id.in_(permitted_user_ids))
            )
            .order_by(User.name)
        )

        results = session.exec(stmt).all()
        return [
            {
                "user_id": row.user_id,
                "name": row.name,
                "username": row.username,
                "task_count": row.task_count,
            }
            for row in results
        ]

    def get_tasks_by_media(
        self,
        session: Session,
        media_id: int,
    ) -> list[dict]:
        """
        Get all tasks assigned for a given media, with assigner/assignee names.

        Args:
            session: Database session
            media_id: ID of the media

        Returns:
            List of dicts representing tasks with user name details
        """
        stmt = select(Task).where(Task.media_id == media_id).order_by(Task.task_id)
        tasks = list(session.exec(stmt).all())

        result = []
        for task in tasks:
            assigner = session.get(User, task.assigner_id)
            assignee = session.get(User, task.assignee_id)
            media = session.get(Media, task.media_id) if task.media_id else None
            result.append({
                "task_id": task.task_id,
                "type": task.type,
                "media_id": task.media_id,
                "media_type": media.media_type if media else None,
                "annotation_id": task.annotation_id,
                "assigner_id": task.assigner_id,
                "assignee_id": task.assignee_id,
                "assigner_name": assigner.name if assigner else None,
                "assignee_name": assignee.name if assignee else None,
                "status": task.status,
                "comment": task.comment,
                "datetime": _format_task_datetime(task.datetime),
            })
        return result

    def upsert_assignments(
        self,
        session: Session,
        media_id: int,
        assigner_id: int,
        task_type: str,
        assignments: list[dict],
        annotation_id: int | None = None,
    ) -> int:
        """
        Batch upsert task assignments.

        For media tasks: match by (media_id, assignee_id).
        For annotation tasks: match by (annotation_id, assignee_id).
        Existing tasks get comment/assigner updated; new ones are created
        with status='assigned'.

        Args:
            session: Database session
            media_id: ID of the media
            assigner_id: ID of the user doing the assignment
            task_type: 'media' or 'annotation'
            assignments: List of dicts with keys 'user_id' and 'comment'
            annotation_id: Required for annotation tasks

        Returns:
            Number of tasks upserted
        """
        now = datetime.now(UTC)
        count = 0

        for item in assignments:
            assignee_id = item["user_id"]
            comment = item.get("comment")

            if task_type == AssignmentTaskType.ANNOTATION.value and annotation_id is not None:
                existing_stmt = select(Task).where(
                    Task.type == AssignmentTaskType.ANNOTATION.value,
                    Task.annotation_id == annotation_id,
                    Task.assignee_id == assignee_id,
                )
            else:
                existing_stmt = select(Task).where(
                    Task.type == AssignmentTaskType.MEDIA.value,
                    Task.media_id == media_id,
                    Task.assignee_id == assignee_id,
                )
            existing = session.exec(existing_stmt).first()

            if existing:
                existing.comment = comment
                existing.assigner_id = assigner_id
                existing.datetime = now
                session.add(existing)
            else:
                new_task = Task(
                    type=task_type,
                    media_id=media_id,
                    annotation_id=annotation_id,
                    assigner_id=assigner_id,
                    assignee_id=assignee_id,
                    status=TaskStatus.ASSIGNED.value,
                    comment=comment,
                    datetime=now,
                )
                session.add(new_task)

            count += 1

        session.commit()
        return count

    def mark_media_task_reviewed(
        self,
        session: Session,
        media_id: int,
        assignee_id: int,
    ) -> bool:
        """
        Mark an assigned media task as 'reviewed' for a specific user.
        Called when user sets meaningful labels on a media.
        """
        stmt = select(Task).where(
            Task.type == AssignmentTaskType.MEDIA.value,
            Task.media_id == media_id,
            Task.assignee_id == assignee_id,
            Task.status == TaskStatus.ASSIGNED.value,
        )
        task = session.exec(stmt).first()

        if task:
            task.status = TaskStatus.REVIEWED.value
            task.datetime = datetime.now(UTC)
            session.add(task)
            session.flush()
            return True
        return False

    def mark_media_task_assigned(
        self,
        session: Session,
        media_id: int,
        assignee_id: int,
    ) -> bool:
        """
        Revert a media task back to 'assigned' for a specific user.
        Called when user clears labels or sets only 'not analysed' (label_id=1).
        """
        stmt = select(Task).where(
            Task.type == AssignmentTaskType.MEDIA.value,
            Task.media_id == media_id,
            Task.assignee_id == assignee_id,
            Task.status == TaskStatus.REVIEWED.value,
        )
        task = session.exec(stmt).first()

        if task:
            task.status = TaskStatus.ASSIGNED.value
            task.datetime = datetime.now(UTC)
            session.add(task)
            session.flush()
            return True
        return False

    def mark_annotation_task_reviewed(
        self,
        session: Session,
        annotation_id: int,
        assignee_id: int,
    ) -> bool:
        """
        Mark an annotation task as 'reviewed' for a specific user.
        Called when user creates or updates a review on the annotation.
        """
        stmt = select(Task).where(
            Task.type == AssignmentTaskType.ANNOTATION.value,
            Task.annotation_id == annotation_id,
            Task.assignee_id == assignee_id,
            Task.status == TaskStatus.ASSIGNED.value,
        )
        task = session.exec(stmt).first()

        if task:
            task.status = TaskStatus.REVIEWED.value
            task.datetime = datetime.now(UTC)
            session.add(task)
            session.flush()
            return True
        return False

    def mark_annotation_task_assigned(
        self,
        session: Session,
        annotation_id: int,
        assignee_id: int,
    ) -> bool:
        """
        Revert an annotation task back to 'assigned' for a specific user.
        Called when the user's review on the annotation is deleted.
        """
        stmt = select(Task).where(
            Task.type == AssignmentTaskType.ANNOTATION.value,
            Task.annotation_id == annotation_id,
            Task.assignee_id == assignee_id,
            Task.status == TaskStatus.REVIEWED.value,
        )
        task = session.exec(stmt).first()

        if task:
            task.status = TaskStatus.ASSIGNED.value
            task.datetime = datetime.now(UTC)
            session.add(task)
            session.flush()
            return True
        return False

    def _build_list_query(
        self,
        user_id: int,
        is_admin: bool,
        accessible_collection_ids: list[int] | None,
        accessible_collection_scopes: list[tuple[int, int]] | None = None,
        filters: dict | None = None,
    ):
        """Build the base select statement with permission and column filters.

        Sorting is handled by the caller via apply_ordering / _sort_stmt.
        Person filters use exact IDs via _FILTER_SPECS so dropdown values cannot
        match unrelated users with the same display name.
        """
        if filters is None:
            filters = {}
        filters = dict(filters)

        stmt = (
            select(
                Task,
                _AssignerUser.name.label("assigner_name"),
                _AssigneeUser.name.label("assignee_name"),
                Media.name.label("media_name"),
                Media.media_type.label("media_type"),
            )
            .outerjoin(_AssignerUser, Task.assigner_id == _AssignerUser.user_id)
            .outerjoin(_AssigneeUser, Task.assignee_id == _AssigneeUser.user_id)
            .outerjoin(Media, Task.media_id == Media.media_id)
        )

        # Permission filter
        if not is_admin:
            permissions_cond = or_(
                Task.assigner_id == user_id,
                Task.assignee_id == user_id
            )
            if accessible_collection_scopes:
                scope_conditions = [
                    and_(
                        ProjectCollection.project_id == project_id,
                        MediaCollection.collection_id == collection_id,
                    )
                    for project_id, collection_id in accessible_collection_scopes
                ]
                collection_media_stmt = (
                    select(MediaCollection.media_id)
                    .join(ProjectCollection, ProjectCollection.collection_id == MediaCollection.collection_id)
                    .where(or_(*scope_conditions))
                )
                permissions_cond = or_(
                    permissions_cond,
                    Task.media_id.in_(collection_media_stmt)
                )
            elif accessible_collection_ids:
                collection_media_stmt = select(MediaCollection.media_id).where(
                    MediaCollection.collection_id.in_(accessible_collection_ids)
                )
                permissions_cond = or_(
                    permissions_cond,
                    Task.media_id.in_(collection_media_stmt)
                )
            stmt = stmt.where(permissions_cond)

        task_type = filters.pop("type", None)
        if task_type is not None:
            normalized_type = str(task_type).strip().lower()
            if normalized_type == AssignmentTaskType.MEDIA.value:
                stmt = stmt.where(Task.type == AssignmentTaskType.MEDIA.value)
            elif normalized_type == AssignmentTaskType.ANNOTATION.value:
                stmt = stmt.where(Task.type == AssignmentTaskType.ANNOTATION.value)
            else:
                stmt = stmt.where(Task.type.ilike(f"%{task_type}%"))

        task_status = filters.pop("status", None)
        if task_status is not None:
            stmt = stmt.where(Task.status.ilike(f"%{task_status}%"))

        # Standard declarative filters
        stmt = apply_filters(stmt, filters, _FILTER_SPECS)

        if filters.get("assigner_name"):
            stmt = stmt.where(_AssignerUser.name.ilike(f"%{filters['assigner_name']}%"))
        if filters.get("assignee_name"):
            stmt = stmt.where(_AssigneeUser.name.ilike(f"%{filters['assignee_name']}%"))

        if filters.get("collection_id") is not None:
            stmt = stmt.where(
                Task.media_id.in_(
                    select(MediaCollection.media_id).where(
                        MediaCollection.collection_id == filters["collection_id"]
                    )
                )
            )
        if filters.get("project_id") is not None:
            project_media_stmt = (
                select(MediaCollection.media_id)
                .join(
                    ProjectCollection,
                    ProjectCollection.collection_id == MediaCollection.collection_id,
                )
                .where(ProjectCollection.project_id == filters["project_id"])
            )
            stmt = stmt.where(Task.media_id.in_(project_media_stmt))

        return stmt

    def _sort_stmt(self, stmt, order_by: str | None, order_dir: str):
        """Apply ordering using the module-level _SORT_FIELDS mapping."""
        return apply_ordering(stmt, order_by, order_dir, _SORT_FIELDS, Task.datetime)

    def list_tasks(
        self,
        session: Session,
        user_id: int,
        is_admin: bool,
        accessible_collection_ids: list[int] | None,
        accessible_collection_scopes: list[tuple[int, int]] | None = None,
        skip: int = 0,
        limit: int = 10,
        order_by: str | None = None,
        order_dir: str = "asc",
        **filters,
    ) -> tuple[int, list[dict]]:
        stmt = self._build_list_query(
            user_id,
            is_admin,
            accessible_collection_ids,
            accessible_collection_scopes=accessible_collection_scopes,
            filters=filters,
        )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = session.exec(count_stmt).one()

        stmt = self._sort_stmt(stmt, order_by, order_dir)
        stmt = stmt.offset(skip).limit(limit)
        results = session.exec(stmt).all()

        items = []
        for task, assigner_name, assignee_name, media_name, media_type in results:
            task_dict = task.model_dump()
            task_dict["datetime"] = _format_task_datetime(task.datetime)
            task_dict["assigner_name"] = assigner_name
            task_dict["assignee_name"] = assignee_name
            task_dict["media_name"] = media_name
            task_dict["media_type"] = media_type
            items.append(task_dict)

        return total, items

    def get_annotation_tasks_for_user(
        self,
        session: Session,
        annotation_ids: list[int],
        user_id: int,
    ) -> dict[int, "Task"]:
        """Return annotation_id -> Task mapping for annotation tasks assigned to a specific user."""
        if not annotation_ids:
            return {}

        annotation_tasks = session.exec(
            select(Task).where(
                Task.type == AssignmentTaskType.ANNOTATION.value,
                Task.annotation_id.in_(annotation_ids),
                Task.assignee_id == user_id,
            )
        ).all()
        return {task.annotation_id: task for task in annotation_tasks}


# Singleton instance
task_repository = TaskRepository()
