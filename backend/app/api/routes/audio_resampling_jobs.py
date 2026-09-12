"""音频重采样任务接口。 / Audio resampling endpoints."""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep, TaskPublisherDep
from app.models import Annotation, Media, MediaCollection, ProjectCollection
from app.schemas.media import (
    AudioResamplingJobRequest,
    AudioResamplingJobResponse,
    AudioResamplingRejectedItem,
)
from app.services import authorization_service, media_service
from app.services.authorization_policy import AuthorizationAction

router = APIRouter(prefix="/audio-resampling-jobs", tags=["音频重采样 / audio resampling"])


@router.post("", status_code=202, summary="创建音频重采样任务或预检 / Create Audio Resampling Job or Preview")
async def create_audio_resampling_job(
    request: AudioResamplingJobRequest,
    session: SessionDep,
    current_user: CurrentUser,
    publisher: TaskPublisherDep,
    project_id: int = Query(..., description="项目 ID / Project ID"),
    dry_run: bool = Query(False, description="预检模式，仅统计受影响标注而不入队任务 / Dry-run preview mode"),
) -> JSONResponse:
    """为有写入权限的音频创建后台降采样任务或执行预检统计。 / Queue downsampling or preview affected annotations."""
    accepted: list[int] = []
    rejected: list[AudioResamplingRejectedItem] = []
    for media_id in dict.fromkeys(request.media_ids):
        media = session.get(Media, media_id)
        if not media or media.media_type != "audio" or media.is_metadata or not media.audio_setting:
            rejected.append(AudioResamplingRejectedItem(media_id=media_id, status_code=422, message="Audio file is not available"))
            continue
        links = session.exec(
            select(MediaCollection.collection_id)
            .join(ProjectCollection, ProjectCollection.collection_id == MediaCollection.collection_id)
            .where(MediaCollection.media_id == media_id, ProjectCollection.project_id == project_id)
        ).all()
        if not links:
            rejected.append(AudioResamplingRejectedItem(media_id=media_id, status_code=403, message="No write permission on media"))
            continue
        try:
            for collection_id in links:
                authorization_service.require_collection_action(
                    session, current_user, AuthorizationAction.MEDIA_EDIT,
                    collection_id=collection_id, project_id=project_id,
                    denied_detail="No write permission on media",
                )
        except Exception:
            rejected.append(AudioResamplingRejectedItem(media_id=media_id, status_code=403, message="No write permission on media"))
            continue
        if request.target_sampling_rate_hz > media.audio_setting.sampling_rate_hz:
            rejected.append(AudioResamplingRejectedItem(
                media_id=media_id, status_code=422,
                message="Target sampling rate must not exceed the current sampling rate",
            ))
            continue
        accepted.append(media_id)

    target_max_freq = request.target_sampling_rate_hz / 2.0
    affected_ann_count = 0
    affected_media_count = 0
    if accepted:
        affected_ann_count = session.exec(
            select(func.count(Annotation.annotation_id))
            .where(col(Annotation.media_id).in_(accepted), Annotation.max_y > target_max_freq)
        ).one() or 0
        affected_media_count = session.exec(
            select(func.count(func.distinct(Annotation.media_id)))
            .where(col(Annotation.media_id).in_(accepted), Annotation.max_y > target_max_freq)
        ).one() or 0

    if dry_run:
        response = AudioResamplingJobResponse(
            queue_id=None,
            accepted_media_ids=accepted,
            rejected=rejected,
            affected_annotation_count=affected_ann_count,
            affected_media_count=affected_media_count,
        )
        return JSONResponse(status_code=200, content={
            "code": 200,
            "message": "Audio resampling preview completed",
            "data": response.model_dump(),
        })

    if not accepted:
        return JSONResponse(status_code=202, content={
            "code": 202, "message": "No audio resampling job created",
            "data": {
                "queue_id": None,
                "accepted_media_ids": [],
                "rejected": [item.model_dump() for item in rejected],
                "affected_annotation_count": 0,
                "affected_media_count": 0,
            },
        })
    result = await media_service.create_audio_resampling_job(
        session, current_user, publisher, accepted, request.target_sampling_rate_hz,
    )
    response = AudioResamplingJobResponse(
        queue_id=result.queue_id,
        accepted_media_ids=accepted,
        rejected=rejected,
        affected_annotation_count=affected_ann_count,
        affected_media_count=affected_media_count,
    )
    return JSONResponse(status_code=202, content={
        "code": 202, "message": "Audio resampling job created", "data": response.model_dump(),
    })

