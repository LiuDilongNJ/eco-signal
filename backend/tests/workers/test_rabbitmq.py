import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.enums import QueueStatus, WorkerTaskType
from app.workers import rabbitmq_worker
from app.workers.exceptions import TaskRetryError
from app.workers.publisher import TaskPublisher
from app.workers.rabbitmq import (
    DEAD_ROUTING_KEY,
    HEADER_QUEUE_ID,
    HEADER_RETRY_COUNT,
    HEADER_TASK_LANE,
    TASK_ROUTING_KEY_ANALYSIS,
    TASK_ROUTING_KEY,
    TASK_RETRY_QUEUE,
)


class FakeExchange:
    def __init__(self):
        self.published = []

    async def publish(self, message, routing_key):
        self.published.append((message, routing_key))


class FakePublisherChannel:
    def __init__(self):
        self.exchange = FakeExchange()
        self.is_closed = False

    async def get_exchange(self, name, ensure=True):
        return self.exchange

    async def close(self):
        self.is_closed = True


class FakeWorkerChannel:
    def __init__(self):
        self.exchange = FakeExchange()
        self.default_exchange = FakeExchange()

    async def get_exchange(self, name, ensure=True):
        return self.exchange


class FakeMessage:
    def __init__(self, body: bytes, headers=None, *, redelivered=False):
        self.body = body
        self.headers = headers or {}
        self.redelivered = redelivered
        self.acked = False

    async def ack(self):
        self.acked = True


@pytest.mark.anyio
async def test_interactive_worker_runs_maintenance_and_cancels_schedules(monkeypatch):
    startup_sync = AsyncMock(return_value={"synced": 0})
    scheduled = []
    cancelled = []

    async def run_daily(hour, minute, func, name):
        scheduled.append((hour, minute, func, name))
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(name)
            raise

    async def consume(stop_event):
        await asyncio.sleep(0)
        stop_event.set()

    monkeypatch.setattr(rabbitmq_worker, "init_sentry", MagicMock())
    monkeypatch.setattr(rabbitmq_worker, "startup_sync_network_nodes", startup_sync)
    monkeypatch.setattr(rabbitmq_worker, "_run_daily", run_daily)
    monkeypatch.setattr(rabbitmq_worker, "_runs_maintenance", MagicMock(return_value=True))
    monkeypatch.setattr(rabbitmq_worker, "_consume", consume)

    await rabbitmq_worker.main()

    startup_sync.assert_awaited_once_with({})
    assert [name for _, _, _, name in scheduled] == [
        "sync_network_nodes",
        "cleanup_expired_chunks",
        "cleanup_expired_offline_imports",
        "cleanup_expired_collection_bundle_exports",
    ]
    assert cancelled == [
        "sync_network_nodes",
        "cleanup_expired_chunks",
        "cleanup_expired_offline_imports",
        "cleanup_expired_collection_bundle_exports",
    ]


@pytest.mark.anyio
async def test_analysis_worker_does_not_start_maintenance(monkeypatch):
    start_maintenance = AsyncMock()

    async def consume(stop_event):
        stop_event.set()

    monkeypatch.setattr(rabbitmq_worker, "init_sentry", MagicMock())
    monkeypatch.setattr(rabbitmq_worker, "_runs_maintenance", MagicMock(return_value=False))
    monkeypatch.setattr(rabbitmq_worker, "_start_maintenance", start_maintenance)
    monkeypatch.setattr(rabbitmq_worker, "_consume", consume)

    await rabbitmq_worker.main()

    start_maintenance.assert_not_awaited()


@pytest.mark.anyio
async def test_task_publisher_emits_json_message(monkeypatch):
    channel = FakePublisherChannel()
    publisher = TaskPublisher()
    monkeypatch.setattr(publisher, "_get_channel", AsyncMock(return_value=channel))

    await publisher.enqueue_task(WorkerTaskType.PROCESS_MEDIA_BATCH, queue_id=123, items=[])

    message, routing_key = channel.exchange.published[0]
    assert routing_key == TASK_ROUTING_KEY
    assert json.loads(message.body.decode("utf-8")) == {
        "task": "process_media_batch",
        "kwargs": {"queue_id": 123, "items": []},
    }
    assert message.headers[HEADER_QUEUE_ID] == 123
    assert message.headers[HEADER_TASK_LANE] == "interactive"


@pytest.mark.anyio
async def test_task_publisher_routes_analysis_to_analysis_lane(monkeypatch):
    channel = FakePublisherChannel()
    publisher = TaskPublisher()
    monkeypatch.setattr(publisher, "_get_channel", AsyncMock(return_value=channel))

    await publisher.enqueue_task(WorkerTaskType.ANALYZE_BIRDNET, queue_id=123)

    message, routing_key = channel.exchange.published[0]
    assert routing_key == TASK_ROUTING_KEY_ANALYSIS
    assert message.headers[HEADER_TASK_LANE] == "analysis"


@pytest.mark.anyio
async def test_process_message_acknowledges_success(monkeypatch):
    handler = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setitem(rabbitmq_worker.TASK_REGISTRY, "unit_task", handler)
    message = FakeMessage(json.dumps({"task": "unit_task", "kwargs": {"queue_id": 1}}).encode())

    await rabbitmq_worker.process_message(message, FakeWorkerChannel())

    handler.assert_awaited_once()
    context = handler.await_args.args[0]
    assert context["cancellation_token"].is_cancelled is False
    assert handler.await_args.kwargs == {"queue_id": 1}
    assert message.acked is True


@pytest.mark.anyio
async def test_process_message_skips_cancelled_queue(monkeypatch):
    handler = AsyncMock(return_value={"status": "ok"})
    finalize = MagicMock()
    monkeypatch.setitem(rabbitmq_worker.TASK_REGISTRY, "unit_task", handler)
    monkeypatch.setattr(
        rabbitmq_worker,
        "prepare_queue_for_execution",
        MagicMock(return_value=QueueStatus.ERROR),
    )
    monkeypatch.setattr(rabbitmq_worker, "cancellation_requested", MagicMock(return_value=True))
    monkeypatch.setattr(rabbitmq_worker, "finalize_queue_cancellation", finalize)
    message = FakeMessage(json.dumps({"task": "unit_task", "kwargs": {"queue_id": 44}}).encode())

    await rabbitmq_worker.process_message(message, FakeWorkerChannel())

    handler.assert_not_awaited()
    finalize.assert_called_once_with(44)
    assert message.acked is True


@pytest.mark.anyio
async def test_process_message_finalizes_cancellation_signalled_by_handler(monkeypatch):
    async def handler(ctx, queue_id):
        assert queue_id == 45
        ctx["cancellation_token"].cancel()

    finalize = MagicMock()
    monkeypatch.setitem(rabbitmq_worker.TASK_REGISTRY, "unit_task", handler)
    monkeypatch.setattr(
        rabbitmq_worker,
        "prepare_queue_for_execution",
        MagicMock(return_value=QueueStatus.RUNNING),
    )
    monkeypatch.setattr(rabbitmq_worker, "finalize_queue_cancellation", finalize)
    message = FakeMessage(json.dumps({"task": "unit_task", "kwargs": {"queue_id": 45}}).encode())

    await rabbitmq_worker.process_message(message, FakeWorkerChannel())

    finalize.assert_called_once_with(45)
    assert message.acked is True


@pytest.mark.anyio
async def test_process_message_does_not_retry_cancelled_queue(monkeypatch):
    async def handler(_ctx, queue_id):
        assert queue_id == 1
        raise TaskRetryError("try later", defer=9)

    monkeypatch.setitem(rabbitmq_worker.TASK_REGISTRY, "retry_task", handler)
    monkeypatch.setattr(rabbitmq_worker, "cancellation_requested", MagicMock(return_value=True))
    finalize = MagicMock()
    monkeypatch.setattr(rabbitmq_worker, "finalize_queue_cancellation", finalize)
    channel = FakeWorkerChannel()
    message = FakeMessage(json.dumps({"task": "retry_task", "kwargs": {"queue_id": 1}}).encode())

    await rabbitmq_worker.process_message(message, channel)

    assert channel.default_exchange.published == []
    finalize.assert_called_with(1)
    assert message.acked is True


@pytest.mark.anyio
async def test_process_message_retries_task_retry(monkeypatch):
    async def handler(_ctx, queue_id):
        assert queue_id == 1
        raise TaskRetryError("try later", defer=9)

    monkeypatch.setitem(rabbitmq_worker.TASK_REGISTRY, "retry_task", handler)
    channel = FakeWorkerChannel()
    message = FakeMessage(json.dumps({"task": "retry_task", "kwargs": {"queue_id": 1}}).encode())

    await rabbitmq_worker.process_message(message, channel)

    retry_message, routing_key = channel.default_exchange.published[0]
    assert routing_key == TASK_RETRY_QUEUE
    assert retry_message.headers[HEADER_RETRY_COUNT] == 1
    assert retry_message.headers[HEADER_TASK_LANE] == "interactive"
    assert retry_message.expiration == 9
    assert message.acked is True


@pytest.mark.anyio
async def test_process_message_sends_unknown_task_to_dead(monkeypatch):
    mark_error = MagicMock()
    monkeypatch.setattr(rabbitmq_worker, "_mark_queue_error", mark_error)
    channel = FakeWorkerChannel()
    body = json.dumps({"task": "missing_task", "kwargs": {"queue_id": 77}}).encode()
    message = FakeMessage(body)

    await rabbitmq_worker.process_message(message, channel)

    _, routing_key = channel.exchange.published[0]
    assert routing_key == DEAD_ROUTING_KEY
    mark_error.assert_called_once()
    assert message.acked is True


@pytest.mark.anyio
async def test_process_message_dead_letters_redelivered_task(monkeypatch):
    handler = AsyncMock()
    mark_error = MagicMock()
    monkeypatch.setitem(rabbitmq_worker.TASK_REGISTRY, "unit_task", handler)
    monkeypatch.setattr(rabbitmq_worker, "_mark_queue_error", mark_error)
    channel = FakeWorkerChannel()
    body = json.dumps({"task": "unit_task", "kwargs": {"queue_id": 91}}).encode()
    message = FakeMessage(body, redelivered=True)

    await rabbitmq_worker.process_message(message, channel)

    handler.assert_not_awaited()
    assert channel.exchange.published[0][1] == DEAD_ROUTING_KEY
    mark_error.assert_called_once_with(91, "Task was redelivered after the worker process exited")
    assert message.acked is True


@pytest.mark.anyio
async def test_watch_queue_cancellation_sets_token(monkeypatch):
    token = rabbitmq_worker.CancellationToken()
    monkeypatch.setattr(rabbitmq_worker, "cancellation_requested", MagicMock(return_value=True))

    await rabbitmq_worker._watch_queue_cancellation(12, token)

    assert token.is_cancelled is True


@pytest.mark.parametrize(
    ("payload", "headers", "expected"),
    [
        (None, {}, None),
        ({"kwargs": {"queue_id": "13"}}, {}, 13),
        ({"kwargs": {"queue_id": 13}}, {HEADER_QUEUE_ID: "bad"}, None),
    ],
)
def test_queue_id_from_payload_handles_headers_payload_and_invalid_values(
    payload,
    headers,
    expected,
):
    assert rabbitmq_worker._queue_id_from_payload(payload, headers) == expected


def _mock_worker_session(queue):
    session = MagicMock()
    session.get.return_value = queue
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = False
    return session, context


def test_mark_queue_error_ignores_missing_queue_id():
    rabbitmq_worker._mark_queue_error(None, "Crash")


def test_mark_queue_error_ignores_unknown_queue(monkeypatch):
    session, context = _mock_worker_session(None)
    monkeypatch.setattr(rabbitmq_worker, "Session", MagicMock(return_value=context))

    rabbitmq_worker._mark_queue_error(14, "Crash")

    session.commit.assert_not_called()


def test_mark_queue_error_preserves_cancellation_marker(monkeypatch):
    queue = MagicMock(
        status=QueueStatus.ERROR,
        error=rabbitmq_worker.TASK_CANCELLED_MESSAGE,
    )
    session, context = _mock_worker_session(queue)
    finalize = MagicMock()
    monkeypatch.setattr(rabbitmq_worker, "Session", MagicMock(return_value=context))
    monkeypatch.setattr(rabbitmq_worker, "finalize_queue_cancellation", finalize)

    rabbitmq_worker._mark_queue_error(15, "Crash")

    session.rollback.assert_called_once_with()
    finalize.assert_called_once_with(15)
    session.commit.assert_not_called()


def test_mark_queue_error_updates_running_queue(monkeypatch):
    queue = MagicMock(status=QueueStatus.RUNNING, error=None)
    session, context = _mock_worker_session(queue)
    monkeypatch.setattr(rabbitmq_worker, "Session", MagicMock(return_value=context))

    rabbitmq_worker._mark_queue_error(16, "Crash")

    assert queue.status == QueueStatus.ERROR
    assert queue.error == "Crash"
    assert queue.stop_time is not None
    session.add.assert_called_once_with(queue)
    session.commit.assert_called_once_with()
