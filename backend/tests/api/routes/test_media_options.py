from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import Project, Collection, ProjectCollection
from app.models.media import Media, MediaCollection, AudioSetting


class TestMediaOptions:
    """Tests for media options dropdown endpoint."""

    def test_list_media_options_unauthorized(self, client: TestClient) -> None:
        """Dropdown options allow anonymous access and return a standard payload."""
        r = client.get(f"{settings.API_V1_STR}/media-options?project_id=1")
        assert r.status_code == 200
        assert isinstance(r.json()["data"], list)

    def test_list_media_options_missing_project_id(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Return 422 if project_id is missing."""
        r = client.get(
            f"{settings.API_V1_STR}/media-options",
            headers=superuser_token_headers
        )
        assert r.status_code == 422

    def test_list_media_options_admin_sees_all(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can see all media for a project across all collections."""
        # 1. Setup project and two collections
        project = Project(name="Admin Project", url="http://test.com", creator_id=1)
        db.add(project)
        db.commit()
        db.refresh(project)

        col1 = Collection(name="Coll 1", creator_id=1, public_access=True)
        col2 = Collection(name="Coll 2", creator_id=1, public_access=True)
        db.add(col1)
        db.add(col2)
        db.commit()
        db.refresh(col1)
        db.refresh(col2)

        db.add(ProjectCollection(project_id=project.project_id, collection_id=col1.collection_id))
        db.add(ProjectCollection(project_id=project.project_id, collection_id=col2.collection_id))
        db.commit()

        # 2. Create audio setting and media in each collection
        audio_setting = AudioSetting(duration_s=10.5, sampling_rate_hz=44100)
        db.add(audio_setting)
        db.commit()
        db.refresh(audio_setting)

        m1 = Media(
            filename="admin_m1.wav", 
            name="Admin M1", 
            media_type="audio", 
            uploader_id=1, 
            creator_id=1,
            audio_setting_id=audio_setting.audio_setting_id
        )
        m2 = Media(
            filename="admin_m2.wav", 
            name="Admin M2", 
            media_type="audio", 
            uploader_id=1, 
            creator_id=1,
            audio_setting_id=audio_setting.audio_setting_id
        )
        db.add(m1)
        db.add(m2)
        db.commit()
        db.refresh(m1)
        db.refresh(m2)

        db.add(MediaCollection(media_id=m1.media_id, collection_id=col1.collection_id, added_by=1))
        db.add(MediaCollection(media_id=m2.media_id, collection_id=col2.collection_id, added_by=1))
        db.commit()

        # 3. Request options as admin
        r = client.get(
            f"{settings.API_V1_STR}/media-options?project_id={project.project_id}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        # Should see both
        ids = [item["media_id"] for item in data]
        assert m1.media_id in ids
        assert m2.media_id in ids

    def test_list_media_options_name_filter(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Verify name filtering works (fuzzy match on name/filename)."""
        project = Project(name="Filter Project", url="http://test.com", creator_id=1)
        db.add(project)
        db.commit()
        db.refresh(project)

        col = Collection(name="Filter Coll", creator_id=1, public_access=True)
        db.add(col)
        db.commit()
        db.refresh(col)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=col.collection_id))

        audio_setting = AudioSetting(duration_s=5.0, sampling_rate_hz=44100)
        db.add(audio_setting)
        db.commit()
        db.refresh(audio_setting)

        m1 = Media(
            filename="matching_file.wav", 
            name="UniqueName", 
            media_type="audio", 
            uploader_id=1, 
            creator_id=1,
            audio_setting_id=audio_setting.audio_setting_id
        )
        m2 = Media(
            filename="other.wav", 
            name="Other", 
            media_type="audio", 
            uploader_id=1, 
            creator_id=1,
            audio_setting_id=audio_setting.audio_setting_id
        )
        db.add(m1)
        db.add(m2)
        db.commit()
        db.refresh(m1)
        db.refresh(m2)
        db.add(MediaCollection(media_id=m1.media_id, collection_id=col.collection_id, added_by=1))
        db.add(MediaCollection(media_id=m2.media_id, collection_id=col.collection_id, added_by=1))
        db.commit()

        # Filter by name
        r = client.get(
            f"{settings.API_V1_STR}/media-options?project_id={project.project_id}&name=Unique",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["media_id"] == m1.media_id

        # Filter by filename
        r = client.get(
            f"{settings.API_V1_STR}/media-options?project_id={project.project_id}&name=matching",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["media_id"] == m1.media_id
