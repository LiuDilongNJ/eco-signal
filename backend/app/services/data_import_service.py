from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlmodel import Session

from app.models import Project, User
from app.schemas.data_import import (
    DataImportCreateRequest,
    DataImportCreateResponse,
    DataImportStatusResponse,
)
from app.services import permission_service

OFFLINE_IMPORT_CONTEXT_PREFIX = "offline-import"
OFFLINE_IMPORT_CONTEXT_TTL_SECONDS = 7 * 24 * 3600


def _now_string() -> str:
    return datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def _context_key(batch_id: str) -> str:
    return f"{OFFLINE_IMPORT_CONTEXT_PREFIX}:{batch_id}"


class DataImportService:
    """Business logic for offline import upload sessions stored in Redis."""

    async def create_upload_session(
        self,
        session: Session,
        redis: Redis,
        current_user: User,
        payload: DataImportCreateRequest,
    ) -> DataImportCreateResponse:
        project = session.get(Project, payload.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        if not permission_service.has_resource_permission(
            session,
            current_user,
            "project",
            "write",
            project_id=payload.project_id,
        ):
            raise HTTPException(
                status_code=403,
                detail="No project:write permission on target project",
            )

        batch_id = str(uuid.uuid4())
        now = _now_string()
        context = {
            "batch_id": batch_id,
            "project_id": payload.project_id,
            "uploader_id": current_user.user_id,
            "file_upload_id": None,
            "queue_id": None,
            "status": "uploading",
            "error": None,
            "summary_json": None,
            "cleanup_after": None,
            "creation_date": now,
            "update_date": now,
        }
        await redis.set(
            _context_key(batch_id),
            json.dumps(context, separators=(",", ":")),
            ex=OFFLINE_IMPORT_CONTEXT_TTL_SECONDS,
        )

        return DataImportCreateResponse(
            batch_id=batch_id,
            project_id=payload.project_id,
            status=context["status"],
        )

    async def get_status(
        self,
        session: Session,
        redis: Redis,
        current_user: User,
        batch_id: str,
    ) -> DataImportStatusResponse:
        context = await self.get_context(redis, batch_id)
        if context is None:
            raise HTTPException(status_code=404, detail="Data import not found")

        can_manage_project = permission_service.has_resource_permission(
            session,
            current_user,
            "project",
            "write",
            project_id=context["project_id"],
        )
        if not permission_service.is_admin(current_user) and current_user.user_id != context["uploader_id"] and not can_manage_project:
            raise HTTPException(status_code=403, detail="Access denied")

        return DataImportStatusResponse(**context)

    async def get_context(self, redis: Redis, batch_id: str) -> dict[str, Any] | None:
        raw = await redis.get(_context_key(batch_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    async def update_context(
        self,
        redis: Redis,
        batch_id: str,
        **updates: Any,
    ) -> dict[str, Any] | None:
        context = await self.get_context(redis, batch_id)
        if context is None:
            return None
        context.update(updates)
        context["update_date"] = _now_string()
        await redis.set(
            _context_key(batch_id),
            json.dumps(context, separators=(",", ":")),
            ex=OFFLINE_IMPORT_CONTEXT_TTL_SECONDS,
        )
        return context

    async def list_context_keys(self, redis: Redis) -> list[str]:
        keys = await redis.keys(f"{OFFLINE_IMPORT_CONTEXT_PREFIX}:*")
        normalized: list[str] = []
        for key in keys:
            normalized.append(key.decode("utf-8") if isinstance(key, bytes) else str(key))
        return normalized


data_import_service = DataImportService()
