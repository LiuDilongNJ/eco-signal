"""
Tests for recording detail page APIs:
  C1 - GET /media/{id} labels filtered by current user
  C2 - GET /media (list) labels filtered by current user
  A1 - enhanced GET /media/{id} response (previews, names, collection/project)
  B1 - audio streaming  GET /media/{id}/audio
  B2 - spectrogram      GET /media/{id}/spectrogram
  B3 - FFT preferences  GET/PUT /media/{id}/preferences
  B4 - media navigation GET /media/{id}/navigation-items
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Collection, Media, MediaCollection, AudioSetting,
    Permission, UserPermission, Role, Project, ProjectCollection
)
from app.models.label import Label, LabelMedia
from app.models.media import Preview
from app.models.site import Site
from app.models.user import User
from tests.utils.utils import random_lower_string


# Shared helpers

def _make_role(db: Session, name: str | None = None) -> Role:
    role = Role(name=name or f"role_{random_lower_string()[:8]}")
    db.add(role)
    db.flush()
    return role


def _make_user(db: Session, role: Role, is_admin: bool = False) -> User:
    admin_role = db.exec(select(Role).where(Role.name == "Administrator")).first()
    r = admin_role if is_admin else role
    u = User(
        username=f"u_{random_lower_string()[:8]}",
        email=f"{random_lower_string()[:8]}@t.com",
        password="hashed",
        name="Test",
        role_id=r.role_id,
        active=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_collection(db: Session, user_id: int, public_access: bool = True) -> Collection:
    col = Collection(
        name=f"col_{random_lower_string()[:6]}",
        creator_id=user_id,
        public_access=public_access,
    )
    db.add(col)
    db.flush()
    project = Project(
        name=f"proj_{random_lower_string()[:6]}",
        url=f"https://recording-{random_lower_string()[:8]}.example",
        creator_id=user_id,
        public=True,
    )
    db.add(project)
    db.flush()
    db.add(ProjectCollection(project_id=project.project_id, collection_id=col.collection_id))
    db.flush()
    return col


def _project_id_for_media(db: Session, media_id: int) -> int:
    project_id = db.exec(
        select(ProjectCollection.project_id)
        .join(MediaCollection, MediaCollection.collection_id == ProjectCollection.collection_id)
        .where(MediaCollection.media_id == media_id)
    ).first()
    assert project_id is not None
    return project_id


def _media_project_params(db: Session, media_id: int) -> dict[str, int]:
    return {"project_id": _project_id_for_media(db, media_id)}


def _make_audio_setting(
    db: Session,
    duration_s: float = 10.0,
    channels: int = 1,
    sample_rate: int = 44100,
) -> AudioSetting:
    s = AudioSetting(sampling_rate_hz=sample_rate, bit_depth=16, channel_num=channels, duration_s=duration_s)
    db.add(s)
    db.flush()
    return s


def _make_media(db: Session, collection: Collection, user_id: int,
                audio_setting: AudioSetting | None = None, filename: str | None = None) -> Media:
    # audio_type requires an audio_setting per DB constraint; use metadata if none provided
    if audio_setting is None:
        audio_setting = _make_audio_setting(db)
    m = Media(
        name=f"rec_{random_lower_string()[:6]}.wav",
        uploader_id=user_id,
        creator_id=user_id,
        media_type="audio",
        filename=filename or f"{random_lower_string()[:8]}.wav",
        directory=1,
        audio_setting_id=audio_setting.audio_setting_id,
    )
    db.add(m)
    db.flush()
    db.add(MediaCollection(media_id=m.media_id, collection_id=collection.collection_id, added_by=user_id))
    db.flush()
    return m


def _grant_audio_read(db: Session, user_id: int, collection_id: int) -> None:
    project = Project(name=f"proj_{random_lower_string()[:6]}", creator_id=user_id, url="https://recording.example")
    db.add(project)
    db.flush()
    db.add(ProjectCollection(project_id=project.project_id, collection_id=collection_id))
    db.flush()
    perm = db.exec(select(Permission).where(Permission.name == "audio:read")).first()
    if not perm:
        perm = Permission(name="audio:read", resource_type="audio", action="read")
        db.add(perm)
        db.flush()
    db.add(UserPermission(user_id=user_id, project_id=project.project_id, collection_id=collection_id, permission_id=perm.permission_id))
    db.flush()



class TestMediaDetailLabels:
    """C1: labels field in GET /media/{id} is per-user."""

    def test_get_media_labels_empty_when_unset(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """When no labels are associated, response returns an empty list."""
        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=1, audio_setting=aset)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}",
            headers=superuser_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["labels"] == []

    def test_get_media_labels_returns_current_user_labels(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """labels field returns only the current user's labels."""
        # Get the admin user (superuser)
        from app.models.user import User as UserModel
        admin = db.exec(select(UserModel).where(UserModel.role_id == 1)).first()

        col = _make_collection(db, user_id=admin.user_id, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=admin.user_id, audio_setting=aset)

        # Use built-in 'tagged' label (id=2 from data.sql)
        tagged_label = db.exec(select(Label).where(Label.name == "tagged")).first()
        if not tagged_label:
            tagged_label = Label(name="tagged", creator_id=admin.user_id)
            db.add(tagged_label)
            db.flush()

        db.add(LabelMedia(media_id=media.media_id, user_id=admin.user_id, label_id=tagged_label.label_id))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}",
            headers=superuser_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert "tagged" in data["labels"]
        assert data["labels"] == ["tagged"]

    def test_get_media_labels_not_leaked_across_users(
        self, client: TestClient, db: Session, superuser_token_headers: dict, normal_user_token_headers: dict
    ) -> None:
        """Labels from user A should not appear in user B's response."""
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        normal = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()

        col = _make_collection(db, user_id=admin.user_id, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=admin.user_id, audio_setting=aset)

        reviewed_label = db.exec(select(Label).where(Label.name == "reviewed")).first()
        if not reviewed_label:
            reviewed_label = Label(name="reviewed", creator_id=admin.user_id)
            db.add(reviewed_label)
            db.flush()

        # Only admin has 'reviewed' label
        db.add(LabelMedia(media_id=media.media_id, user_id=admin.user_id, label_id=reviewed_label.label_id))
        db.commit()

        # normal user should NOT see admin's label
        _grant_audio_read(db, normal.user_id, col.collection_id)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}",
            headers=normal_user_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["labels"] == []



class TestMediaListLabels:
    """C2: labels in GET /media list are per-user."""

    def test_list_media_labels_empty_when_unset(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """When no labels, list returns an empty label list per media."""
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        col = _make_collection(db, user_id=admin.user_id, public_access=True)

        from app.models.project import Project, ProjectCollection
        proj = Project(name=f"p_{random_lower_string()[:6]}", url="http://x.com", creator_id=1)
        db.add(proj)
        db.flush()
        db.add(ProjectCollection(project_id=proj.project_id, collection_id=col.collection_id))
        db.flush()

        _make_media(db, col, user_id=admin.user_id)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media?project_id={proj.project_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        items = r.json()["data"]
        assert len(items) > 0
        for item in items:
            assert item["labels"] == []

    def test_list_media_labels_user_specific(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """Labels in list only reflect the requesting user's labels."""
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        col = _make_collection(db, user_id=admin.user_id, public_access=True)

        from app.models.project import Project, ProjectCollection
        proj = Project(name=f"p_{random_lower_string()[:6]}", url="http://x.com", creator_id=1)
        db.add(proj)
        db.flush()
        db.add(ProjectCollection(project_id=proj.project_id, collection_id=col.collection_id))
        db.flush()

        media = _make_media(db, col, user_id=admin.user_id)

        tagged_label = db.exec(select(Label).where(Label.name == "tagged")).first()
        if not tagged_label:
            tagged_label = Label(name="tagged", creator_id=admin.user_id)
            db.add(tagged_label)
            db.flush()

        db.add(LabelMedia(media_id=media.media_id, user_id=admin.user_id, label_id=tagged_label.label_id))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media?project_id={proj.project_id}&collection_id={col.collection_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        items = r.json()["data"]
        found = next((i for i in items if i["media_id"] == media.media_id), None)
        assert found is not None
        assert "tagged" in found["labels"]



class TestMediaDetailEnhanced:
    """A1: GET /media/{id} returns enhanced fields."""

    def test_get_media_detail_has_audio_url(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=1, audio_setting=aset)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}",
            headers=superuser_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert "audio_url" in data
        assert f"/media/{media.media_id}/audio" in data["audio_url"]

    def test_get_media_detail_has_collection_info(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=1, audio_setting=aset)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}",
            headers=superuser_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["collection_id"] == col.collection_id
        assert data["collection_name"] == col.name

    def test_get_media_detail_has_project_info(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        from app.models.project import Project, ProjectCollection
        col = _make_collection(db, user_id=1, public_access=True)
        proj = Project(name=f"TestProj_{random_lower_string()[:6]}", url="http://x.com", creator_id=1)
        db.add(proj)
        db.flush()
        db.add(ProjectCollection(project_id=proj.project_id, collection_id=col.collection_id))
        db.flush()
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=1, audio_setting=aset)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}",
            headers=superuser_token_headers,
            params={"project_id": proj.project_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["project_id"] == proj.project_id
        assert data["project_name"] == proj.name

    def test_get_media_detail_has_previews(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=1, audio_setting=aset)

        preview = Preview(media_id=media.media_id, filename="spec.png", type="spectrogram")
        db.add(preview)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}",
            headers=superuser_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data["previews"]) == 1
        p = data["previews"][0]
        assert p["type"] == "spectrogram"
        assert p["preview_id"] == preview.preview_id
        assert "audio" not in p["url"]  # URL should point to previews endpoint

    def test_get_media_detail_has_site_name(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        site = Site(name="My Site", creator_id=1)
        db.add(site)
        db.flush()
        aset = _make_audio_setting(db)
        media = Media(
            name="test.wav", media_type="audio", uploader_id=1, creator_id=1,
            filename="test.wav", directory=1,
            audio_setting_id=aset.audio_setting_id,
            site_id=site.site_id,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=1))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}",
            headers=superuser_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["site_name"] == "My Site"

    def test_get_media_detail_permission_denied(
        self, client: TestClient, db: Session, normal_user_token_headers: dict
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=False)
        media = _make_media(db, col, user_id=1)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}",
            headers=normal_user_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        assert r.status_code == 403

    def test_get_media_detail_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        r = client.get(
            f"{settings.API_V1_STR}/media/99999999",
            headers=superuser_token_headers,
            params={"project_id": 1},
        )
        assert r.status_code == 404

    def test_get_media_detail_anonymous_public_collection_allowed(
        self, client: TestClient, db: Session
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        media = _make_media(db, col, user_id=1, audio_setting=_make_audio_setting(db))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}",
            params=_media_project_params(db, media.media_id),
        )
        assert r.status_code == 200



class TestAudioStreaming:
    """B1: Audio streaming endpoint."""

    def test_audio_anonymous_public_collection_allowed(
        self, client: TestClient, db: Session
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=1, audio_setting=aset)
        db.commit()

        r = client.get(f"{settings.API_V1_STR}/media/{media.media_id}/audio", params=_media_project_params(db, media.media_id))
        # Anonymous should pass permission check for public collections and reach file/generation path.
        assert r.status_code in (200, 404, 500)
        assert r.status_code not in (401, 403)

    def test_audio_media_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        r = client.get(f"{settings.API_V1_STR}/media/99999999/audio", headers=superuser_token_headers, params={"project_id": 1})
        assert r.status_code == 404

    def test_audio_no_file_on_disk_returns_404(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """When media exists but the audio file is not on disk, return 404."""
        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=1, audio_setting=aset, filename="nonexistent_file.wav")
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/audio",
            headers=superuser_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        assert r.status_code == 404
        assert "Audio media not found on server" in (r.json().get("message") or r.json().get("detail", ""))

    def test_audio_permission_denied_for_private_collection(
        self, client: TestClient, db: Session, normal_user_token_headers: dict
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=False)
        media = _make_media(db, col, user_id=1)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/audio",
            headers=normal_user_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        assert r.status_code == 403

    def test_audio_anonymous_private_collection_forbidden(
        self, client: TestClient, db: Session
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=False)
        media = _make_media(db, col, user_id=1)
        db.commit()

        r = client.get(f"{settings.API_V1_STR}/media/{media.media_id}/audio", params=_media_project_params(db, media.media_id))
        assert r.status_code == 403

    def test_audio_accessible_for_public_collection(
        self, client: TestClient, db: Session, normal_user_token_headers: dict
    ) -> None:
        """User can access audio from a public collection (will get 404 for no file, not 403)."""
        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=1, audio_setting=aset, filename="public_sound.wav")
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/audio",
            headers=normal_user_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        # Should be 404 (no file on disk), not 403
        assert r.status_code in (200, 404)
        if r.status_code == 404:
            assert "Audio media not found on server" in (r.json().get("message") or r.json().get("detail", ""))

    def test_audio_stream_uses_flac_media_type_for_new_uploads(
        self, client: TestClient, db: Session, superuser_token_headers: dict, tmp_path: Path
    ) -> None:
        """Direct streaming keeps the FLAC MIME type for normalized uploads."""
        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=1, audio_setting=aset, filename="normalized.flac")
        db.commit()

        from app.media_paths import logical_audio_media_path

        audio_file = tmp_path / logical_audio_media_path(col.collection_id, media.directory or "", "normalized.flac")
        audio_file.parent.mkdir(parents=True, exist_ok=True)
        audio_file.write_bytes(b"fLaC")
        original_media_root = settings.MEDIA_ROOT
        settings.MEDIA_ROOT = str(tmp_path)
        try:
            r = client.get(
                f"{settings.API_V1_STR}/media/{media.media_id}/audio",
                headers=superuser_token_headers,
                params=_media_project_params(db, media.media_id),
            )
        finally:
            settings.MEDIA_ROOT = original_media_root

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("audio/flac")

    def test_audio_stream_keeps_wav_media_type_for_wav_records(
        self, client: TestClient, db: Session, superuser_token_headers: dict, tmp_path: Path
    ) -> None:
        """WAV records stream with the WAV MIME type."""
        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=1, audio_setting=aset, filename="source.wav")
        db.commit()

        from app.media_paths import logical_audio_media_path

        audio_file = tmp_path / logical_audio_media_path(col.collection_id, media.directory or "", "source.wav")
        audio_file.parent.mkdir(parents=True, exist_ok=True)
        audio_file.write_bytes(b"RIFF")
        original_media_root = settings.MEDIA_ROOT
        settings.MEDIA_ROOT = str(tmp_path)
        try:
            r = client.get(
                f"{settings.API_V1_STR}/media/{media.media_id}/audio",
                headers=superuser_token_headers,
                params=_media_project_params(db, media.media_id),
            )
        finally:
            settings.MEDIA_ROOT = original_media_root

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("audio/wav")

    def test_audio_bandpass_filters_with_sox_sinc(
        self, client: TestClient, db: Session, superuser_token_headers: dict, tmp_path: Path
    ) -> None:
        import io

        import numpy as np
        import soundfile as sf

        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db, duration_s=0.5, channels=2, sample_rate=48000)
        media = _make_media(db, col, user_id=1, audio_setting=aset, filename="band.wav")
        db.commit()

        sr = 48000
        duration_s = 0.5
        t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
        low = 0.5 * np.sin(2 * np.pi * 500 * t)
        high = 0.5 * np.sin(2 * np.pi * 10000 * t)
        stereo = np.stack([low + high, low + high], axis=1).astype(np.float32)

        from app.media_paths import logical_audio_media_path

        audio_file = tmp_path / logical_audio_media_path(col.collection_id, media.directory or "", "band.wav")
        audio_file.parent.mkdir(parents=True, exist_ok=True)
        sf.write(audio_file, stereo, sr, format="WAV", subtype="PCM_16")
        original_media_root = settings.MEDIA_ROOT
        settings.MEDIA_ROOT = str(tmp_path)
        try:
            params = _media_project_params(db, media.media_id)
            params.update({"format": "wav", "channel": 1, "min_freq": 8000, "max_freq": 12000, "filter": True})
            r = client.get(
                f"{settings.API_V1_STR}/media/{media.media_id}/audio",
                headers=superuser_token_headers,
                params=params,
            )
            params_full = dict(params)
            params_full.update({"min_freq": 0, "max_freq": 24000})
            r_full = client.get(
                f"{settings.API_V1_STR}/media/{media.media_id}/audio",
                headers=superuser_token_headers,
                params=params_full,
            )
        finally:
            settings.MEDIA_ROOT = original_media_root

        assert r.status_code == 200
        assert r_full.status_code == 200
        assert r.content != r_full.content

        filtered, _ = sf.read(io.BytesIO(r.content), dtype="float32")
        full, _ = sf.read(io.BytesIO(r_full.content), dtype="float32")
        assert float(np.std(filtered)) < float(np.std(full)) * 0.75


class TestAudioFreqHelpers:
    def test_normalize_and_full_spectrum(self) -> None:
        from app.services import media_service

        assert media_service._normalize_detail_freq_band(44100, 0, None) == (0, 22050)
        assert media_service._normalize_detail_freq_band(44100, 8647, 11324) == (8647, 11324)
        assert media_service._normalize_detail_freq_band(44100, 23000, None) == (23000, 23000)

    """B2: Spectrogram generation endpoint."""

    @pytest.mark.parametrize(
        "params",
        [
            {"width": 99},
            {"height": 2049},
            {"width": 4096, "height": 2048},
            {"fft_size": 300},
        ],
    )
    def test_spectrogram_rejects_unsafe_render_parameters(
        self, client: TestClient, params: dict[str, int]
    ) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/media/1/spectrogram",
            params={"project_id": 1, **params},
        )
        assert response.status_code == 422

    def test_spectrogram_anonymous_public_collection_allowed(
        self, client: TestClient, db: Session
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=1, audio_setting=aset)
        db.commit()

        r = client.get(f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram", params=_media_project_params(db, media.media_id))
        # Anonymous should pass permission check for public collections and reach file/generation path.
        assert r.status_code in (200, 404, 500)
        assert r.status_code not in (401, 403)

    def test_spectrogram_media_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        r = client.get(f"{settings.API_V1_STR}/media/99999999/spectrogram", headers=superuser_token_headers, params={"project_id": 1})
        assert r.status_code == 404

    def test_spectrogram_no_file_on_disk_returns_404(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=1, audio_setting=aset, filename="no_such_file.wav")
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram",
            headers=superuser_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        assert r.status_code == 404
        assert "Audio media not found on server" in (r.json().get("message") or r.json().get("detail", ""))

    def test_spectrogram_permission_denied(
        self, client: TestClient, db: Session, normal_user_token_headers: dict
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=False)
        media = _make_media(db, col, user_id=1)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram",
            headers=normal_user_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        assert r.status_code == 403

    def test_spectrogram_anonymous_private_collection_forbidden(
        self, client: TestClient, db: Session
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=False)
        media = _make_media(db, col, user_id=1)
        db.commit()

        r = client.get(f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram", params=_media_project_params(db, media.media_id))
        assert r.status_code == 403

    def test_spectrogram_accepts_query_params(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """Verify all query params are accepted (response may be 404 due to missing file)."""
        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=1, audio_setting=aset)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram"
            f"?start_time=0&end_time=5&min_freq=0&max_freq=8000&fft_size=2048&channel=1&width=800&height=300",
            headers=superuser_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        # Either 404 (no file) or 200 (PNG); never 422 (bad params)
        assert r.status_code in (200, 404, 500)
        assert r.status_code != 422

    def test_spectrogram_without_end_time_renders_dynamic_output(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        from app.services import media_service
        import numpy as np
        import soundfile as sf

        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db, duration_s=1.0, sample_rate=48000)
        media = _make_media(db, col, user_id=1, audio_setting=aset, filename="static.flac")
        db.add(
            Preview(
                media_id=media.media_id,
                filename="static_player_s.png",
                type="spectrogram",
            )
        )
        db.commit()

        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_dir = tmp_path / "sounds" / str(col.collection_id) / "1"
        audio_dir.mkdir(parents=True, exist_ok=True)
        sf.write(audio_dir / "static.flac", np.zeros((48000, 1), dtype=np.float32), 48000, format="FLAC")
        preview_dir = tmp_path / "images" / str(col.collection_id) / "1"
        preview_dir.mkdir(parents=True, exist_ok=True)
        (preview_dir / "static_player_s.png").write_bytes(b"\x89PNG\r\nstatic")
        monkeypatch.setattr(
            media_service,
            "generate_spectrogram_png",
            lambda **_kwargs: b"\x89PNG\r\ndynamic",
        )

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram",
            headers=superuser_token_headers,
            params=_media_project_params(db, media.media_id),
        )

        assert r.status_code == 200
        assert r.content == b"\x89PNG\r\ndynamic"
        assert r.headers["content-type"].startswith("image/png")

    def test_spectrogram_without_end_time_does_not_create_player_preview(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        from app.services import media_service

        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db, duration_s=1.0, sample_rate=48000)
        media = _make_media(db, col, user_id=1, audio_setting=aset, filename="lazy.flac")
        db.commit()

        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_dir = tmp_path / "sounds" / str(col.collection_id) / "1"
        audio_dir.mkdir(parents=True, exist_ok=True)
        import numpy as np
        import soundfile as sf

        sf.write(audio_dir / "lazy.flac", np.zeros((48000, 1), dtype=np.float32), 48000, format="FLAC")
        monkeypatch.setattr(
            media_service,
            "generate_spectrogram_png",
            lambda *_args, **_kwargs: b"\x89PNG\r\nlazy",
        )

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram",
            headers=superuser_token_headers,
            params=_media_project_params(db, media.media_id),
        )

        preview = db.exec(
            select(Preview).where(
                Preview.media_id == media.media_id,
                Preview.type == "spectrogram",
                Preview.filename.like("%_player_s.png"),
            )
        ).first()

        assert r.status_code == 200
        assert r.content == b"\x89PNG\r\nlazy"
        assert preview is None

    def test_spectrogram_with_end_time_keeps_dynamic_generation(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        aset = _make_audio_setting(db)
        media = _make_media(db, col, user_id=1, audio_setting=aset, filename="dynamic.flac")
        db.commit()

        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_dir = tmp_path / "sounds" / str(col.collection_id) / "1"
        audio_dir.mkdir(parents=True, exist_ok=True)
        import numpy as np
        import soundfile as sf

        samples = np.zeros((44100, 1), dtype=np.float32)
        sf.write(audio_dir / "dynamic.flac", samples, 44100, format="FLAC")

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/spectrogram"
            f"?start_time=0&end_time=5&width=800&height=300",
            headers=superuser_token_headers,
            params=_media_project_params(db, media.media_id),
        )

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/png")
        assert r.content.startswith(b"\x89PNG\r\n")



class TestMediaNavigation:
    """B4: Media navigation within a collection."""

    def _make_three_media(self, db: Session, col: Collection, user_id: int) -> list[Media]:
        media_list = []
        for _ in range(3):
            m = _make_media(db, col, user_id=user_id)
            media_list.append(m)
        db.commit()
        return sorted(media_list, key=lambda x: x.media_id)

    def test_navigation_requires_auth(self, client: TestClient) -> None:
        r = client.get(f"{settings.API_V1_STR}/media/1/navigation-items?collection_id=1")
        assert r.status_code == 401

    def test_navigation_missing_collection_id(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        r = client.get(f"{settings.API_V1_STR}/media/1/navigation-items", headers=superuser_token_headers)
        assert r.status_code == 422

    def test_navigation_middle_media_has_prev_and_next(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        items = self._make_three_media(db, col, user_id=1)
        middle = items[1]

        r = client.get(
            f"{settings.API_V1_STR}/media/{middle.media_id}/navigation-items?collection_id={col.collection_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["prev"] is not None
        assert data["next"] is not None
        assert data["prev"]["media_id"] == items[0].media_id
        assert data["next"]["media_id"] == items[2].media_id

    def test_navigation_first_media_has_no_prev(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        items = self._make_three_media(db, col, user_id=1)
        first = items[0]

        r = client.get(
            f"{settings.API_V1_STR}/media/{first.media_id}/navigation-items?collection_id={col.collection_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["prev"] is None
        assert data["next"] is not None

    def test_navigation_last_media_has_no_next(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        items = self._make_three_media(db, col, user_id=1)
        last = items[-1]

        r = client.get(
            f"{settings.API_V1_STR}/media/{last.media_id}/navigation-items?collection_id={col.collection_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["prev"] is not None
        assert data["next"] is None

    def test_navigation_single_media_no_prev_no_next(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        media = _make_media(db, col, user_id=1)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/navigation-items?collection_id={col.collection_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["prev"] is None
        assert data["next"] is None

    def test_navigation_media_not_in_collection_returns_404(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        other_col = _make_collection(db, user_id=1, public_access=True)
        media = _make_media(db, col, user_id=1)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/navigation-items?collection_id={other_col.collection_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404

    def test_navigation_nav_items_contain_name(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """Navigation items include media name."""
        col = _make_collection(db, user_id=1, public_access=True)
        items = self._make_three_media(db, col, user_id=1)

        r = client.get(
            f"{settings.API_V1_STR}/media/{items[1].media_id}/navigation-items?collection_id={col.collection_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert "media_id" in data["prev"]
        assert "name" in data["prev"]



class TestPreviewServing:
    """Preview file serving endpoint."""

    def test_preview_requires_auth(self, client: TestClient) -> None:
        r = client.get(f"{settings.API_V1_STR}/media/1/previews/1")
        assert r.status_code == 401

    def test_preview_media_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        r = client.get(f"{settings.API_V1_STR}/media/99999999/previews/1", headers=superuser_token_headers, params={"project_id": 1})
        assert r.status_code == 404

    def test_preview_record_not_found(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        col = _make_collection(db, user_id=1, public_access=True)
        media = _make_media(db, col, user_id=1)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/previews/99999",
            headers=superuser_token_headers,
            params=_media_project_params(db, media.media_id),
        )
        assert r.status_code == 404

    def test_preview_wrong_media_returns_404(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """Preview belonging to different media returns 404."""
        col = _make_collection(db, user_id=1, public_access=True)
        media1 = _make_media(db, col, user_id=1)
        media2 = _make_media(db, col, user_id=1)

        preview = Preview(media_id=media2.media_id, filename="other.png", type="spectrogram")
        db.add(preview)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media1.media_id}/previews/{preview.preview_id}",
            headers=superuser_token_headers,
            params=_media_project_params(db, media1.media_id),
        )
        assert r.status_code == 404
