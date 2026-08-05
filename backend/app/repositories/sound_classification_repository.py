from typing import Any

from sqlmodel import Session, func, select

from app.models.annotation import Annotation
from app.models.taxon import SoundClassification
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
    apply_pagination,
)
from app.schemas.sound_classification import SoundClassificationWrite

_FILTER_SPECS: list[FilterSpec] = [
    ("sound_id", SoundClassification.sound_id, FilterOp.EQ),
    ("soundscape_component", SoundClassification.soundscape_component, FilterOp.LIKE),
    ("sound_type", SoundClassification.sound_type, FilterOp.LIKE),
]

_SORT_FIELDS: dict[str, Any] = {
    "sound_id": SoundClassification.sound_id,
    "soundscape_component": SoundClassification.soundscape_component,
    "sound_type": SoundClassification.sound_type,
}


class SoundClassificationRepository:
    def _apply_filters(self, stmt: Any, filters: dict[str, Any]) -> Any:
        stmt = apply_filters(stmt, filters, _FILTER_SPECS)
        return stmt

    def _apply_ordering(self, stmt: Any, order_by: str, order_dir: str) -> Any:
        return apply_ordering(
            stmt,
            order_by,
            order_dir,
            _SORT_FIELDS,
            SoundClassification.sound_id,
            SoundClassification.sound_id,
        )

    def list_page(
        self,
        session: Session,
        page: int,
        page_size: int,
        filters: dict[str, Any],
        order_by: str,
        order_dir: str,
    ) -> tuple[list[SoundClassification], int]:
        base_stmt = self._apply_filters(select(SoundClassification), filters)
        total = session.exec(select(func.count()).select_from(base_stmt.subquery())).one()
        stmt = self._apply_ordering(base_stmt, order_by, order_dir)
        stmt = apply_pagination(stmt, page, page_size)
        return list(session.exec(stmt).all()), total

    def list_for_export(
        self,
        session: Session,
        order_by: str,
        order_dir: str,
    ) -> list[SoundClassification]:
        stmt = self._apply_ordering(select(SoundClassification), order_by, order_dir)
        return list(session.exec(stmt).all())

    def get(self, session: Session, sound_id: int) -> SoundClassification | None:
        return session.get(SoundClassification, sound_id)

    def has_duplicate(
        self,
        session: Session,
        data: SoundClassificationWrite,
        exclude_id: int | None = None,
    ) -> bool:
        stmt = select(func.count()).select_from(SoundClassification).where(
            func.lower(func.trim(SoundClassification.soundscape_component))
            == data.soundscape_component.casefold()
        )
        if data.sound_type is None:
            stmt = stmt.where(SoundClassification.sound_type.is_(None))
        else:
            stmt = stmt.where(
                func.lower(func.trim(SoundClassification.sound_type)) == data.sound_type.casefold()
            )
        if exclude_id is not None:
            stmt = stmt.where(SoundClassification.sound_id != exclude_id)
        return session.exec(stmt).one() > 0

    def get_existing_keys(self, session: Session) -> set[tuple[str, str | None]]:
        """Load all normalized (component, sound_type) pairs for bulk duplicate checks."""
        stmt = select(
            func.lower(func.trim(SoundClassification.soundscape_component)),
            func.lower(func.trim(SoundClassification.sound_type)),
        )
        return {(component, sound_type) for component, sound_type in session.exec(stmt).all()}

    def create(self, session: Session, data: SoundClassificationWrite) -> SoundClassification:
        item = SoundClassification(**data.model_dump())
        session.add(item)
        session.commit()
        session.refresh(item)
        return item

    def update(
        self,
        session: Session,
        item: SoundClassification,
        data: SoundClassificationWrite,
    ) -> SoundClassification:
        for field, value in data.model_dump().items():
            setattr(item, field, value)
        session.add(item)
        session.commit()
        session.refresh(item)
        return item

    def create_many(
        self,
        session: Session,
        rows: list[SoundClassificationWrite],
    ) -> list[SoundClassification]:
        items = [SoundClassification(**row.model_dump()) for row in rows]
        session.add_all(items)
        session.commit()
        for item in items:
            session.refresh(item)
        return items

    def is_referenced(self, session: Session, sound_id: int) -> bool:
        count = session.exec(
            select(func.count()).select_from(Annotation).where(Annotation.sound_id == sound_id)
        ).one()
        return count > 0

    def delete(self, session: Session, item: SoundClassification) -> None:
        session.delete(item)
        session.commit()


sound_classification_repository = SoundClassificationRepository()
