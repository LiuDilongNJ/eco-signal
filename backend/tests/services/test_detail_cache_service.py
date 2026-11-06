"""Capacity, process coordination, and response lifetime tests."""

import asyncio
import json
import multiprocessing
import os
import time
from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
import soundfile as sf
from fastapi import HTTPException

from app.core.config import Settings, settings
from app.models import FileUpload
from app.services import detail_cache_service as cache
from app.services import media_service
from app.services.detail_asset_response import DetailAssetFileResponse
from app.services.storage_service import (
    StorageStatusUnavailableError,
    get_storage_status,
)
from app.workers import rabbitmq_worker
from app.workers.tasks import maintenance
from tests.utils.user import create_random_user


@pytest.fixture
def cache_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "DETAIL_CACHE_MAX_BYTES", 32768)
    monkeypatch.setattr(settings, "DETAIL_CACHE_TARGET_BYTES", 16384)
    return tmp_path


def make_bundle(name, *, age=0, size=4096):
    bundle = cache.root() / "1" / name
    bundle.mkdir(parents=True)
    (bundle / "audio.wav").write_bytes(b"x" * size)
    access = bundle / ".last_access"
    access.touch()
    os.utime(access, (time.time() - age, time.time() - age))
    return bundle


def test_cleanup_expires_without_requests(cache_root):
    old = make_bundle("old", age=settings.DETAIL_CACHE_TTL_SECONDS + 10)
    fresh = make_bundle("fresh")
    result = cache.cleanup()
    assert not old.exists() and fresh.exists()
    assert result.deleted == 1 and result.freed_bytes > 0
    assert cache.read_snapshot()["last_success"] > 0


def test_cleanup_evicts_oldest_to_low_watermark(cache_root):
    bundles = [make_bundle(str(i), age=100 - i, size=8192) for i in range(5)]
    result = cache.cleanup()
    assert result.bytes_used <= settings.DETAIL_CACHE_TARGET_BYTES
    assert not bundles[0].exists() and bundles[-1].exists()


def test_cleanup_preserves_readers_and_lock_files(cache_root):
    bundle = make_bundle("active", age=50000)
    with cache.bundle_lock(bundle.name, shared=True):
        result = cache.cleanup()
    assert bundle.exists() and result.skipped_locked == 1
    assert (cache.root() / ".locks").is_dir()
    assert cache.cleanup().deleted == 1


def test_cleanup_skips_when_builder_is_active(cache_root):
    with cache.build_lock():
        assert cache.cleanup().skipped_locked == 1


def test_cleanup_ignores_symlinks(cache_root):
    external = cache_root / "outside"
    external.mkdir()
    (external / "keep").write_text("data")
    cache.root().mkdir(parents=True)
    (cache.root() / "linked").symlink_to(external, target_is_directory=True)
    parent = cache.root() / "2"
    parent.mkdir()
    (parent / "linked").symlink_to(external, target_is_directory=True)
    assert cache.cleanup().deleted == 0
    assert (external / "keep").read_text() == "data"


def test_size_does_not_follow_nested_symlinks(cache_root):
    bundle = make_bundle("size")
    external = cache_root / "external"
    external.write_bytes(b"x" * 100000)
    (bundle / "link").symlink_to(external)
    assert cache.size_bytes(bundle) < 100000


def test_cleanup_continues_after_delete_failure(cache_root, monkeypatch):
    first = make_bundle("failed", age=60000)
    second = make_bundle("good", age=50000)
    original = cache.shutil.rmtree

    def remove(path):
        if path == first:
            raise PermissionError("denied")
        original(path)

    monkeypatch.setattr(cache.shutil, "rmtree", remove)
    result = cache.cleanup()
    assert result.errors == 1 and result.deleted == 1
    assert first.exists() and not second.exists()


def test_cleanup_rechecks_recent_access(cache_root, monkeypatch):
    bundle = make_bundle("refreshed", age=50000)
    original = cache.accessed_at
    calls = 0

    def access(path):
        nonlocal calls
        calls += 1
        return original(path) if calls == 1 else time.time()

    monkeypatch.setattr(cache, "accessed_at", access)
    assert cache.cleanup().deleted == 0
    assert bundle.exists()


@pytest.mark.parametrize(
    "required,reason", [(40000, "request_too_large"), (30000, "capacity")]
)
def test_admission_rejects_without_deleting_locked_data(cache_root, required, reason):
    bundle = make_bundle("active", size=8192)
    with (
        cache.bundle_lock(bundle.name, shared=True),
        pytest.raises(HTTPException) as exc,
    ):
        cache.admit(required, exclude=cache.root() / "new")
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == f"detail_cache_{reason}"
    assert bundle.exists()


def test_admission_reclaims_then_checks_space(cache_root, monkeypatch):
    make_bundle("old", size=20000)
    monkeypatch.setattr(cache, "ensure_disk_space", MagicMock())
    cache.admit(24000, exclude=cache.root() / "new")
    cache.ensure_disk_space.assert_called_once_with(24000)


def test_admission_rejects_failed_capacity_scan(cache_root, monkeypatch):
    monkeypatch.setattr(cache, "_cleanup", MagicMock(side_effect=OSError("denied")))
    with pytest.raises(HTTPException) as exc:
        cache.admit(1, exclude=cache.root() / "new")
    assert exc.value.detail["code"] == "detail_cache_capacity_unavailable"


def test_admission_rejects_cleanup_errors(cache_root, monkeypatch):
    monkeypatch.setattr(cache, "_cleanup", lambda **_: cache.CleanupResult(errors=1))
    with pytest.raises(HTTPException):
        cache.admit(1, exclude=cache.root() / "new")


@pytest.mark.parametrize(
    "free,required,allowed", [(600, 0, True), (600, 200, False), (50, 0, False)]
)
def test_disk_reserve_uses_bytes_and_percentage(
    cache_root, monkeypatch, free, required, allowed
):
    monkeypatch.setattr(settings, "DETAIL_CACHE_MIN_FREE_BYTES", 500)
    monkeypatch.setattr(settings, "DETAIL_CACHE_MIN_FREE_PERCENT", 10)
    monkeypatch.setattr(
        cache.shutil, "disk_usage", lambda _: SimpleNamespace(total=1000, free=free)
    )
    if allowed:
        cache.ensure_disk_space(required)
    else:
        with pytest.raises(HTTPException):
            cache.ensure_disk_space(required)


def test_read_scope_transfers_and_releases_lease(cache_root):
    stack = ExitStack()
    with cache.read_scope(stack), ExitStack() as lease:
        lease.enter_context(cache.bundle_lock("bundle", shared=True))
        cache.retain_read_lock(lease)
    with pytest.raises(cache.CacheLockTimeout):
        with cache.bundle_lock("bundle", timeout=0):
            pass
    stack.close()
    with cache.bundle_lock("bundle", timeout=0):
        pass


def test_owned_read_scope_releases_on_error(cache_root):
    with pytest.raises(ValueError):
        with cache.read_scope(), ExitStack() as lease:
            lease.enter_context(cache.bundle_lock("bundle", shared=True))
            cache.retain_read_lock(lease)
            raise ValueError("failed render")
    with cache.bundle_lock("bundle", timeout=0):
        pass


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure", [None, RuntimeError("transport failed"), asyncio.CancelledError()]
)
async def test_response_always_releases_read_lease(cache_root, monkeypatch, failure):
    stack = ExitStack()
    stack.enter_context(cache.bundle_lock("response", shared=True))

    async def send_response(*_args):
        if failure is not None:
            raise failure

    monkeypatch.setattr("starlette.responses.FileResponse.__call__", send_response)
    response = DetailAssetFileResponse("unused", leases=stack)
    if failure is None:
        await response({}, None, None)
    else:
        with pytest.raises(type(failure)):
            await response({}, None, None)
    with cache.bundle_lock("response", timeout=0):
        pass


def _hold_lock(root_path, ready):
    settings.MEDIA_ROOT = root_path
    with cache.build_lock():
        ready.set()
        time.sleep(60)


def test_process_exit_releases_file_lock(cache_root):
    ctx = multiprocessing.get_context("fork")
    ready = ctx.Event()
    process = ctx.Process(target=_hold_lock, args=(str(cache_root), ready))
    process.start()
    try:
        assert ready.wait(5)
        with pytest.raises(cache.CacheLockTimeout):
            with cache.build_lock(timeout=0):
                pass
    finally:
        process.terminate()
        process.join(5)
    with cache.build_lock(timeout=0):
        pass


def _build_in_process(root_path, start, result):
    settings.MEDIA_ROOT = root_path
    source = Path(root_path) / "source.wav"
    media_service.media_repository.get_with_detail_relations = (
        lambda *_: SimpleNamespace(media_id=1, filename="source.wav")
    )
    media_service._get_audio_path_for_media = lambda _: source
    original = media_service._rebuild_detail_selection

    def rebuild(**kwargs):
        active = Path(root_path) / "active"
        fd = os.open(active, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            with (Path(root_path) / "builds").open("a") as log:
                log.write("build\n")
            time.sleep(0.1)
            return original(**kwargs)
        finally:
            os.close(fd)
            active.unlink()

    media_service._rebuild_detail_selection = rebuild
    try:
        with cache.read_scope():
            bundle = media_service.get_or_create_detail_asset_bundle(
                None,
                1,
                start_time=start,
                end_time=0.5,
                min_freq=1,
                max_freq=None,
                channel=0,
                filter_enabled=False,
                fft_size=512,
            )
            result.put(bundle.playback_audio_path.exists())
    except Exception as exc:
        result.put(str(exc))


@pytest.mark.parametrize("starts,builds", [([0, 0], 1), ([0, 0.1], 2)])
def test_builds_coordinate_between_processes(cache_root, monkeypatch, starts, builds):
    monkeypatch.setattr(settings, "DETAIL_CACHE_MAX_BYTES", 10 * 1024**3)
    monkeypatch.setattr(settings, "DETAIL_CACHE_TARGET_BYTES", 8 * 1024**3)
    sf.write(cache_root / "source.wav", np.zeros(48000), 48000)
    ctx = multiprocessing.get_context("fork")
    results = ctx.Queue()
    processes = [
        ctx.Process(target=_build_in_process, args=(str(cache_root), start, results))
        for start in starts
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(15)
        if process.is_alive():
            process.terminate()
            process.join()
        assert process.exitcode == 0
    assert [results.get(timeout=2) for _ in processes] == [True, True]
    assert len((cache_root / "builds").read_text().splitlines()) == builds


def test_pending_cleanup_protects_references_and_writers(cache_root, monkeypatch):
    pending = cache_root / "tmp/pending/1"
    pending.mkdir(parents=True)
    for name in ("orphan", "referenced", "writing", "fresh"):
        file = pending / name
        file.write_bytes(b"audio")
        if name != "fresh":
            os.utime(file, (0, 0))
    (pending / "link").symlink_to(pending / "orphan")
    monkeypatch.setattr(maintenance, "Session", MagicMock())
    monkeypatch.setattr(
        maintenance.file_upload_repository,
        "is_path_referenced",
        lambda _, path: path.endswith("referenced"),
    )
    with cache.pending_lock(pending / "writing"):
        result = maintenance._cleanup_pending_files()
    assert result["deleted"] == 1 and result["skipped_locked"] == 1
    assert not (pending / "orphan").exists()
    assert (pending / "referenced").exists() and (pending / "writing").exists()


@pytest.mark.anyio
async def test_database_failure_does_not_prevent_cache_cleanup(cache_root, monkeypatch):
    old = make_bundle("old", age=50000)
    pending = cache_root / "tmp/pending/1"
    pending.mkdir(parents=True)
    (pending / "orphan").write_text("audio")
    os.utime(pending / "orphan", (0, 0))
    monkeypatch.setattr(
        maintenance, "Session", MagicMock(side_effect=RuntimeError("db unavailable"))
    )
    result = await maintenance.cleanup_audio_assets({})
    assert result["detail"]["deleted"] == 1 and result["pending"]["errors"] == 1
    assert not old.exists() and (pending / "orphan").exists()


def test_snapshot_failures_and_corruption(cache_root, monkeypatch):
    cache.root().mkdir(parents=True)
    (cache.root() / ".stats.json").write_text("invalid")
    assert cache.read_snapshot() == {}
    original = Path.write_text

    def fail(path, *args, **kwargs):
        if path.name == ".stats.tmp":
            raise PermissionError("denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail)
    cache.publish_snapshot(cache.CleanupResult(errors=1))
    assert cache.read_snapshot() == {}


def test_empty_cache_publishes_successful_maintenance(cache_root):
    assert cache.cleanup().deleted == 0
    assert cache.read_snapshot()["last_success"] > 0


def test_cleanup_reports_unsafe_root(cache_root):
    external = cache_root / "external"
    external.mkdir()
    cache.root().parent.mkdir(parents=True)
    cache.root().symlink_to(external, target_is_directory=True)
    assert cache.cleanup().errors == 1
    assert not (external / ".stats.json").exists()


def test_storage_invalid_capacity_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        cache.shutil, "disk_usage", lambda _: SimpleNamespace(total=0, free=0)
    )
    with pytest.raises(StorageStatusUnavailableError):
        get_storage_status()


@pytest.mark.parametrize(
    "updates",
    [
        {"DETAIL_CACHE_MAX_BYTES": 0},
        {"DETAIL_CACHE_TARGET_BYTES": 0},
        {"DETAIL_CACHE_TTL_SECONDS": -1},
        {"DETAIL_CACHE_CLEANUP_SECONDS": 0},
        {"DETAIL_CACHE_MIN_FREE_BYTES": 0},
        {"DETAIL_CACHE_MIN_FREE_PERCENT": 100},
        {"PENDING_FILE_TTL_SECONDS": 0},
        {"DETAIL_CACHE_TARGET_BYTES": 11 * 1024**3},
    ],
)
def test_cache_configuration_rejects_invalid_values(updates):
    values = settings.model_dump()
    values.update(updates)
    with pytest.raises(ValueError):
        Settings(**values)


@pytest.mark.parametrize("status", [1, 2, 3, 4, 5])
def test_pending_cleanup_respects_database_reference_for_all_states(
    cache_root, monkeypatch, db, status
):
    user = create_random_user(db)
    pending = cache_root / "tmp/pending" / str(user.user_id)
    pending.mkdir(parents=True)
    file = pending / "keep.wav"
    file.write_text("audio")
    os.utime(file, (0, 0))
    relative = file.relative_to(cache_root).as_posix()
    record = FileUpload(
        path=relative,
        filename=file.name,
        name=file.name,
        status=status,
        directory=0,
        uploader_id=user.user_id,
    )
    db.add(record)
    db.flush()
    monkeypatch.setattr(maintenance, "Session", lambda _: nullcontext(db))
    assert maintenance._cleanup_pending_files()["deleted"] == 0
    assert file.exists()


@pytest.mark.anyio
async def test_periodic_cleanup_starts_immediately_and_recovers(monkeypatch):
    cleanup = AsyncMock(side_effect=[RuntimeError("temporary"), {}])
    calls = 0

    async def sleep(seconds):
        nonlocal calls
        assert seconds == settings.DETAIL_CACHE_CLEANUP_SECONDS
        calls += 1
        if calls == 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(rabbitmq_worker, "cleanup_audio_assets", cleanup)
    monkeypatch.setattr(rabbitmq_worker.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await rabbitmq_worker._run_audio_maintenance()
    assert cleanup.await_count == 2


@pytest.fixture
def audio_bundle(cache_root, monkeypatch):
    monkeypatch.setattr(settings, "DETAIL_CACHE_MAX_BYTES", 10 * 1024**3)
    monkeypatch.setattr(settings, "DETAIL_CACHE_TARGET_BYTES", 8 * 1024**3)
    source = cache_root / "source.wav"
    sf.write(source, np.zeros(48000), 48000)
    monkeypatch.setattr(
        media_service.media_repository,
        "get_with_detail_relations",
        lambda *_: SimpleNamespace(media_id=1, filename="source.wav"),
    )
    monkeypatch.setattr(media_service, "_get_audio_path_for_media", lambda _: source)

    def build(**overrides):
        args = dict(
            start_time=0,
            end_time=0.5,
            min_freq=1,
            max_freq=None,
            channel=0,
            filter_enabled=False,
            fft_size=512,
        )
        args.update(overrides)
        return media_service.get_or_create_detail_asset_bundle(None, 1, **args)

    return build


def test_cache_hit_remains_readable_below_disk_reserve(audio_bundle, monkeypatch):
    first = audio_bundle()
    monkeypatch.setattr(
        cache, "ensure_disk_space", lambda *_: cache.reject("low_space")
    )
    second = audio_bundle(fft_size=1024, channel=1, min_freq=100, max_freq=1000)
    assert second.key == first.key
    assert (
        second.playback_audio_path.read_bytes()
        == first.playback_audio_path.read_bytes()
    )
    with pytest.raises(HTTPException) as error:
        audio_bundle(start_time=0.1)
    assert error.value.detail["code"] == "detail_cache_low_space"


def test_filtered_frequency_changes_create_distinct_audio(audio_bundle):
    first = audio_bundle(filter_enabled=True, min_freq=100, max_freq=1000)
    second = audio_bundle(filter_enabled=True, min_freq=200, max_freq=1000)
    assert first.key != second.key
    assert first.source_audio_path.exists() and second.source_audio_path.exists()


def test_failed_stage_preserves_old_cache_and_removes_temporary_files(
    audio_bundle, monkeypatch
):
    first = audio_bundle()
    path = first.source_audio_path
    before = path.read_bytes()
    manifest = path.parent / "manifest.json"
    old_manifest = manifest.read_bytes()
    # An invalidated manifest forces replacement of otherwise valid audio.
    metadata = json.loads(old_manifest)
    metadata["version"] = 0
    manifest.write_text(json.dumps(metadata))
    monkeypatch.setattr(
        media_service, "_run_sox", MagicMock(side_effect=OSError(28, "No space left"))
    )
    with pytest.raises(HTTPException) as error:
        audio_bundle()
    assert error.value.status_code == 503
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".*.tmp.*"))


@pytest.mark.anyio
@pytest.mark.parametrize("transport_error", [False, True])
async def test_real_range_response_holds_lease_until_body_finishes(
    cache_root, transport_error
):
    path = cache_root / "audio.ogg"
    path.write_bytes(b"0123456789")
    stack = ExitStack()
    stack.enter_context(cache.bundle_lock("response", shared=True))
    response = DetailAssetFileResponse(str(path), leases=stack)
    messages = []

    async def send(message):
        with pytest.raises(cache.CacheLockTimeout):
            with cache.bundle_lock("response", timeout=0):
                pass
        messages.append(message)
        if transport_error and message["type"] == "http.response.body":
            raise RuntimeError("disconnected")

    scope = {"type": "http", "method": "GET", "headers": [(b"range", b"bytes=2-5")]}
    if transport_error:
        with pytest.raises(RuntimeError, match="disconnected"):
            await response(scope, None, send)
    else:
        await response(scope, None, send)
        assert messages[0]["status"] == 206
        assert messages[-1]["body"] == b"2345"
    with cache.bundle_lock("response", timeout=0):
        pass


def test_pending_lock_metadata_is_bounded_under_upload_churn(cache_root):
    for index in range(2048):
        with cache.pending_lock(cache_root / "tmp/pending/1" / str(index)):
            pass
    assert len(list((cache_root / "tmp/.pending-locks").iterdir())) <= 1024
