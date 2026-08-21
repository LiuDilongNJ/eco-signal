from __future__ import annotations

import asyncio
import json
import logging
import signal
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any

import aio_pika
import soundfile as sf
from aio_pika import DeliveryMode, Message
from aio_pika.abc import (
    AbstractIncomingMessage,
    AbstractRobustChannel,
    AbstractRobustConnection,
)
from sqlmodel import Session
from prometheus_client import Counter, Histogram

from app.core.config import settings
from app.core.db import engine
from app.core.observability import init_sentry
from app.core.task_cancellation import (
    TASK_CANCELLED_MESSAGE,
    CancellationToken,
    TaskCancelledError,
)
from app.enums import QueueStatus, WorkerTaskType
from app.models.system import Queue
from app.workers.cancellation import (
    cancellation_requested,
    finalize_queue_cancellation,
    prepare_queue_for_execution,
)
from app.workers.exceptions import TaskRetryError
from app.workers.rabbitmq import (
    DEAD_ROUTING_KEY,
    HEADER_QUEUE_ID,
    HEADER_RETRY_COUNT,
    HEADER_TASK_LANE,
    TASK_DEAD_QUEUE,
    TASK_EXCHANGE,
    TASK_LANES,
    declare_topology,
    rabbitmq_url,
    task_lane_config,
)
from app.workers.tasks import (
    analyze_acoustic_index,
    analyze_batdetect,
    analyze_birdnet,
    analyze_insects,
    cleanup_expired_chunks,
    cleanup_expired_collection_bundle_exports,
    cleanup_expired_offline_imports,
    export_collection_bundle,
    import_collection_bundle,
    merge_file_chunks,
    process_media_batch,
    startup_sync_network_nodes,
    sync_network_nodes,
)

logger = logging.getLogger(__name__)

WORKER_TASKS_TOTAL = Counter(
    "ecosignal_worker_tasks_total",
    "Completed worker tasks by lane and outcome",
    labelnames=("lane", "status"),
)
WORKER_TASK_DURATION_SECONDS = Histogram(
    "ecosignal_worker_task_duration_seconds",
    "Worker task duration by lane and task type",
    labelnames=("lane", "task"),
    buckets=(0.1, 0.5, 1.0, 5.0, 30.0, 60.0, 300.0, 900.0, 3600.0),
)

TaskHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

TASK_REGISTRY: dict[str, TaskHandler] = {
    WorkerTaskType.ANALYZE_BIRDNET.value: analyze_birdnet,
    WorkerTaskType.ANALYZE_BATDETECT.value: analyze_batdetect,
    WorkerTaskType.ANALYZE_INSECTS.value: analyze_insects,
    WorkerTaskType.ANALYZE_ACOUSTIC_INDEX.value: analyze_acoustic_index,
    WorkerTaskType.PROCESS_MEDIA_BATCH.value: process_media_batch,
    WorkerTaskType.MERGE_FILE_CHUNKS.value: merge_file_chunks,
    WorkerTaskType.IMPORT_COLLECTION_BUNDLE.value: import_collection_bundle,
    WorkerTaskType.EXPORT_COLLECTION_BUNDLE.value: export_collection_bundle,
}


def _headers(message: AbstractIncomingMessage) -> dict[str, Any]:
    return dict(message.headers or {})


def _queue_id_from_payload(payload: dict[str, Any] | None, headers: dict[str, Any]) -> int | None:
    raw = headers.get(HEADER_QUEUE_ID)
    if raw is None and payload is not None:
        raw = payload.get("kwargs", {}).get("queue_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _mark_queue_error(queue_id: int | None, message: str) -> None:
    if queue_id is None:
        return
    with Session(engine) as session:
        queue = session.get(Queue, queue_id)
        if queue is None:
            return
        if queue.status == QueueStatus.ERROR and queue.error == TASK_CANCELLED_MESSAGE:
            session.rollback()
            finalize_queue_cancellation(queue_id)
            return
        if queue.status in {QueueStatus.PENDING, QueueStatus.RUNNING}:
            queue.status = QueueStatus.ERROR
            queue.error = message
            queue.stop_time = datetime.now(UTC).replace(tzinfo=None)
            session.add(queue)
            session.commit()


async def _watch_queue_cancellation(queue_id: int, token: CancellationToken) -> None:
    while not token.is_cancelled:
        if cancellation_requested(queue_id):
            token.cancel()
            return
        await asyncio.sleep(0.5)


async def _publish_dead(
    channel: AbstractRobustChannel,
    body: bytes,
    headers: dict[str, Any],
    reason: str,
) -> None:
    exchange = await channel.get_exchange(TASK_EXCHANGE, ensure=True)
    dead_headers = dict(headers)
    dead_headers["x-error"] = reason[:1000]
    await exchange.publish(
        Message(
            body,
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            headers=dead_headers,
        ),
        routing_key=DEAD_ROUTING_KEY,
    )


async def _publish_retry(
    channel: AbstractRobustChannel,
    body: bytes,
    headers: dict[str, Any],
    retry_count: int,
    defer: int,
    lane: str,
) -> None:
    retry_headers = dict(headers)
    retry_headers[HEADER_RETRY_COUNT] = retry_count
    retry_headers[HEADER_TASK_LANE] = lane
    await channel.default_exchange.publish(
        Message(
            body,
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            expiration=max(defer, 1),
            headers=retry_headers,
        ),
        routing_key=task_lane_config(lane)["retry_queue"],
    )


def _task_lane(headers: dict[str, Any]) -> str:
    lane = str(headers.get(HEADER_TASK_LANE, "interactive"))
    task_lane_config(lane)
    return lane


async def process_message(message: AbstractIncomingMessage, channel: AbstractRobustChannel) -> None:
    headers = _headers(message)
    payload: dict[str, Any] | None = None
    queue_id: int | None = None
    cancellation_token: CancellationToken | None = None
    cancellation_watcher: asyncio.Task[None] | None = None
    task_name = "unknown"
    started_at: float | None = None
    try:
        payload = json.loads(message.body.decode("utf-8"))
        task_name = payload["task"]
        kwargs = payload.get("kwargs") or {}
        if not isinstance(kwargs, dict):
            raise ValueError("Task kwargs must be an object")
        if message.redelivered:
            reason = "Task was redelivered after the worker process exited"
            _mark_queue_error(_queue_id_from_payload(payload, headers), reason)
            await _publish_dead(channel, message.body, headers, reason)
            await message.ack()
            return
        handler = TASK_REGISTRY.get(task_name)
        if handler is None:
            raise ValueError(f"Unknown task: {task_name}")

        queue_id = _queue_id_from_payload(payload, headers)
        if queue_id is not None:
            queue_status = prepare_queue_for_execution(queue_id)
            if queue_status is None:
                await message.ack()
                return
            if queue_status in {QueueStatus.COMPLETED, QueueStatus.ERROR, QueueStatus.WARNING}:
                if cancellation_requested(queue_id):
                    finalize_queue_cancellation(queue_id)
                await message.ack()
                return
            cancellation_token = CancellationToken()
            cancellation_watcher = asyncio.create_task(
                _watch_queue_cancellation(queue_id, cancellation_token)
            )

        audio_duration: float | None = None
        audio_path = kwargs.get("audio_path")
        if isinstance(audio_path, str) and Path(audio_path).is_file():
            try:
                info = sf.info(audio_path)
                audio_duration = info.frames / info.samplerate if info.samplerate else None
            except (OSError, RuntimeError, sf.LibsndfileError):
                logger.warning("Could not read task audio duration: path=%s", audio_path)
        started_at = monotonic()
        logger.info(
            "Starting RabbitMQ task: task=%s queue_id=%s audio_duration_seconds=%s",
            task_name,
            kwargs.get("queue_id"),
            audio_duration,
        )
        await asyncio.wait_for(
            handler({"cancellation_token": cancellation_token}, **kwargs),
            timeout=settings.WORKER_JOB_TIMEOUT,
        )
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if queue_id is not None and cancellation_requested(queue_id):
            raise TaskCancelledError("Task cancellation requested")
        logger.info(
            "Completed RabbitMQ task: task=%s queue_id=%s elapsed_seconds=%.3f",
            task_name,
            kwargs.get("queue_id"),
            monotonic() - started_at,
        )
        lane = _task_lane(headers)
        WORKER_TASK_DURATION_SECONDS.labels(lane=lane, task=task_name).observe(monotonic() - started_at)
        WORKER_TASKS_TOTAL.labels(lane=lane, status="completed").inc()
        await message.ack()
    except TaskCancelledError:
        if queue_id is not None:
            finalize_queue_cancellation(queue_id)
        WORKER_TASKS_TOTAL.labels(lane=_task_lane(headers), status="cancelled").inc()
        await message.ack()
    except TaskRetryError as exc:
        retry_count = int(headers.get(HEADER_RETRY_COUNT, 0)) + 1
        queue_id = _queue_id_from_payload(payload, headers)
        if queue_id is not None and cancellation_requested(queue_id):
            finalize_queue_cancellation(queue_id)
        elif retry_count >= settings.WORKER_RETRY_MAX_TRIES:
            reason = f"Task exceeded retry limit: {exc}"
            _mark_queue_error(queue_id, reason)
            await _publish_dead(channel, message.body, headers, reason)
            WORKER_TASKS_TOTAL.labels(lane=_task_lane(headers), status="failed").inc()
        else:
            await _publish_retry(
                channel,
                message.body,
                headers,
                retry_count,
                exc.defer,
                _task_lane(headers),
            )
            WORKER_TASKS_TOTAL.labels(lane=_task_lane(headers), status="retried").inc()
        await message.ack()
    except Exception as exc:  # noqa: BLE001
        logger.exception("RabbitMQ task failed")
        reason = str(exc)
        _mark_queue_error(_queue_id_from_payload(payload, headers), reason)
        await _publish_dead(channel, message.body, headers, reason)
        WORKER_TASKS_TOTAL.labels(lane=_task_lane(headers), status="failed").inc()
        await message.ack()
    finally:
        if cancellation_watcher is not None:
            cancellation_watcher.cancel()
            await asyncio.gather(cancellation_watcher, return_exceptions=True)


async def _run_daily(hour: int, minute: int, func: TaskHandler, name: str) -> None:
    while True:
        now = datetime.now(UTC)
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
        try:
            await func({})
        except Exception:  # noqa: BLE001
            logger.exception("Scheduled task failed: %s", name)


async def _consume(stop_event: asyncio.Event) -> None:
    connection: AbstractRobustConnection = await aio_pika.connect_robust(rabbitmq_url())
    try:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=settings.WORKER_PREFETCH_COUNT)
        configured_lane = settings.WORKER_QUEUE.strip().lower()
        lanes = tuple(TASK_LANES) if configured_lane == "all" else (configured_lane,)

        async def callback(message: AbstractIncomingMessage) -> None:
            await process_message(message, channel)

        consumed_queues: list[str] = []
        for lane in lanes:
            _, queue = await declare_topology(channel, lane=lane)
            if queue is None:
                continue
            await queue.consume(callback)
            consumed_queues.append(task_lane_config(lane)["queue"])
        logger.info(
            "RabbitMQ worker consuming: queues=%s dead_queue=%s",
            ",".join(consumed_queues),
            TASK_DEAD_QUEUE,
        )
        await stop_event.wait()
    finally:
        await connection.close()


def _runs_maintenance() -> bool:
    return settings.WORKER_QUEUE.strip().lower() in {"interactive", "all"}


async def _start_maintenance() -> list[asyncio.Task[None]]:
    await startup_sync_network_nodes({})
    schedules = (
        (2, 0, sync_network_nodes, "sync_network_nodes"),
        (3, 0, cleanup_expired_chunks, "cleanup_expired_chunks"),
        (3, 30, cleanup_expired_offline_imports, "cleanup_expired_offline_imports"),
        (4, 0, cleanup_expired_collection_bundle_exports, "cleanup_expired_collection_bundle_exports"),
    )
    return [
        asyncio.create_task(_run_daily(hour, minute, func, name), name=f"maintenance:{name}")
        for hour, minute, func, name in schedules
    ]


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_sentry("worker")
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    maintenance_tasks: list[asyncio.Task[None]] = []
    try:
        if _runs_maintenance():
            maintenance_tasks = await _start_maintenance()
        await _consume(stop_event)
    finally:
        for task in maintenance_tasks:
            task.cancel()
        if maintenance_tasks:
            await asyncio.gather(*maintenance_tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
