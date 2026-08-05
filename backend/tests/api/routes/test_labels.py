"""
Tests for Label API routes.
"""
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models.collection import Collection
from app.models.label import Label, LabelMedia
from app.models.media import Media, AudioSetting, MediaCollection
from app.models.project import Project, ProjectCollection
from app.models.task import Task
from app.models.user import Role, User


def _link_collection_to_project(db: Session, collection: Collection, creator_id: int) -> int:
    project = Project(
        name=f"Label Project {uuid4().hex[:8]}",
        url=f"https://labels-{uuid4().hex[:8]}.example",
        public=True,
        creator_id=creator_id,
    )
    db.add(project)
    db.flush()
    db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
    db.flush()
    return project.project_id


class TestLabelRoutes:
    """Tests for label-related endpoints."""

    def test_create_label_success_normal_user(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        """POST /labels creates a private label for normal user."""
        label_name = f"label_{uuid4().hex[:8]}"
        r = client.post(
            f"{settings.API_V1_STR}/labels",
            headers=normal_user_token_headers,
            json={"name": label_name},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0
        assert payload["data"] is None
        user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).one()
        row = db.exec(
            select(Label).where(Label.name == label_name, Label.creator_id == user.user_id)
        ).first()
        assert row is not None
        assert row.type == "private"

    def test_create_label_success_admin(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """POST /labels allows admin to create private labels."""
        label_name = f"admin_{uuid4().hex[:8]}"
        r = client.post(
            f"{settings.API_V1_STR}/labels",
            headers=superuser_token_headers,
            json={"name": label_name},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0
        assert payload["data"] is None
        row = db.exec(select(Label).where(Label.name == label_name).order_by(Label.label_id.desc())).first()
        assert row is not None
        assert row.type == "private"

    def test_create_label_duplicate_name_same_user_returns_400(
        self, client: TestClient, normal_user_token_headers: dict
    ) -> None:
        """POST /labels rejects duplicate label names for the same user."""
        label_name = f"dup_{uuid4().hex[:8]}"
        first = client.post(
            f"{settings.API_V1_STR}/labels",
            headers=normal_user_token_headers,
            json={"name": label_name},
        )
        assert first.status_code == 200

        second = client.post(
            f"{settings.API_V1_STR}/labels",
            headers=normal_user_token_headers,
            json={"name": label_name.upper()},
        )
        assert second.status_code == 400
        assert second.json()["message"] == "Label with same name already exists"

    def test_create_label_rejects_type_payload(
        self, client: TestClient, normal_user_token_headers: dict
    ) -> None:
        """POST /labels does not allow clients to choose label visibility."""
        r = client.post(
            f"{settings.API_V1_STR}/labels",
            headers=normal_user_token_headers,
            json={"name": f"extra_{uuid4().hex[:8]}", "type": "public"},
        )
        assert r.status_code == 422

    def test_list_labels_contains_public_label(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        """Public labels should be visible in normal user label list."""
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        assert admin is not None
        label_name = f"global_{uuid4().hex[:8]}"
        db.add(Label(name=label_name, creator_id=admin.user_id, type="public"))
        db.commit()

        listed = client.get(
            f"{settings.API_V1_STR}/labels",
            headers=normal_user_token_headers,
        )
        assert listed.status_code == 200
        data = listed.json()["data"]
        names = [item["name"] for item in data]
        assert label_name in names
        public_item = next(item for item in data if item["name"] == label_name)
        assert public_item["type"] == "public"

    def test_list_labels_excludes_admin_private_label(
        self, client: TestClient, superuser_token_headers: dict, normal_user_token_headers: dict
    ) -> None:
        """Admin-created labels are private unless their type is public."""
        label_name = f"apriv_{uuid4().hex[:8]}"
        created = client.post(
            f"{settings.API_V1_STR}/labels",
            headers=superuser_token_headers,
            json={"name": label_name},
        )
        assert created.status_code == 200

        listed = client.get(
            f"{settings.API_V1_STR}/labels",
            headers=normal_user_token_headers,
        )
        assert listed.status_code == 200
        names = [item["name"] for item in listed.json()["data"]]
        assert label_name not in names

    def test_list_labels_anonymous_allowed(self, client: TestClient) -> None:
        """GET /labels allows anonymous access."""
        r = client.get(f"{settings.API_V1_STR}/labels")
        assert r.status_code == 200

    def test_list_labels_anonymous_only_public_labels(self, client: TestClient, db: Session) -> None:
        """Anonymous should only see public labels."""
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        assert admin is not None
        normal_user = db.exec(select(User).where(User.role_id != 1)).first()
        if normal_user is None:
            role = Role(name=f"lbl_na_{uuid4().hex[:6]}")
            db.add(role)
            db.flush()
            normal_user = User(
                username=f"ln_{uuid4().hex[:8]}",
                email=f"ln_{uuid4().hex[:8]}@example.com",
                password="hashed",
                name="Labels Normal",
                role_id=role.role_id,
            )
            db.add(normal_user)
            db.commit()
            db.refresh(normal_user)

        admin_label_name = f"a_{uuid4().hex[:8]}"
        private_label_name = f"p_{uuid4().hex[:8]}"
        db.add_all(
            [
                Label(name=admin_label_name, creator_id=admin.user_id, type="public"),
                Label(name=private_label_name, creator_id=normal_user.user_id),
            ]
        )
        db.commit()

        r = client.get(f"{settings.API_V1_STR}/labels")
        assert r.status_code == 200
        names = [item["name"] for item in r.json()["data"]]
        assert admin_label_name in names
        assert private_label_name not in names

    def test_list_labels_anonymous_empty_returns_empty_list(self, client: TestClient, db: Session) -> None:
        """Anonymous list returns empty array when no public labels are visible."""
        non_admin = db.exec(select(User).where(User.role_id != 1)).first()
        if non_admin is None:
            role = Role(name=f"lbl_emp_{uuid4().hex[:6]}")
            db.add(role)
            db.flush()
            non_admin = User(
                username=f"le_{uuid4().hex[:8]}",
                email=f"le_{uuid4().hex[:8]}@example.com",
                password="hashed",
                name="Labels Empty",
                role_id=role.role_id,
            )
            db.add(non_admin)
            db.commit()
            db.refresh(non_admin)
        labels = db.exec(select(Label)).all()
        for label in labels:
            label.creator_id = non_admin.user_id
            label.type = "private"
            db.add(label)
        db.commit()

        r = client.get(f"{settings.API_V1_STR}/labels")
        assert r.status_code == 200
        assert r.json()["data"] == []

    def test_list_labels_success(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        """GET /labels returns own and public labels."""
        # Get the current normal user
        user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
        assert user is not None
        
        # Get an admin user
        admin = db.exec(select(User).where(User.role_id == 1)).first()
        assert admin is not None
        
        # Create another normal user
        other_user = User(
            username="otheruser", 
            email="other@example.com", 
            password="hashed", 
            name="Other", 
            role_id=2
        )
        db.add(other_user)
        db.commit()
        db.refresh(other_user)
        
        l1 = Label(name="user_label", creator_id=user.user_id)
        l2 = Label(name="public_label", creator_id=admin.user_id, type="public")
        l3 = Label(name="other_label", creator_id=other_user.user_id) 
        
        db.add_all([l1, l2, l3])
        db.commit()
        
        r = client.get(
            f"{settings.API_V1_STR}/labels",
            headers=normal_user_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        names = [l["name"] for l in data]
        assert "user_label" in names
        assert "public_label" in names
        assert "other_label" not in names
        assert all("type" in item for item in data)

    def test_set_media_labels_unauthorized(self, client: TestClient) -> None:
        """PUT /media/{id} requires authentication."""
        r = client.put(f"{settings.API_V1_STR}/media-labels", json={"label_id": None})
        assert r.status_code == 401

    def test_set_media_labels_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """PUT /media/{id} returns 404 if media not found."""
        r = client.put(
            f"{settings.API_V1_STR}/media-labels",
            headers=superuser_token_headers,
            params={"project_id": 1},
            json={"media_ids": [99999], "label_id": None},
        )
        assert r.status_code == 200
        assert r.json()["data"]["failed"][0]["media_id"] == 99999

    def test_set_media_label_rejects_label_ids_payload(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """List payloads must not be accepted because extra fields are forbidden."""
        s = AudioSetting(duration_s=10.0, sampling_rate_hz=44100)
        db.add(s)
        db.flush()
        media = Media(media_type="audio", audio_setting_id=s.audio_setting_id, creator_id=1)
        db.add(media)
        db.commit()
        db.refresh(media)

        r = client.put(
            f"{settings.API_V1_STR}/media-labels",
            headers=superuser_token_headers,
            json={"label_ids": [1]},
        )
        assert r.status_code == 422

    def test_set_media_labels_success(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Successfully set, override, and clear the single label for a media."""
        # 1. Setup media linked to a collection (required by media detail permission checks)
        collection = Collection(name="Label Col A", public_access=True, creator_id=1)
        db.add(collection)
        db.flush()
        project_id = _link_collection_to_project(db, collection, 1)

        s = AudioSetting(duration_s=10.0, sampling_rate_hz=44100)
        db.add(s)
        db.flush()
        media = Media(media_type="audio", audio_setting_id=s.audio_setting_id, creator_id=1)
        db.add(media)
        db.flush()
        db.add(
            MediaCollection(
                media_id=media.media_id,
                collection_id=collection.collection_id,
                added_by=1,
            )
        )
        db.commit()
        db.refresh(media)
        
        l1 = Label(name="Tag A", creator_id=1)
        l2 = Label(name="Tag B", creator_id=1)
        db.add_all([l1, l2])
        db.commit()
        db.refresh(l1)
        db.refresh(l2)
        
        # 2. Set label
        r = client.put(
            f"{settings.API_V1_STR}/media-labels",
            headers=superuser_token_headers,
            params={"project_id": project_id},
            json={"media_ids": [media.media_id], "label_id": l1.label_id},
        )
        assert r.status_code == 200
        assert r.json()["data"]["succeeded"] == [media.media_id]
        lm = db.exec(select(LabelMedia).where(LabelMedia.media_id == media.media_id)).first()
        assert lm is not None
        assert lm.label_id == l1.label_id

        # 3. Override with another label
        r = client.put(
            f"{settings.API_V1_STR}/media-labels",
            headers=superuser_token_headers,
            params={"project_id": project_id},
            json={"media_ids": [media.media_id], "label_id": l2.label_id},
        )
        assert r.status_code == 200
        assert r.json()["data"]["succeeded"] == [media.media_id]
        lm2 = db.exec(select(LabelMedia).where(LabelMedia.media_id == media.media_id)).first()
        assert lm2 is not None
        assert lm2.label_id == l2.label_id

        # 4. Clear
        r = client.put(
            f"{settings.API_V1_STR}/media-labels",
            headers=superuser_token_headers,
            params={"project_id": project_id},
            json={"media_ids": [media.media_id], "label_id": None},
        )
        assert r.status_code == 200
        assert r.json()["data"]["succeeded"] == [media.media_id]

    def test_set_media_labels_invalid_id(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        """Return 400 if label_id is not accessible."""
        # 1. Setup media and permissions
        user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
        collection = Collection(name="Public Col", public_access=True, creator_id=user.user_id)
        db.add(collection)
        db.flush()
        project_id = _link_collection_to_project(db, collection, user.user_id)
        
        s = AudioSetting(duration_s=10.0, sampling_rate_hz=44100)
        db.add(s)
        db.flush()
        media = Media(media_type="audio", audio_setting_id=s.audio_setting_id, creator_id=user.user_id)
        db.add(media)
        db.flush()
        
        # Link media to collection
        mc = MediaCollection(media_id=media.media_id, collection_id=collection.collection_id, added_by=user.user_id)
        db.add(mc)
        db.commit()
        db.refresh(media)
        
        # 2. Create another user's private label
        other_user = User(
            username="otheruser2", 
            email="other2@example.com", 
            password="hashed", 
            name="Other2", 
            role_id=2
        )
        db.add(other_user)
        db.flush()
        other_label = Label(name="private_other", creator_id=other_user.user_id)
        db.add(other_label)
        db.commit()
        db.refresh(other_label)
        
        r = client.put(
            f"{settings.API_V1_STR}/media-labels",
            headers=normal_user_token_headers,
            params={"project_id": project_id},
            json={"media_ids": [media.media_id], "label_id": other_label.label_id},
        )
        assert r.status_code == 200
        assert "not accessible" in r.json()["data"]["failed"][0]["message"]

    def test_set_media_labels_updates_task_status(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Setting meaningful labels should auto-update task status to reviewed."""
        # Setup media linked to a collection (required by media detail permission checks)
        collection = Collection(name="Label Col B", public_access=True, creator_id=1)
        db.add(collection)
        db.flush()
        project_id = _link_collection_to_project(db, collection, 1)

        s = AudioSetting(duration_s=10.0, sampling_rate_hz=44100)
        db.add(s)
        db.flush()
        media = Media(media_type="audio", audio_setting_id=s.audio_setting_id, creator_id=1)
        db.add(media)
        db.flush()
        db.add(
            MediaCollection(
                media_id=media.media_id,
                collection_id=collection.collection_id,
                added_by=1,
            )
        )
        db.commit()
        db.refresh(media)
        
        # Setup admin assignment task
        task = Task(
            type="media",
            media_id=media.media_id,
            assigner_id=1,
            assignee_id=1,
            status="assigned"
        )
        db.add(task)
        
        # Add labels
        l_not_analysed = Label(name="not analysed", creator_id=1)
        l_meaningful = Label(name="some tagging", creator_id=1)
        db.add_all([l_not_analysed, l_meaningful])
        
        db.commit()
        db.refresh(task)
        db.refresh(l_not_analysed)
        db.refresh(l_meaningful)
        
        # 1. Update with label_id=1 (not analysed shouldn't complete the task)
        # Note: In real app, label 1 is globally known, here we just check if it's 1.
        # But wait, the system logic checks 'lid != 1'. If l_not_analysed doesn't get id 1,
        # it might fail; our test logic requires lid=1.
        # Let's bypass creating a new label if id=1 already exists, or hardcode the id to be safe.
        # Wait, the database might already have label_id 1 from data.sql. So let's just query label_id 1.
        l_not_analysed = db.get(Label, 1)
        if not l_not_analysed:
            l_not_analysed = Label(label_id=1, name="not analysed", creator_id=1)
            db.add(l_not_analysed)
            db.commit()
            db.refresh(l_not_analysed)
            
        r = client.put(
            f"{settings.API_V1_STR}/media-labels",
            headers=superuser_token_headers,
            params={"project_id": project_id},
            json={"media_ids": [media.media_id], "label_id": 1},
        )
        assert r.status_code == 200
        
        # Check task status (should still be 'assigned')
        db.refresh(task)
        assert task.status == "assigned"
        
        # 2. Update with meaningful label
        r = client.put(
            f"{settings.API_V1_STR}/media-labels",
            headers=superuser_token_headers,
            params={"project_id": project_id},
            json={"media_ids": [media.media_id], "label_id": l_meaningful.label_id},
        )
        assert r.status_code == 200
        
        # Check task status (should now be 'reviewed')
        db.refresh(task)
        assert task.status == "reviewed"

    # ------------------------------------------------------------------
    # DELETE /labels/{label_id}
    # ------------------------------------------------------------------

    def test_delete_label_unauthorized(self, client: TestClient) -> None:
        """DELETE /labels/{id} requires authentication."""
        r = client.delete(f"{settings.API_V1_STR}/labels/9999")
        assert r.status_code == 401

    def test_delete_label_not_found(
        self, client: TestClient, normal_user_token_headers: dict
    ) -> None:
        """DELETE /labels/{id} returns 404 for non-existent label."""
        r = client.delete(
            f"{settings.API_V1_STR}/labels/9999999",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 404

    def test_delete_system_label_forbidden(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """DELETE /labels/{id} is always forbidden for system labels."""
        for label_id in (1, 2, 3):
            r = client.delete(
                f"{settings.API_V1_STR}/labels/{label_id}",
                headers=superuser_token_headers,
            )
            assert r.status_code == 403

    def test_delete_own_label_success(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        """Normal user can delete their own label."""
        del_name = f"to_delete_{uuid4().hex[:8]}"
        created = client.post(
            f"{settings.API_V1_STR}/labels",
            headers=normal_user_token_headers,
            json={"name": del_name},
        )
        assert created.status_code == 200
        assert created.json()["data"] is None
        user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).one()
        lbl = db.exec(select(Label).where(Label.name == del_name, Label.creator_id == user.user_id)).one()
        label_id = lbl.label_id

        r = client.delete(
            f"{settings.API_V1_STR}/labels/{label_id}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        assert r.json()["code"] == 0

        # Confirm it's gone
        listed = client.get(
            f"{settings.API_V1_STR}/labels",
            headers=normal_user_token_headers,
        )
        ids = [item["label_id"] for item in listed.json()["data"]]
        assert label_id not in ids

    def test_delete_other_users_label_forbidden(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        """Normal user cannot delete another user's label."""
        other = User(
            username="del_other",
            email="del_other@example.com",
            password="hashed",
            name="DelOther",
            role_id=2,
        )
        db.add(other)
        db.flush()
        other_label = Label(name=f"private_{uuid4().hex[:6]}", creator_id=other.user_id)
        db.add(other_label)
        db.commit()
        db.refresh(other_label)

        r = client.delete(
            f"{settings.API_V1_STR}/labels/{other_label.label_id}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 403

    def test_delete_label_cascades_label_media(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Deleting a label removes associated label_media rows."""
        s = AudioSetting(duration_s=5.0, sampling_rate_hz=22050)
        db.add(s)
        db.flush()
        media = Media(media_type="audio", audio_setting_id=s.audio_setting_id, creator_id=1)
        db.add(media)
        db.flush()
        lbl = Label(name=f"cascade_{uuid4().hex[:6]}", creator_id=1)
        db.add(lbl)
        db.commit()
        db.refresh(media)
        db.refresh(lbl)

        lm = LabelMedia(media_id=media.media_id, user_id=1, label_id=lbl.label_id)
        db.add(lm)
        db.commit()

        r = client.delete(
            f"{settings.API_V1_STR}/labels/{lbl.label_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200

        remaining = db.exec(
            select(LabelMedia).where(LabelMedia.label_id == lbl.label_id)
        ).all()
        assert remaining == []

    def test_admin_cannot_delete_other_users_label(
        self, client: TestClient, superuser_token_headers: dict, normal_user_token_headers: dict, db: Session
    ) -> None:
        """Admin cannot delete a label created by a normal user."""
        del_name = f"admin_del_{uuid4().hex[:8]}"
        created = client.post(
            f"{settings.API_V1_STR}/labels",
            headers=normal_user_token_headers,
            json={"name": del_name},
        )
        assert created.status_code == 200
        assert created.json()["data"] is None
        user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).one()
        lbl = db.exec(select(Label).where(Label.name == del_name, Label.creator_id == user.user_id)).one()
        label_id = lbl.label_id

        r = client.delete(
            f"{settings.API_V1_STR}/labels/{label_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 403
