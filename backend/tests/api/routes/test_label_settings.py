"""Tests for admin label settings endpoints."""
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Role, User
from app.models.label import Label, LabelMedia
from app.models.media import Media
from tests.utils.csv import read_csv_rows

BASE = f"{settings.API_V1_STR}/label-settings"


def _admin_user(db: Session) -> User:
    user = db.exec(select(User).where(User.role_id == 1)).first()
    assert user is not None
    return user


def _create_user(db: Session, *, name: str) -> User:
    role = Role(name=f"lbls_{uuid4().hex[:6]}")
    db.add(role)
    db.flush()
    user = User(
        username=f"ls_{uuid4().hex[:8]}",
        name=name,
        email=f"ls_{uuid4().hex[:8]}@example.com",
        password="hashed_password",
        role_id=role.role_id,
    )
    db.add(user)
    db.flush()
    return user


def _create_label(
    db: Session,
    *,
    name: str,
    creator_id: int,
    type: str = "private",
    creation_date: datetime | None = None,
) -> Label:
    label = Label(name=name, creator_id=creator_id, type=type)
    if creation_date is not None:
        label.creation_date = creation_date
    db.add(label)
    db.flush()
    return label


class TestLabelSettingsList:
    def test_list_requires_admin(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
    ) -> None:
        assert client.get(BASE).status_code == 401
        assert client.get(BASE, headers=normal_user_token_headers).status_code == 403

    def test_list_filters_and_returns_creator_name(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        creator = _create_user(db, name="Label Creator")
        now = datetime(2026, 5, 20, 12, 0, 0)
        target = _create_label(
            db,
            name=f"bird_{uuid4().hex[:5]}",
            creator_id=creator.user_id,
            type="public",
            creation_date=now,
        )
        _create_label(db, name=f"frog_{uuid4().hex[:5]}", creator_id=creator.user_id, type="private")
        db.commit()

        response = client.get(
            BASE,
            headers=superuser_token_headers,
            params={
                "label_id": target.label_id,
                "name": "bird",
                "type": "public",
                "creator_id": creator.user_id,
                "creation_date_from": (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "creation_date_to": (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["page_info"]["total"] == 1
        item = payload["data"][0]
        assert item["label_id"] == target.label_id
        assert item["creator_id"] == creator.user_id
        assert item["creator_name"] == "Label Creator"
        assert item["type"] == "public"

    def test_list_sorts_by_creator_name(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        zed = _create_user(db, name="Zed Creator")
        amy = _create_user(db, name="Amy Creator")
        _create_label(db, name=f"z_{uuid4().hex[:6]}", creator_id=zed.user_id)
        _create_label(db, name=f"a_{uuid4().hex[:6]}", creator_id=amy.user_id)
        db.commit()

        response = client.get(
            BASE,
            headers=superuser_token_headers,
            params={"order_by": "creator_name", "order_dir": "asc", "page_size": 100},
        )

        assert response.status_code == 200
        creator_names = [item["creator_name"] for item in response.json()["data"]]
        assert creator_names.index("Amy Creator") < creator_names.index("Zed Creator")

    def test_list_filters_type_with_fuzzy_match(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        creator = _create_user(db, name="Type Filter Creator")
        public_label = _create_label(
            db,
            name=f"pub_{uuid4().hex[:5]}",
            creator_id=creator.user_id,
            type="public",
        )
        private_label = _create_label(
            db,
            name=f"pri_{uuid4().hex[:5]}",
            creator_id=creator.user_id,
            type="private",
        )
        db.commit()

        response = client.get(
            BASE,
            headers=superuser_token_headers,
            params={"type": "publ"},
        )

        assert response.status_code == 200, response.json()
        ids = {item["label_id"] for item in response.json()["data"]}
        assert public_label.label_id in ids
        assert private_label.label_id not in ids


class TestLabelSettingsCrud:
    def test_create_get_update_and_delete(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        name = f"ls_{uuid4().hex[:8]}"
        created = client.post(
            BASE,
            headers=superuser_token_headers,
            json={"name": name, "type": "public"},
        )
        assert created.status_code == 200
        created_item = created.json()["data"]
        assert created_item["name"] == name
        assert created_item["type"] == "public"
        assert created_item["creator_id"] == _admin_user(db).user_id
        assert created_item["creator_name"]

        label_id = created_item["label_id"]
        detail = client.get(f"{BASE}/{label_id}", headers=superuser_token_headers)
        assert detail.status_code == 200
        assert detail.json()["data"]["label_id"] == label_id

        updated = client.put(
            f"{BASE}/{label_id}",
            headers=superuser_token_headers,
            json={"name": f"upd_{uuid4().hex[:6]}", "type": "private"},
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["type"] == "private"

        deleted = client.delete(f"{BASE}/{label_id}", headers=superuser_token_headers)
        assert deleted.status_code == 200
        assert db.get(Label, label_id) is None

    def test_update_system_label_type_allowed_and_delete_forbidden(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        system_label = db.get(Label, 1)
        if system_label is None:
            system_label = Label(label_id=1, name="not analysed", creator_id=1, type="public")
            db.add(system_label)
            db.commit()

        update = client.put(
            f"{BASE}/1",
            headers=superuser_token_headers,
            json={"type": "private"},
        )
        assert update.status_code == 200
        assert update.json()["data"]["type"] == "private"

        delete = client.delete(f"{BASE}/1", headers=superuser_token_headers)
        assert delete.status_code == 403

    def test_delete_cleans_label_media(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        admin = _admin_user(db)
        label = _create_label(db, name=f"del_{uuid4().hex[:6]}", creator_id=admin.user_id)
        media = Media(media_type="audio", is_metadata=True, creator_id=admin.user_id)
        db.add(media)
        db.flush()
        db.add(LabelMedia(media_id=media.media_id, user_id=admin.user_id, label_id=label.label_id))
        db.commit()

        response = client.delete(f"{BASE}/{label.label_id}", headers=superuser_token_headers)

        assert response.status_code == 200
        assert db.exec(select(LabelMedia).where(LabelMedia.label_id == label.label_id)).all() == []

    def test_validation_errors(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        name = f"dup_{uuid4().hex[:6]}"
        first = client.post(BASE, headers=superuser_token_headers, json={"name": name})
        assert first.status_code == 200

        duplicate = client.post(BASE, headers=superuser_token_headers, json={"name": name})
        assert duplicate.status_code == 400

        invalid_type = client.post(
            BASE,
            headers=superuser_token_headers,
            json={"name": f"bad_{uuid4().hex[:6]}", "type": "global"},
        )
        assert invalid_type.status_code == 422

        empty_name = client.post(BASE, headers=superuser_token_headers, json={"name": "   "})
        assert empty_name.status_code == 422

        long_name = client.post(BASE, headers=superuser_token_headers, json={"name": "x" * 21})
        assert long_name.status_code == 422


class TestLabelSettingsOptionsAndExport:

    def test_export_uses_filters_and_includes_creator_name(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        creator = _create_user(db, name="Export Creator")
        label = _create_label(db, name=f"exp_{uuid4().hex[:6]}", creator_id=creator.user_id, type="public")
        _create_label(db, name=f"skip_{uuid4().hex[:5]}", creator_id=creator.user_id, type="private")
        db.commit()

        response = client.get(
            f"{BASE}/exports",
            headers=superuser_token_headers,
            params={"type": "public", "creator_id": creator.user_id},
        )

        assert response.status_code == 200
        assert response.headers.get("content-disposition") == (
            'attachment; filename="label-settings.csv"; '
            "filename*=UTF-8''label-settings.csv"
        )
        rows = read_csv_rows(response.text)
        assert rows[0] == ["label_id", "name", "type", "creator_id", "creator_name", "creation_date"]
        assert any(row[0] == str(label.label_id) and row[4] == "Export Creator" for row in rows[1:])
