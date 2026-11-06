"""Capacity reporting for the container root and the media filesystem."""

import shutil
from datetime import UTC, datetime

from app.media_paths import media_root
from app.schemas.storage import FilesystemStatus, StorageHealth, StorageStatus

WARNING_PERCENT = 80.0
CRITICAL_PERCENT = 90.0


class StorageStatusUnavailableError(RuntimeError):
    pass


def _storage_status(used_percent: float) -> StorageHealth:
    if used_percent >= CRITICAL_PERCENT:
        return "critical"
    if used_percent >= WARNING_PERCENT:
        return "warning"
    return "healthy"


def get_storage_status() -> StorageStatus:
    filesystems = []
    for scope, path in (("container_root", "/"), ("media", str(media_root()))):
        try:
            usage = shutil.disk_usage(path)
            if usage.total <= 0 or not 0 <= usage.free <= usage.total:
                raise OSError("Invalid filesystem capacity")
            used = usage.total - usage.free
            percent = used / usage.total * 100
            filesystems.append(
                FilesystemStatus(
                    scope=scope,
                    path=path,
                    available=True,
                    total_bytes=usage.total,
                    used_bytes=used,
                    free_bytes=usage.free,
                    used_percent=round(percent, 1),
                    status=_storage_status(percent),
                )
            )
        except OSError:
            filesystems.append(
                FilesystemStatus(
                    scope=scope, path=path, available=False, status="unavailable"
                )
            )
    if not any(item.available for item in filesystems):
        raise StorageStatusUnavailableError("Storage status is unavailable")
    severity = {"healthy": 0, "unavailable": 1, "warning": 2, "critical": 3}
    return StorageStatus(
        checked_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        status=max((item.status for item in filesystems), key=severity.__getitem__),
        filesystems=filesystems,
    )
