from fastapi import HTTPException
from sqlalchemy import delete, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.csv_export import CsvColumn, export_columns_csv
from app.models import User
from app.models.collection import Collection, CollectionContributor
from app.models.media import Media, MediaCollection
from app.models.permission import Permission, UserPermission
from app.models.project import Project, ProjectContributor
from app.models.system import FileUpload
from app.models.task import Task
from app.models.user import UserPreference
from app.repositories import permission_repository, role_repository, user_repository
from app.schemas import (
    UserCreate,
    UserUpdate,
    UserUpdateMe,
)
from app.schemas.response import ApiResponse, PagedApiResponse, api_page, api_success
from app.schemas.user import (
    COLLECTION_CONTRIBUTOR_ROLES,
    CreatorOption,
    PROJECT_CONTRIBUTOR_ROLES,
    SetContributorRequest,
    UserListPublic,
    UserPreferenceUpdate,
)
from app.services import permission_service

_USER_EXPORT_COLUMNS = [
    CsvColumn("user_id"), CsvColumn("username"), CsvColumn("name"),
    CsvColumn("email"), CsvColumn("orcid"), CsvColumn("color"),
    CsvColumn("contrib"), CsvColumn("active"),
]

def _raise_if_user_has_required_ownership(session: Session, user_id: int) -> None:
    """Block deletion when required ownership would leave orphaned records."""
    if session.exec(
        select(Project.project_id).where(Project.creator_id == user_id)
    ).first():
        raise HTTPException(
            status_code=409,
            detail="Cannot delete user: they are the creator of one or more projects",
        )

    if session.exec(
        select(Collection.collection_id).where(Collection.creator_id == user_id)
    ).first():
        raise HTTPException(
            status_code=409,
            detail="Cannot delete user: they are the creator of one or more collections",
        )

    if session.exec(
        select(MediaCollection.media_id).where(MediaCollection.added_by == user_id)
    ).first():
        raise HTTPException(
            status_code=409,
            detail="Cannot delete user: they are referenced by media collection links",
        )


def _cleanup_user_delete_dependencies(session: Session, user_id: int) -> None:
    """Remove or detach user-owned records that should not block account deletion."""
    session.exec(
        update(Media).where(Media.creator_id == user_id).values(creator_id=None)
    )
    session.exec(delete(FileUpload).where(FileUpload.uploader_id == user_id))
    session.exec(
        delete(Task).where(
            or_(Task.assigner_id == user_id, Task.assignee_id == user_id)
        )
    )
    session.exec(delete(UserPermission).where(UserPermission.user_id == user_id))


def _resolve_user_data_scope(
    session: Session,
    current_user: User,
) -> tuple[list[int] | None, list[int] | None]:
    """
    Resolve data-permission scope for list/export operations.

    Returns:
        (allowed_project_ids, allowed_collection_ids) where None means no restriction (admin).
        For managers, exactly one of the two lists will be non-None.
    """
    if permission_service.is_admin(current_user):
        return None, None

    project_ids = permission_repository.get_project_ids_with_write_permission(
        session, current_user.user_id
    )
    if project_ids:
        return project_ids, None

    collection_ids = permission_repository.get_accessible_collection_ids(
        session, current_user.user_id, "collection", "write"
    )
    if collection_ids:
        return None, collection_ids

    # No scope — gated by ActiveManager, should not reach here
    return [], None


def _get_collection_write_scopes(
    session: Session,
    user_id: int,
) -> list[tuple[int, int]]:
    """Return project-local collection:write scopes expanded by the effective view."""
    return permission_repository.get_effective_collection_scopes(
        session,
        user_id,
        "collection",
        "write",
    )


def _resolve_user_list_data_scope(
    session: Session,
    current_user: User,
    project_id: int | None = None,
    collection_id: int | None = None,
    scope: str = "current",
) -> tuple[list[int] | None, list[tuple[int, int]] | None]:
    """
    Resolve data scope for user listing, options, export, and target-user checks.

    None means unrestricted admin. Non-admin scopes are already intersected with
    request context, so repository filtering must never trust raw query params.
    """
    if permission_service.is_admin(current_user):
        return None, None

    project_write_ids = permission_repository.get_project_ids_with_write_permission(
        session, current_user.user_id
    )
    project_write_set = set(project_write_ids)
    collection_write_scopes = [
        pair
        for pair in _get_collection_write_scopes(session, current_user.user_id)
        if pair[0] not in project_write_set
    ]

    if scope == "all":
        return project_write_ids, collection_write_scopes

    if project_id is not None and collection_id is not None:
        if project_id in project_write_set:
            return [project_id], []
        pair = (project_id, collection_id)
        if pair in collection_write_scopes:
            return [], [pair]
        return [], []

    if project_id is not None:
        project_ids = [project_id] if project_id in project_write_set else []
        collection_scopes = [
            pair for pair in collection_write_scopes if pair[0] == project_id
        ]
        return project_ids, collection_scopes

    if collection_id is not None:
        project_ids = [
            allowed_project_id
            for allowed_project_id in project_write_ids
            if permission_service.has_resource_permission(
                session,
                current_user,
                "collection",
                "write",
                project_id=allowed_project_id,
                collection_id=collection_id,
            )
        ]
        collection_scopes = [
            pair for pair in collection_write_scopes if pair[1] == collection_id
        ]
        return project_ids, collection_scopes

    return project_write_ids, collection_write_scopes


def _check_user_manage_permission(
    session: Session,
    current_user: User,
    target_user: User,
) -> None:
    """
    Check if current_user has permission to manage target_user.
    
    Rules:
    1. Admin can manage anyone.
    2. Non-admin cannot manage an Admin.
    3. Managers can only manage ordinary users within their project:write or
       project-local collection:write scope.
    """
    if permission_service.is_admin(current_user):
        return

    # Non-admin cannot manage an Admin
    if permission_service.is_admin(target_user):
        raise HTTPException(
            status_code=403,
            detail="Managers are not allowed to manage Administrator accounts",
        )

    allowed_projects, allowed_collection_scopes = _resolve_user_list_data_scope(
        session,
        current_user,
        scope="all",
    )
    scope_filter = user_repository.build_manager_scope_user_condition(
        allowed_projects or [],
        allowed_collection_scopes or [],
    )
    stmt = select(User.user_id).where(
        User.user_id == target_user.user_id,
        scope_filter,
    )
    if session.exec(stmt).first():
        return

    # No overlapping scope
    raise HTTPException(
        status_code=403,
        detail="Target user is not within your management scope",
    )


def list_users(
    session: Session,
    current_user: User,
    page: int = 1,
    page_size: int = 15,
    user_id: int | None = None,
    username: str | None = None,
    name: str | None = None,
    email: str | None = None,
    orcid: str | None = None,
    color: str | None = None,
    active: bool | None = None,
    project_id: int | None = None,
    collection_id: int | None = None,
    scope: str = "current",
    contribution_role: str | None = None,
    order_by: str = "user_id",
    order_dir: str = "asc"
) -> PagedApiResponse[list[UserListPublic]]:
    """
    Retrieve paginated list of users with search, sorting, and data-permission filtering.

    Data permission rules:
    - Admin: no restriction (all users)
    - Project manager (project:write): only users in managed projects
    - Collection manager (collection:write): only users in managed collections
    """
    allowed_project_ids, allowed_collection_scopes = _resolve_user_list_data_scope(
        session,
        current_user,
        project_id=project_id,
        collection_id=collection_id,
        scope=scope,
    )

    # contribution_role 仅在明确 project_id / collection_id 上下文时生效；
    # 若单独传递（无 project_id/collection_id），则忽略该参数。
    # 列表筛选允许模糊匹配，因此这里不再做角色白名单精确校验。
    normalized_role = contribution_role.strip() if isinstance(contribution_role, str) else contribution_role
    if normalized_role == "":
        normalized_role = None

    effective_contribution_role: str | None = None
    if collection_id is not None:
        if normalized_role is not None:
            effective_contribution_role = normalized_role
    elif project_id is not None:
        if normalized_role is not None:
            effective_contribution_role = normalized_role

    result = user_repository.get_multi_paginated(
        session,
        page=page,
        page_size=page_size,
        user_id=user_id,
        username=username,
        name=name,
        email=email,
        orcid=orcid,
        color=color,
        active=active,
        project_id=project_id,
        collection_id=collection_id,
        scope=scope,
        contribution_role=effective_contribution_role,
        allowed_project_ids=allowed_project_ids,
        allowed_collection_scopes=allowed_collection_scopes,
        order_by=order_by,
        order_dir=order_dir
    )

    data = []
    for item in result["data"]:
        # In SQLAlchemy 2.0+ with multiple entities (e.g. select(User, Contributor)), 
        # item is a Row object which acts like a tuple.
        if type(item).__name__ == 'Row' or isinstance(item, tuple):
            user, contrib = item[0], item[1]
            user_dict = user.model_dump()
            user_dict["is_admin"] = permission_service.is_admin(user)
            if contrib:
                user_dict["contrib"] = contrib.contribution_role
            data.append(UserListPublic.model_validate(user_dict))
        else:
            data.append(
                UserListPublic.model_validate(
                    {**item.model_dump(), "is_admin": permission_service.is_admin(item)}
                )
            )

    return api_page(
        data=data,
        total=result["count"],
        page=result["page"],
        page_size=result["page_size"]
    )


def list_creator_options(
    session: Session,
    current_user: User,
    project_id: int,
    collection_id: int | None = None,
) -> ApiResponse[list[CreatorOption]]:
    """Return scoped Creator candidates, including all system administrators."""
    if not permission_service.is_admin(current_user):
        if collection_id is None:
            has_access = permission_service.has_resource_permission(
                session,
                current_user,
                "project",
                "read",
                project_id=project_id,
            )
        else:
            has_access = permission_service.has_resource_permission(
                session,
                current_user,
                "audio",
                "write",
                project_id=project_id,
                collection_id=collection_id,
            )
        if not has_access:
            raise HTTPException(status_code=403, detail="No access to the requested project or collection")

    allowed_project_ids, allowed_collection_scopes = _resolve_user_list_data_scope(
        session,
        current_user,
        project_id=project_id,
        collection_id=collection_id,
        scope="current",
    )
    candidates = user_repository.get_creator_candidates(
        session,
        project_id=project_id,
        collection_id=collection_id,
        allowed_project_ids=allowed_project_ids,
        allowed_collection_scopes=allowed_collection_scopes,
    )
    return api_success(
        data=[
            CreatorOption(
                user_id=user.user_id,
                name=user.name,
                username=user.username,
                is_admin=permission_service.is_admin(user),
            )
            for user in candidates
        ]
    )


def export_users_csv(
    session: Session,
    current_user: User,
    color: str | None = None,
    project_id: int | None = None,
    collection_id: int | None = None,
    scope: str = "current",
    order_by: str = "user_id",
    order_dir: str = "asc",
) -> str:
    """Export users to CSV format with data-permission filtering.

    - Admin: exports all users
    - Project manager: exports users in managed projects
    - Collection manager: exports users in managed collections
    """
    allowed_project_ids, allowed_collection_scopes = _resolve_user_list_data_scope(
        session,
        current_user,
        project_id=project_id,
        collection_id=collection_id,
        scope=scope,
    )

    result = user_repository.get_multi_paginated(
        session,
        page=1,
        page_size=1_000_000,
        color=color,
        scope=scope,
        project_id=project_id,
        collection_id=collection_id,
        allowed_project_ids=allowed_project_ids,
        allowed_collection_scopes=allowed_collection_scopes,
        order_by=order_by,
        order_dir=order_dir,
        include_total=False,
    )

    # When project_id or collection_id is set, get_multi_paginated returns
    # (User, Contributor) Row tuples — unpack them before CSV export.
    rows: list[UserListPublic] = []
    for item in result["data"]:
        if type(item).__name__ == "Row" or isinstance(item, tuple):
            user, contrib = item[0], item[1]
            user_dict = user.model_dump()
            user_dict["is_admin"] = permission_service.is_admin(user)
            if contrib:
                user_dict["contrib"] = contrib.contribution_role
            rows.append(UserListPublic.model_validate(user_dict))
        else:
            rows.append(
                UserListPublic.model_validate(
                    {**item.model_dump(), "is_admin": permission_service.is_admin(item)}
                )
            )

    return export_columns_csv(_USER_EXPORT_COLUMNS, rows)


def create_user(
    session: Session,
    current_user: User,
    user_in: UserCreate,
    project_id: int,
    collection_id: int | None = None,
) -> None:
    """Create a new user and bind them to the specified project or collection.

    Permission check:
    - If collection_id is provided: current_user must have collection:write on that collection.
      The new user will be granted collection:read on that collection and project:read on the project.
    - Otherwise: current_user must have project:write on the project.
      The new user will be granted project:read on that project.
    Admin bypasses all permission checks.
    """
    # Check email uniqueness
    existing_user = user_repository.get_by_email(session=session, email=user_in.email)
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )

    # Check username uniqueness
    existing_username = user_repository.get_by_username(session=session, username=user_in.username)
    if existing_username:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )

    if collection_id is not None:
        project_collection_ids = set(
            permission_repository.get_project_collection_ids(session, project_id)
        )
        if collection_id not in project_collection_ids:
            raise HTTPException(
                status_code=400,
                detail="collection_id does not belong to the given project_id",
            )

        # Scenario A: bind to collection — requires collection:write
        if not permission_service.has_resource_permission(
            session,
            current_user,
            "collection",
            "write",
            project_id=project_id,
            collection_id=collection_id,
        ):
            raise HTTPException(
                status_code=403,
                detail="No write permission on this collection",
            )

        new_user = user_repository.create(session=session, obj_in=user_in)

        # Query collection:read permission from DB
        coll_perm = session.exec(
            select(Permission).where(
                Permission.resource_type == "collection",
                Permission.action == "read",
            )
        ).one()
        session.add(UserPermission(
            user_id=new_user.user_id,
            project_id=project_id,
            collection_id=collection_id,
            permission_id=coll_perm.permission_id,
        ))

        # Also grant project:read permission
        proj_perm = session.exec(
            select(Permission).where(
                Permission.resource_type == "project",
                Permission.action == "read",
            )
        ).one()
        session.add(UserPermission(
            user_id=new_user.user_id,
            project_id=project_id,
            permission_id=proj_perm.permission_id,
        ))
        
        session.commit()

    else:
        # Scenario B: bind to project — requires project:write
        if not permission_service.has_resource_permission(
            session, current_user, "project", "write", project_id=project_id
        ):
            raise HTTPException(
                status_code=403,
                detail="No write permission on this project",
            )

        new_user = user_repository.create(session=session, obj_in=user_in)

        # Query project:read permission from DB
        perm = session.exec(
            select(Permission).where(
                Permission.resource_type == "project",
                Permission.action == "read",
            )
        ).one()
        session.add(UserPermission(
            user_id=new_user.user_id,
            project_id=project_id,
            permission_id=perm.permission_id,
        ))
        
        session.commit()

    session.refresh(new_user)


def get_user_by_id(
    session: Session, user_id: int, current_user: User
) -> User:
    """Get a specific user by ID with permission check."""
    user = user_repository.get(session, user_id)
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )
    
    if user == current_user:
        return user

    # Managers can only view users within their scope
    _check_user_manage_permission(session, current_user, user)
    
    return user


def update_user_me(
    session: Session, user_in: UserUpdateMe, current_user: User
) -> None:
    """Update current user's own profile."""
    if user_in.email:
        existing_user = user_repository.get_by_email(session=session, email=user_in.email)
        if existing_user and existing_user.user_id != current_user.user_id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
    
    user_data = user_in.model_dump(exclude_unset=True)
    current_user.sqlmodel_update(user_data)
    session.add(current_user)
    session.commit()
    session.refresh(current_user)


def update_user_preference(
    session: Session, pref_in: UserPreferenceUpdate, current_user: User
) -> None:
    """Upsert preferences for the current user."""
    pref = session.exec(
        select(UserPreference).where(UserPreference.user_id == current_user.user_id)
    ).first()

    if pref is None:
        pref = UserPreference(user_id=current_user.user_id)
        session.add(pref)

    update_data = pref_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(pref, field, value)

    session.commit()
    session.refresh(pref)


def update_password_me(
    session: Session, current_password: str, new_password: str, current_user: User
) -> ApiResponse:
    """Update current user's password."""
    if not verify_password(current_password, current_user.password):
        raise HTTPException(status_code=400, detail="Incorrect password")

    if current_password == new_password:
        raise HTTPException(
            status_code=400, detail="New password cannot be the same as the current one"
        )

    hashed = get_password_hash(new_password)
    current_user.password = hashed
    session.add(current_user)
    session.commit()
    return ApiResponse(message="Password updated successfully")


def update_user(
    session: Session, user_id: int, user_in: UserUpdate, current_user: User
) -> None:
    """Update a user by ID (admin/manager operation)."""
    db_user = user_repository.get(session, user_id)
    if not db_user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )
    
    # Check if current user can manage this specific user
    _check_user_manage_permission(session, current_user, db_user)

    if user_in.email:
        existing_user = user_repository.get_by_email(session=session, email=user_in.email)
        if existing_user and existing_user.user_id != user_id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )

    if user_in.username:
        existing_user = user_repository.get_by_username(session=session, username=user_in.username)
        if existing_user and existing_user.user_id != user_id:
            raise HTTPException(
                status_code=409, detail="User with this username already exists"
            )

    user_repository.update(session=session, db_obj=db_user, obj_in=user_in)


def delete_user(
    session: Session, user_id: int, current_user: User
) -> ApiResponse:
    """Delete a user by ID (admin/manager operation)."""
    user = user_repository.get(session, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user == current_user:
        if permission_service.is_admin(current_user):
            raise HTTPException(
                status_code=403, detail="Super users are not allowed to delete themselves"
            )
        raise HTTPException(
            status_code=403, detail="Use /me endpoint to delete yourself"
        )

    # Check if current user can manage this specific user
    _check_user_manage_permission(session, current_user, user)

    _raise_if_user_has_required_ownership(session, user_id)
    _cleanup_user_delete_dependencies(session, user_id)

    session.delete(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Cannot delete user: they are still referenced by other records",
        ) from exc
    return ApiResponse(message="User deleted successfully")


def admin_update_password(
    session: Session, user_id: int, new_password: str, current_user: User
) -> ApiResponse:
    """Update a user's password by ID (admin/manager operation)."""
    user = user_repository.get(session, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if current user can manage this specific user
    _check_user_manage_permission(session, current_user, user)

    hashed = get_password_hash(new_password)
    user.password = hashed
    session.add(user)
    session.commit()
    return ApiResponse(message="Password updated successfully")


def update_user_role(
    session: Session, user_id: int, is_admin: bool
) -> ApiResponse:
    """Update a user's role (admin operation)."""
    user = user_repository.get(session, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    role_name = settings.ADMIN_ROLE_NAME if is_admin else "User"
    role = role_repository.get_by_name(session, role_name)
    if role is None:
        raise RuntimeError(f"Required role is not configured: {role_name}")

    user.role_id = role.role_id
    
    session.add(user)
    session.commit()
    
    action = "granted admin role" if is_admin else "revoked admin role"
    return ApiResponse(message=f"User {action} successfully")


def set_contributor(
    session: Session, user_id: int, body: SetContributorRequest, current_user: User
) -> ApiResponse:
    """
    Set a user as a contributor to a project or collection.
    If collection_id is provided in body, prioritizes collection contributor.
    Otherwise, sets project contributor.
    
    Permission check:
    - Admin: bypasses.
    - If collection_id: current_user must have collection:write.
    - If project_id: current_user must have project:write.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.collection_id is not None:
        project_collection_ids = set(
            permission_repository.get_project_collection_ids(session, body.project_id)
        )
        if body.collection_id not in project_collection_ids:
            raise HTTPException(
                status_code=400,
                detail="collection_id does not belong to the given project_id",
            )

        # Check permission
        if not permission_service.has_resource_permission(
            session,
            current_user,
            "collection",
            "write",
            project_id=body.project_id,
            collection_id=body.collection_id,
        ):
            raise HTTPException(status_code=403, detail="No write permission on this collection")

        # Verify collection exists
        collection = session.get(Collection, body.collection_id)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")
            
        if body.contribution_role and body.contribution_role not in COLLECTION_CONTRIBUTOR_ROLES:
            raise HTTPException(status_code=400, detail="Invalid contribution role for collection")
        
        # Check if already a collection contributor
        stmt = select(CollectionContributor).where(
            CollectionContributor.user_id == user_id,
            CollectionContributor.collection_id == body.collection_id
        )
        contrib = session.exec(stmt).first()
        
        if not body.contribution_role:
            if contrib:
                session.delete(contrib)
        elif contrib:
            contrib.contribution_role = body.contribution_role
            session.add(contrib)
        else:
            new_contrib = CollectionContributor(
                user_id=user_id,
                collection_id=body.collection_id,
                contribution_role=body.contribution_role
            )
            session.add(new_contrib)
            
    else:
        # Check permission
        if not permission_service.has_resource_permission(
            session, current_user, "project", "write", project_id=body.project_id
        ):
            raise HTTPException(status_code=403, detail="No write permission on this project")

        # Verify project exists
        project = session.get(Project, body.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
            
        if body.contribution_role and body.contribution_role not in PROJECT_CONTRIBUTOR_ROLES:
            raise HTTPException(status_code=400, detail="Invalid contribution role for project")
            
        # Check if already a project contributor
        stmt = select(ProjectContributor).where(
            ProjectContributor.user_id == user_id,
            ProjectContributor.project_id == body.project_id
        )
        contrib = session.exec(stmt).first()
        
        if not body.contribution_role:
            if contrib:
                session.delete(contrib)
        elif contrib:
            contrib.contribution_role = body.contribution_role
            session.add(contrib)
        else:
            new_contrib = ProjectContributor(
                user_id=user_id,
                project_id=body.project_id,
                contribution_role=body.contribution_role
            )
            session.add(new_contrib)

    session.commit()
    return ApiResponse(message="Contributor set successfully")
