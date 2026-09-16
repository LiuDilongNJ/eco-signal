"""Tests for audio resampling jobs endpoint."""

import datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Annotation,
    AudioSetting,
    Collection,
    Media,
    MediaCollection,
    Permission,
    Project,
    ProjectCollection,
    SoundClassification,
    User,
    UserPermission,
)
from tests.utils.utils import random_lower_string


def _create_audio_fixture(
    db: Session,
    sampling_rate_hz: int = 48000,
    codec: str | None = None,
) -> tuple[Media, Project, Collection]:
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
        file_metadata={"stored": {"codec": codec}} if codec else None,
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

    annotations = [
        Annotation(media_id=media.media_id, creator_id=1, sound_id=1, min_x=0, max_x=1, min_y=1000, max_y=5000),
        Annotation(media_id=media.media_id, creator_id=1, sound_id=1, min_x=1, max_x=2, min_y=7000, max_y=10000),
        Annotation(media_id=media.media_id, creator_id=1, sound_id=1, min_x=2, max_x=3, min_y=8000, max_y=10000),
        Annotation(media_id=media.media_id, creator_id=1, sound_id=1, min_x=3, max_x=4, min_y=9000, max_y=12000),
        Annotation(media_id=media.media_id, creator_id=1, sound_id=1, min_x=4, max_x=5, min_y=7000, max_y=8000),
    ]
    db.add_all(annotations)
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
    assert data["annotation_impact"] == {
        "max_frequency_hz": 8000.0,
        "removed_annotation_count": 2,
        "clipped_annotation_count": 1,
        "affected_media_count": 1,
    }


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
    assert data["annotation_impact"] == {
        "max_frequency_hz": 8000.0,
        "removed_annotation_count": 0,
        "clipped_annotation_count": 0,
        "affected_media_count": 0,
    }
    mock_create_job.assert_called_once()


def test_audio_resampling_preview_deduplicates_media_and_ignores_rejected_items(
    client: TestClient, superuser_token_headers: dict, db: Session
) -> None:
    media, project, _col = _create_audio_fixture(db, sampling_rate_hz=48000)
    db.add(Annotation(
        media_id=media.media_id,
        creator_id=1,
        sound_id=1,
        min_x=0,
        max_x=1,
        min_y=9000,
        max_y=12000,
    ))
    db.commit()

    response = client.post(
        f"/api/v1/audio-resampling-jobs?project_id={project.project_id}&dry_run=true",
        headers=superuser_token_headers,
        json={"media_ids": [media.media_id, media.media_id, 999999], "target_sampling_rate_hz": 16000},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["accepted_media_ids"] == [media.media_id]
    assert [item["media_id"] for item in data["rejected"]] == [999999]
    assert data["annotation_impact"]["removed_annotation_count"] == 1
    assert data["annotation_impact"]["clipped_annotation_count"] == 0


def test_audio_resampling_preview_counts_only_media_with_write_permission(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    accepted_media, project, accepted_collection = _create_audio_fixture(db)
    denied_media, _other_project, denied_collection = _create_audio_fixture(db)
    db.add(ProjectCollection(
        project_id=project.project_id,
        collection_id=denied_collection.collection_id,
    ))
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).one()
    permission = db.exec(select(Permission).where(Permission.name == "media:write")).one()
    db.add(UserPermission(
        user_id=user.user_id,
        project_id=project.project_id,
        collection_id=accepted_collection.collection_id,
        permission_id=permission.permission_id,
    ))
    db.add_all([
        Annotation(
            media_id=accepted_media.media_id,
            creator_id=1,
            sound_id=1,
            min_x=0,
            max_x=1,
            min_y=9000,
            max_y=12000,
        ),
        Annotation(
            media_id=denied_media.media_id,
            creator_id=1,
            sound_id=1,
            min_x=0,
            max_x=1,
            min_y=9000,
            max_y=12000,
        ),
    ])
    db.commit()

    response = client.post(
        f"/api/v1/audio-resampling-jobs?project_id={project.project_id}&dry_run=true",
        headers=normal_user_token_headers,
        json={
            "media_ids": [accepted_media.media_id, denied_media.media_id],
            "target_sampling_rate_hz": 16000,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["accepted_media_ids"] == [accepted_media.media_id]
    assert [item["media_id"] for item in data["rejected"]] == [denied_media.media_id]
    assert data["annotation_impact"]["removed_annotation_count"] == 1
    assert data["annotation_impact"]["affected_media_count"] == 1


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


def test_audio_resampling_rejects_rate_unsupported_by_audio_codec(
    client: TestClient, superuser_token_headers: dict, db: Session
) -> None:
    media, project, _col = _create_audio_fixture(db, sampling_rate_hz=48000, codec="opus")

    response = client.post(
        f"/api/v1/audio-resampling-jobs?project_id={project.project_id}&dry_run=true",
        headers=superuser_token_headers,
        json={"media_ids": [media.media_id], "target_sampling_rate_hz": 44100},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["accepted_media_ids"] == []
    assert data["rejected"] == [{
        "media_id": media.media_id,
        "status_code": 422,
        "message": "OPUS audio only supports target sampling rates: 8000, 12000, 16000, 24000, 48000 Hz",
    }]
