from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, tuple_
from sqlalchemy.orm import aliased
from sqlmodel import Session, func, or_, select

from app.core.config import settings
from app.enums.task import AssignmentTaskType, TaskStatus
from app.models import Media, MediaCollection, Role, Task, User
from app.models.annotation import Annotation
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


@dataclass(frozen=True)
class TaskNavigationAccess:
    project_id: int
    user_id: int
    collection_id: int | None = None
    is_admin: bool = False
    media_read_ids: frozenset[int] = frozenset()
    annotation_read_ids: frozenset[int] = frozenset()
    annotation_read_own_ids: frozenset[int] = frozenset()

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

    def count_by_annotation_ids(self, session: Session, annotation_ids: list[int]) -> int:
        statement = select(func.count(Task.task_id)).where(Task.annotation_id.in_(annotation_ids))
        return session.exec(statement).one()

    def _navigation_paths(self, access: TaskNavigationAccess):
        paths = select(MediaCollection.collection_id).join(
            ProjectCollection,
            ProjectCollection.collection_id == MediaCollection.collection_id,
        ).where(
            ProjectCollection.project_id == access.project_id,
            MediaCollection.media_id == Annotation.media_id,
        )
        if access.collection_id is not None:
            paths = paths.where(MediaCollection.collection_id == access.collection_id)
        if not access.is_admin:
            paths = paths.where(
                MediaCollection.collection_id.in_(access.media_read_ids),
                or_(
                    MediaCollection.collection_id.in_(access.annotation_read_ids),
                    and_(
                        MediaCollection.collection_id.in_(access.annotation_read_own_ids),
                        Annotation.creator_id == access.user_id,
                    ),
                ),
            )
        return paths.correlate(Annotation)

    def navigation_anchor_visible(
        self, session: Session, annotation_id: int, access: TaskNavigationAccess,
    ) -> bool:
        return session.exec(select(Annotation.annotation_id).where(
            Annotation.annotation_id == annotation_id,
            self._navigation_paths(access).exists(),
        )).first() is not None

    def get_navigation_items(
        self, session: Session, access: TaskNavigationAccess,
        media_id: int, annotation: Annotation | None,
    ) -> tuple[dict | None, dict | None]:
        # The authorized path is selected before LIMIT, so hidden rows cannot
        # mask a later accessible task or combine grants from different paths.
        path = self._navigation_paths(access).order_by(MediaCollection.collection_id).limit(1)
        stmt = select(Task, Media.media_type, path.scalar_subquery().label("collection_id")).join(
            Annotation, Annotation.annotation_id == Task.annotation_id,
        ).join(Media, Media.media_id == Annotation.media_id).where(
            Task.media_id == Annotation.media_id,
            self._navigation_paths(access).exists(),
        )
        stmt = apply_filters(stmt, {
            "assignee_id": access.user_id,
        }, _FILTER_SPECS).where(
            Task.type == AssignmentTaskType.ANNOTATION.value,
            Task.status == TaskStatus.ASSIGNED.value,
            Media.media_type.in_(("audio", "photo")),
        )
        columns = (Annotation.media_id, Annotation.min_x, Annotation.min_y, Annotation.annotation_id)
        if annotation is not None:
            anchor = (media_id, annotation.min_x, annotation.min_y, annotation.annotation_id)
            previous_filter = tuple_(*columns) < anchor
            next_filter = tuple_(*columns) > anchor
        else:
            previous_filter = Annotation.media_id < media_id
            next_filter = Annotation.media_id >= media_id

        def item(condition, descending: bool) -> dict | None:
            ordering = (*columns, Task.task_id)
            row = session.exec(stmt.where(condition).order_by(
                *(column.desc() if descending else column.asc() for column in ordering),
            ).limit(1)).first()
            if row is None:
                return None
            task, media_type, collection_id = row
            return {
                "task_id": task.task_id, "project_id": access.project_id,
                "collection_id": collection_id, "media_id": task.media_id,
                "media_type": media_type, "annotation_id": task.annotation_id,
            }

        return item(previous_filter, True), item(next_filter, False)

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

    def get_assignable_users_for_media_collections(
        self,
        session: Session,
        media_collections: dict[int, set[int]],
        project_id: int,
    ) -> list[dict]:
        """Get users assignable to all specified media within a project.

        Admins are always eligible. Non-admin users must hold effective
        project_collection access to at least one collection for every
        target media so they can open every assigned task.
        """
        if not media_collections:
            return []

        all_collection_ids = set().union(*media_collections.values())
        permitted_user_ids: list[int] = []
        if all_collection_ids:
            rows = session.exec(
                select(
                    UserEffectivePermission.user_id,
                    UserEffectivePermission.collection_id,
                )
                .where(
                    UserEffectivePermission.scope_type == "project_collection",
                    UserEffectivePermission.project_id == project_id,
                    UserEffectivePermission.collection_id.in_(all_collection_ids),
                )
                .distinct()
            ).all()
            user_collections: dict[int, set[int]] = {}
            for user_id, collection_id in rows:
                if collection_id is not None:
                    user_collections.setdefault(user_id, set()).add(collection_id)

            media_col_sets = list(media_collections.values())
            permitted_user_ids = [
                user_id
                for user_id, cols in user_collections.items()
                if all(bool(cols & media_cols) for media_cols in media_col_sets)
            ]

        admin_role_ids = select(Role.role_id).where(Role.name == settings.ADMIN_ROLE_NAME)
        condition = User.role_id.in_(admin_role_ids)
        if permitted_user_ids:
            condition = condition | User.user_id.in_(permitted_user_ids)

        stmt = (
            select(User.user_id, User.name, User.username)
            .where(condition)
            .order_by(User.name)
        )
        results = session.exec(stmt).all()
        return [
            {
                "user_id": row.user_id,
                "name": row.name,
                "username": row.username,
                "task_count": 0,
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

    def upsert_batch_assignments(
        self,
        session: Session,
        targets: list[tuple[int, int | None]],
        assigner_id: int,
        task_type: str,
        assignments: list[dict],
        *,
        commit: bool = True,
    ) -> int:
        """Bulk upsert task assignments in O(1) queries.

        Targets are (media_id, annotation_id) pairs where annotation_id is
        populated for annotation tasks and None for media tasks.
        """
        if not targets or not assignments:
            return 0

        # Deduplicate assignees while preserving order (last comment wins).
        deduped_assignments: dict[int, str | None] = {}
        for item in assignments:
            deduped_assignments[item["user_id"]] = item.get("comment")
        assignee_ids = list(deduped_assignments.keys())

        is_annotation_task = task_type == AssignmentTaskType.ANNOTATION.value
        if is_annotation_task:
            ann_ids = [ann_id for _, ann_id in targets if ann_id is not None]
            existing_rows = session.exec(
                select(Task).where(
                    Task.type == AssignmentTaskType.ANNOTATION.value,
                    Task.annotation_id.in_(ann_ids),
                    Task.assignee_id.in_(assignee_ids),
                )
            ).all()
            existing_map: dict[tuple[int, int], Task] = {
                (row.annotation_id, row.assignee_id): row
                for row in existing_rows
                if row.annotation_id is not None
            }
        else:
            media_ids = [media_id for media_id, _ in targets]
            existing_rows = session.exec(
                select(Task).where(
                    Task.type == AssignmentTaskType.MEDIA.value,
                    Task.media_id.in_(media_ids),
                    Task.assignee_id.in_(assignee_ids),
                )
            ).all()
            existing_map = {
                (row.media_id, row.assignee_id): row
                for row in existing_rows
                if row.media_id is not None
            }

        now = datetime.now(UTC)
        new_tasks: list[Task] = []
        count = 0

        for media_id, annotation_id in targets:
            target_key_id = annotation_id if is_annotation_task and annotation_id is not None else media_id
            for assignee_id, comment in deduped_assignments.items():
                existing = existing_map.get((target_key_id, assignee_id))
                if existing is not None:
                    existing.comment = comment
                    existing.assigner_id = assigner_id
                    existing.datetime = now
                    session.add(existing)
                else:
                    new_task = Task(
                        type=task_type,
                        media_id=media_id,
                        annotation_id=annotation_id if is_annotation_task else None,
                        assigner_id=assigner_id,
                        assignee_id=assignee_id,
                        status=TaskStatus.ASSIGNED.value,
                        comment=comment,
                        datetime=now,
                    )
                    new_tasks.append(new_task)
                    existing_map[(target_key_id, assignee_id)] = new_task
                count += 1

        if new_tasks:
            session.add_all(new_tasks)

        if commit:
            session.commit()
        else:
            session.flush()
        return count

    def upsert_assignments(
        self,
        session: Session,
        media_id: int,
        assigner_id: int,
        task_type: str,
        assignments: list[dict],
        annotation_id: int | None = None,
        *,
        commit: bool = True,
    ) -> int:
        """
        Batch upsert task assignments for a single media or annotation target.
        """
        return self.upsert_batch_assignments(
            session=session,
            targets=[(media_id, annotation_id)],
            assigner_id=assigner_id,
            task_type=task_type,
            assignments=assignments,
            commit=commit,
        )

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
