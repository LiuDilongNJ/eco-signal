"""Analysis tasks for AI model processing."""
import asyncio
import datetime
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlmodel import Session

from app.ai.exceptions import ModelDownloadError
from app.core.db import engine
from app.core.task_cancellation import (
    TASK_CANCELLED_MESSAGE,
    CancellationToken,
    TaskCancelledError,
)
from app.enums import QueueStatus
from app.models.system import Queue
from app.services.analysis_queue_message_cache import cache_analysis_queue_message
from app.services.analysis_service import analysis_service
from app.workers.exceptions import TaskRetryError

logger = logging.getLogger(__name__)

_MODEL_RETRY_DEFER = 30


def _format_analysis_completion_message(result: dict[str, Any]) -> str | None:
    completion_message = result.get("completion_message")
    if completion_message:
        return str(completion_message)

    model_name = result.get("analysis_message_model")
    if not model_name:
        if "stored_count" not in result:
            return None
        output_items = [
            f"{name}: {value}"
            for name, value in result.items()
            if name not in {"stored_count", "detection_count", "completion_message", "warning", "message"}
        ]
        return ", ".join(output_items) if output_items else "Acoustic index calculation finished."

    detection_count = int(result.get("detection_count") or 0)
    annotation_count = int(result.get("annotation_count") or 0)
    message = f"{model_name} found {detection_count} detections. {annotation_count} tags were inserted."

    unmatched_count = int(result.get("unmatched_species_count") or 0)
    unmatched_species = [str(species) for species in result.get("unmatched_species") or [] if species]
    if unmatched_count > 0 and unmatched_species:
        species_text = ", ".join(unmatched_species)
        message += f"({unmatched_count} tags with unmatched species: {species_text} inserted into comments)"

    warning = result.get("warning")
    if warning:
        message += f" {warning}"

    return message


def _update_annotation_count_after_merge(
    result: dict[str, Any],
    merge_count: int | None,
    *,
    keep_merged_only: bool,
) -> None:
    if not isinstance(merge_count, int):
        return

    original_count = int(result.get("annotation_count") or 0)
    result["annotation_count"] = merge_count if keep_merged_only else original_count + merge_count


def _mark_queue_error(queue_id: int, message: str) -> None:
    with Session(engine) as session:
        queue = session.get(Queue, queue_id)
        if queue and queue.status in {QueueStatus.PENDING, QueueStatus.RUNNING}:
            queue.status = QueueStatus.ERROR
            queue.error = message
            queue.stop_time = datetime.datetime.now(datetime.UTC)
            session.commit()


async def _run_with_queue(
        task_name: str,
        queue_id: int,
        work_fn: Callable[[Session, Queue], dict[str, Any]],
        cancellation_token: CancellationToken | None = None,
) -> dict[str, Any]:
    """
    Common wrapper for analysis tasks.

    Handles queue lifecycle (running -> completed/error) and
    ModelDownloadError retries so each task only defines its own work logic.
    """
    def _do_work() -> dict[str, Any]:
        with Session(engine) as session:
            queue = session.get(Queue, queue_id)
            if not queue:
                logger.error(f"Queue {queue_id} not found")
                return {"error": "Queue not found"}

            if queue.status == QueueStatus.ERROR and queue.error == TASK_CANCELLED_MESSAGE:
                raise TaskCancelledError("Task cancellation requested")
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()

            logger.info(f"Starting {task_name} analysis for queue {queue_id}")

            result = work_fn(session, queue)
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            session.refresh(queue, with_for_update=True)
            if queue.status == QueueStatus.ERROR and queue.error == TASK_CANCELLED_MESSAGE:
                raise TaskCancelledError("Task cancellation requested")
            completion_message = _format_analysis_completion_message(result)
            if completion_message:
                try:
                    cache_analysis_queue_message(queue.queue_id, completion_message)
                    result["message"] = completion_message
                except Exception:
                    logger.warning(
                        "Failed to cache analysis completion message for queue %s",
                        queue.queue_id,
                        exc_info=True,
                    )

            queue.status = QueueStatus.COMPLETED
            queue.completed = result.get("detection_count", result.get("stored_count", 1))
            queue.total = queue.completed
            queue.stop_time = datetime.datetime.now(datetime.UTC)
            session.commit()

            return {"queue_id": queue.queue_id, "status": "completed", **result}

    try:
        return await asyncio.to_thread(_do_work)
    except TaskCancelledError:
        logger.info(f"{task_name} cancellation completed for queue {queue_id}")
        raise
    except asyncio.CancelledError:
        logger.warning(f"{task_name} cancelled for queue {queue_id}")
        _mark_queue_error(queue_id, f"{task_name} task cancelled by worker shutdown")
        raise
    except ModelDownloadError as e:
        logger.warning(f"{task_name} model download error for queue {queue_id}, retrying: {e}")
        with Session(engine) as session:
            queue = session.get(Queue, queue_id)
            if queue:
                queue.status = QueueStatus.PENDING
                session.commit()
        raise TaskRetryError(str(e), defer=_MODEL_RETRY_DEFER)
    except Exception as e:
        logger.exception(f"{task_name} failed for queue {queue_id}")
        _mark_queue_error(queue_id, str(e))
        return {"error": str(e)}


async def analyze_birdnet(
        ctx: dict[str, Any],
        queue_id: int,
        audio_path: str,
        media_id: int | None = None,
        min_confidence: float = 0.1,
        overlap: float = 0.0,
        sensitivity: float = 1.0,
        sf_thresh: float = 0.03,
        min_frequency: int = 1,
        max_frequency: int = 15000,
        lat: float | None = None,
        lon: float | None = None,
        week: int | None = None,
        locale: str = "en_us",
        top_n: int | None = None,
        merge_enabled: bool = False,
        merge_max_gap: float = 0.0,
        merge_keep_only: bool = False,
) -> dict[str, Any]:
    """BirdNET analysis task. Executed by ARQ Worker in background."""
    cancellation_token = ctx.get("cancellation_token")
    def work(session: Session, queue: Queue) -> dict[str, Any]:
        if media_id:
            result = analysis_service.analyze_and_store_birdnet(
                session=session,
                audio_path=Path(audio_path),
                media_id=media_id,
                creator_id=queue.user_id,
                min_confidence=min_confidence,
                overlap=overlap,
                sensitivity=sensitivity,
                sf_thresh=sf_thresh,
                min_frequency=min_frequency,
                max_frequency=max_frequency,
                lat=lat,
                lon=lon,
                week=week,
                locale=locale,
                top_n=top_n,
                cancellation_token=cancellation_token,
                commit=False,
            )
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            if merge_enabled and result["annotation_count"] > 0:
                creator_type = f"BirdNET-Analyzer {analysis_service.birdnet.version}"
                merge_count = analysis_service.merge_annotations(
                    session=session,
                    media_id=media_id,
                    creator_type=creator_type,
                    max_gap=merge_max_gap,
                    keep_merged_only=merge_keep_only,
                    annotation_ids=result.get("annotation_ids"),
                    commit=False,
                )
                _update_annotation_count_after_merge(
                    result,
                    merge_count,
                    keep_merged_only=merge_keep_only,
                )
            return result

        detections = analysis_service.birdnet.analyze(
            Path(audio_path),
            min_confidence=min_confidence,
            overlap=overlap,
            sensitivity=sensitivity,
            sf_thresh=sf_thresh,
            lat=lat,
            lon=lon,
            week=week,
            min_frequency=min_frequency,
            max_frequency=max_frequency,
            locale=locale,
            top_n=top_n,
            cancellation_token=cancellation_token,
        )
        return {
            "detection_count": len(detections),
            "annotation_count": 0,
            "analysis_message_model": f"BirdNET v{analysis_service.birdnet.version}",
        }

    return await _run_with_queue("BirdNET", queue_id, work, cancellation_token)


async def analyze_batdetect(
        ctx: dict[str, Any],
        queue_id: int,
        audio_path: str,
        media_id: int,
        detection_threshold: float = 0.3,
        chunk_size: float = 2.0,
        merge_enabled: bool = False,
        merge_max_gap: float = 0.0,
        merge_keep_only: bool = False,
) -> dict[str, Any]:
    """Batdetect2 analysis task. Executed by ARQ Worker in background."""
    cancellation_token = ctx.get("cancellation_token")
    def work(session: Session, queue: Queue) -> dict[str, Any]:
        result = analysis_service.analyze_and_store_batdetect(
            session=session,
            audio_path=Path(audio_path),
            media_id=media_id,
            creator_id=queue.user_id,
            detection_threshold=detection_threshold,
            chunk_size=chunk_size,
            cancellation_token=cancellation_token,
            commit=False,
        )
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if merge_enabled and result["annotation_count"] > 0:
            creator_type = f"batdetect2 {analysis_service.batdetect.version}"
            merge_count = analysis_service.merge_annotations(
                session=session,
                media_id=media_id,
                creator_type=creator_type,
                max_gap=merge_max_gap,
                keep_merged_only=merge_keep_only,
                annotation_ids=result.get("annotation_ids"),
                commit=False,
            )
            _update_annotation_count_after_merge(
                result,
                merge_count,
                keep_merged_only=merge_keep_only,
            )
        return result

    return await _run_with_queue("batdetect2", queue_id, work, cancellation_token)


async def analyze_insects(
        ctx: dict[str, Any],
        queue_id: int,
        audio_path: str,
        media_id: int,
        window_size: float = 4.0,
        stride_length: float = 4.0,
        max_freq: int = 48000,
        merge_enabled: bool = False,
        merge_max_gap: float = 0.0,
        merge_keep_only: bool = False,
) -> dict[str, Any]:
    """insects-base-cnn10-96k-t analysis task. Executed by ARQ Worker in background."""
    cancellation_token = ctx.get("cancellation_token")
    def work(session: Session, queue: Queue) -> dict[str, Any]:
        result = analysis_service.analyze_and_store_insects(
            session=session,
            audio_path=Path(audio_path),
            media_id=media_id,
            creator_id=queue.user_id,
            window_size=window_size,
            stride_length=stride_length,
            max_freq=max_freq,
            cancellation_token=cancellation_token,
            commit=False,
        )
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if merge_enabled and result["annotation_count"] > 0:
            creator_type = "insects-base-cnn10-96k-t"
            merge_count = analysis_service.merge_annotations(
                session=session,
                media_id=media_id,
                creator_type=creator_type,
                max_gap=merge_max_gap,
                keep_merged_only=merge_keep_only,
                annotation_ids=result.get("annotation_ids"),
                commit=False,
            )
            _update_annotation_count_after_merge(
                result,
                merge_count,
                keep_merged_only=merge_keep_only,
            )
        return result

    return await _run_with_queue("insects", queue_id, work, cancellation_token)


async def analyze_acoustic_index(
        ctx: dict[str, Any],
        queue_id: int,
        audio_path: str,
        media_id: int,
        index_id: int | None,
        index_name: str,
        params: dict[str, Any] | None = None,
        stored_params: dict[str, Any] | None = None,
        channel: str = "left",
        min_time: str | int | float = 0,
        max_time: str | int | float | None = None,
        min_frequency: str | int | float = 1,
        max_frequency: str | int | float | None = None,
        log_id: int | None = None,
        filter_enabled: bool = False,
) -> dict[str, Any]:
    """Generic acoustic index analysis task. Executed by ARQ Worker in background."""
    cancellation_token = ctx.get("cancellation_token")
    def work(session: Session, queue: Queue) -> dict[str, Any]:
        if index_id is None:
            if max_time is None or max_frequency is None:
                raise ValueError("max_time and max_frequency are required for acoustic analysis")
            return analysis_service.analyze_acoustic_selection(
                session=session,
                audio_path=Path(audio_path),
                media_id=media_id,
                user_id=queue.user_id,
                analysis_type=index_name,
                params=params or {},
                channel=channel,
                min_time=float(min_time),
                max_time=float(max_time),
                min_frequency=float(min_frequency),
                max_frequency=float(max_frequency),
                filter_enabled=filter_enabled,
                cancellation_token=cancellation_token,
                commit=False,
            )
        return analysis_service.analyze_and_store_acoustic_index(
            session=session,
            audio_path=Path(audio_path),
            media_id=media_id,
            user_id=queue.user_id,
            index_type_name=index_name,
            index_id=index_id,
            params=params,
            stored_params=stored_params,
            channel=channel,
            min_time=min_time,
            max_time=max_time,
            min_frequency=min_frequency,
            max_frequency=max_frequency,
            log_id=log_id,
            filter_enabled=filter_enabled,
            cancellation_token=cancellation_token,
            commit=False,
        )

    return await _run_with_queue(index_name, queue_id, work, cancellation_token)
