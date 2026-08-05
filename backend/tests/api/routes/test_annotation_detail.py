"""
Tests for annotation detail APIs:
  A3 - GET /annotations/{annotation_id} with embedded reviews
  B5 - GET /annotations/{annotation_id}/navigation-items
  List filters on GET /annotations (soundscape, uncertain, etc.)
  Task field on annotation responses.
"""
from datetime import datetime, UTC

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Collection, Media, MediaCollection, Project, ProjectCollection, Role
from app.models.annotation import Annotation, AnnotationReview, AnnotationReviewStatus
from app.models.task import Task
from app.models.user import User
from tests.utils.utils import random_lower_string


# Shared helpers

def _make_user(db: Session) -> User:
    role = db.exec(select(Role).where(Role.name == "User")).first()
    u = User(
        username=f"u_{random_lower_string()[:8]}",
        email=f"{random_lower_string()[:8]}@t.com",
        password="hashed",
        name="Test",
        role_id=role.role_id,
        active=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_media_in_collection(
    db: Session, public_access: bool = True, public_tags: bool = True
) -> tuple[Media, Collection, Project]:
    col = Collection(
        name=f"col_{random_lower_string()[:6]}",
        creator_id=1,
        public_access=public_access,
        public_tags=public_tags,
    )
    db.add(col)
    db.flush()
    # use metadata type to avoid audio_setting constraint
    media = Media(
        name=f"rec_{random_lower_string()[:6]}.wav",
        uploader_id=1,
        creator_id=1,
        media_type="audio", is_metadata=True,
    )
    db.add(media)
    db.flush()
    db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=1))
    db.flush()
    project = Project(
        name=f"proj_{random_lower_string()[:6]}",
        url=f"https://example.com/{random_lower_string()[:8]}",
        creator_id=1,
        public=True,
        active=True,
    )
    db.add(project)
    db.flush()
    db.add(ProjectCollection(project_id=project.project_id, collection_id=col.collection_id))
    db.flush()
    return media, col, project


def _make_annotation(
    db: Session, media: Media,
    min_x: float = 0.0, max_x: float = 10.0,
    min_y: float = 0.0, max_y: float = 8000.0,
    creator_id: int = 1,
    sound_id: int = 1,
    uncertain: bool | None = None,
) -> Annotation:
    ann = Annotation(
        media_id=media.media_id,
        min_x=min_x, max_x=max_x,
        min_y=min_y, max_y=max_y,
        creator_id=creator_id,
        creator_type="user",
        sound_id=sound_id,
        uncertain=uncertain,
    )
    db.add(ann)
    db.flush()
    return ann


def _make_task(
    db: Session,
    assigner_id: int,
    assignee_id: int,
    media: Media,
    annotation: Annotation | None = None,
    task_type: str = "annotation",
    status: str = "assigned",
    comment: str | None = None,
) -> Task:
    task = Task(
        type=task_type,
        media_id=media.media_id,
        annotation_id=annotation.annotation_id if annotation else None,
        assigner_id=assigner_id,
        assignee_id=assignee_id,
        status=status,
        comment=comment,
        datetime=datetime.now(UTC),
    )
    db.add(task)
    db.flush()
    return task


class TestAnnotationListFilters:
    """Filters on the annotation list endpoint."""

    def test_soundscape_filter(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """soundscape filter matches exact value."""
        from app.models.taxon import SoundClassification
        sc_geo = db.exec(
            select(SoundClassification).where(SoundClassification.soundscape_component == "Geophony")
        ).first()
        if not sc_geo:
            sc_geo = SoundClassification(soundscape_component="Geophony", sound_type="Wind")
            db.add(sc_geo)
            db.flush()

        sc_bio = db.exec(
            select(SoundClassification).where(SoundClassification.soundscape_component == "Biophony")
        ).first()
        if not sc_bio:
            sc_bio = SoundClassification(soundscape_component="Biophony", sound_type="Bird")
            db.add(sc_bio)
            db.flush()

        media, col, project = _make_media_in_collection(db)
        ann_geo = _make_annotation(db, media, sound_id=sc_geo.sound_id, min_x=0.0, max_x=5.0)
        ann_bio = _make_annotation(db, media, sound_id=sc_bio.sound_id, min_x=5.0, max_x=10.0)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/annotations"
            f"?project_id={project.project_id}&media_id={media.media_id}&soundscape_component=Geophony",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        ids = [a["annotation_id"] for a in r.json()["data"]]
        assert ann_geo.annotation_id in ids
        assert ann_bio.annotation_id not in ids

    def test_uncertain_filter(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        media, col, project = _make_media_in_collection(db)
        ann_uncertain = _make_annotation(db, media, uncertain=True, min_x=0.0, max_x=5.0)
        ann_certain = _make_annotation(db, media, uncertain=False, min_x=5.0, max_x=10.0)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/annotations?project_id={project.project_id}&media_id={media.media_id}&uncertain=true",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        ids = [a["annotation_id"] for a in r.json()["data"]]
        assert ann_uncertain.annotation_id in ids
        assert ann_certain.annotation_id not in ids


class TestAnnotationDetail:
    """A3: Single annotation detail with embedded reviews."""

    def test_get_annotation_requires_auth(self, client: TestClient) -> None:
        r = client.get(f"{settings.API_V1_STR}/annotations/1?project_id=1")
        assert r.status_code == 401

    def test_get_annotation_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        r = client.get(
            f"{settings.API_V1_STR}/annotations/99999999",
            params={"project_id": 999999},
            headers=superuser_token_headers,
        )
        assert r.status_code == 404

    def test_get_annotation_returns_fields(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        media, col, project = _make_media_in_collection(db)
        ann = _make_annotation(db, media, min_x=1.0, max_x=5.0, min_y=100.0, max_y=4000.0)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{ann.annotation_id}",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["annotation_id"] == ann.annotation_id
        assert data["min_x"] == 1.0
        assert data["max_x"] == 5.0
        assert "reviews" in data
        assert isinstance(data["reviews"], list)

    def test_get_annotation_with_reviews(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """Reviews are embedded in the annotation detail response."""
        media, col, project = _make_media_in_collection(db)
        ann = _make_annotation(db, media)

        status = db.exec(
            select(AnnotationReviewStatus).where(AnnotationReviewStatus.annotation_review_status_id == 1)
        ).first()
        if not status:
            status = AnnotationReviewStatus(name="Accepted")
            db.add(status)
            db.flush()

        review = AnnotationReview(
            annotation_id=ann.annotation_id,
            reviewer_id=1,
            annotation_review_status_id=status.annotation_review_status_id,
            note="Looks good",
        )
        db.add(review)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{ann.annotation_id}",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data["reviews"]) == 1
        rev = data["reviews"][0]
        assert rev["annotation_id"] == ann.annotation_id
        assert rev["reviewer_id"] == 1
        assert rev["note"] == "Looks good"
        assert "reviewer_name" in rev
        assert "status_name" in rev

    def test_get_annotation_empty_reviews(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        media, col, project = _make_media_in_collection(db)
        ann = _make_annotation(db, media)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{ann.annotation_id}",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["reviews"] == []

    def test_get_annotation_access_denied_private_collection(
        self, client: TestClient, db: Session, normal_user_token_headers: dict
    ) -> None:
        """Normal user cannot access other's annotation in private collection without public_tags."""
        media, col, project = _make_media_in_collection(db, public_access=False, public_tags=False)
        ann = _make_annotation(db, media, creator_id=1)  # created by admin
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{ann.annotation_id}",
            params={"project_id": project.project_id},
            headers=normal_user_token_headers,
        )
        assert r.status_code == 404  # 404 because it's inaccessible (not exposed as 403)

    def test_get_annotation_visible_via_public_tags(
        self, client: TestClient, db: Session, normal_user_token_headers: dict
    ) -> None:
        """Normal user CAN see annotation in public_tags collection."""
        media, col, project = _make_media_in_collection(db, public_access=False, public_tags=True)
        ann = _make_annotation(db, media, creator_id=1)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{ann.annotation_id}",
            params={"project_id": project.project_id},
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        assert r.json()["data"]["annotation_id"] == ann.annotation_id


class TestAnnotationNavigation:
    """B5: Annotation navigation within a media."""

    def _create_annotations(self, db: Session, media: Media, count: int) -> list[Annotation]:
        annotations = []
        for i in range(count):
            ann = _make_annotation(db, media, min_x=float(i * 10), max_x=float(i * 10 + 5))
            annotations.append(ann)
        db.commit()
        return sorted(annotations, key=lambda a: a.annotation_id)

    def test_navigation_requires_auth(self, client: TestClient) -> None:
        r = client.get(f"{settings.API_V1_STR}/annotations/1/navigation-items?media_id=1")
        assert r.status_code == 401

    def test_navigation_missing_media_id(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        r = client.get(
            f"{settings.API_V1_STR}/annotations/1/navigation-items",
            headers=superuser_token_headers,
        )
        assert r.status_code == 422

    def test_navigation_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        r = client.get(
            f"{settings.API_V1_STR}/annotations/99999999/navigation-items?media_id=1",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404

    def test_navigation_middle_annotation(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        media, col, project = _make_media_in_collection(db)
        anns = self._create_annotations(db, media, 3)
        middle = anns[1]

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{middle.annotation_id}/navigation-items"
            f"?media_id={media.media_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["prev_annotation_id"] == anns[0].annotation_id
        assert data["next_annotation_id"] == anns[2].annotation_id

    def test_navigation_first_annotation_no_prev(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        media, col, project = _make_media_in_collection(db)
        anns = self._create_annotations(db, media, 3)
        first = anns[0]

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{first.annotation_id}/navigation-items"
            f"?media_id={media.media_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["prev_annotation_id"] is None
        assert data["next_annotation_id"] == anns[1].annotation_id

    def test_navigation_last_annotation_no_next(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        media, col, project = _make_media_in_collection(db)
        anns = self._create_annotations(db, media, 3)
        last = anns[-1]

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{last.annotation_id}/navigation-items"
            f"?media_id={media.media_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["prev_annotation_id"] == anns[-2].annotation_id
        assert data["next_annotation_id"] is None

    def test_navigation_single_annotation(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        media, col, project = _make_media_in_collection(db)
        anns = self._create_annotations(db, media, 1)

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{anns[0].annotation_id}/navigation-items"
            f"?media_id={media.media_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["prev_annotation_id"] is None
        assert data["next_annotation_id"] is None

    def test_navigation_response_schema(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """Response has the correct schema."""
        media, col, project = _make_media_in_collection(db)
        anns = self._create_annotations(db, media, 2)

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{anns[0].annotation_id}/navigation-items"
            f"?media_id={media.media_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert "prev_annotation_id" in data
        assert "next_annotation_id" in data


class TestAnnotationTask:
    """Task field injected into annotation detail/list responses."""

    def test_task_is_null_when_no_task_assigned(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        media, col, project = _make_media_in_collection(db)
        ann = _make_annotation(db, media)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{ann.annotation_id}",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.json()["data"]["task"] is None

    def test_task_returned_when_annotation_task_assigned_to_current_user(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        media, col, project = _make_media_in_collection(db)
        ann = _make_annotation(db, media)
        _make_task(
            db, assigner_id=1, assignee_id=1, media=media, annotation=ann,
            task_type="annotation", comment="请核实物种",
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{ann.annotation_id}",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        task = r.json()["data"]["task"]
        assert task is not None
        assert task["type"] == "annotation"
        assert task["status"] == "assigned"
        assert task["comment"] == "请核实物种"

    def test_task_is_null_when_assigned_to_other_user(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """Annotation task assigned to a different user should not appear in current user's response."""
        other_user = _make_user(db)
        db.flush()
        media, col, project = _make_media_in_collection(db)
        ann = _make_annotation(db, media)
        _make_task(
            db, assigner_id=1, assignee_id=other_user.user_id,
            media=media, annotation=ann, task_type="annotation",
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{ann.annotation_id}",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.json()["data"]["task"] is None

    def test_annotation_task_takes_priority_over_media_task(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """When both media and annotation tasks exist, only the annotation task is exposed."""
        media, col, project = _make_media_in_collection(db)
        ann = _make_annotation(db, media)
        # media-level task (lower priority)
        _make_task(
            db, assigner_id=1, assignee_id=1, media=media, annotation=None,
            task_type="media", comment="review media",
        )
        # annotation-level task (higher priority)
        _make_task(
            db, assigner_id=1, assignee_id=1, media=media, annotation=ann,
            task_type="annotation", comment="review annotation",
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{ann.annotation_id}",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        task = r.json()["data"]["task"]
        assert task is not None
        assert task["type"] == "annotation"
        assert task["comment"] == "review annotation"

    def test_media_task_is_hidden_when_no_annotation_task(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """Media-level tasks should not appear on annotation detail responses."""
        media, col, project = _make_media_in_collection(db)
        ann = _make_annotation(db, media)
        _make_task(
            db, assigner_id=1, assignee_id=1, media=media, annotation=None,
            task_type="media", comment="review media",
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/annotations/{ann.annotation_id}",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.json()["data"]["task"] is None

    def test_media_task_is_hidden_for_all_annotations_in_list(
        self, client: TestClient, db: Session, superuser_token_headers: dict
    ) -> None:
        """Media-level tasks should not be expanded onto annotations in list responses."""
        media, col, project = _make_media_in_collection(db)
        ann1 = _make_annotation(db, media, min_x=0.0, max_x=5.0)
        ann2 = _make_annotation(db, media, min_x=5.0, max_x=10.0)
        _make_task(
            db, assigner_id=1, assignee_id=1, media=media, annotation=None,
            task_type="media", comment="review media",
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/annotations?project_id={project.project_id}&media_id={media.media_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200

        items = r.json()["data"]
        by_id = {item["annotation_id"]: item for item in items}
        assert by_id[ann1.annotation_id]["task"] is None
        assert by_id[ann2.annotation_id]["task"] is None
