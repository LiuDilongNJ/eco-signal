from sqlmodel import Session, select

from app.models.effective_permission import UserEffectivePermission
from app.models.user import User
from app.repositories import permission_repository as default_permission_repository
from app.schemas.menu import MenuItemPublic
from app.services import permission_service


def _menu_item(name: str, visible: bool) -> MenuItemPublic:
    return MenuItemPublic(name=name, visible=visible)


def _effective_permission_pairs(session: Session, user_id: int) -> set[tuple[str, str]]:
    rows = session.exec(
        select(UserEffectivePermission.resource_type, UserEffectivePermission.action)
        .where(UserEffectivePermission.user_id == user_id)
        .distinct()
    ).all()
    return {(resource_type, action) for resource_type, action in rows}


def get_current_user_menu_items(
    session: Session,
    current_user: User,
    permission_repo=default_permission_repository,
    project_id: int = 0,
    collection_id: int | None = None,
) -> list[MenuItemPublic]:
    """Build menu visibility scoped to the given project."""
    is_admin = permission_service.is_admin(current_user)
    permission_pairs = (
        set()
        if is_admin
        else _effective_permission_pairs(session, current_user.user_id)
    )

    has_project_write_here = is_admin or permission_service.has_resource_permission(
        session, current_user, "project", "write", project_id=project_id
    )

    has_selected_collection_write_here = is_admin or (
        collection_id is not None
        and current_user.user_id is not None
        and permission_repo.has_collection_permission(
            session,
            current_user.user_id,
            project_id,
            collection_id,
            "collection",
            "write",
        )
    )

    if is_admin:
        has_any_accessible_collection = bool(
            permission_repo.get_project_collection_ids(session, project_id)
        )
    else:
        # Any effective collection-scoped permission in this project suffices
        has_any_accessible_collection = (
            session.exec(
                select(UserEffectivePermission.collection_id)
                .where(
                    UserEffectivePermission.user_id == current_user.user_id,
                    UserEffectivePermission.project_id == project_id,
                    UserEffectivePermission.scope_type == "project_collection",
                )
                .limit(1)
            ).first()
            is not None
        )

    can_show_collection_scoped_items = has_any_accessible_collection
    can_manage_project_level_menus = has_project_write_here or has_selected_collection_write_here
    can_manage_users = can_show_collection_scoped_items and can_manage_project_level_menus

    def has(resource_type: str, action: str) -> bool:
        return is_admin or (resource_type, action) in permission_pairs

    return [
        _menu_item("Projects", has_project_write_here),
        _menu_item("Collections", can_manage_project_level_menus),
        _menu_item("Users", can_manage_users),
        _menu_item("Audios", can_show_collection_scoped_items and has("audio", "read")),
        _menu_item("Photos", can_show_collection_scoped_items and has("audio", "read")),
        _menu_item("Sites", can_show_collection_scoped_items and has("site", "read")),
        _menu_item("Annotations", can_show_collection_scoped_items and has("annotation", "read")),
        _menu_item("Reviews", can_show_collection_scoped_items and has("review", "read")),
        _menu_item(
            "Tasks",
            can_show_collection_scoped_items
            and (has("audio", "write") or has("review", "write")),
        ),
        _menu_item("Queue", True),
        _menu_item("Index Logs", True),
    ]
