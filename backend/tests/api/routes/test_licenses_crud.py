"""
Tests for License CRUD endpoints.

Covers: list, create, get, update, delete, options, permission checks.
"""
import csv

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models.media import License
from tests.utils.csv import read_csv_rows

BASE = f"{settings.API_V1_STR}/licenses"
OPTIONS = f"{settings.API_V1_STR}/license-options"


# Helpers

def _create_license(db: Session, name: str = "Test License", link: str = "https://example.com") -> License:
    obj = License(name=name, link=link)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# GET /license-options  (public)

class TestLicenseOptions:
    def test_options_no_auth(self, client: TestClient, db: Session) -> None:
        """Options endpoint is public."""
        _create_license(db, "CC0", "https://creativecommons.org/publicdomain/zero/1.0/")
        r = client.get(OPTIONS)
        assert r.status_code == 200
        data = r.json()["data"]
        assert isinstance(data, list)
        assert any(item["name"] == "CC0" for item in data)

    def test_options_returns_id_and_name(self, client: TestClient, db: Session) -> None:
        obj = _create_license(db)
        r = client.get(OPTIONS)
        assert r.status_code == 200
        items = r.json()["data"]
        found = next((i for i in items if i["license_id"] == obj.license_id), None)
        assert found is not None
        assert "name" in found
        assert "link" not in found


# GET /licenses  (admin)

class TestListLicenses:
    def test_list_requires_auth(self, client: TestClient) -> None:
        r = client.get(BASE)
        assert r.status_code in (401, 403)

    def test_list_normal_user_forbidden(self, client: TestClient, normal_user_token_headers: dict) -> None:
        r = client.get(BASE, headers=normal_user_token_headers)
        assert r.status_code == 403

    def test_list_admin(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        _create_license(db, "CC-BY", "https://creativecommons.org/licenses/by/4.0/")
        r = client.get(BASE, headers=superuser_token_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert isinstance(body["data"], list)
        assert body["page_info"]["total"] >= 1

    def test_list_pagination(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        for i in range(3):
            _create_license(db, f"License {i}", f"https://example.com/{i}")
        r = client.get(f"{BASE}?page=1&page_size=2", headers=superuser_token_headers)
        assert r.status_code == 200
        assert len(r.json()["data"]) <= 2

    def test_list_filter_by_license_id(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        target = _create_license(db, "FilterLicense", "https://license-filter.example")
        _create_license(db, "OtherLicense", "https://other-license.example")
        r = client.get(f"{BASE}?license_id={target.license_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        items = r.json()["data"]
        assert len(items) == 1
        assert items[0]["license_id"] == target.license_id

    def test_list_sort_by_license_id_desc(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        first = _create_license(db, "License Sort A", "https://sort-a.example")
        second = _create_license(db, "License Sort B", "https://sort-b.example")

        r = client.get(
            f"{BASE}?order_by=license_id&order_dir=desc&page_size=100",
            headers=superuser_token_headers,
        )

        assert r.status_code == 200
        items = [item for item in r.json()["data"] if item["license_id"] in {first.license_id, second.license_id}]
        assert items[0]["license_id"] == second.license_id
        assert items[1]["license_id"] == first.license_id


class TestExportLicenses:
    def test_export_licenses_with_filters(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        license_obj = _create_license(db, "ExportLicense", "https://export-license.example")
        r = client.get(
            f"{BASE}/exports?license_id={license_obj.license_id}&name=ExportLicense&order_by=link",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.headers.get("content-disposition") == (
            'attachment; filename="licenses.csv"; '
            "filename*=UTF-8''licenses.csv"
        )
        rows = read_csv_rows(r.text)
        assert rows[0] == ["license_id", "name", "link"]
        assert len(rows) == 2
        assert rows[1][0] == str(license_obj.license_id)


# POST /licenses  (admin)

class TestCreateLicense:
    def test_create_requires_auth(self, client: TestClient) -> None:
        r = client.post(BASE, json={"name": "X", "link": "https://x.com"})
        assert r.status_code in (401, 403)

    def test_create_normal_user_forbidden(self, client: TestClient, normal_user_token_headers: dict) -> None:
        r = client.post(BASE, headers=normal_user_token_headers, json={"name": "X", "link": "https://x.com"})
        assert r.status_code == 403

    def test_create_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        payload = {"name": "CC-BY-NC-4.0", "link": "https://creativecommons.org/licenses/by-nc/4.0/"}
        r = client.post(BASE, headers=superuser_token_headers, json=payload)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["name"] == "CC-BY-NC-4.0"
        assert data["link"] == payload["link"]
        assert "license_id" in data

    def test_create_missing_field(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.post(BASE, headers=superuser_token_headers, json={"name": "Missing link"})
        assert r.status_code == 422

    def test_create_rejects_normalized_duplicate_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        _create_license(db, "Duplicate License", "https://creativecommons.org/licenses/by/4.0/")

        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={"name": "  duplicate license  ", "link": "https://example.com/other"},
        )

        assert response.status_code == 409
        assert response.json()["message"] == "License name already exists"

    def test_create_allows_same_link_with_different_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        link = "https://creativecommons.org/licenses/by/4.0/"
        _create_license(db, "CC-BY", link)

        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={"name": "Attribution License", "link": link},
        )

        assert response.status_code == 200


# GET /licenses/{license_id}  (admin)

class TestGetLicense:
    def test_get_requires_auth(self, client: TestClient, db: Session) -> None:
        obj = _create_license(db)
        r = client.get(f"{BASE}/{obj.license_id}")
        assert r.status_code in (401, 403)

    def test_get_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.get(f"{BASE}/999999", headers=superuser_token_headers)
        assert r.status_code == 404

    def test_get_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        obj = _create_license(db)
        r = client.get(f"{BASE}/{obj.license_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["license_id"] == obj.license_id
        assert data["name"] == obj.name
        assert data["link"] == obj.link


# PUT /licenses/{license_id}  (admin)

class TestUpdateLicense:
    def test_update_requires_auth(self, client: TestClient, db: Session) -> None:
        obj = _create_license(db)
        r = client.put(f"{BASE}/{obj.license_id}", json={"name": "Updated"})
        assert r.status_code in (401, 403)

    def test_update_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.put(f"{BASE}/999999", headers=superuser_token_headers, json={"name": "X"})
        assert r.status_code == 404

    def test_update_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        obj = _create_license(db)
        r = client.put(
            f"{BASE}/{obj.license_id}",
            headers=superuser_token_headers,
            json={"name": "Updated Name", "link": "https://updated.example.com"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["name"] == "Updated Name"
        assert data["link"] == "https://updated.example.com"

    def test_update_rejects_normalized_duplicate_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        existing = _create_license(db, "Existing License", "https://creativecommons.org/licenses/by/4.0/")
        target = _create_license(db, "Target License", "https://creativecommons.org/publicdomain/zero/1.0/")

        response = client.put(
            f"{BASE}/{target.license_id}",
            headers=superuser_token_headers,
            json={"name": " existing license "},
        )

        assert response.status_code == 409
        db.refresh(target)
        assert target.name == "Target License"
        assert existing.name == "Existing License"

    def test_update_own_name_normalizes_and_succeeds(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        target = _create_license(db, "Own License", "https://creativecommons.org/licenses/by/4.0/")

        response = client.put(
            f"{BASE}/{target.license_id}",
            headers=superuser_token_headers,
            json={"name": "  own license  "},
        )

        assert response.status_code == 200
        assert response.json()["data"]["name"] == "own license"


# DELETE /licenses/{license_id}  (admin)

class TestDeleteLicense:
    def test_delete_requires_auth(self, client: TestClient, db: Session) -> None:
        obj = _create_license(db)
        r = client.delete(f"{BASE}/{obj.license_id}")
        assert r.status_code in (401, 403)

    def test_delete_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.delete(f"{BASE}/999999", headers=superuser_token_headers)
        assert r.status_code == 404

    def test_delete_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        obj = _create_license(db)
        r = client.delete(f"{BASE}/{obj.license_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        # Verify it's gone
        r2 = client.get(f"{BASE}/{obj.license_id}", headers=superuser_token_headers)
        assert r2.status_code == 404

    def test_delete_in_use_rejected(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """License referenced by media cannot be deleted."""
        from sqlmodel import select
        from app.models.media import AudioSetting, Media
        from app.models import User
        license_obj = _create_license(db, "In Use License", "https://inuse.com")
        user = db.exec(select(User)).first()
        audio_setting = AudioSetting(sampling_rate_hz=44100, duration_s=60.0)
        db.add(audio_setting)
        db.commit()
        db.refresh(audio_setting)
        media = Media(
            media_type="audio",
            license_id=license_obj.license_id,
            uploader_id=user.user_id,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.commit()
        r = client.delete(f"{BASE}/{license_obj.license_id}", headers=superuser_token_headers)
        assert r.status_code == 400


def test_license_links_are_validated(client: TestClient, superuser_token_headers: dict, db: Session) -> None:
    for link in ("reference text", "ftp://example.com/license", "   "):
        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={"name": "Invalid Link", "link": link},
        )
        assert response.status_code == 422

    license_obj = _create_license(db)
    for link in (None, ""):
        response = client.put(
            f"{BASE}/{license_obj.license_id}",
            headers=superuser_token_headers,
            json={"link": link},
        )
        assert response.status_code == 422
