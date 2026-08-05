from __future__ import annotations

from urllib.parse import quote

from aio_pika import ExchangeType
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractQueue

from app.core.config import settings

TASK_EXCHANGE = "ecosignal.tasks"
TASK_QUEUE_INTERACTIVE = "ecosignal.tasks.interactive"
TASK_QUEUE_ANALYSIS = "ecosignal.tasks.analysis"
TASK_QUEUE = TASK_QUEUE_INTERACTIVE
TASK_RETRY_QUEUE_INTERACTIVE = "ecosignal.tasks.interactive.retry"
TASK_RETRY_QUEUE_ANALYSIS = "ecosignal.tasks.analysis.retry"
TASK_RETRY_QUEUE = TASK_RETRY_QUEUE_INTERACTIVE
TASK_DEAD_QUEUE = "ecosignal.tasks.dead"
TASK_ROUTING_KEY_INTERACTIVE = "interactive"
TASK_ROUTING_KEY_ANALYSIS = "analysis"
TASK_ROUTING_KEY = TASK_ROUTING_KEY_INTERACTIVE
DEAD_ROUTING_KEY = "dead"

HEADER_RETRY_COUNT = "x-retry-count"
HEADER_CREATED_AT = "x-created-at"
HEADER_QUEUE_ID = "x-queue-id"
HEADER_TASK_LANE = "x-task-lane"

TASK_LANES = {
    "interactive": {
        "queue": TASK_QUEUE_INTERACTIVE,
        "retry_queue": TASK_RETRY_QUEUE_INTERACTIVE,
        "routing_key": TASK_ROUTING_KEY_INTERACTIVE,
    },
    "analysis": {
        "queue": TASK_QUEUE_ANALYSIS,
        "retry_queue": TASK_RETRY_QUEUE_ANALYSIS,
        "routing_key": TASK_ROUTING_KEY_ANALYSIS,
    },
}


def rabbitmq_url() -> str:
    user = quote(settings.RABBITMQ_USER, safe="")
    password = quote(settings.RABBITMQ_PASSWORD, safe="")
    vhost = quote(settings.RABBITMQ_VHOST.lstrip("/") or "/", safe="")
    return f"amqp://{user}:{password}@{settings.RABBITMQ_HOST}:{settings.RABBITMQ_PORT}/{vhost}"


def task_lane_config(lane: str) -> dict[str, str]:
    try:
        return TASK_LANES[lane]
    except KeyError as exc:
        raise ValueError(f"Unknown task lane: {lane}") from exc


async def declare_topology(
    channel: AbstractChannel,
    *,
    lane: str | None = None,
) -> tuple[AbstractExchange, AbstractQueue | None]:
    exchange = await channel.declare_exchange(
        TASK_EXCHANGE,
        ExchangeType.DIRECT,
        durable=True,
    )
    primary_queue: AbstractQueue | None = None
    for selected_lane in ((lane,) if lane else tuple(TASK_LANES)):
        config = task_lane_config(selected_lane)
        queue = await channel.declare_queue(config["queue"], durable=True)
        await queue.bind(exchange, routing_key=config["routing_key"])
        await channel.declare_queue(
            config["retry_queue"],
            durable=True,
            arguments={
                "x-dead-letter-exchange": TASK_EXCHANGE,
                "x-dead-letter-routing-key": config["routing_key"],
            },
        )
        primary_queue = queue

    dead_queue = await channel.declare_queue(TASK_DEAD_QUEUE, durable=True)
    await dead_queue.bind(exchange, routing_key=DEAD_ROUTING_KEY)
    return exchange, primary_queue
