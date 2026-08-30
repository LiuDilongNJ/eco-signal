from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Float, and_, case, cast, delete, insert, text
from sqlmodel import Session, func, or_, select

from app.models.index import IndexLog, IndexType
from app.models.media import Media, MediaCollection
from app.models.project import ProjectCollection
from app.models.user import User
from app.repositories.base import BaseRepository
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
    apply_pagination,
)

_FILTER_SPECS: list[FilterSpec] = [
    # Exact matches
    ("log_id",    IndexLog.log_id,         FilterOp.EQ),
    ("media_id",  IndexLog.media_id,       FilterOp.EQ),
    ("var_order", IndexLog.variable_order, FilterOp.RANGE),
    # Fuzzy matches on IndexLog columns
    ("version",  IndexLog.version,        FilterOp.LIKE),
    ("var_type", IndexLog.variable_type,  FilterOp.LIKE),
    ("var_name", IndexLog.variable_name,  FilterOp.LIKE),
    ("creation_date", IndexLog.creation_date, FilterOp.DATE_RANGE),
    # Fuzzy matches on joined table columns (always outerjoin'd in _build_list_query)
    ("media_name", Media.name,      FilterOp.LIKE),
    ("user",       User.name,       FilterOp.LIKE),
    ("index_type", IndexType.name,  FilterOp.LIKE),
]

_SORT_FIELDS: dict[str, Any] = {
    "log_id":         IndexLog.log_id,
    "id":             IndexLog.log_id,
    "version":        IndexLog.version,
    "min_time":       IndexLog.min_time,
    "max_time":       IndexLog.max_time,
    "min_frequency":  IndexLog.min_frequency,
    "max_frequency":  IndexLog.max_frequency,
    "variable_type":  IndexLog.variable_type,
    "variable_order": IndexLog.variable_order,
    "variable_name":  IndexLog.variable_name,
    "variable_value": IndexLog.variable_value,
    "var_type":       IndexLog.variable_type,
    "var_order":      IndexLog.variable_order,
    "var_name":       IndexLog.variable_name,
    "var_value":      IndexLog.variable_value,
    "creation_date":  IndexLog.creation_date,
    "media_name":     Media.name,
    "media":          Media.name,
    "user_name":      User.name,
    "user":           User.name,
    "index_name":     IndexType.name,
    "index_type":     IndexType.name,
}


class IndexLogRepository(BaseRepository[IndexLog, Any, Any]):
    def __init__(self):
        super().__init__(IndexLog)

    def reserve_log_id(self, session: Session) -> int:
        """Reserve one log_id for a grouped acoustic index batch."""
        return session.execute(text("SELECT nextval('index_log_log_id_seq')")).scalar_one()

    def create_from_results(
        self,
        session: Session,
        *,
        media_id: int,
        user_id: int,
        index_id: int,
        version: str,
        results: dict[str, Any],
        params: dict[str, Any] | None = None,
        output_first: bool = False,
        min_time: str | None = None,
        max_time: str | None = None,
        min_frequency: str | None = None,
        max_frequency: str | None = None,
        log_id: int | None = None,
        commit: bool = True,
    ) -> int:
        """
        Create multiple IndexLog entries from analysis results.

        All rows in one batch share the same log_id (group identifier).
        Uses a raw INSERT to bypass the ORM identity map (the table has no real PK).

        Returns:
            Number of rows inserted
        """
        group_log_id = log_id if log_id is not None else self.reserve_log_id(session)
        now = datetime.now(UTC)

        common = dict(
            log_id=group_log_id,
            media_id=media_id,
            user_id=user_id,
            index_id=index_id,
            version=version,
            min_time=min_time,
            max_time=max_time,
            min_frequency=min_frequency,
            max_frequency=max_frequency,
            creation_date=now,
        )

        rows: list[dict[str, Any]] = []

        input_rows: list[dict[str, Any]] = []
        output_rows: list[dict[str, Any]] = []

        if params:
            for order, (name, value) in enumerate(params.items(), start=1):
                input_rows.append({
                    **common,
                    "variable_type": "input",
                    "variable_order": order,
                    "variable_name": name,
                    "variable_value": str(value),
                })

        for order, (name, value) in enumerate(results.items(), start=1):
            if name == "error":
                continue
            output_rows.append({
                **common,
                "variable_type": "output",
                "variable_order": order,
                "variable_name": name,
                "variable_value": str(value),
            })

        rows.extend(output_rows if output_first else input_rows)
        rows.extend(input_rows if output_first else output_rows)

        for offset, row in enumerate(rows):
            row["creation_date"] = now + timedelta(microseconds=offset)

        if rows:
            session.execute(insert(IndexLog), rows)
            if commit:
                session.commit()
            else:
                session.flush()

        return len(rows)

    def has_group(
        self,
        session: Session,
        *,
        log_id: int,
        media_id: int,
        index_id: int,
    ) -> bool:
        """Return whether the exact delete tuple exists."""
        stmt = (
            select(IndexLog.log_id)
            .where(
                and_(
                    IndexLog.log_id == log_id,
                    IndexLog.media_id == media_id,
                    IndexLog.index_id == index_id,
                )
            )
            .limit(1)
        )
        return session.exec(stmt).first() is not None

    def has_log_id(
        self,
        session: Session,
        *,
        log_id: int,
    ) -> bool:
        """Return whether any row exists for the provided log_id."""
        stmt = select(IndexLog.log_id).where(IndexLog.log_id == log_id).limit(1)
        return session.exec(stmt).first() is not None

    def get_group_user_id(
        self,
        session: Session,
        *,
        log_id: int,
        media_id: int,
        index_id: int,
    ) -> int | None:
        """Return the owner of an exact index-log group."""
        stmt = (
            select(IndexLog.user_id)
            .where(
                IndexLog.log_id == log_id,
                IndexLog.media_id == media_id,
                IndexLog.index_id == index_id,
            )
            .limit(1)
        )
        return session.exec(stmt).first()

    def delete_group(
        self,
        session: Session,
        *,
        log_id: int,
        media_id: int,
        index_id: int,
    ) -> int:
        """Delete all rows in the `(log_id, media_id, index_id)` group."""
        result = session.execute(
            delete(IndexLog).where(
                and_(
                    IndexLog.log_id == log_id,
                    IndexLog.media_id == media_id,
                    IndexLog.index_id == index_id,
                )
            )
        )
        session.commit()
        return result.rowcount or 0

    def _numeric_expr(self, column):
        numeric_pattern = r"^\s*[+-]?((\d+(\.\d*)?)|(\.\d+))\s*$"
        return case(
            (column.op("~")(numeric_pattern), cast(column, Float)),
            else_=None,
        )

    def _apply_numeric_range(self, stmt, filters: dict, key: str, column):
        lo = filters.get(f"{key}_min")
        hi = filters.get(f"{key}_max")
        if lo is None and hi is None:
            return stmt
        numeric_value = self._numeric_expr(column)
        if lo is not None:
            stmt = stmt.where(numeric_value >= lo)
        if hi is not None:
            stmt = stmt.where(numeric_value <= hi)
        return stmt

    def _apply_scope_filter(self, stmt, filters: dict):
        if filters.get("collection_id") is not None:
            stmt = stmt.where(
                IndexLog.media_id.in_(
                    select(MediaCollection.media_id).where(
                        MediaCollection.collection_id == filters["collection_id"]
                    )
                )
            )
        if filters.get("project_id") is not None:
            project_media_stmt = (
                select(MediaCollection.media_id)
                .join(
                    ProjectCollection,
                    ProjectCollection.collection_id == MediaCollection.collection_id,
                )
                .where(ProjectCollection.project_id == filters["project_id"])
            )
            stmt = stmt.where(IndexLog.media_id.in_(project_media_stmt))
        return stmt

    def _apply_visibility_filter(
        self,
        stmt,
        *,
        user_id: int,
        is_admin: bool,
        accessible_collection_ids: list[int] | None,
        accessible_collection_scopes: list[tuple[int, int]] | None = None,
    ):
        if is_admin:
            return stmt

        permissions_cond = IndexLog.user_id == user_id
        if accessible_collection_scopes:
            scope_conditions = [
                and_(
                    ProjectCollection.project_id == project_id,
                    MediaCollection.collection_id == collection_id,
                )
                for project_id, collection_id in accessible_collection_scopes
            ]
            collection_media_stmt = (
                select(MediaCollection.media_id)
                .join(ProjectCollection, ProjectCollection.collection_id == MediaCollection.collection_id)
                .where(or_(*scope_conditions))
            )
            permissions_cond = or_(
                permissions_cond,
                IndexLog.media_id.in_(collection_media_stmt)
            )
        elif accessible_collection_ids:
            collection_media_stmt = select(MediaCollection.media_id).where(
                MediaCollection.collection_id.in_(accessible_collection_ids)
            )
            permissions_cond = or_(
                permissions_cond,
                IndexLog.media_id.in_(collection_media_stmt)
            )
        return stmt.where(permissions_cond)

    def _build_list_query(
        self,
        user_id: int,
        is_admin: bool,
        accessible_collection_ids: list[int] | None,
        accessible_collection_scopes: list[tuple[int, int]] | None = None,
        filters: dict | None = None,
    ):
        """Build the base select statement with permission and column filters.

        Sorting is handled by the caller (get_logs_page) via apply_ordering.
        """
        if filters is None:
            filters = {}

        stmt = (
            select(
                IndexLog,
                Media.name.label("media_name"),
                User.name.label("user_name"),
                IndexType.name.label("index_name")
            )
            .outerjoin(Media, IndexLog.media_id == Media.media_id)
            .outerjoin(User, IndexLog.user_id == User.user_id)
            .outerjoin(IndexType, IndexLog.index_id == IndexType.index_id)
        )

        stmt = self._apply_visibility_filter(
            stmt,
            user_id=user_id,
            is_admin=is_admin,
            accessible_collection_ids=accessible_collection_ids,
            accessible_collection_scopes=accessible_collection_scopes,
        )

        # Standard declarative filters
        stmt = apply_filters(stmt, filters, _FILTER_SPECS)
        stmt = self._apply_numeric_range(stmt, filters, "min_t", IndexLog.min_time)
        stmt = self._apply_numeric_range(stmt, filters, "max_t", IndexLog.max_time)
        stmt = self._apply_numeric_range(stmt, filters, "min_f", IndexLog.min_frequency)
        stmt = self._apply_numeric_range(stmt, filters, "max_f", IndexLog.max_frequency)
        stmt = self._apply_numeric_range(stmt, filters, "var_value", IndexLog.variable_value)
        stmt = self._apply_scope_filter(stmt, filters)
        return stmt

    def get_logs_page(
        self,
        session: Session,
        user_id: int,
        is_admin: bool,
        accessible_collection_ids: list[int] | None,
        accessible_collection_scopes: list[tuple[int, int]] | None = None,
        page: int = 1,
        page_size: int = 15,
        order_by: str | None = None,
        order_dir: str = "asc",
        **filters,
    ):
        """Get a paginated list of index logs matching the filters."""
        stmt = self._build_list_query(
            user_id=user_id,
            is_admin=is_admin,
            accessible_collection_ids=accessible_collection_ids,
            accessible_collection_scopes=accessible_collection_scopes,
            filters=filters,
        )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = session.exec(count_stmt).one()
        if total == 0:
            return [], 0

        stmt = apply_ordering(stmt, order_by, order_dir, _SORT_FIELDS, IndexLog.log_id)
        stmt = apply_pagination(stmt, page, page_size)

        results = session.exec(stmt).all()

        final_results = []
        for log, m_name, u_name, i_name in results:
            log_data = log.model_dump()
            log_data["media_name"] = m_name
            log_data["user_name"] = u_name
            log_data["index_name"] = i_name
            final_results.append(log_data)

        return final_results, total

index_log_repository = IndexLogRepository()
