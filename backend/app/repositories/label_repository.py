from typing import Any, Sequence

from sqlalchemy import func as sa_func
from sqlmodel import Session, func, or_, select

from app.models.label import Label, LabelMedia
from app.models.user import User
from app.repositories.base import BaseRepository
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
    apply_pagination,
)

LABEL_TYPE_PUBLIC = "public"
LABEL_TYPE_PRIVATE = "private"

_LABEL_SETTINGS_FILTER_SPECS: list[FilterSpec] = [
    ("label_id", Label.label_id, FilterOp.EQ),
    ("name", Label.name, FilterOp.LIKE),
    ("type", Label.type, FilterOp.LIKE),
    ("creator_id", Label.creator_id, FilterOp.EQ),
    ("creation_date", Label.creation_date, FilterOp.DATE_RANGE),
]

_LABEL_SETTINGS_SORT_FIELDS: dict[str, Any] = {
    "label_id": Label.label_id,
    "name": Label.name,
    "type": Label.type,
    "creator_id": Label.creator_id,
    "creator_name": User.name,
    "creation_date": Label.creation_date,
}


class LabelRepository(BaseRepository[Label, Label, Label]):
    def __init__(self):
        super().__init__(Label)

    def get_accessible_labels(self, session: Session, user_id: int) -> Sequence[Label]:
        statement = select(Label).where(
            or_(
                Label.creator_id == user_id,
                Label.type == LABEL_TYPE_PUBLIC,
            )
        ).order_by(Label.label_id)
        return session.exec(statement).all()

    def get_public_labels(self, session: Session) -> Sequence[Label]:
        statement = select(Label).where(Label.type == LABEL_TYPE_PUBLIC).order_by(Label.label_id)
        return session.exec(statement).all()

    def get_public_by_name(self, session: Session, name: str) -> Label | None:
        """Return the first public label matching a name case-insensitively."""
        statement = (
            select(Label)
            .where(
                Label.type == LABEL_TYPE_PUBLIC,
                sa_func.lower(Label.name) == name.lower(),
            )
            .order_by(Label.label_id)
        )
        return session.exec(statement).first()

    def list_settings(
        self,
        session: Session,
        *,
        page: int,
        page_size: int,
        filters: dict[str, Any],
        order_by: str,
        order_dir: str,
    ) -> tuple[Sequence[dict[str, Any]], int]:
        base = select(
            Label.label_id,
            Label.name,
            Label.creator_id,
            Label.type,
            Label.creation_date,
            User.name.label("creator_name"),
        ).outerjoin(User, User.user_id == Label.creator_id)
        if filters.get("creator_name"):
            base = base.where(User.name.ilike(f"%{filters['creator_name']}%"))
        base = apply_filters(base, filters, _LABEL_SETTINGS_FILTER_SPECS)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = session.exec(count_stmt).one()

        stmt = apply_ordering(
            base,
            order_by,
            order_dir,
            _LABEL_SETTINGS_SORT_FIELDS,
            Label.label_id,
            tie_break_col=Label.label_id,
        )
        stmt = apply_pagination(stmt, page, page_size)
        rows = session.exec(stmt).all()
        return [dict(row._mapping) for row in rows], total

    def list_settings_for_export(
        self,
        session: Session,
        *,
        filters: dict[str, Any],
        order_by: str,
        order_dir: str,
    ) -> Sequence[dict[str, Any]]:
        stmt = select(
            Label.label_id,
            Label.name,
            Label.creator_id,
            Label.type,
            Label.creation_date,
            User.name.label("creator_name"),
        ).outerjoin(User, User.user_id == Label.creator_id)
        if filters.get("creator_name"):
            stmt = stmt.where(User.name.ilike(f"%{filters['creator_name']}%"))
        stmt = apply_filters(stmt, filters, _LABEL_SETTINGS_FILTER_SPECS)
        stmt = apply_ordering(
            stmt,
            order_by,
            order_dir,
            _LABEL_SETTINGS_SORT_FIELDS,
            Label.label_id,
            tie_break_col=Label.label_id,
        )
        return [dict(row._mapping) for row in session.exec(stmt).all()]

    def get_setting_by_id(self, session: Session, label_id: int) -> dict[str, Any] | None:
        stmt = (
            select(
                Label.label_id,
                Label.name,
                Label.creator_id,
                Label.type,
                Label.creation_date,
                User.name.label("creator_name"),
            )
            .outerjoin(User, User.user_id == Label.creator_id)
            .where(Label.label_id == label_id)
        )
        row = session.exec(stmt).first()
        return dict(row._mapping) if row else None

    def get_user_media_labels(self, session: Session, media_id: int, user_id: int) -> Sequence[LabelMedia]:
        """Get labels associated with a media by a specific user."""
        statement = select(LabelMedia).where(
            LabelMedia.media_id == media_id,
            LabelMedia.user_id == user_id
        )
        return session.exec(statement).all()

    def get_by_id(self, session: Session, label_id: int) -> Label | None:
        return session.get(Label, label_id)

    def get_label_media_by_label(self, session: Session, label_id: int) -> Sequence[LabelMedia]:
        """Get all label_media rows for a given label."""
        statement = select(LabelMedia).where(LabelMedia.label_id == label_id)
        return session.exec(statement).all()

    def get_by_creator_and_name(
        self,
        session: Session,
        creator_id: int,
        name: str,
        exclude_label_id: int | None = None,
    ) -> Label | None:
        """Get a label by creator and case-insensitive name."""
        statement = select(Label).where(
            Label.creator_id == creator_id,
            sa_func.lower(Label.name) == name.lower(),
        )
        if exclude_label_id is not None:
            statement = statement.where(Label.label_id != exclude_label_id)
        return session.exec(statement).first()


label_repository = LabelRepository()
