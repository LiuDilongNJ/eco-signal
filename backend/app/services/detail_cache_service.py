"""Filesystem coordination and capacity policy for disposable audio assets."""

import errno
import fcntl
import hashlib
import json
import logging
import os
import shutil
import stat
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import HTTPException
from prometheus_client import CollectorRegistry, Counter

from app.core.config import settings
from app.media_paths import media_root

logger = logging.getLogger(__name__)
METRIC_REGISTRY = CollectorRegistry()
_metric_registry = None if os.getenv("PROMETHEUS_MULTIPROC_DIR") else METRIC_REGISTRY
REMOVED = Counter(
    "ecosignal_detail_cache_removed_total",
    "Removed cache bundles",
    registry=_metric_registry,
)
FREED = Counter(
    "ecosignal_detail_cache_freed_bytes_total",
    "Released cache bytes",
    registry=_metric_registry,
)
ERRORS = Counter(
    "ecosignal_detail_cache_cleanup_errors_total",
    "Cache cleanup errors",
    registry=_metric_registry,
)
SKIPPED = Counter(
    "ecosignal_detail_cache_locked_total",
    "Locked cache bundles skipped",
    registry=_metric_registry,
)
REJECTED = Counter(
    "ecosignal_detail_cache_rejected_total",
    "Rejected cache builds",
    ("reason",),
    registry=_metric_registry,
)
_read_stack: ContextVar[ExitStack | None] = ContextVar(
    "detail_asset_read_stack", default=None
)


class CacheLockTimeout(TimeoutError):
    pass


def root() -> Path:
    return media_root() / "tmp" / "detail"


def safe_directory(path: Path, boundary: Path) -> bool:
    try:
        return (
            not path.is_symlink()
            and path.is_dir()
            and path.resolve().is_relative_to(boundary.resolve())
        )
    except OSError:
        return False


class FileLock:
    def __init__(self, path: Path, *, shared: bool = False, timeout: float = 60.0):
        self.path = path
        self.shared = shared
        self.timeout = timeout
        self.file = None
        self.waited = 0.0

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.file = os.fdopen(fd, "a+b")
        started = time.monotonic()
        try:
            while True:
                try:
                    fcntl.flock(
                        self.file.fileno(),
                        (fcntl.LOCK_SH if self.shared else fcntl.LOCK_EX)
                        | fcntl.LOCK_NB,
                    )
                    self.waited = time.monotonic() - started
                    return self
                except BlockingIOError:
                    if time.monotonic() - started >= self.timeout:
                        raise CacheLockTimeout(str(self.path))
                    time.sleep(0.05)
        except BaseException:
            self.close()
            raise

    def downgrade(self) -> None:
        fcntl.flock(self.file.fileno(), fcntl.LOCK_SH)

    def close(self) -> None:
        if self.file is not None:
            self.file.close()
            self.file = None

    def __exit__(self, *_args):
        self.close()


def bundle_lock(key: str, *, shared: bool = False, timeout: float = 60.0) -> FileLock:
    shard = int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) % 1024
    return FileLock(
        root() / ".locks" / f"{shard:04d}.lock", shared=shared, timeout=timeout
    )


def build_lock(*, timeout: float = 60.0) -> FileLock:
    return FileLock(root() / ".locks" / "build.lock", timeout=timeout)


@contextmanager
def read_scope(stack: ExitStack | None = None) -> Iterator[None]:
    owned = stack is None
    stack = stack if stack is not None else ExitStack()
    token = _read_stack.set(stack)
    try:
        yield
    finally:
        _read_stack.reset(token)
        if owned:
            stack.close()


def retain_read_lock(stack: ExitStack) -> None:
    owner = _read_stack.get()
    if owner is not None:
        owner.callback(stack.pop_all().close)


def pending_lock(path: Path, *, timeout: float = 60.0) -> FileLock:
    key = int(hashlib.sha256(str(path.absolute()).encode()).hexdigest()[:8], 16) % 1024
    return FileLock(
        media_root() / "tmp" / ".pending-locks" / f"{key:04d}.lock", timeout=timeout
    )


def accessed_at(path: Path) -> float:
    for candidate in (path / ".last_access", path / "manifest.json", path):
        try:
            return candidate.lstat().st_mtime
        except FileNotFoundError:
            continue
    return 0.0


def _raise_scan_error(error: OSError) -> None:
    raise error


def size_bytes(path: Path) -> int:
    size = 0
    for base, dirs, files in os.walk(
        path, followlinks=False, onerror=_raise_scan_error
    ):
        dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink()]
        for name in files:
            try:
                item = (Path(base) / name).lstat()
                if stat.S_ISREG(item.st_mode):
                    size += max(item.st_size, item.st_blocks * 512)
            except FileNotFoundError:
                continue
    return size


@dataclass
class CleanupResult:
    deleted: int = 0
    freed_bytes: int = 0
    skipped_locked: int = 0
    errors: int = 0
    bytes_used: int = 0
    bundles: int = 0


def reject(reason: str) -> None:
    REJECTED.labels(reason=reason).inc()
    raise HTTPException(
        503,
        detail={
            "code": f"detail_cache_{reason}",
            "message": "Audio processing is temporarily unavailable",
        },
        headers={"Retry-After": "60"},
    )


def ensure_disk_space(required: int = 0) -> None:
    usage = shutil.disk_usage(media_root())
    reserve = max(
        settings.DETAIL_CACHE_MIN_FREE_BYTES,
        int(usage.total * settings.DETAIL_CACHE_MIN_FREE_PERCENT / 100),
    )
    if usage.free - required < reserve:
        reject("low_space")


def _cleanup(*, required: int = 0, exclude: Path | None = None) -> CleanupResult:
    result = CleanupResult()
    cache_root = root()
    if not cache_root.exists():
        cache_root.mkdir(parents=True)
    if not safe_directory(cache_root, media_root()):
        raise OSError("Unsafe detail cache directory")
    entries = []
    for media_dir in cache_root.iterdir():
        if media_dir.name.startswith(".") or not safe_directory(media_dir, cache_root):
            continue
        try:
            for bundle in media_dir.iterdir():
                if safe_directory(bundle, cache_root):
                    entries.append((accessed_at(bundle), bundle, size_bytes(bundle)))
        except OSError:
            result.errors += 1
            logger.exception("Could not scan audio cache directory: %s", media_dir)
    result.bytes_used = sum(item[2] for item in entries)
    result.bundles = len(entries)
    over_budget = result.bytes_used + required > settings.DETAIL_CACHE_MAX_BYTES
    target = min(
        settings.DETAIL_CACHE_TARGET_BYTES, settings.DETAIL_CACHE_MAX_BYTES - required
    )
    cutoff = time.time() - settings.DETAIL_CACHE_TTL_SECONDS
    for accessed, bundle, _size in sorted(
        entries, key=lambda item: (item[0], str(item[1]))
    ):
        if bundle == exclude:
            continue
        expired = accessed < cutoff
        if not expired and (not over_budget or result.bytes_used <= target):
            continue
        try:
            with bundle_lock(bundle.name, timeout=0):
                if not safe_directory(bundle, cache_root):
                    continue
                current_access = accessed_at(bundle)
                if current_access != accessed or (expired and current_access >= cutoff):
                    continue
                before = size_bytes(bundle)
                try:
                    shutil.rmtree(bundle)
                finally:
                    remaining = size_bytes(bundle) if bundle.exists() else 0
                    freed = max(0, before - remaining)
                    result.bytes_used -= freed
                    result.freed_bytes += freed
                    if remaining:
                        os.utime(bundle, (accessed, accessed), follow_symlinks=False)
                result.deleted += 1
                result.bundles -= 1
        except CacheLockTimeout:
            result.skipped_locked += 1
        except OSError:
            result.errors += 1
            logger.exception("Could not remove audio cache bundle: %s", bundle)
    for media_dir in cache_root.iterdir():
        if media_dir.name.startswith(".") or not safe_directory(media_dir, cache_root):
            continue
        try:
            media_dir.rmdir()
        except OSError as exc:
            if exc.errno not in (errno.ENOTEMPTY, errno.ENOENT):
                result.errors += 1
                logger.warning(
                    "Could not remove empty audio cache directory: %s",
                    media_dir,
                    exc_info=True,
                )
    REMOVED.inc(result.deleted)
    FREED.inc(result.freed_bytes)
    SKIPPED.inc(result.skipped_locked)
    ERRORS.inc(result.errors)
    logger.info("Audio cache cleanup completed: %s", asdict(result))
    publish_snapshot(result)
    return result


def publish_snapshot(result: CleanupResult) -> None:
    snapshot = root() / ".stats.json"
    data = asdict(result) | {"checked_at": time.time()}
    if result.errors == 0:
        data["last_success"] = data["checked_at"]
    else:
        data["last_success"] = read_snapshot().get("last_success", 0)
    temporary = snapshot.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(data), encoding="utf-8")
        temporary.replace(snapshot)
    except OSError:
        logger.warning("Could not publish audio cache statistics", exc_info=True)


def read_snapshot() -> dict:
    try:
        snapshot = json.loads((root() / ".stats.json").read_text(encoding="utf-8"))
        return snapshot if isinstance(snapshot, dict) else {}
    except (OSError, ValueError):
        return {}


def cleanup() -> CleanupResult:
    try:
        with build_lock(timeout=0):
            return _cleanup()
    except CacheLockTimeout:
        logger.info("Audio cache cleanup skipped: build or maintenance in progress")
        return CleanupResult(skipped_locked=1)
    except OSError:
        ERRORS.inc()
        logger.exception("Audio cache cleanup unavailable")
        return CleanupResult(errors=1)


def admit(required: int, *, exclude: Path) -> None:
    if required > settings.DETAIL_CACHE_MAX_BYTES:
        reject("request_too_large")
    try:
        result = _cleanup(required=required, exclude=exclude)
    except OSError:
        logger.exception("Could not assess audio cache capacity")
        reject("capacity_unavailable")
    if result.errors:
        reject("capacity_unavailable")
    if result.bytes_used + required > settings.DETAIL_CACHE_MAX_BYTES:
        reject("capacity")
    ensure_disk_space(required)


def record_build(bundle: Path) -> None:
    _cleanup(exclude=bundle)
