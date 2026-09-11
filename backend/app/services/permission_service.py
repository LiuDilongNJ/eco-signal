from sqlalchemy import or_
from sqlmodel import Session, select

from app.models.collection import Collection
from app.models.effective_permission import UserEffectivePermission
from app.models.permission import Permission
from app.models.project import Project, ProjectCollection
from app.models.user import User
from app.repositories import permission_repository
from app.services.authorization_service import is_admin

from app.services.permission_rules import (
    COLLECTION_SCOPED_RESOURCES,
    OWNABLE_RESOURCE_TYPES,
    SUB_RESOURCE_TYPES,
)


def has_resource_permission(
    session: Session,
    user: User,
    resource_type: str,
    action: str,
    collection_id: int | None = None,
    project_id: int | None = None,
) -> bool:
    """
    Check if a user has permission on a resource.

    Check flow:
    1. Admin always passes.
    2. Public read rules are handled separately from user permissions.
    3. Stored permission inheritance is pre-expanded by user_effective_permissions.

    Args:
        session: Database session
        user: User object (must be loaded with role)
        resource_type: Type of resource to check (e.g. 'media', 'collection')
        action: Action to perform ('read' or 'write')
        collection_id: The collection context (required for collection/sub-resource checks)
        project_id: The project context (required for project-level checks)

    Returns:
        True if access is allowed
    """
    # Step 1: Administrator has full access
    if is_admin(user):
        return True

    # Step 2: Public resource check (read only)
    if _is_public_read_allowed(
        session,
        resource_type=resource_type,
        action=action,
        project_id=project_id,
        collection_id=collection_id,
    ):
        return True

    # Effective permission checks require a logged-in user.
    if user.user_id is None:
        return False

    if resource_type in COLLECTION_SCOPED_RESOURCES and (
        project_id is None or collection_id is None
    ):
        return False

    # Project and project-local collection inheritance rules are pre-expanded
    # in the effective permission view.
    return permission_repository.has_effective_permission(
        session,
        user.user_id,
        resource_type,
        action,
        project_id=project_id,
        collection_id=collection_id,
        scope_type="project_collection"
        if resource_type in COLLECTION_SCOPED_RESOURCES
        else "project",
    )


def _is_public_read_allowed(
    session: Session,
    *,
    resource_type: str,
    action: str,
    project_id: int | None,
    collection_id: int | None,
) -> bool:
    """Handle public read rules outside the effective permission view."""
    if action != "read":
        return False

    # project.public -> project itself readable.
    if resource_type == "project" and project_id is not None:
        project = session.get(Project, project_id)
        if project and project.public:
            return True

    if project_id is None or collection_id is None:
        return False

    # collection.public_access within public project -> collection/media/site readable.
    if resource_type in {"collection", "media", "site"}:
        return permission_repository.is_public_project_collection(
            session, project_id, collection_id
        )

    # collection.public_tags within public project -> annotation readable.
    if resource_type == "annotation":
        return permission_repository.is_public_project_collection(
            session,
            project_id,
            collection_id,
            require_public_tags=True,
        )

    return False


def get_effective_permission_pairs(
    session: Session,
    user_id: int | None,
    *,
    project_id: int | None = None,
    collection_id: int | None = None,
) -> set[tuple[str, str]]:
    """
    Distinct (resource_type, action) pairs from the canonical effective view.

    A collection scope also keeps project-scoped rows, whose collection_id is
    NULL, so project-level grants stay visible alongside the collection path.
    """
    if user_id is None:
        return set()

    stmt = select(
        UserEffectivePermission.resource_type,
        UserEffectivePermission.action,
    ).where(UserEffectivePermission.user_id == user_id)

    if project_id is not None:
        stmt = stmt.where(UserEffectivePermission.project_id == project_id)
    if collection_id is not None:
        stmt = stmt.where(
            or_(
                UserEffectivePermission.collection_id == collection_id,
                UserEffectivePermission.collection_id.is_(None),
            )
        )

    return {
        (resource_type, action)
        for resource_type, action in session.exec(stmt.distinct()).all()
    }


def _public_read_permission_names(
    session: Session,
    project_id: int | None,
    collection_id: int | None,
) -> set[str]:
    """Public read grants for a scope, mirroring `_is_public_read_allowed`."""
    if project_id is None:
        return set()

    project = session.get(Project, project_id)
    if not project or not project.public:
        return set()

    names = {"project:read"}
    if permission_repository.get_public_collection_scopes(
        session,
        project_id=project_id,
        collection_id=collection_id,
    ):
        names.update({"collection:read", "media:read", "site:read"})
    if permission_repository.get_public_collection_scopes(
        session,
        project_id=project_id,
        collection_id=collection_id,
        require_public_tags=True,
    ):
        names.add("annotation:read")
    return names


def get_current_user_effective_permissions(
    session: Session,
    user: User | None,
    *,
    project_id: int | None = None,
    collection_id: int | None = None,
) -> list[str]:
    """
    Effective `resource:action` names for a scope, used to gate UI actions.

    A project-only scope returns grants that apply across the whole project. It
    deliberately excludes collection-local grants; list row capabilities expose
    operations that vary between records.
    """
    if user is not None and is_admin(user):
        return sorted(session.exec(select(Permission.name)).all())

    names: set[str] = set()
    if user is not None and project_id is not None and collection_id is None:
        stored_names = set(
            permission_repository.get_project_direct_permission_names(
                session, user.user_id, project_id
            )
        )
        names.update(stored_names)
        for name in tuple(stored_names):
            resource_type, action = name.split(":", 1)
            names.add("project:read")
            if action == "write":
                names.add(f"{resource_type}:read")
                if resource_type in OWNABLE_RESOURCE_TYPES:
                    names.update({f"{resource_type}:read_own", f"{resource_type}:write_own"})
            elif action == "read" and resource_type in OWNABLE_RESOURCE_TYPES:
                names.add(f"{resource_type}:read_own")
            elif action == "write_own" and resource_type in OWNABLE_RESOURCE_TYPES:
                names.add(f"{resource_type}:read_own")
        if "project:write" in stored_names:
            names.update({"project:read", "collection:read", "collection:write"})
            for resource_type in SUB_RESOURCE_TYPES:
                names.update({f"{resource_type}:read", f"{resource_type}:write"})
                if resource_type in OWNABLE_RESOURCE_TYPES:
                    names.update({f"{resource_type}:read_own", f"{resource_type}:write_own"})
    elif project_id is not None and collection_id is not None:
        names.update({
            f"{resource_type}:{action}"
            for resource_type, action in get_effective_permission_pairs(
                session,
                user.user_id if user else None,
                project_id=project_id,
                collection_id=collection_id,
            )
        })

    public_collection_id = collection_id if collection_id is not None else None
    public_names = _public_read_permission_names(session, project_id, public_collection_id)
    if collection_id is None:
        public_names.intersection_update({"project:read"})
    names.update(public_names)
    return sorted(names)


def can_access_project(
    session: Session,
    user: User | None,
    project_id: int,
    action: str = "read",
) -> bool:
    """
    Check if a user (or anonymous) can access a project.

    Public projects are readable by everyone, but only the project itself —
    the collections and sub-resources below are NOT automatically accessible.

    Args:
        session: Database session
        user: User object or None for anonymous
        project_id: Project ID
        action: Action ('read' or 'write')

    Returns:
        True if access is allowed
    """
    project = session.get(Project, project_id)
    if not project:
        return False

    # Public projects: anyone can read the project itself
    if project.public and action == "read":
        return True

    if user is None:
        return False

    return has_resource_permission(
        session, user, "project", action, project_id=project_id
    )


def can_access_collection(
    session: Session,
    user: User | None,
    project_id: int,
    collection_id: int,
    action: str = "read",
) -> bool:
    """
    Check if a user (or anonymous) can access a collection.

    Public collections are readable by everyone only when accessed through a public project.

    Args:
        session: Database session
        user: User object or None for anonymous
        collection_id: Collection ID
        action: Action ('read' or 'write')

    Returns:
        True if access is allowed
    """
    if not permission_repository.is_project_collection_linked(session, project_id, collection_id):
        return False

    if action == "read" and permission_repository.is_public_project_collection(
        session,
        project_id,
        collection_id,
    ):
        return True

    if user is None:
        return False

    return has_resource_permission(
        session,
        user,
        "collection",
        action,
        project_id=project_id,
        collection_id=collection_id,
    )


def get_accessible_collection_ids(
    session: Session,
    user: User | None,
    action: str = "read",
    project_id: int | None = None,
) -> list[int]:
    """
    Get all collection IDs accessible to a user for the given action (on 'collection' resource).

    Includes public collections (for read) and collections the user has permission on.

    Args:
        session: Database session
        user: User object or None for anonymous
        action: Action to check

    Returns:
        List of accessible collection IDs
    """
    collection_ids: set[int] = set()

    # Include public collections for read
    if action == "read":
        public_stmt = select(Collection.collection_id).where(Collection.public_access.is_(True))
        if project_id is not None:
            public_stmt = (
                public_stmt
                .join(ProjectCollection, ProjectCollection.collection_id == Collection.collection_id)
                .join(Project, Project.project_id == ProjectCollection.project_id)
                .where(
                    ProjectCollection.project_id == project_id,
                    Project.public.is_(True),
                )
            )
        collection_ids.update(session.exec(public_stmt).all())

    if user is None:
        return list(collection_ids)

    if is_admin(user):
        all_stmt = select(Collection.collection_id)
        return list(session.exec(all_stmt).all())

    # Permission-based accessible collections
    perm_ids = permission_repository.get_accessible_collection_ids(
        session, user.user_id, "collection", action, project_id=project_id
    )
    collection_ids.update(perm_ids)

    return list(collection_ids)
