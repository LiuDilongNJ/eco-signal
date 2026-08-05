from dataclasses import dataclass

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.models.collection import Collection
from app.models.effective_permission import UserEffectivePermission
from app.models.permission import Permission, UserPermission
from app.models.project import Project, ProjectCollection
from app.models.user import User
from app.repositories import permission_repository, user_repository

# Resource types that are NOT top-level: they inherit from collection:write / project:write
_SUB_RESOURCE_TYPES: frozenset[str] = frozenset({
    "audio", "site", "annotation", "review"
})
_COLLECTION_SCOPED_RESOURCES: frozenset[str] = frozenset({"collection", *_SUB_RESOURCE_TYPES})


@dataclass(frozen=True)
class _PermissionManagementContext:
    project_ids: set[int] | None
    collection_scopes: set[tuple[int, int]] | None

    @property
    def is_admin(self) -> bool:
        return self.project_ids is None and self.collection_scopes is None

    def can_manage_project(self, project_id: int) -> bool:
        return self.is_admin or project_id in (self.project_ids or set())

    def can_manage_collection(self, project_id: int, collection_id: int) -> bool:
        return (
            self.is_admin
            or project_id in (self.project_ids or set())
            or (project_id, collection_id) in (self.collection_scopes or set())
        )


@dataclass(frozen=True)
class _PermissionSyncSelection:
    project_ids: set[int]
    collection_scopes: set[tuple[int, int]]


@dataclass(frozen=True)
class _StoredPermissionMaps:
    project_permissions: dict[int, list[str]]
    collection_permissions: dict[tuple[int, int], list[str]]


@dataclass(frozen=True)
class CollectionResourceScope:
    collection: Collection
    project_id: int
    collection_id: int


def resolve_collection_project_id(
    session: Session,
    collection_id: int,
    project_id: int | None,
) -> int:
    """Resolve and validate the project path for a collection-scoped operation."""
    if project_id is not None:
        linked = session.exec(
            select(ProjectCollection).where(
                ProjectCollection.project_id == project_id,
                ProjectCollection.collection_id == collection_id,
            )
        ).first()
        if not linked:
            raise HTTPException(
                status_code=400,
                detail="collection_id does not belong to the given project_id",
            )
        return project_id

    project_ids = list(
        session.exec(
            select(ProjectCollection.project_id).where(
                ProjectCollection.collection_id == collection_id,
            )
        ).all()
    )
    if len(project_ids) == 1:
        return project_ids[0]

    raise HTTPException(
        status_code=400,
        detail="project_id is required when collection belongs to multiple projects",
    )


def require_collection_resource_permission(
    session: Session,
    user: User,
    resource_type: str,
    action: str,
    *,
    collection_id: int,
    project_id: int | None,
    not_found_detail: str = "Collection not found",
    denied_detail: str | None = None,
) -> CollectionResourceScope:
    """Validate a collection scope and require the requested resource permission."""
    collection = session.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail=not_found_detail)

    resolved_project_id = resolve_collection_project_id(session, collection_id, project_id)
    if not has_resource_permission(
        session,
        user,
        resource_type,
        action,
        project_id=resolved_project_id,
        collection_id=collection_id,
    ):
        detail = denied_detail or f"No {resource_type}:{action} permission on collection"
        raise HTTPException(status_code=403, detail=detail)

    return CollectionResourceScope(
        collection=collection,
        project_id=resolved_project_id,
        collection_id=collection_id,
    )


def require_any_collection_path_permission(
    session: Session,
    user: User,
    resource_type: str,
    action: str,
    *,
    collection_id: int,
    not_found_detail: str = "Collection not found",
    denied_detail: str | None = None,
) -> Collection:
    """
    Require permission on any project-local path for a collection-scoped resource.

    This is intended for collection-owned detail endpoints whose payload does not
    vary by project path, so callers do not need to provide project_id.
    """
    collection = session.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail=not_found_detail)

    if not has_resource_permission_on_any_collection_path(
        session,
        user,
        [collection_id],
        resource_type,
        action,
    ):
        detail = denied_detail or f"No {resource_type}:{action} permission on collection"
        raise HTTPException(status_code=403, detail=detail)

    return collection


def _minimize_effective_permissions(permission_names: list[str]) -> list[str]:
    """
    Minimize a permission list for display:
    - Keep write and drop read for the same resource_type.
    """
    action_map: dict[str, set[str]] = {}
    for name in permission_names:
        if ":" not in name:
            continue
        resource_type, action = name.split(":", 1)
        action_map.setdefault(resource_type, set()).add(action)

    minimized: list[str] = []
    for resource_type, actions in action_map.items():
        if "write" in actions:
            minimized.append(f"{resource_type}:write")
        elif "read" in actions:
            minimized.append(f"{resource_type}:read")
        else:
            for action in sorted(actions):
                minimized.append(f"{resource_type}:{action}")

    return sorted(minimized)


def _normalize_permissions(permission_names: list[str], scope_type: str) -> list[str]:
    """
    Remove redundant permissions that are already implied by higher-level ones.

    Redundancy rules:
    - project:write  → implies ALL sub-resource read+write AND project:read
    - collection:write → implies ALL sub-resource read+write AND collection:read
    - Any resource:write → implies the same resource:read

    Enforcement rules (Rule 4):
    - Any permission present → implies scope_type:read

    Args:
        permission_names: Raw permission name list from the request
        scope_type: 'project' or 'collection'

    Returns:
        Cleaned permission name list with redundancies removed
    """
    names = set(permission_names)

    # If sub-resource permissions are present, ensure base read exists
    # (only add if neither read nor write for the scope are provided)
    if names:
        scope_write = f"{scope_type}:write"
        scope_read = f"{scope_type}:read"
        if scope_write not in names and scope_read not in names:
            names.add(scope_read)

    # Rule 1: scope:write implies all sub-resource read+write + scope:read
    scope_write = f"{scope_type}:write"
    if scope_write in names:
        # Remove scope:read (write implies read)
        names.discard(f"{scope_type}:read")
        # Remove all sub-resource permissions (they are inherited)
        for sub in _SUB_RESOURCE_TYPES:
            names.discard(f"{sub}:read")
            names.discard(f"{sub}:write")

    # Rule 2: resource:write implies resource:read
    for name in list(names):
        resource_type, action = name.split(":", 1)
        if action == "write" and f"{resource_type}:read" in names:
            names.discard(f"{resource_type}:read")

    return list(names)


def _remove_cross_scope_redundancies(
    collection_perms: list[str],
    parent_project_perms: set[str],
) -> list[str]:
    """
    Remove collection-level permissions already covered by parent project-level permissions.

    Cross-scope rules:
    - If parent project has project:write → all collection perms are redundant
    - If parent project has a sub-resource permission (e.g. audio:write) →
      the same permission at collection level is redundant
    - If parent project has resource:write → collection-level resource:read is also redundant

    Args:
        collection_perms: Normalized collection-level permission names
        parent_project_perms: Normalized project-level permission names from parent projects

    Returns:
        Filtered collection permission list
    """
    # project:write covers everything at collection level
    if "project:write" in parent_project_perms:
        return []

    remaining = []
    for perm in collection_perms:
        resource_type, action = perm.split(":", 1)
        # Same permission exists at project level → redundant
        if perm in parent_project_perms:
            continue
        # Parent has resource:write, collection has resource:read → redundant
        if action == "read" and f"{resource_type}:write" in parent_project_perms:
            continue
        remaining.append(perm)

    return remaining


def is_admin(user: User) -> bool:
    """
    Check if a user is an Administrator.

    Args:
        user: User object

    Returns:
        True if user has the Administrator role
    """
    if not user.role:
        return False
    return user.role.name == settings.ADMIN_ROLE_NAME


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
        resource_type: Type of resource to check (e.g. 'audio', 'collection')
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

    if resource_type in _COLLECTION_SCOPED_RESOURCES and (
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
        if resource_type in _COLLECTION_SCOPED_RESOURCES
        else "project",
    )


def has_resource_permission_on_any_collection_path(
    session: Session,
    user: User,
    collection_ids: list[int],
    resource_type: str,
    action: str,
    project_id: int | None = None,
) -> bool:
    """
    Check collection-path permission while preserving the admin bypass rule.

    Use this from services instead of calling permission_repository directly.
    The repository only knows stored/effective permissions; this service helper
    owns role-level semantics such as Administrator bypass.
    """
    if is_admin(user):
        return True

    if user.user_id is None:
        return False

    return permission_repository.has_resource_permission_on_any_collection_path(
        session,
        user.user_id,
        collection_ids,
        resource_type,
        action,
        project_id=project_id,
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

    # collection.public_access within public project -> collection/audio/site readable.
    if resource_type in {"collection", "audio", "site"}:
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


def _get_manager_collection_write_scopes(
    session: Session,
    user_id: int,
    project_write_ids: set[int],
) -> set[tuple[int, int]]:
    """Return project-local collection:write scopes not already covered by project:write."""
    return {
        (project_id, collection_id)
        for project_id, collection_id in permission_repository.get_effective_collection_scopes(
            session,
            user_id,
            "collection",
            "write",
        )
        if project_id not in project_write_ids
    }


def _get_target_user_or_404(session: Session, user_id: int) -> User:
    target_user = session.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    return target_user


def _get_permission_management_context(
    session: Session,
    current_user: User,
    target_user: User,
) -> _PermissionManagementContext:
    """
    Resolve the current user's permission-management window for a target user.

    Admin users get an unrestricted context. Non-admin managers are restricted
    to project:write projects plus project-local collection:write paths, and
    may only manage ordinary users inside that window.
    """
    if is_admin(current_user):
        return _PermissionManagementContext(None, None)

    if is_admin(target_user):
        raise HTTPException(
            status_code=403,
            detail="Managers are not allowed to manage Administrator accounts",
        )

    project_write_ids = set(
        permission_repository.get_project_ids_with_write_permission(
            session, current_user.user_id
        )
    )
    collection_write_scopes = _get_manager_collection_write_scopes(
        session,
        current_user.user_id,
        project_write_ids,
    )

    scope_filter = user_repository.build_manager_scope_user_condition(
        sorted(project_write_ids),
        sorted(collection_write_scopes),
    )
    can_manage_target = session.exec(
        select(User.user_id).where(
            User.user_id == target_user.user_id,
            scope_filter,
        )
    ).first()
    if not can_manage_target:
        raise HTTPException(
            status_code=403,
            detail="Target user is not within your management scope",
        )

    return _PermissionManagementContext(project_write_ids, collection_write_scopes)


def _load_stored_permission_maps(session: Session, user_id: int) -> _StoredPermissionMaps:
    stmt = (
        select(UserPermission, Permission)
        .join(Permission)
        .where(UserPermission.user_id == user_id)
    )
    project_permissions: dict[int, list[str]] = {}
    collection_permissions: dict[tuple[int, int], list[str]] = {}
    for up, perm in session.exec(stmt).all():
        if up.project_id is not None and up.collection_id is None:
            project_permissions.setdefault(up.project_id, []).append(perm.name)
        elif up.project_id is not None and up.collection_id is not None:
            collection_permissions.setdefault((up.project_id, up.collection_id), []).append(perm.name)

    return _StoredPermissionMaps(
        {project_id: sorted(perms) for project_id, perms in project_permissions.items()},
        {scope: sorted(perms) for scope, perms in collection_permissions.items()},
    )


def _load_effective_collection_permission_map(
    session: Session,
    user_id: int,
) -> dict[tuple[int, int], list[str]]:
    raw_permissions: dict[tuple[int, int], list[str]] = {}
    rows = session.exec(
        select(UserEffectivePermission).where(
            UserEffectivePermission.user_id == user_id,
            UserEffectivePermission.scope_type == "project_collection",
            UserEffectivePermission.collection_id.is_not(None),
        )
    ).all()
    for row in rows:
        if row.resource_type == "project":
            continue
        raw_permissions.setdefault((row.project_id, row.collection_id), []).append(
            f"{row.resource_type}:{row.action}"
        )

    return {
        scope: _minimize_effective_permissions(perms)
        for scope, perms in raw_permissions.items()
    }


def _load_visible_project_collection_tree(
    session: Session,
    context: _PermissionManagementContext,
) -> list[tuple[Project, list[Collection]]]:
    stmt = (
        select(Project, Collection)
        .join(ProjectCollection, ProjectCollection.project_id == Project.project_id, isouter=True)
        .join(Collection, Collection.collection_id == ProjectCollection.collection_id, isouter=True)
        .order_by(Project.name, Project.project_id, Collection.name, Collection.collection_id)
    )
    if not context.is_admin:
        visible_project_ids = (context.project_ids or set()) | {
            project_id for project_id, _ in (context.collection_scopes or set())
        }
        if not visible_project_ids:
            return []
        stmt = stmt.where(Project.project_id.in_(visible_project_ids))

    project_map: dict[int, tuple[Project, list[Collection]]] = {}
    visible_collection_scopes = context.collection_scopes or set()
    for project, collection in session.exec(stmt).all():
        if (
            collection is not None
            and not context.is_admin
            and project.project_id not in (context.project_ids or set())
        ):
            if (project.project_id, collection.collection_id) not in visible_collection_scopes:
                continue
        project_map.setdefault(project.project_id, (project, []))
        if collection is not None:
            project_map[project.project_id][1].append(collection)

    return list(project_map.values())


def get_user_permission_config(
    session: Session,
    user_id: int,
    current_user: User,
) -> dict:
    target_user = _get_target_user_or_404(session, user_id)
    context = _get_permission_management_context(session, current_user, target_user)
    stored_maps = _load_stored_permission_maps(session, user_id)
    effective_collection_permissions = _load_effective_collection_permission_map(session, user_id)
    visible_tree = _load_visible_project_collection_tree(session, context)

    projects_result = []
    for proj, collections in visible_tree:
        stored_project_permissions = (
            stored_maps.project_permissions.get(proj.project_id, [])
            if context.can_manage_project(proj.project_id)
            else []
        )
        collections_data = []
        for col in collections:
            scope_key = (proj.project_id, col.collection_id)
            collections_data.append({
                "project_id": proj.project_id,
                "collection_id": col.collection_id,
                "collection_name": col.name,
                "stored_permissions": stored_maps.collection_permissions.get(scope_key, []),
                "effective_permissions": effective_collection_permissions.get(scope_key, []),
            })

        projects_result.append({
            "project_id": proj.project_id,
            "project_name": proj.name,
            "can_manage_project": context.can_manage_project(proj.project_id),
            "stored_permissions": stored_project_permissions,
            "effective_permissions": _minimize_effective_permissions(stored_project_permissions),
            "collections": collections_data,
        })

    return {
        "is_admin": is_admin(target_user),
        "can_manage_admin_role": context.is_admin,
        "projects": projects_result,
    }


def _load_permission_id_map(session: Session) -> dict[str, int]:
    return {p.name: p.permission_id for p in session.exec(select(Permission)).all()}


def _get_sync_selection(request_projects) -> _PermissionSyncSelection:
    return _PermissionSyncSelection(
        {project_node.project_id for project_node in request_projects},
        {
            (project_node.project_id, collection_node.collection_id)
            for project_node in request_projects
            for collection_node in project_node.collections
        },
    )


def _raise_for_invalid_permissions(permission_names: list[str], perm_map: dict[str, int]) -> None:
    invalid = [name for name in permission_names if name not in perm_map]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid permission names: {invalid}",
        )


def _apply_admin_toggle(
    session: Session,
    target_user: User,
    request,
    context: _PermissionManagementContext,
) -> None:
    if request.is_admin is None:
        return

    current_is_admin = is_admin(target_user)
    if request.is_admin == current_is_admin:
        return

    if not context.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Only administrators can set or revoke admin role",
        )

    superuser_role_id = 1
    normal_user_role_id = 2
    target_user.role_id = superuser_role_id if request.is_admin else normal_user_role_id
    session.add(target_user)


def _validate_permission_payload(
    request_projects,
    perm_map: dict[str, int],
    context: _PermissionManagementContext,
) -> None:
    for project_node in request_projects:
        _raise_for_invalid_permissions(project_node.stored_permissions, perm_map)
        # Only system administrators may grant project:write (management-level).
        # A non-admin manager can delegate collection:write and below, but must
        # not be able to clone a peer project manager.
        if not context.is_admin and "project:write" in project_node.stored_permissions:
            raise HTTPException(
                status_code=403,
                detail="Managers cannot grant project:write",
            )
        if not context.can_manage_project(project_node.project_id):
            if project_node.stored_permissions:
                raise HTTPException(
                    status_code=403,
                    detail=f"No project:write permission on project {project_node.project_id}",
                )
            invalid_col_scopes = [
                collection_node.collection_id
                for collection_node in project_node.collections
                if not context.can_manage_collection(
                    project_node.project_id,
                    collection_node.collection_id,
                )
            ]
            if invalid_col_scopes:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"No collection:write permission on project {project_node.project_id} "
                        f"collection paths: {invalid_col_scopes}"
                    ),
                )

        for collection_node in project_node.collections:
            if collection_node.project_id != project_node.project_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Collection {collection_node.collection_id} carries mismatched project_id",
                )
            _raise_for_invalid_permissions(collection_node.stored_permissions, perm_map)


def _validate_requested_resources(session: Session, request_projects) -> None:
    for project_node in request_projects:
        if not session.get(Project, project_node.project_id):
            raise HTTPException(
                status_code=404,
                detail=f"Project {project_node.project_id} not found",
            )

        project_collection_ids = set(
            permission_repository.get_project_collection_ids(session, project_node.project_id)
        )
        for collection_node in project_node.collections:
            if collection_node.collection_id not in project_collection_ids:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Collection {collection_node.collection_id} does not belong "
                        f"to project {project_node.project_id}"
                    ),
                )


def _delete_user_permission_rows(session: Session, stmt) -> None:
    for row in session.exec(stmt).all():
        session.delete(row)


def _delete_project_collection_permissions_except(
    session: Session,
    user_id: int,
    project_id: int,
    requested_collection_ids: set[int],
) -> None:
    stmt = select(UserPermission).where(
        UserPermission.user_id == user_id,
        UserPermission.project_id == project_id,
        UserPermission.collection_id.is_not(None),
    )
    if requested_collection_ids:
        stmt = stmt.where(UserPermission.collection_id.notin_(requested_collection_ids))
    _delete_user_permission_rows(session, stmt)


def _cleanup_admin_omitted_scopes(
    session: Session,
    user_id: int,
    request_projects,
    selection: _PermissionSyncSelection,
) -> None:
    stmt = select(UserPermission).where(UserPermission.user_id == user_id)
    if selection.project_ids:
        stmt = stmt.where(UserPermission.project_id.notin_(selection.project_ids))
    _delete_user_permission_rows(session, stmt)

    for project_node in request_projects:
        requested_collection_ids = {
            collection_node.collection_id for collection_node in project_node.collections
        }
        _delete_project_collection_permissions_except(
            session,
            user_id,
            project_node.project_id,
            requested_collection_ids,
        )


def _cleanup_manager_omitted_scopes(
    session: Session,
    user_id: int,
    request_projects,
    selection: _PermissionSyncSelection,
    context: _PermissionManagementContext,
) -> None:
    managed_project_ids = context.project_ids or set()
    omitted_project_ids = managed_project_ids - selection.project_ids
    for project_id in omitted_project_ids:
        permission_repository.sync_project_permissions(session, user_id, project_id, set())
        _delete_project_collection_permissions_except(session, user_id, project_id, set())

    requested_by_project = {
        project_node.project_id: {
            collection_node.collection_id for collection_node in project_node.collections
        }
        for project_node in request_projects
    }
    for project_id in managed_project_ids & selection.project_ids:
        _delete_project_collection_permissions_except(
            session,
            user_id,
            project_id,
            requested_by_project.get(project_id, set()),
        )

    for project_id, collection_id in (context.collection_scopes or set()) - selection.collection_scopes:
        permission_repository.sync_project_collection_permissions(
            session,
            user_id,
            project_id,
            collection_id,
            set(),
        )


def _cleanup_omitted_scopes(
    session: Session,
    user_id: int,
    request_projects,
    selection: _PermissionSyncSelection,
    context: _PermissionManagementContext,
) -> None:
    if context.is_admin:
        _cleanup_admin_omitted_scopes(session, user_id, request_projects, selection)
    else:
        _cleanup_manager_omitted_scopes(session, user_id, request_projects, selection, context)


def _normalized_project_permission_map(request_projects) -> dict[int, set[str]]:
    return {
        project_node.project_id: set(
            _normalize_permissions(list(project_node.stored_permissions), "project")
        )
        for project_node in request_projects
    }


def _sync_project_nodes(
    session: Session,
    user_id: int,
    request_projects,
    perm_map: dict[str, int],
    context: _PermissionManagementContext,
) -> dict[int, set[str]]:
    project_perm_map = _normalized_project_permission_map(request_projects)
    for project_node in request_projects:
        if not context.can_manage_project(project_node.project_id):
            continue

        target_ids = {perm_map[name] for name in project_perm_map[project_node.project_id]}
        permission_repository.sync_project_permissions(
            session,
            user_id,
            project_node.project_id,
            target_ids,
        )
    return project_perm_map


def _normalized_collection_permissions(
    collection_node,
    parent_perms: set[str],
) -> list[str]:
    requested_collection_perms = set(collection_node.stored_permissions)
    cleaned = _normalize_permissions(list(collection_node.stored_permissions), "collection")
    if parent_perms:
        cleaned = _remove_cross_scope_redundancies(cleaned, parent_perms)
        if cleaned == ["collection:read"] and not any(
            permission_name.startswith("collection:")
            for permission_name in requested_collection_perms
        ):
            cleaned = []
    return cleaned


def _sync_collection_nodes(
    session: Session,
    user_id: int,
    request_projects,
    perm_map: dict[str, int],
    project_perm_map: dict[int, set[str]],
    context: _PermissionManagementContext,
) -> None:
    for project_node in request_projects:
        parent_perms = project_perm_map.get(project_node.project_id, set())
        for collection_node in project_node.collections:
            if not context.can_manage_collection(
                project_node.project_id,
                collection_node.collection_id,
            ):
                continue

            cleaned = _normalized_collection_permissions(collection_node, parent_perms)
            target_ids = {perm_map[name] for name in cleaned}
            permission_repository.sync_project_collection_permissions(
                session,
                user_id,
                project_node.project_id,
                collection_node.collection_id,
                target_ids,
            )


def sync_user_permissions_global(
    session: Session,
    user_id: int,
    request,
    current_user: User,
) -> None:
    """
    Unified user permission sync across multiple project/collection scopes.

    Handles:
    1. Admin toggle (is_admin) — only Admin can set this.
    2. Batch permission sync for each project node in request.projects.
    3. Authorization checks: non-Admin managers can only modify scopes
       where they have project:write or collection:write.

    Args:
        session: Database session
        user_id: Target user ID
        request: UserPermissionSyncRequest with is_admin and projects
        current_user: The user performing the action

    Returns:
        None
    """

    target_user = _get_target_user_or_404(session, user_id)
    context = _get_permission_management_context(session, current_user, target_user)
    request_projects = request.projects or []
    perm_map = _load_permission_id_map(session)
    selection = _get_sync_selection(request_projects)

    _apply_admin_toggle(session, target_user, request, context)
    _validate_permission_payload(request_projects, perm_map, context)
    _validate_requested_resources(session, request_projects)
    _cleanup_omitted_scopes(session, user_id, request_projects, selection, context)
    project_perm_map = _sync_project_nodes(session, user_id, request_projects, perm_map, context)
    _sync_collection_nodes(session, user_id, request_projects, perm_map, project_perm_map, context)

    session.commit()
