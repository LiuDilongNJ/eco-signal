"""
Test cases for media timeline route.
"""
from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Collection, Permission, Project, ProjectCollection, UserPermission
from app.models.media import AudioSetting, Media, MediaCollection, PhotoSetting
from app.models.site import IucnGet, Site
from app.repositories import user_repository
from app.schemas import UserCreate
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def create_test_collection(db: Session, creator_id: int = 1, **kwargs) -> Collection:
    """Create a test collection."""
    defaults = {
        "name": f"Timeline Collection {random_lower_string()[:8]}",
        "description": "Test description",
        "public_access": True,
        "public_tags": False,
        "creator_id": creator_id,
    }
    defaults.update(kwargs)
    collection = Collection(**defaults)
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


def create_test_project(db: Session, creator_id: int = 1, **kwargs) -> Project:
    """Create a test project."""
    defaults = {
        "name": f"Timeline Project {random_lower_string()[:8]}",
        "url": f"https://example.com/{random_lower_string()[:8]}",
        "description": "Test description",
        "public": True,
        "active": True,
        "creator_id": creator_id,
    }
    defaults.update(kwargs)
    project = Project(**defaults)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def create_user_with_headers(db: Session, client: TestClient, *, name: str = "Timeline User"):
    """Create a user and return (user, headers)."""
    email = random_email()
    password = "testpassword123"
    user_in = UserCreate(
        username=random_lower_string()[:20],
        name=name,
        email=email,
        password=password,
    )
    user = user_repository.create(session=db, obj_in=user_in)
    headers = user_authentication_headers(client=client, username=user.username, password=password)
    return user, headers


def grant_collection_read_permission(
    db: Session,
    *,
    user_id: int,
    collection_id: int,
    project_id: int | None = None,
) -> None:
    """Grant collection:read on one collection."""
    if project_id is None:
        project_ids = db.exec(
            select(ProjectCollection.project_id).where(
                ProjectCollection.collection_id == collection_id
            )
        ).all()
        assert len(project_ids) == 1
        project_id = project_ids[0]
    read_perm = db.exec(
        select(Permission).where(
            Permission.resource_type == "collection",
            Permission.action == "read",
        )
    ).one()
    db.add(
        UserPermission(
            user_id=user_id,
            project_id=project_id,
            collection_id=collection_id,
            permission_id=read_perm.permission_id,
        )
    )
    db.commit()


def grant_audio_read_permission(
    db: Session,
    *,
    user_id: int,
    collection_id: int,
    project_id: int | None = None,
) -> None:
    """Grant audio:read on one collection path."""
    if project_id is None:
        project_ids = db.exec(
            select(ProjectCollection.project_id).where(
                ProjectCollection.collection_id == collection_id
            )
        ).all()
        assert len(project_ids) == 1
        project_id = project_ids[0]
    read_perm = db.exec(
        select(Permission).where(
            Permission.resource_type == "audio",
            Permission.action == "read",
        )
    ).one()
    db.add(
        UserPermission(
            user_id=user_id,
            project_id=project_id,
            collection_id=collection_id,
            permission_id=read_perm.permission_id,
        )
    )
    db.commit()


def grant_project_audio_read_permission(
    db: Session,
    *,
    user_id: int,
    project_id: int,
) -> None:
    """Grant project-scoped audio:read."""
    read_perm = db.exec(
        select(Permission).where(
            Permission.resource_type == "audio",
            Permission.action == "read",
        )
    ).one()
    db.add(
        UserPermission(
            user_id=user_id,
            project_id=project_id,
            collection_id=None,
            permission_id=read_perm.permission_id,
        )
    )
    db.commit()


class TestMediaTimeline:
    """Tests for GET /media-timeline-items."""

    @staticmethod
    def _seed_timeline_media(
        db: Session,
        *,
        collection_ids: list[int],
        creator_id: int = 1,
        with_metadata: bool = True,
        site_name: str | None = None,
        realm_name: str | None = None,
    ) -> tuple[int, int | None]:
        realm_id = None
        if realm_name is not None:
            realm = IucnGet(pid=0, name=realm_name, level=1)
            db.add(realm)
            db.flush()
            realm_id = realm.iucn_get_id

        site = Site(
            name=site_name or f"Timeline Site {random_lower_string()[:6]}",
            creator_id=creator_id,
            realm_id=realm_id,
        )
        db.add(site)
        db.flush()

        audio_setting = AudioSetting(
            duration_s=120.0,
            sampling_rate_hz=44100,
            recording_gain_db=15,
        )
        db.add(audio_setting)
        db.flush()

        audio_media = Media(
            media_type="audio",
            filename=f"timeline_audio_{random_lower_string()[:6]}.wav",
            name="timeline_audio",
            creator_id=creator_id,
            uploader_id=creator_id,
            date_time=datetime(2026, 3, 17, 12, 0, 0),
            audio_setting_id=audio_setting.audio_setting_id,
            site_id=site.site_id,
            duty_cycle_recording=60,
            duty_cycle_period=600,
        )
        db.add(audio_media)
        db.flush()

        for collection_id in collection_ids:
            db.add(MediaCollection(media_id=audio_media.media_id, collection_id=collection_id, added_by=creator_id))

        metadata_id = None
        if with_metadata:
            metadata_media = Media(
                media_type="audio", is_metadata=True,
                filename=f"timeline_meta_{random_lower_string()[:6]}.csv",
                name="timeline_meta",
                creator_id=creator_id,
                uploader_id=creator_id,
                date_time=datetime(2026, 3, 17, 13, 0, 0),
                duty_cycle_recording=90,
                duty_cycle_period=900,
            )
            db.add(metadata_media)
            db.flush()
            db.add(
                MediaCollection(
                    media_id=metadata_media.media_id,
                    collection_id=collection_ids[0],
                    added_by=creator_id,
                )
            )
            metadata_id = metadata_media.media_id

        db.commit()
        return audio_media.media_id, metadata_id

    @staticmethod
    def _seed_photo_media(
        db: Session,
        *,
        collection_id: int,
        creator_id: int = 1,
        name: str = "timeline_photo",
    ) -> int:
        photo_setting = PhotoSetting()
        db.add(photo_setting)
        db.flush()

        photo_media = Media(
            media_type="photo",
            filename=f"{name}.jpg",
            name=name,
            creator_id=creator_id,
            uploader_id=creator_id,
            date_time=datetime(2026, 3, 17, 14, 0, 0),
            photo_setting_id=photo_setting.photo_setting_id,
        )
        db.add(photo_media)
        db.flush()
        db.add(
            MediaCollection(
                media_id=photo_media.media_id,
                collection_id=collection_id,
                added_by=creator_id,
            )
        )
        db.commit()
        return photo_media.media_id

    def test_media_timeline_anonymous_project_only_public_success(self, client: TestClient, db: Session) -> None:
        """Anonymous project-only timeline should aggregate public collections only."""
        project = create_test_project(db, public=True)
        public_collection = create_test_collection(db, public_access=True)
        private_collection = create_test_collection(db, public_access=False)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=public_collection.collection_id))
        db.add(ProjectCollection(project_id=project.project_id, collection_id=private_collection.collection_id))
        db.commit()

        public_audio_id, public_meta_id = self._seed_timeline_media(
            db,
            collection_ids=[public_collection.collection_id],
            realm_name="Freshwater",
        )
        private_audio_id, _ = self._seed_timeline_media(
            db,
            collection_ids=[private_collection.collection_id],
            site_name="Private Site",
        )

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={"project_id": project.project_id},
        )
        assert r.status_code == 200
        payload = r.json()["data"]
        assert payload["project_id"] == project.project_id
        assert payload["collection_id"] is None

        ids = {item["media_id"] for item in payload["items"]}
        assert public_audio_id in ids
        assert public_meta_id in ids
        assert private_audio_id not in ids

        audio_item = next(item for item in payload["items"] if item["media_id"] == public_audio_id)
        assert audio_item["realm"] == "Freshwater"
        assert audio_item["start_date"] == "2026-03-17 12:00:00"
        assert audio_item["end_date"] == "2026-03-17 12:02:00"
        assert audio_item["duration_s"] == 120.0
        assert audio_item["duty_cycle_period"] == 600

        meta_item = next(item for item in payload["items"] if item["media_id"] == public_meta_id)
        assert meta_item["is_metadata"] is True
        assert meta_item["item_count"] == 1
        assert meta_item["site_name"] == "not geo-referenced"
        assert meta_item["realm"] is None
        assert meta_item["duration_s"] is None
        assert meta_item["duty_cycle_period"] is None

        assert payload["time_range"]["min"] == "2026-02-28 00:00:00"
        assert payload["time_range"]["max"] == "2026-04-02 00:00:00"

    def test_media_timeline_project_only_private_anonymous_denied(self, client: TestClient, db: Session) -> None:
        """Anonymous users cannot access private project timeline scope."""
        project = create_test_project(db, public=False)
        collection = create_test_collection(db, public_access=False)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={"project_id": project.project_id},
        )
        assert r.status_code == 403

    def test_media_timeline_project_only_private_with_audio_permission(self, client: TestClient, db: Session) -> None:
        """Authenticated users should only see private-project media from audio-readable collections."""
        project = create_test_project(db, public=False)
        allowed_collection = create_test_collection(db, public_access=False)
        denied_collection = create_test_collection(db, public_access=False)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=allowed_collection.collection_id))
        db.add(ProjectCollection(project_id=project.project_id, collection_id=denied_collection.collection_id))
        db.commit()

        viewer, headers = create_user_with_headers(db, client, name="Timeline Viewer")
        grant_audio_read_permission(db, user_id=viewer.user_id, collection_id=allowed_collection.collection_id)

        allowed_audio_id, _ = self._seed_timeline_media(
            db,
            collection_ids=[allowed_collection.collection_id],
            creator_id=viewer.user_id,
        )
        denied_audio_id, _ = self._seed_timeline_media(
            db,
            collection_ids=[denied_collection.collection_id],
            creator_id=viewer.user_id,
        )

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={"project_id": project.project_id},
            headers=headers,
        )
        assert r.status_code == 200
        ids = {item["media_id"] for item in r.json()["data"]["items"]}
        assert allowed_audio_id in ids
        assert denied_audio_id not in ids

    def test_media_timeline_project_only_collection_read_without_audio_permission_denied(
        self, client: TestClient, db: Session
    ) -> None:
        """collection:read alone should not make timeline media visible."""
        project = create_test_project(db, public=False)
        collection = create_test_collection(db, public_access=False)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        viewer, headers = create_user_with_headers(db, client, name="Collection Only Viewer")
        grant_collection_read_permission(db, user_id=viewer.user_id, collection_id=collection.collection_id)
        self._seed_timeline_media(
            db,
            collection_ids=[collection.collection_id],
            creator_id=viewer.user_id,
        )

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={"project_id": project.project_id},
            headers=headers,
        )
        assert r.status_code == 403

    def test_media_timeline_project_only_project_audio_read_inherits_to_collections(
        self, client: TestClient, db: Session
    ) -> None:
        """Project-scoped audio:read should expose timeline media in child collections."""
        project = create_test_project(db, public=False)
        collection = create_test_collection(db, public_access=False)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        viewer, headers = create_user_with_headers(db, client, name="Project Audio Reader")
        grant_project_audio_read_permission(
            db, user_id=viewer.user_id, project_id=project.project_id
        )
        audio_id, _ = self._seed_timeline_media(
            db,
            collection_ids=[collection.collection_id],
            creator_id=viewer.user_id,
        )

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={"project_id": project.project_id},
            headers=headers,
        )
        assert r.status_code == 200
        ids = {item["media_id"] for item in r.json()["data"]["items"]}
        assert audio_id in ids

    def test_media_timeline_project_only_deduplicates_cross_collection_media(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict[str, str],
    ) -> None:
        """One media linked to two project collections should appear only once."""
        project = create_test_project(db, public=False)
        collection_a = create_test_collection(db, public_access=False)
        collection_b = create_test_collection(db, public_access=False)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection_a.collection_id))
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection_b.collection_id))
        db.commit()

        shared_audio_id, _ = self._seed_timeline_media(
            db,
            collection_ids=[collection_a.collection_id, collection_b.collection_id],
            with_metadata=False,
        )

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        ids = [item["media_id"] for item in r.json()["data"]["items"]]
        assert ids.count(shared_audio_id) == 1

    def test_media_timeline_collection_scope_success(self, client: TestClient, db: Session) -> None:
        """Collection-scoped timeline should preserve old behavior under the new media route."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        audio_id, meta_id = self._seed_timeline_media(
            db,
            collection_ids=[collection.collection_id],
            realm_name="Marine",
        )

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["collection_id"] == collection.collection_id

        ids = {item["media_id"] for item in data["items"]}
        assert audio_id in ids
        assert meta_id in ids

        audio_item = next(item for item in data["items"] if item["media_id"] == audio_id)
        assert audio_item["realm"] == "Marine"

    def test_media_timeline_collection_scope_private_with_audio_permission(self, client: TestClient, db: Session) -> None:
        """Collection-scoped private timeline still works with audio:read."""
        project = create_test_project(db, public=False)
        collection = create_test_collection(db, public_access=False)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        viewer, headers = create_user_with_headers(db, client, name="Private Timeline Reader")
        grant_audio_read_permission(db, user_id=viewer.user_id, collection_id=collection.collection_id)
        self._seed_timeline_media(db, collection_ids=[collection.collection_id], creator_id=viewer.user_id)

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
            headers=headers,
        )
        assert r.status_code == 200
        assert len(r.json()["data"]["items"]) >= 1

    def test_media_timeline_collection_scope_private_collection_read_without_audio_permission_denied(
        self, client: TestClient, db: Session
    ) -> None:
        """Collection-scoped private timeline requires audio:read, not collection:read."""
        project = create_test_project(db, public=False)
        collection = create_test_collection(db, public_access=False)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        viewer, headers = create_user_with_headers(db, client, name="Collection Reader")
        grant_collection_read_permission(db, user_id=viewer.user_id, collection_id=collection.collection_id)
        self._seed_timeline_media(db, collection_ids=[collection.collection_id], creator_id=viewer.user_id)

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
            headers=headers,
        )
        assert r.status_code == 403

    def test_media_timeline_collection_scope_mismatch_returns_400(self, client: TestClient, db: Session) -> None:
        """collection_id must belong to project_id."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        self._seed_timeline_media(db, collection_ids=[collection.collection_id])

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
        )
        assert r.status_code == 400

    def test_media_timeline_include_metadata_false(self, client: TestClient, db: Session) -> None:
        """include_metadata=false should exclude metadata items."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        audio_id, meta_id = self._seed_timeline_media(db, collection_ids=[collection.collection_id])

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
                "include_metadata": False,
            },
        )
        assert r.status_code == 200
        ids = {item["media_id"] for item in r.json()["data"]["items"]}
        assert audio_id in ids
        assert meta_id not in ids

    def test_media_timeline_default_groups_metadata_by_month(
        self, client: TestClient, db: Session
    ) -> None:
        """Default metadata granularity should return month-level display buckets."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        _, metadata_id = self._seed_timeline_media(db, collection_ids=[collection.collection_id])
        assert metadata_id is not None

        second_metadata = Media(
            media_type="audio", is_metadata=True,
            filename=f"timeline_meta_{random_lower_string()[:6]}.csv",
            name="timeline_meta_second",
            creator_id=1,
            uploader_id=1,
            date_time=datetime(2026, 3, 20, 10, 0, 0),
        )
        db.add(second_metadata)
        db.flush()
        db.add(
            MediaCollection(
                media_id=second_metadata.media_id,
                collection_id=collection.collection_id,
                added_by=1,
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
        )
        assert r.status_code == 200
        metadata_items = [
            item for item in r.json()["data"]["items"] if item["is_metadata"]
        ]
        assert len(metadata_items) == 1
        assert metadata_items[0]["item_count"] == 2
        assert metadata_items[0]["name"] == "Metadata (2)"
        assert metadata_items[0]["start_date"] == "2026-03-01 00:00:00"
        assert metadata_items[0]["end_date"] == "2026-04-01 00:00:00"
        assert metadata_items[0]["site_key"] == "nogeo"

    def test_media_timeline_overview_groups_metadata_by_media_type(
        self, client: TestClient, db: Session
    ) -> None:
        """Audio metadata and photo metadata in the same site/month must be
        aggregated into separate overview rows, each carrying its own media_type
        and item_count (regression guard for cross-type count merging)."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        # Audio metadata row (no site, same month as the photo metadata row below)
        _, audio_metadata_id = self._seed_timeline_media(db, collection_ids=[collection.collection_id])
        assert audio_metadata_id is not None

        # Photo metadata row: same is_metadata=True, same nogeo site, same month
        photo_setting = PhotoSetting(exposure_ms=8.5, aperture=2.8, iso=400)
        db.add(photo_setting)
        db.flush()
        photo_metadata = Media(
            media_type="photo", is_metadata=True,
            filename=f"timeline_photo_meta_{random_lower_string()[:6]}.csv",
            name="timeline_photo_meta",
            creator_id=1,
            uploader_id=1,
            date_time=datetime(2026, 3, 18, 9, 0, 0),
            photo_setting_id=photo_setting.photo_setting_id,
        )
        db.add(photo_metadata)
        db.flush()
        db.add(
            MediaCollection(
                media_id=photo_metadata.media_id,
                collection_id=collection.collection_id,
                added_by=1,
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
        )
        assert r.status_code == 200
        metadata_items = [
            item for item in r.json()["data"]["items"] if item["is_metadata"]
        ]
        # Must stay split by media_type instead of merging into one "audio" bucket.
        assert len(metadata_items) == 2
        by_type = {item["media_type"]: item for item in metadata_items}
        assert set(by_type) == {"audio", "photo"}
        assert by_type["audio"]["item_count"] == 1
        assert by_type["photo"]["item_count"] == 1

        # media_type=photo overview must only surface the photo metadata bucket.
        r_photo = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
                "media_type": "photo",
            },
        )
        assert r_photo.status_code == 200
        photo_metadata_items = [
            item for item in r_photo.json()["data"]["items"] if item["is_metadata"]
        ]
        assert len(photo_metadata_items) == 1
        assert photo_metadata_items[0]["media_type"] == "photo"
        assert photo_metadata_items[0]["item_count"] == 1

    def test_media_timeline_detail_returns_site_window_exact_rows(
        self, client: TestClient, db: Session
    ) -> None:
        """Detail mode should return exact rows for one site and time window."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        audio_id, metadata_id = self._seed_timeline_media(db, collection_ids=[collection.collection_id])
        assert metadata_id is not None
        audio_site_id = db.exec(select(Media.site_id).where(Media.media_id == audio_id)).one()

        site_resp = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
                "response_mode": "detail",
                "site_key": f"site:{audio_site_id}",
                "start_date": "2026-03-17 00:00:00",
                "end_date": "2026-03-18 00:00:00",
            },
        )
        assert site_resp.status_code == 200
        site_data = site_resp.json()["data"]
        assert site_data["has_more"] is False
        site_ids = {item["media_id"] for item in site_data["items"]}
        assert audio_id in site_ids
        assert metadata_id not in site_ids
        assert site_data["items"][0]["site_key"] == f"site:{audio_site_id}"

        nogeo_resp = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
                "response_mode": "detail",
                "site_key": "nogeo",
                "start_date": "2026-03-17 00:00:00",
                "end_date": "2026-03-18 00:00:00",
            },
        )
        assert nogeo_resp.status_code == 200
        nogeo_ids = {item["media_id"] for item in nogeo_resp.json()["data"]["items"]}
        assert metadata_id in nogeo_ids
        assert audio_id not in nogeo_ids

    def test_media_timeline_site_filter_keeps_non_geo_referenced_items(
        self, client: TestClient, db: Session
    ) -> None:
        """Site filtering should keep timeline rows without a site."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        audio_id, metadata_id = self._seed_timeline_media(db, collection_ids=[collection.collection_id])
        assert metadata_id is not None

        site_id = db.exec(select(Media.site_id).where(Media.media_id == audio_id)).one()
        assert site_id is not None

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
                "site_ids": str(site_id),
            },
        )
        assert r.status_code == 200
        ids = {item["media_id"] for item in r.json()["data"]["items"]}
        assert audio_id in ids
        assert metadata_id in ids

    def test_media_timeline_always_sorts_by_name_ascending(
        self, client: TestClient, db: Session
    ) -> None:
        """Timeline should always sort by name ascending."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        audio_setting = AudioSetting(duration_s=30.0, sampling_rate_hz=44100)
        db.add(audio_setting)
        db.flush()

        media_items = [
            Media(
                media_type="audio",
                filename="z.wav",
                name="Zulu",
                creator_id=1,
                uploader_id=1,
                date_time=datetime(2026, 3, 17, 12, 0, 0),
                audio_setting_id=audio_setting.audio_setting_id,
            ),
            Media(
                media_type="audio",
                filename="a.wav",
                name="Alpha",
                creator_id=1,
                uploader_id=1,
                date_time=datetime(2026, 3, 17, 11, 0, 0),
                audio_setting_id=audio_setting.audio_setting_id,
            ),
        ]
        db.add_all(media_items)
        db.flush()
        for media in media_items:
            db.add(
                MediaCollection(
                    media_id=media.media_id,
                    collection_id=collection.collection_id,
                    added_by=1,
                )
            )
        db.commit()

        resp = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={"project_id": project.project_id},
        )
        assert resp.status_code == 200
        names = [item["name"] for item in resp.json()["data"]["items"]]
        assert names == ["Alpha", "Zulu"]

    def test_media_timeline_includes_photo_media_in_results(
        self, client: TestClient, db: Session
    ) -> None:
        """Timeline overview should return audio, metadata, and photo rows."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        audio_id, metadata_id = self._seed_timeline_media(db, collection_ids=[collection.collection_id])
        photo_id = self._seed_photo_media(db, collection_id=collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
        )
        assert r.status_code == 200
        items = r.json()["data"]["items"]
        ids = {item["media_id"] for item in items}
        assert audio_id in ids
        assert metadata_id in ids
        assert photo_id in ids
        photo_item = next(item for item in items if item["media_id"] == photo_id)
        assert photo_item["media_type"] == "photo"
        assert photo_item["duration_s"] is None
        assert photo_item["start_date"] == photo_item["end_date"]

    def test_media_timeline_detail_includes_photo_media_in_window(
        self, client: TestClient, db: Session
    ) -> None:
        """Detail mode should return photo rows within the requested site window."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        photo_id = self._seed_photo_media(db, collection_id=collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
                "response_mode": "detail",
                "site_key": "nogeo",
                "start_date": "2026-03-17 00:00:00",
                "end_date": "2026-03-18 00:00:00",
            },
        )
        assert r.status_code == 200
        items = r.json()["data"]["items"]
        ids = {item["media_id"] for item in items}
        assert photo_id in ids
        photo_item = next(item for item in items if item["media_id"] == photo_id)
        assert photo_item["media_type"] == "photo"
        assert photo_item["site_key"] == "nogeo"
        assert photo_item["start_date"] == photo_item["end_date"]

    def test_media_timeline_metadata_end_date_equals_start_without_duration(
        self, client: TestClient, db: Session
    ) -> None:
        """Detail-mode metadata rows without stored duration should end at their start time."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        _, metadata_id = self._seed_timeline_media(db, collection_ids=[collection.collection_id])
        assert metadata_id is not None

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
                "response_mode": "detail",
                "site_key": "nogeo",
                "start_date": "2026-03-17 00:00:00",
                "end_date": "2026-03-18 00:00:00",
            },
        )
        assert r.status_code == 200
        metadata_item = next(
            item for item in r.json()["data"]["items"] if item["media_id"] == metadata_id
        )
        assert metadata_item["start_date"] == "2026-03-17 13:00:00"
        assert metadata_item["end_date"] == "2026-03-17 13:00:00"
        assert metadata_item["duration_s"] is None

    def test_media_timeline_metadata_uses_audio_setting_duration_in_detail_mode(
        self, client: TestClient, db: Session
    ) -> None:
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        metadata_audio_setting = AudioSetting(
            duration_s=45.0,
            sampling_rate_hz=22050,
            bit_depth=24,
            channel_num=2,
            recording_gain_db=7,
        )
        db.add(metadata_audio_setting)
        db.flush()

        metadata_media = Media(
            media_type="audio", is_metadata=True,
            filename=f"timeline_meta_as_{random_lower_string()[:6]}.csv",
            name="timeline_meta_audio_setting",
            creator_id=1,
            uploader_id=1,
            date_time=datetime(2026, 3, 17, 13, 0, 0),
            audio_setting_id=metadata_audio_setting.audio_setting_id,
        )
        db.add(metadata_media)
        db.flush()
        db.add(
            MediaCollection(
                media_id=metadata_media.media_id,
                collection_id=collection.collection_id,
                added_by=1,
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
                "response_mode": "detail",
                "site_key": "nogeo",
                "start_date": "2026-03-17 00:00:00",
                "end_date": "2026-03-18 00:00:00",
            },
        )
        assert r.status_code == 200
        metadata_item = next(
            item for item in r.json()["data"]["items"] if item["media_id"] == metadata_media.media_id
        )
        assert metadata_item["duration_s"] == 45.0
        assert metadata_item["start_date"] == "2026-03-17 13:00:00"
        assert metadata_item["end_date"] == "2026-03-17 13:00:45"

    def test_media_timeline_invalid_site_ids_returns_400(self, client: TestClient, db: Session) -> None:
        """Invalid site_ids should return 400."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()
        self._seed_timeline_media(db, collection_ids=[collection.collection_id])

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
                "site_ids": "1,abc",
            },
        )
        assert r.status_code == 400

    def test_media_timeline_media_type_filter_audio_only(self, client: TestClient, db: Session) -> None:
        """media_type=audio should return only audio items, excluding photos."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        audio_id, _ = self._seed_timeline_media(
            db, collection_ids=[collection.collection_id], with_metadata=False,
        )
        photo_id = self._seed_photo_media(db, collection_id=collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
                "media_type": "audio",
            },
        )
        assert r.status_code == 200
        ids = {item["media_id"] for item in r.json()["data"]["items"]}
        assert audio_id in ids
        assert photo_id not in ids

    def test_media_timeline_media_type_filter_photo_only(self, client: TestClient, db: Session) -> None:
        """media_type=photo should return only photo items, excluding audio."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        audio_id, _ = self._seed_timeline_media(
            db, collection_ids=[collection.collection_id], with_metadata=False,
        )
        photo_id = self._seed_photo_media(db, collection_id=collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
                "media_type": "photo",
            },
        )
        assert r.status_code == 200
        ids = {item["media_id"] for item in r.json()["data"]["items"]}
        assert audio_id not in ids
        assert photo_id in ids

    def test_media_timeline_media_type_all_returns_both(self, client: TestClient, db: Session) -> None:
        """media_type=all should return both audio and photo items."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        audio_id, _ = self._seed_timeline_media(
            db, collection_ids=[collection.collection_id], with_metadata=False,
        )
        photo_id = self._seed_photo_media(db, collection_id=collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/media-timeline-items",
            params={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
                "media_type": "all",
            },
        )
        assert r.status_code == 200
        ids = {item["media_id"] for item in r.json()["data"]["items"]}
        assert audio_id in ids
        assert photo_id in ids
