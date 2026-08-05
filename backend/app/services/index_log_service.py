from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.csv_export import CsvColumn, export_columns_csv
from app.models.media import MediaCollection
from app.models.user import User
from app.repositories import index_log_repository, permission_repository
from app.schemas.index_log import IndexLogDeleteItem, IndexLogRead
from app.services import permission_service

_INDEX_LOG_EXPORT_COLUMNS = [
    CsvColumn("log_id"), CsvColumn("media_name"),
    CsvColumn("user_name"), CsvColumn("user_id"),
    CsvColumn("index_name"), CsvColumn("version"),
    CsvColumn("min_time"), CsvColumn("max_time"),
    CsvColumn("min_frequency"), CsvColumn("max_frequency"),
    CsvColumn("variable_type"), CsvColumn("variable_order"),
    CsvColumn("variable_name"), CsvColumn("variable_value"),
    CsvColumn("creation_date"),
]


def list_index_logs(
    session: Session,
    current_user: User,
    page: int = 1,
    page_size: int = 15,
    **kwargs,
) -> tuple[list[dict[str, Any]], int]:
    """
    Get a paginated list of index logs with permissions applied.

    Permission: collection:write → all logs in those collections,
    otherwise → only own logs.
    """
    is_admin = permission_service.is_admin(current_user)
    accessible_collection_scopes = None
    if not is_admin:
        accessible_collection_scopes = permission_repository.get_accessible_collection_scopes(
            session,
            user_id=current_user.user_id,
            resource_type="collection",
            action="write"
        )
    
    items, total = index_log_repository.get_logs_page(
        session=session,
        user_id=current_user.user_id,
        is_admin=is_admin,
        accessible_collection_ids=None,
        accessible_collection_scopes=accessible_collection_scopes,
        page=page,
        page_size=page_size,
        **kwargs
    )
    return [IndexLogRead.model_validate(item).model_dump(mode="json") for item in items], total


def export_index_logs(
    session: Session,
    current_user: User,
    order_by: str | None = "log_id",
    order_dir: str = "asc",
    **kwargs
) -> str:
    """
    Export index logs to CSV with permissions applied.

    Permission: collection:write → all logs in those collections,
    otherwise → only own logs.
    """
    items, _ = list_index_logs(
        session=session,
        current_user=current_user,
        page=1,
        page_size=1_000_000,
        order_by=order_by,
        order_dir=order_dir,
        **kwargs,
    )
    return export_columns_csv(_INDEX_LOG_EXPORT_COLUMNS, items)


def delete_index_logs(
    session: Session,
    current_user: User,
    delete_items: list[IndexLogDeleteItem],
) -> int:
    """
    Batch delete index logs with permissions check.
    Requires project:write level access to the media or site containing them.
    """
    is_admin = permission_service.is_admin(current_user)
    deleted_count = 0
    seen: set[tuple[int, int, int]] = set()

    for item in delete_items:
        group_identity = (item.log_id, item.media_id, item.index_id)
        if group_identity in seen:
            continue
        seen.add(group_identity)

        if not index_log_repository.has_group(
            session,
            log_id=item.log_id,
            media_id=item.media_id,
            index_id=item.index_id,
        ):
            if index_log_repository.has_log_id(session, log_id=item.log_id):
                raise HTTPException(status_code=404, detail="Index log group not found")
            continue
        media_id = item.media_id
        index_id = item.index_id
            
        if not is_admin:
            # A log belongs to a media, which belongs to collections
            media_colls = session.exec(select(MediaCollection).where(MediaCollection.media_id == media_id)).all()
            media_coll_ids = [mc.collection_id for mc in media_colls]
            
            if not permission_service.has_resource_permission_on_any_collection_path(
                session,
                current_user,
                media_coll_ids,
                "collection",
                "write",
            ):
                 raise HTTPException(status_code=403, detail=f"Not enough permissions to delete log {item.log_id}")

        removed_rows = index_log_repository.delete_group(
            session,
            log_id=item.log_id,
            media_id=media_id,
            index_id=index_id,
        )
        if removed_rows > 0:
            deleted_count += 1
        
    return deleted_count
