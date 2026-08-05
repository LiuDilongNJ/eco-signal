"""Transient result messages for completed analysis queues."""
import logging

from redis import Redis as SyncRedis
from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

ANALYSIS_QUEUE_MESSAGE_TTL_SECONDS = 7 * 24 * 60 * 60


def analysis_queue_message_key(queue_id: int) -> str:
    return f"analysis:queue-message:{queue_id}"


def cache_analysis_queue_message(queue_id: int, message: str | None) -> None:
    """Store a completion message without making queue completion depend on Redis."""
    if not message:
        return

    redis = SyncRedis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD or None,
        decode_responses=True,
    )
    try:
        redis.set(
            analysis_queue_message_key(queue_id),
            message,
            ex=ANALYSIS_QUEUE_MESSAGE_TTL_SECONDS,
        )
    finally:
        redis.close()


async def get_analysis_queue_message(redis: Redis, queue_id: int) -> str | None:
    """Read a cached completion message, returning None when the cache is unavailable."""
    try:
        value = await redis.get(analysis_queue_message_key(queue_id))
    except Exception:
        logger.warning("Failed to read analysis queue message cache for queue_id=%s", queue_id, exc_info=True)
        return None

    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)
