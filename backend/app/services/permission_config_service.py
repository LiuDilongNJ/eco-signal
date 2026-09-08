from dataclasses import dataclass

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.models.collection import Collection
from app.models.effective_permission import UserEffectivePermission
from app.models.permission import (
    Permission,
    RolePermission,
    UserPermission,
    UserScopeRole,
)
from app.models.project import Project, ProjectCollection
from app.models.user import Role, User
from app.repositories import permission_repository, role_repository, user_repository
from app.services.authorization_service import is_admin
from app.services.permission_rules import (
    ACCESS_ROLE_CODES,
    OWN_ACTIONS,
    OWNABLE_RESOURCE_TYPES,
    minimize_effective_permissions,
    normalize_permissions,
    remove_cross_scope_redundancies,
)


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
class _ScopeRoleMaps:
    project_roles: dict[int, str]
    collection_roles: dict[tuple[int, int], str]


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
        manageable_only=True,
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


def _load_scope_role_maps(session: Session, user_id: int) -> _ScopeRoleMaps:
    project_roles: dict[int, str] = {}
    collection_roles: dict[tuple[int, int], str] = {}
    rows = session.exec(
        select(UserScopeRole, Role)
        .join(Role, Role.role_id == UserScopeRole.role_id)
        .where(UserScopeRole.user_id == user_id)
    ).all()
    for assignment, role in rows:
        if role.kind != "access" or role.code not in ACCESS_ROLE_CODES:
            continue
        if assignment.collection_id is None:
            project_roles[assignment.project_id] = role.code
        else:
            collection_roles[(assignment.project_id, assignment.collection_id)] = role.code
    return _ScopeRoleMaps(project_roles, collection_roles)


def _role_permission_names(session: Session, role_code: str, scope_type: str) -> list[str]:
    if role_code == "custom":
        return []
    rows = session.exec(
        select(Permission.name)
        .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
        .join(Role, Role.role_id == RolePermission.role_id)
        .where(Role.code == role_code, RolePermission.scope_type == scope_type)
        .order_by(Permission.name)
    ).all()
    return list(rows)


def list_access_roles(session: Session) -> list[dict]:
    """Return role templates for the permission editor without frontend constants."""
    result = []
    for role in role_repository.list_access_roles(session):
        if role.code not in ACCESS_ROLE_CODES:
            continue
        result.append(
            {
                "code": role.code,
                "name": role.name,
                "kind": role.kind,
                "display_order": role.display_order,
                "project_permissions": _role_permission_names(session, role.code, "project"),
                "collection_permissions": _role_permission_names(session, role.code, "collection"),
            }
        )
    return result


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
        scope: minimize_effective_permissions(perms)
        for scope, perms in raw_permissions.items()
    }


def _load_effective_project_permission_map(session: Session, user_id: int) -> dict[int, list[str]]:
    rows = session.exec(
        select(UserEffectivePermission).where(
            UserEffectivePermission.user_id == user_id,
            UserEffectivePermission.scope_type == "project",
            UserEffectivePermission.collection_id.is_(None),
        )
    ).all()
    raw: dict[int, list[str]] = {}
    for row in rows:
        raw.setdefault(row.project_id, []).append(f"{row.resource_type}:{row.action}")
    return {project_id: minimize_effective_permissions(perms) for project_id, perms in raw.items()}


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
    scope_roles = _load_scope_role_maps(session, user_id)
    effective_project_permissions = _load_effective_project_permission_map(session, user_id)
    effective_collection_permissions = _load_effective_collection_permission_map(session, user_id)
    visible_tree = _load_visible_project_collection_tree(session, context)

    projects_result = []
    for proj, collections in visible_tree:
        stored_project_permissions = (
            stored_maps.project_permissions.get(proj.project_id, [])
            if context.can_manage_project(proj.project_id)
            else []
        )
        project_role = scope_roles.project_roles.get(proj.project_id)
        project_direct_permissions = minimize_effective_permissions(
            _role_permission_names(session, project_role, "project")
            if project_role and project_role != "custom"
            else stored_project_permissions
        )
        inherited_permissions = project_direct_permissions
        collections_data = []
        for col in collections:
            scope_key = (proj.project_id, col.collection_id)
            collections_data.append({
                "project_id": proj.project_id,
                "collection_id": col.collection_id,
                "collection_name": col.name,
                "can_manage_collection": context.can_manage_collection(proj.project_id, col.collection_id),
                "assigned_role": scope_roles.collection_roles.get(scope_key),
                "stored_permissions": stored_maps.collection_permissions.get(scope_key, [])
                if scope_roles.collection_roles.get(scope_key) in {None, "custom"}
                else [],
                "inherited_permissions": inherited_permissions,
                "effective_permissions": effective_collection_permissions.get(scope_key, []),
            })

        projects_result.append({
            "project_id": proj.project_id,
            "project_name": proj.name,
            "can_manage_project": context.can_manage_project(proj.project_id),
            "assigned_role": project_role,
            "stored_permissions": stored_project_permissions if project_role in {None, "custom"} else [],
            "effective_permissions": minimize_effective_permissions(
                project_direct_permissions + effective_project_permissions.get(proj.project_id, [])
            ),
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
    current_user: User,
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

    if (
        not request.is_admin
        and current_is_admin
        and target_user.user_id == current_user.user_id
    ):
        raise HTTPException(
            status_code=403,
            detail="Administrators cannot revoke their own administrator role",
        )

    role_code = "administrator" if request.is_admin else "user"
    role = role_repository.get_by_code(session, role_code)
    if role is None:
        role_name = settings.ADMIN_ROLE_NAME if request.is_admin else "User"
        role = role_repository.get_by_name(session, role_name)
        if role is not None and not role.code:
            role.code = role_code
            session.add(role)
    if role is None:
        raise RuntimeError(f"Required system role is not configured: {role_code}")
    target_user.role_id = role.role_id
    session.add(target_user)


def _validate_permission_payload(
    request_projects,
    perm_map: dict[str, int],
    context: _PermissionManagementContext,
) -> None:
    for project_node in request_projects:
        project_role = getattr(project_node, "role", None)
        if project_role is None and project_node.stored_permissions:
            raise HTTPException(status_code=400, detail="Permissions require the Custom role")
        if project_role not in {None, "custom"} and project_node.stored_permissions:
            raise HTTPException(status_code=400, detail="Named roles do not accept custom permissions")
        if project_role == "manager" and not context.is_admin:
            raise HTTPException(status_code=403, detail="Managers cannot grant project Manager")
        _raise_for_invalid_permissions(project_node.stored_permissions, perm_map)
        for permission_name in project_node.stored_permissions:
            resource_type, action = permission_name.split(":", 1)
            if action in OWN_ACTIONS and resource_type not in OWNABLE_RESOURCE_TYPES:
                raise HTTPException(status_code=400, detail=f"Own scope is not supported for {resource_type}")
        # Only system administrators may grant project:write (management-level).
        # A non-admin manager can delegate collection:write and below, but must
        # not be able to clone a peer project manager.
        if not context.is_admin and "project:write" in project_node.stored_permissions:
            raise HTTPException(
                status_code=403,
                detail="Managers cannot grant project:write",
            )
        if not context.can_manage_project(project_node.project_id):
            if project_node.stored_permissions or project_role is not None:
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
            collection_role = getattr(collection_node, "role", None)
            if collection_node.project_id != project_node.project_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Collection {collection_node.collection_id} carries mismatched project_id",
                )
            _raise_for_invalid_permissions(collection_node.stored_permissions, perm_map)
            if collection_role is None and collection_node.stored_permissions:
                raise HTTPException(status_code=400, detail="Permissions require the Custom role")
            if collection_role not in {None, "custom"} and collection_node.stored_permissions:
                raise HTTPException(status_code=400, detail="Named roles do not accept custom permissions")
            for permission_name in collection_node.stored_permissions:
                resource_type, action = permission_name.split(":", 1)
                if action in OWN_ACTIONS and resource_type not in OWNABLE_RESOURCE_TYPES:
                    raise HTTPException(status_code=400, detail=f"Own scope is not supported for {resource_type}")


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
            normalize_permissions(list(project_node.stored_permissions), "project")
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
    cleaned = normalize_permissions(list(collection_node.stored_permissions), "collection")
    if parent_perms:
        cleaned = remove_cross_scope_redundancies(cleaned, parent_perms)
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


def _get_access_role_or_400(session: Session, role_code: str) -> Role:
    if role_code not in ACCESS_ROLE_CODES:
        raise HTTPException(status_code=400, detail=f"Invalid access role: {role_code}")
    role = role_repository.get_by_code(session, role_code)
    if role is None or role.kind != "access":
        raise HTTPException(status_code=400, detail=f"Access role is not configured: {role_code}")
    return role


def _scope_role_row(
    session: Session,
    user_id: int,
    project_id: int,
    collection_id: int | None,
) -> UserScopeRole | None:
    stmt = select(UserScopeRole).where(
        UserScopeRole.user_id == user_id,
        UserScopeRole.project_id == project_id,
    )
    if collection_id is None:
        stmt = stmt.where(UserScopeRole.collection_id.is_(None))
    else:
        stmt = stmt.where(UserScopeRole.collection_id == collection_id)
    return session.exec(stmt).first()


def _clear_scope_assignment(
    session: Session,
    user_id: int,
    project_id: int,
    collection_id: int | None,
) -> None:
    assignment = _scope_role_row(session, user_id, project_id, collection_id)
    if assignment is not None:
        session.delete(assignment)
    if collection_id is None:
        permission_repository.sync_project_permissions(session, user_id, project_id, set())
    else:
        permission_repository.sync_project_collection_permissions(
            session, user_id, project_id, collection_id, set()
        )


def _sync_scope_assignment(
    session: Session,
    user_id: int,
    project_id: int,
    collection_id: int | None,
    role_code: str | None,
    permission_names: list[str],
    perm_map: dict[str, int],
) -> set[str]:
    """Persist one direct scope source and return its canonical direct grants."""
    scope_type = "project" if collection_id is None else "collection"
    if role_code is None:
        _clear_scope_assignment(session, user_id, project_id, collection_id)
        return set()

    role = _get_access_role_or_400(session, role_code)
    assignment = _scope_role_row(session, user_id, project_id, collection_id)
    previous_role_code = None
    if assignment is not None:
        previous_role = session.get(Role, assignment.role_id)
        previous_role_code = previous_role.code if previous_role is not None else None
    if assignment is None:
        assignment = UserScopeRole(
            user_id=user_id,
            role_id=role.role_id,
            project_id=project_id,
            collection_id=collection_id,
        )
        session.add(assignment)
    else:
        assignment.role_id = role.role_id
        session.add(assignment)

    if role_code == "custom":
        if not permission_names and previous_role_code and previous_role_code != "custom":
            permission_names = _role_permission_names(session, previous_role_code, scope_type)
        normalized = set(normalize_permissions(permission_names, scope_type))
        target_ids = {perm_map[name] for name in normalized}
        if collection_id is None:
            permission_repository.sync_project_permissions(session, user_id, project_id, target_ids)
        else:
            permission_repository.sync_project_collection_permissions(
                session, user_id, project_id, collection_id, target_ids
            )
        return normalized

    if collection_id is None:
        permission_repository.sync_project_permissions(session, user_id, project_id, set())
    else:
        permission_repository.sync_project_collection_permissions(
            session, user_id, project_id, collection_id, set()
        )
    return set(_role_permission_names(session, role_code, scope_type))


def _cleanup_scope_assignments(
    session: Session,
    user_id: int,
    request_projects,
    context: _PermissionManagementContext,
) -> None:
    requested_project_ids = {node.project_id for node in request_projects}
    requested_collection_scopes = {
        (node.project_id, collection.collection_id)
        for node in request_projects
        for collection in node.collections
    }
    if context.is_admin:
        project_ids = set(session.exec(select(Project.project_id)).all())
        collection_scopes = set(
            session.exec(select(ProjectCollection.project_id, ProjectCollection.collection_id)).all()
        )
    else:
        project_ids = context.project_ids or set()
        collection_scopes = set(context.collection_scopes or set())
        if project_ids:
            collection_scopes.update(session.exec(
                select(ProjectCollection.project_id, ProjectCollection.collection_id).where(
                    ProjectCollection.project_id.in_(project_ids)
                )
            ).all())

    for project_id in project_ids - requested_project_ids:
        _clear_scope_assignment(session, user_id, project_id, None)
        for linked_project_id, collection_id in collection_scopes:
            if linked_project_id == project_id:
                _clear_scope_assignment(session, user_id, project_id, collection_id)

    for project_id, collection_id in collection_scopes - requested_collection_scopes:
        _clear_scope_assignment(session, user_id, project_id, collection_id)


def _sync_role_nodes(
    session: Session,
    user_id: int,
    request_projects,
    perm_map: dict[str, int],
    context: _PermissionManagementContext,
) -> None:
    project_direct: dict[int, set[str]] = {}
    for project_node in request_projects:
        if context.can_manage_project(project_node.project_id):
            project_direct[project_node.project_id] = _sync_scope_assignment(
                session,
                user_id,
                project_node.project_id,
                None,
                project_node.role,
                project_node.stored_permissions,
                perm_map,
            )

    for project_node in request_projects:
        parent_permissions = project_direct.get(project_node.project_id, set())
        for collection_node in project_node.collections:
            if not context.can_manage_collection(project_node.project_id, collection_node.collection_id):
                continue
            permission_names = collection_node.stored_permissions
            if collection_node.role == "custom":
                permission_names = _normalized_collection_permissions(
                    collection_node, parent_permissions
                )
            _sync_scope_assignment(
                session,
                user_id,
                project_node.project_id,
                collection_node.collection_id,
                collection_node.role,
                permission_names,
                perm_map,
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

    _apply_admin_toggle(session, target_user, request, context, current_user)
    _validate_permission_payload(request_projects, perm_map, context)
    _validate_requested_resources(session, request_projects)
    _cleanup_scope_assignments(session, user_id, request_projects, context)
    _sync_role_nodes(session, user_id, request_projects, perm_map, context)

    session.commit()
