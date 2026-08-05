from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import ProjectCollection
from app.models.media import AudioSetting, Media, MediaCollection
from tests.api.routes.test_sites import (
    create_test_collection,
    create_test_project,
    create_user_with_headers,
    grant_permission,
    link_collection_to_project,
)


def create_test_media(db: Session, collection_id: int, creator_id: int = 1, **kwargs) -> Media:
    """Create a test media record and bind it to one collection."""
    audio_setting = AudioSetting(duration_s=10.0, sampling_rate_hz=44100)
    db.add(audio_setting)
    db.commit()
    db.refresh(audio_setting)

    defaults = {
        "filename": "linked-media.wav",
        "name": "Linked Media",
        "media_type": "audio",
        "uploader_id": creator_id,
        "creator_id": creator_id,
        "audio_setting_id": audio_setting.audio_setting_id,
    }
    defaults.update(kwargs)
    media = Media(**defaults)
    db.add(media)
    db.commit()
    db.refresh(media)

    db.add(
        MediaCollection(
            media_id=media.media_id,
            collection_id=collection_id,
            added_by=creator_id,
        )
    )
    db.commit()
    return media


class TestMediaCollectionLinkOptions:
    """Tests for GET /media/{media_id}/collection-options."""

    def test_get_media_collection_link_options_admin_returns_grouped_and_selected(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin gets grouped options plus selected collection IDs."""
        current_project = create_test_project(db, name="Current Media Project")
        other_project = create_test_project(db, name="Other Media Project")
        duplicate_project = create_test_project(db, name="Duplicate Media Project")

        current_collection = create_test_collection(db, name="Current Media Collection")
        other_collection = create_test_collection(db, name="Other Media Collection")
        duplicate_collection = create_test_collection(
            db, name="Duplicate Media Collection", auto_link_project=False
        )
        unassigned_collection = create_test_collection(
            db, name="Unassigned Media Collection", auto_link_project=False
        )

        link_collection_to_project(db, current_project.project_id, current_collection.collection_id)
        link_collection_to_project(db, other_project.project_id, other_collection.collection_id)
        db.add_all(
            [
                ProjectCollection(
                    project_id=other_project.project_id,
                    collection_id=duplicate_collection.collection_id,
                ),
                ProjectCollection(
                    project_id=duplicate_project.project_id,
                    collection_id=duplicate_collection.collection_id,
                ),
            ]
        )
        db.commit()

        media = create_test_media(db, current_collection.collection_id)
        db.add(
            MediaCollection(
                media_id=media.media_id,
                collection_id=other_collection.collection_id,
                added_by=1,
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/collection-options",
            headers=superuser_token_headers,
            params={"project_id": current_project.project_id},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0
        data = payload["data"]

        assert sorted(data["selected_collection_ids"]) == sorted(
            [current_collection.collection_id, other_collection.collection_id]
        )

        assert data["current_project"]["project_id"] == current_project.project_id
        current_ids = {item["collection_id"] for item in data["current_project"]["collections"]}
        assert current_collection.collection_id in current_ids
        assert any(
            item["collection_id"] == current_collection.collection_id and item["selected"] is True
            for item in data["current_project"]["collections"]
        )

        other_ids = {
            item["collection_id"] for project in data["other_projects"] for item in project["collections"]
        }
        assert other_collection.collection_id in other_ids
        assert duplicate_collection.collection_id in other_ids
        assert any(
            item["collection_id"] == other_collection.collection_id and item["selected"] is True
            for project in data["other_projects"]
            for item in project["collections"]
        )

        duplicate_items = [
            item
            for project in data["other_projects"]
            for item in project["collections"]
            if item["collection_id"] == duplicate_collection.collection_id
        ]
        assert len(duplicate_items) == 2
        for item in duplicate_items:
            assert item["selected"] is False
            assert item["duplicate_project_ids"] == sorted(
                [other_project.project_id, duplicate_project.project_id]
            )

        unassigned_ids = {item["collection_id"] for item in data["unassigned_collections"]}
        assert unassigned_collection.collection_id in unassigned_ids

    def test_get_media_collection_link_options_project_not_found(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Unknown project_id returns 404."""
        collection = create_test_collection(db)
        media = create_test_media(db, collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/collection-options",
            headers=superuser_token_headers,
            params={"project_id": 999999},
        )
        assert r.status_code == 404

    def test_get_media_collection_link_options_no_project_write_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User without project:write on target project gets 403."""
        user, headers = create_user_with_headers(db, client)
        current_project = create_test_project(db)
        media_project = create_test_project(db)
        current_collection = create_test_collection(db)
        media_collection = create_test_collection(db)
        link_collection_to_project(db, current_project.project_id, current_collection.collection_id)
        link_collection_to_project(db, media_project.project_id, media_collection.collection_id)
        media = create_test_media(db, media_collection.collection_id, creator_id=user.user_id)

        grant_permission(db, user.user_id, "audio", "write", collection_id=media_collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/collection-options",
            headers=headers,
            params={"project_id": current_project.project_id},
        )
        assert r.status_code == 403

    def test_get_media_collection_link_options_no_media_write_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User without audio:write on media collections gets 403."""
        user, headers = create_user_with_headers(db, client)
        current_project = create_test_project(db)
        current_collection = create_test_collection(db)
        media_collection = create_test_collection(db)
        link_collection_to_project(db, current_project.project_id, current_collection.collection_id)
        media = create_test_media(db, media_collection.collection_id, creator_id=user.user_id)

        grant_permission(db, user.user_id, "project", "write", project_id=current_project.project_id)

        r = client.get(
            f"{settings.API_V1_STR}/media/{media.media_id}/collection-options",
            headers=headers,
            params={"project_id": current_project.project_id},
        )
        assert r.status_code == 403


class TestSyncMediaCollections:
    """Tests for PUT /media/{media_id}/collections."""

    def test_sync_media_collections_admin(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can fully replace media collection bindings."""
        current_collection = create_test_collection(db)
        target_collection = create_test_collection(db)
        project = create_test_project(db)
        link_collection_to_project(db, project.project_id, current_collection.collection_id)
        link_collection_to_project(db, project.project_id, target_collection.collection_id)
        media = create_test_media(db, current_collection.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/media-collection-links",
            headers=superuser_token_headers,
            params={"project_id": project.project_id},
            json={
                "media_ids": [media.media_id],
                "collection_ids": [current_collection.collection_id, target_collection.collection_id],
            },
        )
        assert r.status_code == 200
        assert r.json()["data"]["succeeded"] == [media.media_id]

        rows = db.exec(
            select(MediaCollection.collection_id).where(MediaCollection.media_id == media.media_id)
        ).all()
        assert sorted(rows) == sorted([current_collection.collection_id, target_collection.collection_id])

    def test_sync_media_collections_regular_user_with_required_permissions(
        self, client: TestClient, db: Session
    ) -> None:
        """Regular user can sync when holding audio:write and collection:write."""
        user, headers = create_user_with_headers(db, client)
        current_collection = create_test_collection(db)
        target_collection = create_test_collection(db)
        project = create_test_project(db)
        link_collection_to_project(db, project.project_id, current_collection.collection_id)
        link_collection_to_project(db, project.project_id, target_collection.collection_id)
        media = create_test_media(db, current_collection.collection_id, creator_id=user.user_id)

        grant_permission(db, user.user_id, "audio", "write", project_id=project.project_id, collection_id=current_collection.collection_id)
        grant_permission(db, user.user_id, "collection", "write", project_id=project.project_id, collection_id=current_collection.collection_id)
        grant_permission(db, user.user_id, "collection", "write", project_id=project.project_id, collection_id=target_collection.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/media-collection-links",
            headers=headers,
            params={"project_id": project.project_id},
            json={
                "media_ids": [media.media_id],
                "collection_ids": [current_collection.collection_id, target_collection.collection_id],
            },
        )
        assert r.status_code == 200

        rows = db.exec(
            select(MediaCollection.collection_id, MediaCollection.added_by).where(
                MediaCollection.media_id == media.media_id
            )
        ).all()
        assert sorted(collection_id for collection_id, _added_by in rows) == sorted(
            [current_collection.collection_id, target_collection.collection_id]
        )
        assert all(added_by == user.user_id for _collection_id, added_by in rows)

    def test_sync_media_collections_missing_collection(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Unknown collection_id returns 400."""
        current_collection = create_test_collection(db)
        project = create_test_project(db)
        link_collection_to_project(db, project.project_id, current_collection.collection_id)
        media = create_test_media(db, current_collection.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/media-collection-links",
            headers=superuser_token_headers,
            params={"project_id": project.project_id},
            json={"media_ids": [media.media_id], "collection_ids": [current_collection.collection_id, 999999]},
        )
        assert r.status_code == 200
        assert r.json()["data"]["failed"][0]["media_id"] == media.media_id

    def test_sync_media_collections_forbidden_without_collection_write(
        self, client: TestClient, db: Session
    ) -> None:
        """User without collection:write on requested collections gets 403."""
        user, headers = create_user_with_headers(db, client)
        current_collection = create_test_collection(db)
        target_collection = create_test_collection(db)
        project = create_test_project(db)
        link_collection_to_project(db, project.project_id, current_collection.collection_id)
        link_collection_to_project(db, project.project_id, target_collection.collection_id)
        media = create_test_media(db, current_collection.collection_id, creator_id=user.user_id)

        grant_permission(db, user.user_id, "audio", "write", project_id=project.project_id, collection_id=current_collection.collection_id)
        grant_permission(db, user.user_id, "collection", "write", project_id=project.project_id, collection_id=current_collection.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/media-collection-links",
            headers=headers,
            params={"project_id": project.project_id},
            json={
                "media_ids": [media.media_id],
                "collection_ids": [current_collection.collection_id, target_collection.collection_id],
            },
        )
        assert r.status_code == 200
        assert r.json()["data"]["failed"][0]["media_id"] == media.media_id

    def test_sync_media_collections_allows_clearing_links(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Empty array clears all media-collection links."""
        current_collection = create_test_collection(db)
        extra_collection = create_test_collection(db)
        project = create_test_project(db)
        link_collection_to_project(db, project.project_id, current_collection.collection_id)
        link_collection_to_project(db, project.project_id, extra_collection.collection_id)
        media = create_test_media(db, current_collection.collection_id)
        db.add(
            MediaCollection(
                media_id=media.media_id,
                collection_id=extra_collection.collection_id,
                added_by=1,
            )
        )
        db.commit()

        r = client.put(
            f"{settings.API_V1_STR}/media-collection-links",
            headers=superuser_token_headers,
            params={"project_id": project.project_id},
            json={"media_ids": [media.media_id], "collection_ids": []},
        )
        assert r.status_code == 200

        rows = db.exec(
            select(MediaCollection.collection_id).where(MediaCollection.media_id == media.media_id)
        ).all()
        assert rows == []
