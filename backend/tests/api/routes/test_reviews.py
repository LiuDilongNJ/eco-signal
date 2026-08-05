"""
Tests for Reviews API endpoints.
"""
import csv
import datetime

import jwt as pyjwt
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Permission, UserPermission, Role
from app.models.annotation import Annotation, AnnotationReview, AnnotationReviewStatus
from app.models.collection import Collection
from app.models.media import Media, MediaCollection, PhotoSetting
from app.models.project import Project, ProjectCollection
from app.models.taxon import SoundClassification
from app.models.user import User
from tests.utils.csv import read_csv_header
from tests.utils.utils import random_lower_string


def _create_normal_user(db: Session) -> User:
    """Create a minimal non-admin test user."""
    role = db.exec(select(Role).where(Role.name == "User")).first()
    user = User(
        role_id=role.role_id,
        username=f"u_{random_lower_string()[:8]}",
        password="hashed",
        name="Test User",
        email=f"{random_lower_string()[:8]}@test.com",
        active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _grant_collection_perm(db: Session, user_id: int, collection_id: int, perm_name: str) -> None:
    perm = db.exec(select(Permission).where(Permission.name == perm_name)).one()
    project_id = db.exec(select(ProjectCollection.project_id).where(ProjectCollection.collection_id == collection_id)).first()
    assert project_id is not None
    db.add(UserPermission(user_id=user_id, project_id=project_id, collection_id=collection_id, permission_id=perm.permission_id))
    db.commit()


def create_test_review_env(db: Session, reviewer_id: int):
    # 1. Setup Taxon/Sound
    sound = db.get(SoundClassification, 1)
    if not sound:
        sound = SoundClassification(name="biophony")
        db.add(sound)
        db.commit()
        db.refresh(sound)

    # 2. Setup Collection (private by default)
    col = Collection(name=f"review_col_{random_lower_string()[:6]}", public_access=False, creator_id=1)
    db.add(col)
    db.commit()
    db.refresh(col)

    project = Project(name=f"review_proj_{random_lower_string()[:6]}", url="https://example.com/review", creator_id=1, public=True, active=True)
    db.add(project)
    db.commit()
    db.refresh(project)
    db.add(ProjectCollection(project_id=project.project_id, collection_id=col.collection_id))
    db.commit()

    # 3. Setup Media
    media = Media(name="test_review_media.wav", uploader_id=1, media_type="audio", is_metadata=True, date_time=datetime.datetime.now(datetime.UTC))
    db.add(media)
    db.commit()
    db.refresh(media)

    mc = MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=1)
    db.add(mc)

    # 4. Setup Annotation
    ann = Annotation(
        media_id=media.media_id,
        sound_id=1,
        min_x=0.0, max_x=2.0, min_y=0.0, max_y=500.0,
        creator_type="user", creator_id=1
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)

    # 5. Setup Status
    status = AnnotationReviewStatus(name=f"Status_{random_lower_string()[:6]}")
    db.add(status)
    db.commit()
    db.refresh(status)

    # 6. Setup Review
    review = AnnotationReview(
        annotation_id=ann.annotation_id,
        reviewer_id=reviewer_id,
        annotation_review_status_id=status.annotation_review_status_id,
        note="Test Note"
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    return review, status, col, media, project


def test_list_reviews(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    superuser_id = 1
    review, status, col, media, project = create_test_review_env(db, reviewer_id=superuser_id)

    response = client.get(
        f"{settings.API_V1_STR}/reviews/",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["code"] == 0
    assert "data" in content
    assert "page_info" in content
    assert content["page_info"]["total"] >= 1

    # Check fields
    item = next((x for x in content["data"] if x["annotation_id"] == review.annotation_id and x["reviewer_id"] == superuser_id), None)
    assert item is not None
    assert item["note"] == "Test Note"
    assert item["media_type"] == "audio"
    reviewer = db.get(User, superuser_id)
    assert reviewer is not None
    assert item["reviewer_name"] == reviewer.name
    assert item["reviewer_name"] != reviewer.username
    assert item["creation_date"] == review.creation_date.strftime("%Y-%m-%d %H:%M:%S")


def test_list_reviews_filters_and_orders_by_media_type(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    review, status, collection, _media, project = create_test_review_env(db, reviewer_id=1)
    photo_setting = PhotoSetting()
    db.add(photo_setting)
    db.flush()
    photo = Media(
        name="review-photo.png",
        uploader_id=1,
        media_type="photo",
        is_metadata=True,
        photo_setting_id=photo_setting.photo_setting_id,
    )
    db.add(photo)
    db.flush()
    db.add(MediaCollection(media_id=photo.media_id, collection_id=collection.collection_id, added_by=1))
    photo_annotation = Annotation(
        media_id=photo.media_id,
        sound_id=1,
        creator_id=1,
        min_x=0,
        max_x=1,
        min_y=0,
        max_y=1,
    )
    db.add(photo_annotation)
    db.flush()
    db.add(AnnotationReview(
        annotation_id=photo_annotation.annotation_id,
        reviewer_id=review.reviewer_id,
        annotation_review_status_id=status.annotation_review_status_id,
    ))
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/reviews",
        params={"project_id": project.project_id, "media_type": "photo", "order_by": "media_type"},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json()["page_info"]["total"] == 1
    assert [item["media_type"] for item in response.json()["data"]] == ["photo"]

    ordered = client.get(
        f"{settings.API_V1_STR}/reviews",
        params={"project_id": project.project_id, "order_by": "media_type", "order_dir": "desc"},
        headers=superuser_token_headers,
    )
    assert [item["media_type"] for item in ordered.json()["data"]] == ["photo", "audio"]


def test_review_statuses_route_is_not_exposed(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/review-statuses",
        headers=superuser_token_headers,
    )

    assert response.status_code == 404


def test_list_reviews_with_filters(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    superuser_id = 1
    review, status, col, media, project = create_test_review_env(db, reviewer_id=superuser_id)
    
    response = client.get(
        f"{settings.API_V1_STR}/reviews/?note=Test Note&status_id={status.annotation_review_status_id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["page_info"]["total"] >= 1


def test_list_reviews_filters_by_project_id(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    superuser_id = 1
    review_in_project, _, _, _, project = create_test_review_env(db, reviewer_id=superuser_id)
    review_other_project, _, _, _, other_project = create_test_review_env(db, reviewer_id=superuser_id)
    assert project.project_id != other_project.project_id

    response = client.get(
        f"{settings.API_V1_STR}/reviews/?project_id={project.project_id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    items = response.json()["data"]

    assert any(
        r["annotation_id"] == review_in_project.annotation_id
        and r["reviewer_id"] == superuser_id
        for r in items
    )
    assert not any(
        r["annotation_id"] == review_other_project.annotation_id
        and r["reviewer_id"] == superuser_id
        for r in items
    )


def test_list_reviews_filters_by_collection_id(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    superuser_id = 1
    review_in_collection, _, collection, _, _ = create_test_review_env(db, reviewer_id=superuser_id)
    review_other_collection, _, other_collection, _, _ = create_test_review_env(db, reviewer_id=superuser_id)
    assert collection.collection_id != other_collection.collection_id

    response = client.get(
        f"{settings.API_V1_STR}/reviews/?collection_id={collection.collection_id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    items = response.json()["data"]

    assert any(
        r["annotation_id"] == review_in_collection.annotation_id
        and r["reviewer_id"] == superuser_id
        for r in items
    )
    assert not any(
        r["annotation_id"] == review_other_collection.annotation_id
        and r["reviewer_id"] == superuser_id
        for r in items
    )


def test_export_reviews(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    superuser_id = 1
    review, status, col, media, project = create_test_review_env(db, reviewer_id=superuser_id)

    response = client.get(
        f"{settings.API_V1_STR}/reviews/exports?sort_by=annotation_id",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert response.headers["content-disposition"] == (
        'attachment; filename="reviews.csv"; '
        "filename*=UTF-8''reviews.csv"
    )

    content = response.content.decode('utf-8')
    header = read_csv_header(content)
    assert header == [
        "annotation_id", "media_name", "media_type", "reviewer_name", "reviewer_id",
        "status_name", "taxon_name", "note", "creation_date",
    ]
    assert "Test Note" in content
    assert status.name in content


def test_update_review_success(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    superuser_id = 1
    review, status, col, media, project = create_test_review_env(db, reviewer_id=superuser_id)
    
    new_status = AnnotationReviewStatus(name="Updated Status")
    db.add(new_status)
    db.commit()
    db.refresh(new_status)
    
    update_data = {
        "annotation_review_status_id": new_status.annotation_review_status_id,
        "note": "Updated Note"
    }
    
    response = client.put(
        f"{settings.API_V1_STR}/annotations/{review.annotation_id}/reviews/{superuser_id}?project_id={project.project_id}",
        headers=superuser_token_headers,
        json=update_data
    )
    
    assert response.status_code == 200
    content = response.json()
    assert content["code"] == 0
    assert content["data"] is None
    db.refresh(review)
    assert review.note == "Updated Note"
    assert review.annotation_review_status_id == new_status.annotation_review_status_id
    st = db.get(AnnotationReviewStatus, review.annotation_review_status_id)
    assert st is not None
    assert st.name == "Updated Status"

def test_update_review_forbidden(
    client: TestClient, superuser_token_headers: dict[str, str], normal_user_token_headers: dict[str, str], db: Session
) -> None:
    superuser_id = 1
    review, status, col, media, project = create_test_review_env(db, reviewer_id=superuser_id)

    update_data = {
        "annotation_review_status_id": status.annotation_review_status_id,
        "note": "Hacked Note"
    }

    # Normal user should get 403 Forbidden because they don't have review:write on the collection
    response = client.put(
        f"{settings.API_V1_STR}/annotations/{review.annotation_id}/reviews/{superuser_id}?project_id={project.project_id}",
        headers=normal_user_token_headers,
        json=update_data
    )
    assert response.status_code == 403


def test_update_review_with_mismatched_project_admin_still_can_update(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    superuser_id = 1
    review, status, _, _, project = create_test_review_env(db, reviewer_id=superuser_id)
    _, _, _, _, other_project = create_test_review_env(db, reviewer_id=superuser_id)
    assert project.project_id != other_project.project_id

    response = client.put(
        f"{settings.API_V1_STR}/annotations/{review.annotation_id}/reviews/{superuser_id}"
        f"?project_id={other_project.project_id}",
        headers=superuser_token_headers,
        json={
            "annotation_review_status_id": status.annotation_review_status_id,
            "note": "Admin cross-project update",
        },
    )
    assert response.status_code == 200
    db.refresh(review)
    assert review.note == "Admin cross-project update"


def test_delete_review_with_mismatched_project_admin_still_can_delete(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    superuser_id = 1
    review, _, _, _, project = create_test_review_env(db, reviewer_id=superuser_id)
    _, _, _, _, other_project = create_test_review_env(db, reviewer_id=superuser_id)
    assert project.project_id != other_project.project_id

    response = client.delete(
        f"{settings.API_V1_STR}/annotations/{review.annotation_id}/reviews/{superuser_id}"
        f"?project_id={other_project.project_id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert db.get(AnnotationReview, (review.annotation_id, superuser_id)) is None


class TestReviewPermissionLogic:
    """Test the new dual-mode permission logic for reviews.

    - collection:write → see ALL reviews in the collection
    - No write access → only see own reviews (reviewer_id = current_user_id)
    """

    def test_normal_user_sees_own_review(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Normal user without collection:write can only see their own reviews."""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        normal_user_id = int(payload["sub"])

        review, status, col, media, project = create_test_review_env(db, reviewer_id=normal_user_id)

        response = client.get(
            f"{settings.API_V1_STR}/reviews/",
            headers=normal_user_token_headers,
        )
        assert response.status_code == 200
        data = response.json()
        items = data["data"]
        assert any(
            r["annotation_id"] == review.annotation_id and r["reviewer_id"] == normal_user_id
            for r in items
        )

    def test_normal_user_cannot_see_other_users_review_without_write(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Normal user without collection:write cannot see reviews owned by others."""
        # Create another user and review
        other_user = _create_normal_user(db)
        review, status, col, media, project = create_test_review_env(db, reviewer_id=other_user.user_id)

        response = client.get(
            f"{settings.API_V1_STR}/reviews/",
            headers=normal_user_token_headers,
        )
        assert response.status_code == 200
        data = response.json()
        items = data["data"]
        # Should not contain the other user's review in a collection normal user has no access to
        other_reviews = [r for r in items if r["annotation_id"] == review.annotation_id and r["reviewer_id"] == other_user.user_id]
        assert len(other_reviews) == 0

    def test_collection_write_user_sees_all_reviews_in_collection(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """User with collection:write can see ALL reviews in that collection."""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        normal_user_id = int(payload["sub"])

        # Create review by another user
        other_user = _create_normal_user(db)
        review, status, col, media, project = create_test_review_env(db, reviewer_id=other_user.user_id)

        # Grant normal_user collection:write on that collection
        _grant_collection_perm(db, normal_user_id, col.collection_id, "collection:write")

        response = client.get(
            f"{settings.API_V1_STR}/reviews/",
            headers=normal_user_token_headers,
        )
        assert response.status_code == 200
        data = response.json()
        items = data["data"]
        # Should now see the other user's review
        other_reviews = [r for r in items if r["annotation_id"] == review.annotation_id and r["reviewer_id"] == other_user.user_id]
        assert len(other_reviews) >= 1
