"""Persistence helpers for collection bundle exports."""

from datetime import datetime
from uuid import UUID

from sqlmodel import Session, select

from app.models import CollectionBundleExport
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
    apply_pagination,
)

_FILTER_SPECS: list[FilterSpec] = [
    ("project_id", CollectionBundleExport.project_id, FilterOp.EQ),
    ("user_id", CollectionBundleExport.user_id, FilterOp.EQ),
]

_SORT_FIELDS = {"creation_date": CollectionBundleExport.creation_date}


class CollectionBundleExportRepository:
    def get(self, session: Session, export_id: UUID) -> CollectionBundleExport | None:
        return session.get(CollectionBundleExport, export_id)

    def list_recent(
        self,
        session: Session,
        *,
        project_id: int,
        user_id: int | None,
    ) -> list[CollectionBundleExport]:
        statement = apply_filters(
            select(CollectionBundleExport),
            {"project_id": project_id, "user_id": user_id},
            _FILTER_SPECS,
        )
        statement = statement.where(CollectionBundleExport.status != "expired")
        statement = apply_ordering(
            statement,
            "creation_date",
            "desc",
            _SORT_FIELDS,
            CollectionBundleExport.creation_date,
        )
        statement = apply_pagination(statement, 1, 50)
        return list(session.exec(statement).all())

    def list_expired(
        self,
        session: Session,
        now: datetime,
    ) -> list[CollectionBundleExport]:
        statement = select(CollectionBundleExport).where(
            CollectionBundleExport.status == "completed",
            CollectionBundleExport.expires_at.is_not(None),
            CollectionBundleExport.expires_at <= now,
        )
        return list(session.exec(statement).all())

    def get_by_queue_ids(
        self,
        session: Session,
        queue_ids: list[int],
    ) -> list[CollectionBundleExport]:
        if not queue_ids:
            return []
        statement = select(CollectionBundleExport).where(
            CollectionBundleExport.queue_id.in_(queue_ids)
        )
        return list(session.exec(statement).all())


collection_bundle_export_repository = CollectionBundleExportRepository()
