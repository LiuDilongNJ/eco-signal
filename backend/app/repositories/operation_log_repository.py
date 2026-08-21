"""
Operation log repository.
"""
from typing import Optional

from sqlalchemy import String, cast, or_
from sqlmodel import Session, select

from app.models.operation_log import OperationLog
from app.models.user import User
from app.repositories.base import BaseRepository
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
    apply_pagination,
)
from app.schemas.operation_log import OperationLogCreate

_FILTER_SPECS: list[FilterSpec] = [
    ("log_id", OperationLog.log_id, FilterOp.EQ),
    ("user_id", OperationLog.user_id, FilterOp.EQ),
    ("action", OperationLog.action, FilterOp.LIKE),
    ("resource_type", OperationLog.resource_type, FilterOp.LIKE),
    ("username", User.username, FilterOp.LIKE),
    ("description", OperationLog.description, FilterOp.LIKE),
    ("date", OperationLog.creation_date, FilterOp.DATE_RANGE),
]

_SORT_FIELDS = {
    "log_id": OperationLog.log_id,
    "username": User.username,
    "creation_date": OperationLog.creation_date,
    "action": OperationLog.action,
    "resource_type": OperationLog.resource_type,
    "description": OperationLog.description,
    "status_code": OperationLog.status_code,
}


class OperationLogRepository(BaseRepository[OperationLog, OperationLogCreate, OperationLogCreate]):
    """Operation log repository implementation."""

    def __init__(self):
        super().__init__(OperationLog)

    def get_logs(
        self,
        session: Session,
        *,
        filters: Optional[dict] = None,
        page: int = 1,
        page_size: int = 20,
        order_by: str = "creation_date",
        order_dir: str = "desc",
    ) -> tuple[list[OperationLog], int]:
        """Get operation logs with filtering, sorting, and pagination."""
        stmt = select(self.model).outerjoin(User, User.user_id == self.model.user_id)

        if filters:
            stmt = apply_filters(stmt, filters, _FILTER_SPECS)

            if filters.get("status_code") not in (None, ""):
                stmt = stmt.where(cast(self.model.status_code, String).ilike(f"%{filters['status_code']}%"))
            
            # Special handling for search parameters if any
            if "search" in filters and filters["search"]:
                search_term = f"%{filters['search']}%"
                stmt = stmt.where(
                    or_(
                        self.model.action.ilike(search_term),
                        self.model.resource_type.ilike(search_term),
                        self.model.description.ilike(search_term),
                    )
                )

        stmt = apply_ordering(stmt, order_by, order_dir, _SORT_FIELDS, self.model.log_id)
        
        # Calculate total directly from the filtered statement (before pagination is applied)
        from sqlalchemy import func
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = session.exec(count_stmt).one()

        stmt = apply_pagination(stmt, page, page_size)
        items = session.exec(stmt).all()
        
        return list(items), total


operation_log_repository = OperationLogRepository()
