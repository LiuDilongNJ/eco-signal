"""
Tests for task status management driven by labels and reviews.

Covers:
- Media task: label set -> reviewed, label cleared -> assigned
- Annotation task: review created -> reviewed, review deleted -> assigned
- Annotation task assignment with annotation_ids
"""

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Project, ProjectCollection, Task, User
from app.models.annotation import Annotation, AnnotationReview, AnnotationReviewStatus
from app.models.collection import Collection
from app.models.label import Label
from app.models.media import AudioSetting, Media, MediaCollection
from app.models.taxon import SoundClassification


def _setup_media_env(db: Session) -> tuple[Media, Collection, User]:
    """Create a media linked to a public collection. Returns (media, collection, admin)."""
    admin = db.exec(select(User).where(User.role_id == 1)).first()

    col = Collection(name="status_test_col", public_access=True, creator_id=admin.user_id)
    db.add(col)
    db.flush()
    project = Project(
        name="status_test_project",
        url=f"https://status-test-{col.collection_id or 'new'}.example",
        public=True,
        creator_id=admin.user_id,
    )
    db.add(project)
    db.flush()
    db.add(ProjectCollection(project_id=project.project_id, collection_id=col.collection_id))

    audio = AudioSetting(sampling_rate_hz=44100, duration_s=10.0)
    db.add(audio)
    db.flush()

    media = Media(
        media_type="audio",
        filename="status_test.wav",
        uploader_id=admin.user_id,
        audio_setting_id=audio.audio_setting_id,
    )
    db.add(media)
    db.flush()

    db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=admin.user_id))
    db.commit()
    db.refresh(media)
    db.refresh(col)
    return media, col, admin


def _setup_annotation(db: Session, media_id: int, creator_id: int) -> Annotation:
    """Create an annotation on a media."""
    sound = db.get(SoundClassification, 1)
    if not sound:
        sound = SoundClassification(name="biophony")
        db.add(sound)
        db.commit()
        db.refresh(sound)

    ann = Annotation(
        media_id=media_id,
        sound_id=sound.sound_id,
        min_x=0.0, max_x=2.0, min_y=0.0, max_y=500.0,
        creator_type="user",
        creator_id=creator_id,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return ann


def _project_id_for_collection(db: Session, collection_id: int) -> int:
    project_id = db.exec(
        select(ProjectCollection.project_id).where(ProjectCollection.collection_id == collection_id)
    ).first()
    assert project_id is not None
    return project_id


def _ensure_review_status(db: Session) -> AnnotationReviewStatus:
    """Return an AnnotationReviewStatus, creating one if needed."""
    status = db.exec(select(AnnotationReviewStatus)).first()
    if not status:
        status = AnnotationReviewStatus(name="Accepted")
        db.add(status)
        db.commit()
        db.refresh(status)
    return status


def _ensure_label(db: Session, label_id: int, name: str, creator_id: int) -> Label:
    """Get or create a label by id."""
    label = db.get(Label, label_id)
    if not label:
        label = Label(label_id=label_id, name=name, creator_id=creator_id)
        db.add(label)
        db.commit()
        db.refresh(label)
    return label


# Media task status: label -> reviewed / assigned

class TestMediaTaskLabelStatus:
    """Label drives media task status."""

    def test_meaningful_label_marks_task_reviewed(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        media, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        task = Task(
            type="media", media_id=media.media_id,
            assigner_id=admin.user_id, assignee_id=admin.user_id,
            status="assigned",
        )
        db.add(task)

        meaningful = Label(name="tagged", creator_id=admin.user_id)
        db.add(meaningful)
        db.commit()
        db.refresh(task)
        db.refresh(meaningful)

        r = client.put(
            f"{settings.API_V1_STR}/media-labels",
            headers=superuser_token_headers,
            params={"project_id": project_id},
            json={"media_ids": [media.media_id], "label_id": meaningful.label_id},
        )
        assert r.status_code == 200
        db.refresh(task)
        assert task.status == "reviewed"

    def test_clear_labels_reverts_task_to_assigned(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        media, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        task = Task(
            type="media", media_id=media.media_id,
            assigner_id=admin.user_id, assignee_id=admin.user_id,
            status="reviewed",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        r = client.put(
            f"{settings.API_V1_STR}/media-labels",
            headers=superuser_token_headers,
            params={"project_id": project_id},
            json={"media_ids": [media.media_id], "label_id": None},
        )
        assert r.status_code == 200
        db.refresh(task)
        assert task.status == "assigned"

    def test_only_not_analysed_label_reverts_task(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Setting only label_id=1 ('not analysed') should revert to assigned."""
        media, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        task = Task(
            type="media", media_id=media.media_id,
            assigner_id=admin.user_id, assignee_id=admin.user_id,
            status="reviewed",
        )
        db.add(task)
        _ensure_label(db, 1, "not analysed", admin.user_id)
        db.commit()
        db.refresh(task)

        r = client.put(
            f"{settings.API_V1_STR}/media-labels",
            headers=superuser_token_headers,
            params={"project_id": project_id},
            json={"media_ids": [media.media_id], "label_id": 1},
        )
        assert r.status_code == 200
        db.refresh(task)
        assert task.status == "assigned"

    def test_label_does_not_affect_annotation_task(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Label changes should not affect annotation-type tasks."""
        media, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        ann = _setup_annotation(db, media.media_id, admin.user_id)

        annotation_task = Task(
            type="annotation", media_id=media.media_id, annotation_id=ann.annotation_id,
            assigner_id=admin.user_id, assignee_id=admin.user_id,
            status="assigned",
        )
        db.add(annotation_task)

        meaningful = Label(name="tagged_cross", creator_id=admin.user_id)
        db.add(meaningful)
        db.commit()
        db.refresh(annotation_task)
        db.refresh(meaningful)

        r = client.put(
            f"{settings.API_V1_STR}/media-labels",
            headers=superuser_token_headers,
            params={"project_id": project_id},
            json={"media_ids": [media.media_id], "label_id": meaningful.label_id},
        )
        assert r.status_code == 200
        db.refresh(annotation_task)
        assert annotation_task.status == "assigned"


# Annotation task assignment with annotation_ids

class TestAnnotationTaskAssignment:
    """Annotation tasks require annotation_ids."""

    def test_assign_annotation_task_success(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        media, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        ann = _setup_annotation(db, media.media_id, admin.user_id)

        r = client.put(
            f"{settings.API_V1_STR}/media/{media.media_id}/tasks",
            headers=superuser_token_headers,
            params={"project_id": project_id},
            json={
                "type": "annotation",
                "annotation_ids": [ann.annotation_id],
                "assignments": [{"user_id": admin.user_id, "comment": "review this annotation"}],
            },
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["assigned_count"] == 1

        task = db.exec(
            select(Task).where(
                Task.type == "annotation",
                Task.annotation_id == ann.annotation_id,
                Task.assignee_id == admin.user_id,
            )
        ).first()
        assert task is not None
        assert task.status == "assigned"
        assert task.media_id == media.media_id
        assert task.comment == "review this annotation"

    def test_assign_annotation_task_missing_annotation_ids(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        media, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        r = client.put(
            f"{settings.API_V1_STR}/media/{media.media_id}/tasks",
            headers=superuser_token_headers,
            params={"project_id": project_id},
            json={
                "type": "annotation",
                "assignments": [{"user_id": admin.user_id}],
            },
        )
        assert r.status_code == 400
        assert "annotation_ids" in r.json()["message"].lower()

    def test_assign_annotation_task_wrong_media(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Annotation must belong to the specified media."""
        media1, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        media2, _, _ = _setup_media_env(db)
        ann = _setup_annotation(db, media2.media_id, admin.user_id)

        r = client.put(
            f"{settings.API_V1_STR}/media/{media1.media_id}/tasks",
            headers=superuser_token_headers,
            params={"project_id": project_id},
            json={
                "type": "annotation",
                "annotation_ids": [ann.annotation_id],
                "assignments": [{"user_id": admin.user_id}],
            },
        )
        assert r.status_code == 400
        assert "does not belong" in r.json()["message"].lower()

    def test_assign_multiple_annotations(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        media, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        ann1 = _setup_annotation(db, media.media_id, admin.user_id)
        ann2 = _setup_annotation(db, media.media_id, admin.user_id)

        r = client.put(
            f"{settings.API_V1_STR}/media/{media.media_id}/tasks",
            headers=superuser_token_headers,
            params={"project_id": project_id},
            json={
                "type": "annotation",
                "annotation_ids": [ann1.annotation_id, ann2.annotation_id],
                "assignments": [{"user_id": admin.user_id}],
            },
        )
        assert r.status_code == 200
        assert r.json()["data"]["assigned_count"] == 2


# Annotation task status: review -> reviewed / assigned

class TestAnnotationTaskReviewStatus:
    """Review drives annotation task status."""

    def test_create_review_marks_task_reviewed(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        media, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        ann = _setup_annotation(db, media.media_id, admin.user_id)
        status = _ensure_review_status(db)

        annotation_task = Task(
            type="annotation", media_id=media.media_id, annotation_id=ann.annotation_id,
            assigner_id=admin.user_id, assignee_id=admin.user_id,
            status="assigned",
        )
        db.add(annotation_task)
        db.commit()
        db.refresh(annotation_task)

        r = client.post(
            f"{settings.API_V1_STR}/reviews",
            headers=superuser_token_headers,
            json={
                "project_id": project_id,
                "annotation_id": ann.annotation_id,
                "annotation_review_status_id": status.annotation_review_status_id,
                "note": "looks good",
            },
        )
        assert r.status_code == 201
        db.refresh(annotation_task)
        assert annotation_task.status == "reviewed"

    def test_update_review_keeps_task_reviewed(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        media, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        ann = _setup_annotation(db, media.media_id, admin.user_id)
        status = _ensure_review_status(db)

        annotation_task = Task(
            type="annotation", media_id=media.media_id, annotation_id=ann.annotation_id,
            assigner_id=admin.user_id, assignee_id=admin.user_id,
            status="assigned",
        )
        db.add(annotation_task)

        review = AnnotationReview(
            annotation_id=ann.annotation_id,
            reviewer_id=admin.user_id,
            annotation_review_status_id=status.annotation_review_status_id,
            note="initial",
        )
        db.add(review)
        db.commit()
        db.refresh(annotation_task)

        r = client.put(
            f"{settings.API_V1_STR}/annotations/{ann.annotation_id}/reviews/{admin.user_id}",
            headers=superuser_token_headers,
            params={"project_id": project_id},
            json={
                "annotation_review_status_id": status.annotation_review_status_id,
                "note": "updated",
            },
        )
        assert r.status_code == 200
        db.refresh(annotation_task)
        assert annotation_task.status == "reviewed"

    def test_delete_review_reverts_task_to_assigned(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        media, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        ann = _setup_annotation(db, media.media_id, admin.user_id)
        status = _ensure_review_status(db)

        annotation_task = Task(
            type="annotation", media_id=media.media_id, annotation_id=ann.annotation_id,
            assigner_id=admin.user_id, assignee_id=admin.user_id,
            status="reviewed",
        )
        db.add(annotation_task)

        review = AnnotationReview(
            annotation_id=ann.annotation_id,
            reviewer_id=admin.user_id,
            annotation_review_status_id=status.annotation_review_status_id,
            note="to delete",
        )
        db.add(review)
        db.commit()
        db.refresh(annotation_task)

        r = client.delete(
            f"{settings.API_V1_STR}/annotations/{ann.annotation_id}/reviews/{admin.user_id}",
            headers=superuser_token_headers,
            params={"project_id": project_id},
        )
        assert r.status_code == 200
        db.refresh(annotation_task)
        assert annotation_task.status == "assigned"

    def test_review_does_not_affect_media_task(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Review changes should not affect media-type tasks."""
        media, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        ann = _setup_annotation(db, media.media_id, admin.user_id)
        status = _ensure_review_status(db)

        media_task = Task(
            type="media", media_id=media.media_id,
            assigner_id=admin.user_id, assignee_id=admin.user_id,
            status="assigned",
        )
        db.add(media_task)
        db.commit()
        db.refresh(media_task)

        r = client.post(
            f"{settings.API_V1_STR}/reviews",
            headers=superuser_token_headers,
            json={
                "project_id": project_id,
                "annotation_id": ann.annotation_id,
                "annotation_review_status_id": status.annotation_review_status_id,
            },
        )
        assert r.status_code == 201
        db.refresh(media_task)
        assert media_task.status == "assigned"


# Review CRUD endpoints

class TestReviewCRUD:
    """Tests for POST /reviews and DELETE /reviews/{annotation_id}/{reviewer_id}."""

    def test_create_review_success(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        media, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        ann = _setup_annotation(db, media.media_id, admin.user_id)
        status = _ensure_review_status(db)

        r = client.post(
            f"{settings.API_V1_STR}/reviews",
            headers=superuser_token_headers,
            json={
                "project_id": project_id,
                "annotation_id": ann.annotation_id,
                "annotation_review_status_id": status.annotation_review_status_id,
                "note": "new review",
            },
        )
        assert r.status_code == 201
        assert r.json()["data"] is None
        rev = db.exec(
            select(AnnotationReview).where(
                AnnotationReview.annotation_id == ann.annotation_id,
                AnnotationReview.reviewer_id == admin.user_id,
            )
        ).first()
        assert rev is not None
        assert rev.note == "new review"

    def test_create_review_duplicate_returns_409(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        media, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        ann = _setup_annotation(db, media.media_id, admin.user_id)
        status = _ensure_review_status(db)

        review = AnnotationReview(
            annotation_id=ann.annotation_id,
            reviewer_id=admin.user_id,
            annotation_review_status_id=status.annotation_review_status_id,
        )
        db.add(review)
        db.commit()

        r = client.post(
            f"{settings.API_V1_STR}/reviews",
            headers=superuser_token_headers,
            json={
                "project_id": project_id,
                "annotation_id": ann.annotation_id,
                "annotation_review_status_id": status.annotation_review_status_id,
            },
        )
        assert r.status_code == 409

    def test_create_review_annotation_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        r = client.post(
            f"{settings.API_V1_STR}/reviews",
            headers=superuser_token_headers,
            json={
                "project_id": 999999,
                "annotation_id": 999999,
                "annotation_review_status_id": 1,
            },
        )
        assert r.status_code == 404

    def test_create_review_requires_auth(self, client: TestClient) -> None:
        r = client.post(
            f"{settings.API_V1_STR}/reviews",
            json={
                "project_id": 1,
                "annotation_id": 1,
                "annotation_review_status_id": 1,
            },
        )
        assert r.status_code == 401

    def test_delete_review_success(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        media, col, admin = _setup_media_env(db)
        project_id = _project_id_for_collection(db, col.collection_id)
        ann = _setup_annotation(db, media.media_id, admin.user_id)
        status = _ensure_review_status(db)

        review = AnnotationReview(
            annotation_id=ann.annotation_id,
            reviewer_id=admin.user_id,
            annotation_review_status_id=status.annotation_review_status_id,
        )
        db.add(review)
        db.commit()

        r = client.delete(
            f"{settings.API_V1_STR}/annotations/{ann.annotation_id}/reviews/{admin.user_id}",
            headers=superuser_token_headers,
            params={"project_id": project_id},
        )
        assert r.status_code == 200

        deleted = db.exec(
            select(AnnotationReview).where(
                AnnotationReview.annotation_id == ann.annotation_id,
                AnnotationReview.reviewer_id == admin.user_id,
            )
        ).first()
        assert deleted is None

    def test_delete_review_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        r = client.delete(
            f"{settings.API_V1_STR}/annotations/999999/reviews/999999",
            headers=superuser_token_headers,
            params={"project_id": 999999},
        )
        assert r.status_code == 404

    def test_delete_review_requires_auth(self, client: TestClient) -> None:
        r = client.delete(f"{settings.API_V1_STR}/annotations/1/reviews/1")
        assert r.status_code == 401
