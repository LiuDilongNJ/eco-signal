from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractChannel, AbstractRobustConnection

from app.enums import WorkerTaskType
from app.workers.rabbitmq import (
    HEADER_CREATED_AT,
    HEADER_QUEUE_ID,
    HEADER_TASK_LANE,
    TASK_EXCHANGE,
    declare_topology,
    rabbitmq_url,
    task_lane_config,
)

_ANALYSIS_TASK_TYPES = {
    WorkerTaskType.ANALYZE_BIRDNET,
    WorkerTaskType.ANALYZE_BATDETECT,
    WorkerTaskType.ANALYZE_INSECTS,
    WorkerTaskType.ANALYZE_ACOUSTIC_INDEX,
}


class TaskPublisher:
    """Publish background tasks to RabbitMQ."""

    def __init__(self) -> None:
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None

    async def _get_channel(self) -> AbstractChannel:
        if self._connection is None or self._connection.is_closed:
            self._connection = await aio_pika.connect_robust(rabbitmq_url())
            self._channel = await self._connection.channel()
            await declare_topology(self._channel)
        if self._channel is None or self._channel.is_closed:
            self._channel = await self._connection.channel()
            await declare_topology(self._channel)
        return self._channel

    async def enqueue_task(self, task_type: WorkerTaskType | str, **kwargs: Any) -> None:
        channel = await self._get_channel()
        exchange = await channel.get_exchange(TASK_EXCHANGE, ensure=True)
        task_name = task_type.value if isinstance(task_type, WorkerTaskType) else str(task_type)
        lane = "analysis" if task_type in _ANALYSIS_TASK_TYPES else "interactive"
        lane_config = task_lane_config(lane)
        body = json.dumps({"task": task_name, "kwargs": kwargs}, separators=(",", ":")).encode("utf-8")
        queue_id = kwargs.get("queue_id")
        headers: dict[str, Any] = {
            HEADER_CREATED_AT: datetime.now(UTC).isoformat(),
        }
        if queue_id is not None:
            headers[HEADER_QUEUE_ID] = queue_id
        headers[HEADER_TASK_LANE] = lane

        await exchange.publish(
            Message(
                body,
                content_type="application/json",
                delivery_mode=DeliveryMode.PERSISTENT,
                headers=headers,
            ),
            routing_key=lane_config["routing_key"],
        )

    async def close(self) -> None:
        if self._channel is not None and not self._channel.is_closed:
            await self._channel.close()
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
