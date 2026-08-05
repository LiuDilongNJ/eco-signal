"""
Operation log service.
"""
from typing import Any, Optional

from sqlmodel import Session

from app.models.operation_log import OperationLog
from app.repositories.operation_log_repository import operation_log_repository


class OperationLogService:
    """Service for managing operation logs."""

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
        """Get operation logs."""
        return operation_log_repository.get_logs(
            session,
            filters=filters,
            page=page,
            page_size=page_size,
            order_by=order_by,
            order_dir=order_dir,
        )
        
    def log_operation(
        self,
        session: Session,
        *,
        action: str,
        resource_type: str,
        user_id: Optional[int] = None,
        resource_id: Optional[str] = None,
        description: Optional[str] = None,
        req_ip: Optional[str] = None,
        req_endpoint: Optional[str] = None,
        payload: Optional[Any] = None,
        status_code: int = 200,
    ) -> OperationLog:
        """Create an operation log.
        
        This method is meant to be called in BackgroundTasks or directly.
        """
        log_obj = OperationLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            description=description,
            req_ip=req_ip,
            req_endpoint=req_endpoint,
            payload=payload,
            status_code=status_code,
        )
        session.add(log_obj)
        session.commit()
        session.refresh(log_obj)
        return log_obj


operation_log_service = OperationLogService()
