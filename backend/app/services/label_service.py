from typing import Sequence

from fastapi import HTTPException
from sqlmodel import Session

from app.csv_export import CsvColumn, export_columns_csv
from app.models.label import Label, LabelMedia
from app.models.user import User
from app.repositories.label_repository import (
    LABEL_TYPE_PRIVATE,
    LABEL_TYPE_PUBLIC,
    label_repository,
)
from app.repositories.task_repository import task_repository
from app.schemas.label import (
    LabelAdminCreateRequest,
    LabelAdminPublic,
    LabelAdminUpdateRequest,
    LabelCreateRequest,
)
from app.schemas.media import MediaBatchFailedItem, MediaBatchOperationResponse

_LABEL_SETTING_EXPORT_COLUMNS = [
    CsvColumn("label_id"), CsvColumn("name"), CsvColumn("type"),
    CsvColumn("creator_id"), CsvColumn("creator_name"),
    CsvColumn("creation_date"),
]


def get_user_labels(session: Session, user: User | None) -> Sequence[Label]:
    """
    Get all labels accessible to the user.
    """
    if user is None:
        return label_repository.get_public_labels(session)
    return label_repository.get_accessible_labels(session, user.user_id)


def create_label(session: Session, label_in: LabelCreateRequest, user: User) -> None:
    """
    Create a new label for the current user.
    """
    name = label_in.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Label name cannot be empty")
    if len(name) > 20:
        raise HTTPException(status_code=400, detail="Label name must be 20 characters or fewer")

    existing = label_repository.get_by_creator_and_name(session, user.user_id, name)
    if existing:
        raise HTTPException(status_code=400, detail="Label with same name already exists")

    label = Label(name=name, creator_id=user.user_id, type=LABEL_TYPE_PRIVATE)
    session.add(label)
    session.commit()
    session.refresh(label)


def _validate_label_type(label_type: str) -> None:
    if label_type not in {LABEL_TYPE_PRIVATE, LABEL_TYPE_PUBLIC}:
        raise HTTPException(status_code=422, detail="Label type must be private or public")


def _normalize_label_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Label name cannot be empty")
    if len(normalized) > 20:
        raise HTTPException(status_code=400, detail="Label name must be 20 characters or fewer")
    return normalized


def _to_admin_public(row: dict) -> LabelAdminPublic:
    return LabelAdminPublic.model_validate(row)


def list_label_settings(
    session: Session,
    *,
    page: int,
    page_size: int,
    filters: dict,
    order_by: str,
    order_dir: str,
) -> tuple[list[LabelAdminPublic], int]:
    rows, total = label_repository.list_settings(
        session,
        page=page,
        page_size=page_size,
        filters=filters,
        order_by=order_by,
        order_dir=order_dir,
    )
    return [_to_admin_public(row) for row in rows], total


def export_label_settings_csv(
    session: Session,
    *,
    filters: dict,
    order_by: str,
    order_dir: str,
) -> str:
    rows = label_repository.list_settings_for_export(
        session,
        filters=filters,
        order_by=order_by,
        order_dir=order_dir,
    )
    items = [_to_admin_public(row) for row in rows]
    return export_columns_csv(_LABEL_SETTING_EXPORT_COLUMNS, items)


def get_label_setting(session: Session, label_id: int) -> LabelAdminPublic:
    row = label_repository.get_setting_by_id(session, label_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Label not found")
    return _to_admin_public(row)


def create_label_setting(
    session: Session,
    label_in: LabelAdminCreateRequest,
    user: User,
) -> LabelAdminPublic:
    name = _normalize_label_name(label_in.name)
    _validate_label_type(label_in.type)

    existing = label_repository.get_by_creator_and_name(session, user.user_id, name)
    if existing:
        raise HTTPException(status_code=400, detail="Label with same name already exists")

    label = Label(name=name, creator_id=user.user_id, type=label_in.type)
    session.add(label)
    session.commit()
    session.refresh(label)
    return get_label_setting(session, label.label_id)


def update_label_setting(
    session: Session,
    label_id: int,
    label_in: LabelAdminUpdateRequest,
) -> LabelAdminPublic:
    label = label_repository.get_by_id(session, label_id)
    if label is None:
        raise HTTPException(status_code=404, detail="Label not found")

    update_data = label_in.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        name = _normalize_label_name(update_data["name"])
        existing = label_repository.get_by_creator_and_name(
            session,
            label.creator_id,
            name,
            exclude_label_id=label_id,
        )
        if existing:
            raise HTTPException(status_code=400, detail="Label with same name already exists")
        label.name = name

    if "type" in update_data and update_data["type"] is not None:
        _validate_label_type(update_data["type"])
        label.type = update_data["type"]

    session.add(label)
    session.commit()
    session.refresh(label)
    return get_label_setting(session, label_id)


def delete_label_setting(session: Session, label_id: int) -> None:
    label = label_repository.get_by_id(session, label_id)
    if label is None:
        raise HTTPException(status_code=404, detail="Label not found")
    if label_id in {1, 2, 3}:
        raise HTTPException(status_code=403, detail="System label cannot be deleted")

    links = label_repository.get_label_media_by_label(session, label_id)
    for link in links:
        session.delete(link)
    session.flush()

    session.delete(label)
    session.commit()


def delete_label(session: Session, label_id: int, user: User) -> None:
    """
    Delete a label by ID.

    - System labels (id=1,2,3) are protected and cannot be deleted.
    - Users can only delete their own labels.
    - Associated label_media rows are removed automatically via CASCADE.
    """
    label = label_repository.get_by_id(session, label_id)
    if label is None:
        raise HTTPException(status_code=404, detail="Label not found")

    if label_id in {1, 2, 3}:
        raise HTTPException(status_code=403, detail="System label cannot be deleted")

    if label.creator_id != user.user_id:
        raise HTTPException(status_code=403, detail="No permission to delete this label")

    # Must explicitly remove label_media rows first; label_id is part of
    # label_media's composite PK, so SQLAlchemy cannot null it out on its own.
    links = label_repository.get_label_media_by_label(session, label_id)
    for link in links:
        session.delete(link)
    session.flush()

    session.delete(label)
    session.commit()


def set_media_label(
    session: Session,
    media_id: int,
    label_id: int | None,
    user: User,
) -> None:
    """
    Set at most one label for a media by a specific user.
    Replaces any existing label link for this user and media.
    """
    accessible_labels = label_repository.get_accessible_labels(session, user.user_id)
    accessible_label_ids = {label.label_id for label in accessible_labels}

    if label_id is not None and label_id not in accessible_label_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Label ID {label_id} is not accessible or does not exist",
        )

    links = label_repository.get_user_media_labels(session, media_id, user.user_id)
    for link in links:
        session.delete(link)
    session.flush()

    if label_id is None:
        task_repository.mark_media_task_assigned(
            session=session,
            media_id=media_id,
            assignee_id=user.user_id,
        )
        session.commit()
        return

    session.add(
        LabelMedia(
            media_id=media_id,
            user_id=user.user_id,
            label_id=label_id,
        )
    )
    session.flush()

    if label_id != 1:
        task_repository.mark_media_task_reviewed(
            session=session,
            media_id=media_id,
            assignee_id=user.user_id,
        )
    else:
        task_repository.mark_media_task_assigned(
            session=session,
            media_id=media_id,
            assignee_id=user.user_id,
        )

    session.commit()


def set_media_labels(
    session: Session,
    media_ids: list[int],
    label_id: int | None,
    user: User,
    *,
    project_id: int,
) -> MediaBatchOperationResponse:
    """Set one label for the current user across multiple media records."""
    from app.services import media_service

    succeeded: list[int] = []
    failed: list[MediaBatchFailedItem] = []

    for media_id in sorted(set(media_ids)):
        try:
            media_service.get_media(session, project_id, media_id, user)
            set_media_label(session, media_id, label_id, user)
            succeeded.append(media_id)
        except HTTPException as exc:
            failed.append(
                MediaBatchFailedItem(
                    media_id=media_id,
                    status_code=exc.status_code,
                    message=str(exc.detail),
                )
            )

    return MediaBatchOperationResponse(succeeded=succeeded, failed=failed)
