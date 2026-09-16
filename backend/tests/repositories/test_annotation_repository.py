"""Tests for annotation persistence helpers."""

import datetime

from sqlmodel import Session

from app.models import (
    Annotation,
    AnnotationReview,
    AnnotationReviewStatus,
    AudioSetting,
    Media,
    Task,
)
from app.repositories.annotation_repository import annotation_repository
from tests.utils.utils import random_lower_string


def test_resampling_impact_and_adjustment_share_frequency_boundaries(db: Session) -> None:
    setting = AudioSetting(
        sampling_rate_hz=48000,
        bit_depth=16,
        channel_num=1,
        duration_s=5,
    )
    db.add(setting)
    db.commit()
    db.refresh(setting)
    media = Media(
        name=f"resampling_{random_lower_string()[:6]}.flac",
        filename="resampling.flac",
        uploader_id=1,
        media_type="audio",
        is_metadata=False,
        audio_setting_id=setting.audio_setting_id,
        date_time=datetime.datetime.now(datetime.UTC),
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    annotations = [
        Annotation(media_id=media.media_id, creator_id=1, min_x=0, max_x=1, min_y=1000, max_y=5000),
        Annotation(
            media_id=media.media_id,
            creator_id=1,
            sound_id=1,
            comments="Keep this annotation",
            min_x=1,
            max_x=2,
            min_y=7000,
            max_y=10000,
        ),
        Annotation(media_id=media.media_id, creator_id=1, min_x=2, max_x=3, min_y=8000, max_y=10000),
        Annotation(media_id=media.media_id, creator_id=1, min_x=3, max_x=4, min_y=9000, max_y=12000),
        Annotation(media_id=media.media_id, creator_id=1, min_x=4, max_x=5, min_y=7000, max_y=8000),
    ]
    db.add_all(annotations)
    db.commit()
    for annotation in annotations:
        db.refresh(annotation)

    review_status = AnnotationReviewStatus(name=f"resampling-{random_lower_string()[:6]}")
    db.add(review_status)
    db.commit()
    db.refresh(review_status)
    clipped = annotations[1]
    removed = annotations[2]
    in_range_id = annotations[0].annotation_id
    clipped_id = clipped.annotation_id
    clipped_uuid = clipped.uuid
    clipped_sound_id = clipped.sound_id
    clipped_comments = clipped.comments
    removed_id = removed.annotation_id
    high_removed_id = annotations[3].annotation_id
    boundary_id = annotations[4].annotation_id
    clipped_task = Task(
        type="review",
        media_id=media.media_id,
        annotation_id=clipped.annotation_id,
        assigner_id=1,
        assignee_id=1,
    )
    removed_task = Task(
        type="review",
        media_id=media.media_id,
        annotation_id=removed.annotation_id,
        assigner_id=1,
        assignee_id=1,
    )
    db.add_all([
        AnnotationReview(
            annotation_id=clipped.annotation_id,
            reviewer_id=1,
            annotation_review_status_id=review_status.annotation_review_status_id,
        ),
        AnnotationReview(
            annotation_id=removed.annotation_id,
            reviewer_id=1,
            annotation_review_status_id=review_status.annotation_review_status_id,
        ),
        clipped_task,
        removed_task,
    ])
    db.commit()
    db.refresh(clipped_task)
    db.refresh(removed_task)
    clipped_task_id = clipped_task.task_id
    removed_task_id = removed_task.task_id

    preview = annotation_repository.get_resampling_impact(db, [media.media_id], 8000)
    assert preview.removed_annotation_count == 2
    assert preview.clipped_annotation_count == 1
    assert preview.affected_media_count == 1

    late_annotation = Annotation(
        media_id=media.media_id,
        creator_id=1,
        sound_id=1,
        min_x=5,
        max_x=6,
        min_y=7500,
        max_y=9000,
    )
    db.add(late_annotation)
    db.commit()
    db.refresh(late_annotation)

    execution_impact = annotation_repository.get_resampling_impact(db, [media.media_id], 8000)
    applied = annotation_repository.apply_resampling_frequency_ceiling(db, media.media_id, 8000)
    assert applied == execution_impact
    assert applied.clipped_annotation_count == preview.clipped_annotation_count + 1
    db.commit()

    assert db.get(Annotation, in_range_id).max_y == 5000
    clipped_after = db.get(Annotation, clipped_id)
    assert clipped_after.max_y == 8000
    assert clipped_after.uuid == clipped_uuid
    assert clipped_after.sound_id == clipped_sound_id
    assert clipped_after.comments == clipped_comments
    assert db.get(Annotation, late_annotation.annotation_id).max_y == 8000
    assert db.get(Annotation, boundary_id).max_y == 8000
    assert db.get(Annotation, removed_id) is None
    assert db.get(Annotation, high_removed_id) is None
    assert db.get(AnnotationReview, (clipped_id, 1)) is not None
    assert db.get(AnnotationReview, (removed_id, 1)) is None
    assert db.get(Task, clipped_task_id) is not None
    removed_annotation_task = db.get(Task, removed_task_id)
    assert removed_annotation_task is not None
    assert removed_annotation_task.annotation_id is None
