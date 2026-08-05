from typing import Any

from sqlalchemy import and_, or_
from sqlmodel import Session, select

from app.models.collection import Collection
from app.models.effective_permission import UserEffectivePermission
from app.models.permission import Permission, UserPermission
from app.models.project import Project, ProjectCollection
from app.repositories.base import BaseRepository


class PermissionRepository(BaseRepository[UserPermission, Any, Any]):
    """
    Repository for permission checking and management operations.

    Permission scope:
    - project_id set, collection_id NULL    → permission applies to the project
    - project_id set, collection_id set     → permission applies only to that
      collection under that specific project
    """

    def __init__(self):
        super().__init__(UserPermission)

    def has_effective_permission(
        self,
        session: Session,
        user_id: int | None,
        resource_type: str,
        action: str,
        *,
        project_id: int | None = None,
        collection_id: int | None = None,
        scope_type: str | None = None,
    ) -> bool:
        """Check the canonical effective permission view."""
        if user_id is None:
            return False

        resolved_scope_type = scope_type or (
            "project_collection" if collection_id is not None else "project"
        )
        stmt = (
            select(UserEffectivePermission.user_id)
            .where(
                UserEffectivePermission.user_id == user_id,
                UserEffectivePermission.scope_type == resolved_scope_type,
                UserEffectivePermission.resource_type == resource_type,
                UserEffectivePermission.action == action,
            )
            .limit(1)
        )
        if project_id is not None:
            stmt = stmt.where(UserEffectivePermission.project_id == project_id)
        if collection_id is None and resolved_scope_type == "project":
            stmt = stmt.where(UserEffectivePermission.collection_id.is_(None))
        elif collection_id is not None:
            stmt = stmt.where(UserEffectivePermission.collection_id == collection_id)

        return session.exec(stmt).first() is not None

    def get_effective_project_ids(
        self,
        session: Session,
        user_id: int | None,
        resource_type: str = "project",
        action: str = "read",
    ) -> list[int]:
        """Return project IDs from the canonical effective permission view."""
        if user_id is None:
            return []

        stmt = (
            select(UserEffectivePermission.project_id)
            .where(
                UserEffectivePermission.user_id == user_id,
                UserEffectivePermission.scope_type == "project",
                UserEffectivePermission.collection_id.is_(None),
                UserEffectivePermission.resource_type == resource_type,
                UserEffectivePermission.action == action,
            )
            .distinct()
        )
        return list(session.exec(stmt).all())

    def get_effective_collection_scopes(
        self,
        session: Session,
        user_id: int | None,
        resource_type: str = "collection",
        action: str = "read",
        project_id: int | None = None,
    ) -> list[tuple[int, int]]:
        """Return project-local collection scopes from the canonical effective view."""
        if user_id is None:
            return []

        stmt = (
            select(UserEffectivePermission.project_id, UserEffectivePermission.collection_id)
            .where(
                UserEffectivePermission.user_id == user_id,
                UserEffectivePermission.scope_type == "project_collection",
                UserEffectivePermission.collection_id.is_not(None),
                UserEffectivePermission.resource_type == resource_type,
                UserEffectivePermission.action == action,
            )
            .distinct()
        )
        if project_id is not None:
            stmt = stmt.where(UserEffectivePermission.project_id == project_id)
        return [(row[0], row[1]) for row in session.exec(stmt).all() if row[1] is not None]

    def get_public_collection_scopes(
        self,
        session: Session,
        *,
        project_id: int | None = None,
        collection_id: int | None = None,
        require_public_tags: bool = False,
    ) -> list[tuple[int, int]]:
        """Return public read scopes from project/collection visibility rules."""
        visibility_filter = (
            Collection.public_tags.is_(True)
            if require_public_tags
            else Collection.public_access.is_(True)
        )
        stmt = (
            select(ProjectCollection.project_id, ProjectCollection.collection_id)
            .join(Collection, Collection.collection_id == ProjectCollection.collection_id)
            .join(Project, Project.project_id == ProjectCollection.project_id)
            .where(Project.public.is_(True), visibility_filter)
            .distinct()
        )
        if project_id is not None:
            stmt = stmt.where(ProjectCollection.project_id == project_id)
        if collection_id is not None:
            stmt = stmt.where(ProjectCollection.collection_id == collection_id)
        return [(row[0], row[1]) for row in session.exec(stmt).all()]

    def has_all_effective_collection_scopes(
        self,
        session: Session,
        user_id: int | None,
        scopes: list[tuple[int, int]],
        resource_type: str,
        action: str,
    ) -> bool:
        """True when the user has the requested permission on every scope."""
        if user_id is None:
            return False
        requested_scopes = set(scopes)
        if not requested_scopes:
            return True

        scope_filters = [
            and_(
                UserEffectivePermission.project_id == project_id,
                UserEffectivePermission.collection_id == collection_id,
            )
            for project_id, collection_id in requested_scopes
        ]
        stmt = (
            select(UserEffectivePermission.project_id, UserEffectivePermission.collection_id)
            .where(
                UserEffectivePermission.user_id == user_id,
                UserEffectivePermission.scope_type == "project_collection",
                UserEffectivePermission.resource_type == resource_type,
                UserEffectivePermission.action == action,
                or_(*scope_filters),
            )
            .distinct()
        )
        granted_scopes = set(session.exec(stmt).all())
        return requested_scopes <= granted_scopes

    def get_project_collection_ids(
        self,
        session: Session,
        project_id: int,
    ) -> list[int]:
        """
        Get all collection IDs associated with a project.

        Args:
            session: Database session
            project_id: Project ID

        Returns:
            List of collection IDs
        """
        stmt = select(ProjectCollection.collection_id).where(
            ProjectCollection.project_id == project_id
        )
        return list(session.exec(stmt).all())

    def get_project_ids_for_collection(
        self,
        session: Session,
        collection_id: int,
    ) -> list[int]:
        """
        Get all project IDs that contain the given collection.

        Args:
            session: Database session
            collection_id: Collection ID

        Returns:
            List of project IDs
        """
        stmt = select(ProjectCollection.project_id).where(
            ProjectCollection.collection_id == collection_id
        )
        return list(session.exec(stmt).all())

    def is_public_project_collection(
        self,
        session: Session,
        project_id: int,
        collection_id: int,
        *,
        require_public_tags: bool = False,
    ) -> bool:
        """True when a collection is linked to a public project and is publicly visible."""
        visibility_filter = (
            Collection.public_tags.is_(True)
            if require_public_tags
            else Collection.public_access.is_(True)
        )
        stmt = (
            select(Collection.collection_id)
            .join(ProjectCollection, ProjectCollection.collection_id == Collection.collection_id)
            .join(Project, Project.project_id == ProjectCollection.project_id)
            .where(
                ProjectCollection.project_id == project_id,
                ProjectCollection.collection_id == collection_id,
                Project.public.is_(True),
                visibility_filter,
            )
            .limit(1)
        )
        return session.exec(stmt).first() is not None

    def is_project_collection_linked(
        self,
        session: Session,
        project_id: int,
        collection_id: int,
    ) -> bool:
        """True when the collection is linked to the project."""
        stmt = (
            select(ProjectCollection.collection_id)
            .where(
                ProjectCollection.project_id == project_id,
                ProjectCollection.collection_id == collection_id,
            )
            .limit(1)
        )
        return session.exec(stmt).first() is not None

    def has_project_permission(
        self,
        session: Session,
        user_id: int,
        project_id: int,
        resource_type: str,
        action: str,
    ) -> bool:
        """Check project-scope effective permission."""
        return self.has_effective_permission(
            session,
            user_id,
            resource_type,
            action,
            project_id=project_id,
            scope_type="project",
        )

    def has_collection_permission(
        self,
        session: Session,
        user_id: int,
        project_id: int,
        collection_id: int,
        resource_type: str,
        action: str,
    ) -> bool:
        """Check project-local collection effective permission."""
        return self.has_effective_permission(
            session,
            user_id,
            resource_type,
            action,
            project_id=project_id,
            collection_id=collection_id,
            scope_type="project_collection",
        )

    def has_collection_resource_permission(
        self,
        session: Session,
        user_id: int,
        project_id: int,
        collection_id: int,
        resource_type: str,
        action: str,
    ) -> bool:
        """Check project-local collection effective permission."""
        return self.has_effective_permission(
            session,
            user_id,
            resource_type,
            action,
            project_id=project_id,
            collection_id=collection_id,
            scope_type="project_collection",
        )

    def get_accessible_project_collection_ids(
        self,
        session: Session,
        user_id: int | None,
        project_id: int,
        resource_type: str = "collection",
        action: str = "read",
    ) -> list[int]:
        """
        Get collection IDs the user can access within a single project.

        Uses the database view `user_effective_permissions` which pre-expands
        project-local permission inheritance into concrete read/write rows.

        Args:
            session: Database session
            user_id: User ID (None for anonymous)
            resource_type: Resource type to check
            action: Action to check

        Returns:
            List of accessible collection IDs
        """
        if user_id is None:
            return []

        return [
            collection_id
            for _, collection_id in self.get_effective_collection_scopes(
                session,
                user_id,
                resource_type,
                action,
                project_id=project_id,
            )
        ]

    def get_accessible_collection_ids(
        self,
        session: Session,
        user_id: int | None,
        resource_type: str = "collection",
        action: str = "read",
        project_id: int | None = None,
    ) -> list[int]:
        """
        Backward-compatible wrapper.

        When `project_id` is provided, results are constrained to that project.
        Otherwise it returns distinct collection IDs across all projects.
        """
        if user_id is None:
            return []

        scopes = self.get_effective_collection_scopes(
            session,
            user_id,
            resource_type,
            action,
            project_id=project_id,
        )
        return sorted({collection_id for _, collection_id in scopes})

    def get_accessible_collection_scopes(
        self,
        session: Session,
        user_id: int | None,
        resource_type: str = "collection",
        action: str = "read",
        project_id: int | None = None,
    ) -> list[tuple[int, int]]:
        """Return project-local collection scopes from the canonical effective view."""
        return self.get_effective_collection_scopes(
            session,
            user_id,
            resource_type,
            action,
            project_id=project_id,
        )

    def has_resource_permission_on_any_collection_path(
        self,
        session: Session,
        user_id: int,
        collection_ids: list[int],
        resource_type: str,
        action: str,
        project_id: int | None = None,
    ) -> bool:
        """True when the user has effective permission on any project-local collection path."""
        if not collection_ids:
            return False

        stmt = (
            select(UserEffectivePermission.collection_id)
            .where(
                UserEffectivePermission.user_id == user_id,
                UserEffectivePermission.scope_type == "project_collection",
                UserEffectivePermission.collection_id.in_(collection_ids),
                UserEffectivePermission.resource_type == resource_type,
                UserEffectivePermission.action == action,
            )
            .limit(1)
        )
        if project_id is not None:
            stmt = stmt.where(UserEffectivePermission.project_id == project_id)
        return session.exec(stmt).first() is not None

    def get_project_ids_with_write_permission(
        self,
        session: Session,
        user_id: int,
    ) -> list[int]:
        """Project IDs where the user has effective project:write permission."""
        return self.get_effective_project_ids(session, user_id, "project", "write")

    def get_collection_ids_with_project_write(
        self,
        session: Session,
        user_id: int,
    ) -> list[int]:
        """Collection IDs carrying a collection-bound effective project:write grant."""
        stmt = (
            select(UserEffectivePermission.collection_id)
            .where(
                UserEffectivePermission.user_id == user_id,
                UserEffectivePermission.scope_type == "project",
                UserEffectivePermission.resource_type == "project",
                UserEffectivePermission.action == "write",
                UserEffectivePermission.collection_id.is_not(None),
            )
            .distinct()
        )
        return list(session.exec(stmt).all())

    def has_any_collection(self, session: Session) -> bool:
        """True when the system has at least one collection."""
        stmt = select(Collection.collection_id).limit(1)
        return session.exec(stmt).first() is not None

    def has_any_accessible_collection(
        self,
        session: Session,
        user_id: int,
    ) -> bool:
        """True when the user has any effective collection access in the view."""
        stmt = (
            select(UserEffectivePermission.collection_id)
            .where(
                UserEffectivePermission.user_id == user_id,
                UserEffectivePermission.scope_type == "project_collection",
            )
            .limit(1)
        )
        return session.exec(stmt).first() is not None

    def get_permission_by_name(self, session: Session, name: str) -> Permission | None:
        """Get a Permission record by its name (e.g. 'project:manage')."""
        stmt = select(Permission).where(Permission.name == name)
        return session.exec(stmt).first()

    def grant_permission(
        self,
        session: Session,
        user_id: int,
        permission_id: int,
        project_id: int | None = None,
        collection_id: int | None = None,
    ) -> UserPermission:
        """
        Grant a permission to a user, scoped to either a project or a collection.

        Args:
            session: Database session
            user_id: User ID
            permission_id: Permission ID
            project_id: Project scope (mutually exclusive with collection_id)
            collection_id: Collection scope (mutually exclusive with project_id)

        Returns:
            Created UserPermission record
        """
        up = UserPermission(
            user_id=user_id,
            permission_id=permission_id,
            project_id=project_id,
            collection_id=collection_id,
        )
        session.add(up)
        session.flush()
        return up

    def sync_project_permissions(
        self,
        session: Session,
        user_id: int,
        project_id: int,
        permission_ids: set[int],
    ) -> dict:
        """
        Sync user permissions scoped to a project.

        Adds permissions in the target set that are missing,
        removes permissions that are no longer in the target set.

        Returns:
            {'added': int, 'removed': int, 'total': int}
        """
        current_stmt = select(UserPermission).where(
            UserPermission.user_id == user_id,
            UserPermission.project_id == project_id,
            UserPermission.collection_id.is_(None),
        )
        current = list(session.exec(current_stmt).all())
        current_ids = {up.permission_id for up in current}

        to_add = permission_ids - current_ids
        to_remove = current_ids - permission_ids

        for perm_id in to_add:
            session.add(UserPermission(
                user_id=user_id,
                project_id=project_id,
                permission_id=perm_id,
            ))

        for up in current:
            if up.permission_id in to_remove:
                session.delete(up)

        return {"added": len(to_add), "removed": len(to_remove), "total": len(permission_ids)}

    def sync_project_collection_permissions(
        self,
        session: Session,
        user_id: int,
        project_id: int,
        collection_id: int,
        permission_ids: set[int],
    ) -> dict:
        """
        Sync user permissions scoped to a project-local collection.

        Returns:
            {'added': int, 'removed': int, 'total': int}
        """
        current_stmt = select(UserPermission).where(
            UserPermission.user_id == user_id,
            UserPermission.project_id == project_id,
            UserPermission.collection_id == collection_id,
        )
        current = list(session.exec(current_stmt).all())
        current_ids = {up.permission_id for up in current}

        to_add = permission_ids - current_ids
        to_remove = current_ids - permission_ids

        for perm_id in to_add:
            session.add(UserPermission(
                user_id=user_id,
                project_id=project_id,
                collection_id=collection_id,
                permission_id=perm_id,
            ))

        for up in current:
            if up.permission_id in to_remove:
                session.delete(up)

        # If user has any permissions on this project-local collection, ensure project:read.
        if permission_ids:
            project_read_perm = self.get_permission_by_name(session, "project:read")
            if project_read_perm and not self.has_project_permission(
                session, user_id, project_id, "project", "read"
            ):
                self.grant_permission(
                    session, user_id, project_read_perm.permission_id, project_id=project_id
                )

        return {"added": len(to_add), "removed": len(to_remove), "total": len(permission_ids)}

    def delete_project_collection_permissions(
        self,
        session: Session,
        project_id: int,
        collection_ids: list[int],
    ) -> None:
        """Delete all project-local collection permissions under one project."""
        if not collection_ids:
            return
        stmt = select(UserPermission).where(
            UserPermission.project_id == project_id,
            UserPermission.collection_id.in_(collection_ids),
        )
        for row in session.exec(stmt).all():
            session.delete(row)


# Singleton instance
permission_repository = PermissionRepository()
