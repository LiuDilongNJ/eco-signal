"""Tests for audio resampling jobs endpoint."""

import datetime
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import (
    Annotation,
    AudioSetting,
    Collection,
    Media,
    MediaCollection,
    Project,
    ProjectCollection,
    SoundClassification,
)
from tests.utils.utils import random_lower_string


def _create_audio_fixture(db: Session, sampling_rate_hz: int = 48000) -> tuple[Media, Project, Collection]:
    sound = db.get(SoundClassification, 1)
    if not sound:
        sound = SoundClassification(sound_id=1, name="biophony")
        db.add(sound)
        db.commit()

    project = Project(
        name=f"resample_proj_{random_lower_string()[:6]}",
        url=f"https://example.com/{random_lower_string()[:8]}",
        creator_id=1,
        public=True,
        active=True,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    col = Collection(
        name=f"resample_col_{random_lower_string()[:6]}",
        public_access=True,
        public_tags=True,
        creator_id=1,
    )
    db.add(col)
    db.commit()
    db.refresh(col)

    pc = ProjectCollection(project_id=project.project_id, collection_id=col.collection_id)
    db.add(pc)

    audio_setting = AudioSetting(
        sampling_rate_hz=sampling_rate_hz,
        bit_depth=16,
        channel_num=1,
        duration_s=5.0,
    )
    db.add(audio_setting)
    db.commit()
    db.refresh(audio_setting)

    media = Media(
        name=f"test_{random_lower_string()[:6]}.wav",
        filename="test.wav",
        directory=None,
        uploader_id=1,
        media_type="audio",
        is_metadata=False,
        audio_setting_id=audio_setting.audio_setting_id,
        date_time=datetime.datetime.now(datetime.UTC),
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    mc = MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=1)
    db.add(mc)
    db.commit()

    return media, project, col


def test_create_audio_resampling_unauthorized(client: TestClient) -> None:
    response = client.post(
        "/api/v1/audio-resampling-jobs?project_id=1",
        json={"media_ids": [1], "target_sampling_rate_hz": 16000},
    )
    assert response.status_code == 401


def test_audio_resampling_dry_run_previews_affected_annotations(
    client: TestClient, superuser_token_headers: dict, db: Session
) -> None:
    media, project, col = _create_audio_fixture(db, sampling_rate_hz=48000)

    # Add 2 annotations: one within 8000 Hz, one exceeding 8000 Hz
    ann_ok = Annotation(
        media_id=media.media_id,
        creator_id=1,
        sound_id=1,
        min_x=0.0,
        max_x=1.0,
        min_y=1000.0,
        max_y=5000.0,
    )
    ann_exceed = Annotation(
        media_id=media.media_id,
        creator_id=1,
        sound_id=1,
        min_x=1.0,
        max_x=2.0,
        min_y=2000.0,
        max_y=12000.0,
    )
    db.add(ann_ok)
    db.add(ann_exceed)
    db.commit()

    # Dry run with target 16000 Hz (Nyquist = 8000 Hz)
    response = client.post(
        f"/api/v1/audio-resampling-jobs?project_id={project.project_id}&dry_run=true",
        headers=superuser_token_headers,
        json={"media_ids": [media.media_id], "target_sampling_rate_hz": 16000},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["queue_id"] is None
    assert data["accepted_media_ids"] == [media.media_id]
    assert data["rejected"] == []
    assert data["affected_annotation_count"] == 1
    assert data["affected_media_count"] == 1


@patch("app.api.routes.audio_resampling_jobs.media_service.create_audio_resampling_job")
def test_audio_resampling_create_job_enqueues_task(
    mock_create_job,
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    media, project, col = _create_audio_fixture(db, sampling_rate_hz=48000)
    mock_queue = MagicMock(queue_id=88)
    mock_create_job.return_value = mock_queue

    response = client.post(
        f"/api/v1/audio-resampling-jobs?project_id={project.project_id}",
        headers=superuser_token_headers,
        json={"media_ids": [media.media_id], "target_sampling_rate_hz": 16000},
    )
    assert response.status_code == 202
    data = response.json()["data"]
    assert data["queue_id"] == 88
    assert data["accepted_media_ids"] == [media.media_id]
    assert data["affected_annotation_count"] == 0
    mock_create_job.assert_called_once()


def test_audio_resampling_rejects_rate_higher_than_current(
    client: TestClient, superuser_token_headers: dict, db: Session
) -> None:
    media, project, col = _create_audio_fixture(db, sampling_rate_hz=24000)

    response = client.post(
        f"/api/v1/audio-resampling-jobs?project_id={project.project_id}",
        headers=superuser_token_headers,
        json={"media_ids": [media.media_id], "target_sampling_rate_hz": 48000},
    )
    assert response.status_code == 202
    data = response.json()["data"]
    assert data["queue_id"] is None
    assert data["accepted_media_ids"] == []
    assert len(data["rejected"]) == 1
    assert data["rejected"][0]["status_code"] == 422
    assert "exceed the current sampling rate" in data["rejected"][0]["message"]
