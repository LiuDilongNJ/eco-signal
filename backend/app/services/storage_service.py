"""Container filesystem storage status helpers."""

import shutil
from typing import Literal

from app.schemas.storage import StorageStatus

_STORAGE_PATH = "/"
_WARNING_PERCENT = 70.0
_CRITICAL_PERCENT = 85.0


class StorageStatusUnavailableError(RuntimeError):
    """Raised when the container filesystem capacity cannot be read."""


def _storage_status(used_percent: float) -> Literal["healthy", "warning", "critical"]:
    if used_percent >= _CRITICAL_PERCENT:
        return "critical"
    if used_percent >= _WARNING_PERCENT:
        return "warning"
    return "healthy"


def get_storage_status() -> StorageStatus:
    """Return capacity for the backend container root filesystem."""
    try:
        usage = shutil.disk_usage(_STORAGE_PATH)
    except OSError as exc:
        raise StorageStatusUnavailableError("Container storage status is unavailable") from exc

    if usage.total <= 0:
        raise StorageStatusUnavailableError("Container storage status is unavailable")

    free_bytes = usage.free
    used_bytes = usage.total - free_bytes
    used_percent = round((used_bytes / usage.total) * 100, 1)

    return StorageStatus(
        path=_STORAGE_PATH,
        total_bytes=usage.total,
        used_bytes=used_bytes,
        free_bytes=free_bytes,
        used_percent=used_percent,
        status=_storage_status(used_percent),
    )
