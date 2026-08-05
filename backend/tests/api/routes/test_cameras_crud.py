"""
Tests for Camera CRUD endpoints and camera-lens association management.

Covers: list, create, get, update, delete, add/remove lens associations, permissions.
"""
import csv

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models.device import Camera, CameraLens, Lens, Sensor
from tests.utils.csv import read_csv_rows

BASE = f"{settings.API_V1_STR}/cameras"


# Helpers

def _make_camera(db: Session, name: str = "Reconyx HP2X", brand: str = "Reconyx") -> Camera:
    obj = Camera(name=name, brand=brand)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _make_lens(db: Session, name: str = "Wide Angle") -> Lens:
    obj = Lens(name=name, focal_length="3.1mm", max_aperture="f/2.0", brand="Reconyx")
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# GET /cameras  (admin)

class TestListCameras:
    def test_list_requires_auth(self, client: TestClient) -> None:
        r = client.get(BASE)
        assert r.status_code in (401, 403)

    def test_list_normal_user_forbidden(self, client: TestClient, normal_user_token_headers: dict) -> None:
        r = client.get(BASE, headers=normal_user_token_headers)
        assert r.status_code == 403

    def test_list_admin(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        _make_camera(db)
        r = client.get(BASE, headers=superuser_token_headers)
        assert r.status_code == 200
        assert r.json()["page_info"]["total"] >= 1

    def test_list_includes_lens_count(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "CountCamera")
        lens = _make_lens(db, "CountLens")
        assoc = CameraLens(camera_id=camera.camera_id, lens_id=lens.lens_id)
        db.add(assoc)
        db.commit()
        r = client.get(BASE, headers=superuser_token_headers)
        items = r.json()["data"]
        found = next((i for i in items if i["camera_id"] == camera.camera_id), None)
        assert found is not None
        assert found["lens_count"] == 1

    def test_list_filter_by_camera_id_and_uuid(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        target = _make_camera(db, "FilterTargetCamera")
        _make_camera(db, "OtherCamera")
        r = client.get(
            f"{BASE}?camera_id={target.camera_id}&uuid={target.uuid}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        items = r.json()["data"]
        assert len(items) == 1
        assert items[0]["camera_id"] == target.camera_id

    def test_list_filter_by_lens_count(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        cam0 = _make_camera(db, "LensCount0")
        cam1 = _make_camera(db, "LensCount1")
        lens = _make_lens(db, "LensForCount")
        db.add(CameraLens(camera_id=cam1.camera_id, lens_id=lens.lens_id))
        db.commit()

        r0 = client.get(f"{BASE}?lens_count=0", headers=superuser_token_headers)
        assert r0.status_code == 200
        ids0 = {i["camera_id"] for i in r0.json()["data"]}
        assert cam0.camera_id in ids0
        assert cam1.camera_id not in ids0

        r1 = client.get(f"{BASE}?lens_count=1", headers=superuser_token_headers)
        assert r1.status_code == 200
        ids1 = {i["camera_id"] for i in r1.json()["data"]}
        assert cam1.camera_id in ids1

    def test_list_filter_camera_id_uuid_and_lens_count_together(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "CombinedFilterCamera")
        lens = _make_lens(db, "CombinedFilterLens")
        db.add(CameraLens(camera_id=camera.camera_id, lens_id=lens.lens_id))
        db.commit()
        r = client.get(
            f"{BASE}?camera_id={camera.camera_id}&uuid={camera.uuid}&lens_count=1",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        items = r.json()["data"]
        assert len(items) == 1
        assert items[0]["camera_id"] == camera.camera_id

    def test_list_sort_by_lens_count_desc(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        low = _make_camera(db, "SortLensCountLow")
        high = _make_camera(db, "SortLensCountHigh")
        lens1 = _make_lens(db, "SortLensCountLens1")
        lens2 = _make_lens(db, "SortLensCountLens2")
        db.add(CameraLens(camera_id=high.camera_id, lens_id=lens1.lens_id))
        db.add(CameraLens(camera_id=high.camera_id, lens_id=lens2.lens_id))
        db.commit()

        r = client.get(
            f"{BASE}?order_by=lens_count&order_dir=desc&page_size=100",
            headers=superuser_token_headers,
        )

        assert r.status_code == 200
        items = [item for item in r.json()["data"] if item["camera_id"] in {low.camera_id, high.camera_id}]
        assert items[0]["camera_id"] == high.camera_id
        assert items[0]["lens_count"] > items[1]["lens_count"]

    def test_list_defaults_to_camera_id_asc(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        first = _make_camera(db, "DefaultSortCameraA")
        second = _make_camera(db, "DefaultSortCameraB")

        r = client.get(
            f"{BASE}?camera_id={first.camera_id}&page_size=100",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.json()["data"][0]["camera_id"] == first.camera_id

        r_all = client.get(f"{BASE}?page_size=100", headers=superuser_token_headers)
        assert r_all.status_code == 200
        items = [item for item in r_all.json()["data"] if item["camera_id"] in {first.camera_id, second.camera_id}]
        assert [item["camera_id"] for item in items] == [first.camera_id, second.camera_id]

    def test_list_invalid_uuid_is_ignored(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        _make_camera(db, "InvalidUuidCamera")
        r = client.get(f"{BASE}?uuid=not-a-uuid", headers=superuser_token_headers)
        assert r.status_code == 200
        assert r.json()["page_info"]["total"] >= 1


class TestExportCameras:
    def test_export_cameras_with_filters(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "ExportCamera", "ExportBrand")
        lens = _make_lens(db, "ExportLens")
        db.add(CameraLens(camera_id=camera.camera_id, lens_id=lens.lens_id))
        db.commit()

        r = client.get(
            f"{BASE}/exports?camera_id={camera.camera_id}&uuid={camera.uuid}&lens_count=1&order_by=brand",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        assert r.headers.get("content-disposition") == (
            'attachment; filename="cameras.csv"; '
            "filename*=UTF-8''cameras.csv"
        )
        rows = read_csv_rows(r.text)
        assert rows[0] == ["camera_id", "uuid", "name", "version", "brand"]
        assert len(rows) == 2
        assert rows[1][0] == str(camera.camera_id)

    def test_export_defaults_to_camera_id_asc(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        first = _make_camera(db, "ExportDefaultSortCameraA")
        second = _make_camera(db, "ExportDefaultSortCameraB")

        r = client.get(f"{BASE}/exports", headers=superuser_token_headers)
        assert r.status_code == 200
        rows = read_csv_rows(r.text)
        data_rows = [row for row in rows[1:] if row and row[0] in {str(first.camera_id), str(second.camera_id)}]
        assert [row[0] for row in data_rows] == [str(first.camera_id), str(second.camera_id)]


# POST /cameras  (admin)

class TestCreateCamera:
    def test_create_requires_auth(self, client: TestClient) -> None:
        r = client.post(BASE, json={"name": "X"})
        assert r.status_code in (401, 403)

    def test_create_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        payload = {"name": "BushnellCore", "version": "v2", "brand": "Bushnell"}
        r = client.post(BASE, headers=superuser_token_headers, json=payload)
        assert r.status_code == 200
        assert r.json()["data"] is None
        cam = db.exec(select(Camera).where(Camera.name == "BushnellCore").order_by(Camera.camera_id.desc())).first()
        assert cam is not None
        assert cam.brand == "Bushnell"
        assert cam.uuid is not None

    def test_create_requires_non_blank_name(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        for payload in ({}, {"name": None}, {"name": "   "}):
            r = client.post(BASE, headers=superuser_token_headers, json=payload)
            assert r.status_code == 422


# GET /cameras/{camera_id}  (admin)

class TestGetCamera:
    def test_get_requires_auth(self, client: TestClient, db: Session) -> None:
        camera = _make_camera(db, "PrivateCamera")
        r = client.get(f"{BASE}/{camera.camera_id}")
        assert r.status_code in (401, 403)

    def test_get_normal_user_forbidden(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "RestrictedCamera")
        r = client.get(f"{BASE}/{camera.camera_id}", headers=normal_user_token_headers)
        assert r.status_code == 403

    def test_get_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.get(f"{BASE}/999999", headers=superuser_token_headers)
        assert r.status_code == 404

    def test_get_with_lenses(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        camera = _make_camera(db, "GetCamera")
        lens = _make_lens(db, "GetLens")
        assoc = CameraLens(
            camera_id=camera.camera_id,
            lens_id=lens.lens_id,
            is_default=True,
            notes="Default lens",
        )
        db.add(assoc)
        db.commit()
        r = client.get(f"{BASE}/{camera.camera_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data["lenses"]) == 1
        assert data["lenses"][0]["lens_id"] == lens.lens_id
        assert data["lenses"][0]["name"] == lens.name
        assert data["lenses"][0]["is_default"] is True
        assert data["lenses"][0]["notes"] == "Default lens"

    def test_get_without_lenses_returns_empty_list(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "UnlinkedCamera")
        r = client.get(f"{BASE}/{camera.camera_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        assert r.json()["data"]["lenses"] == []


# PUT /cameras/{camera_id}  (admin)

class TestUpdateCamera:
    def test_update_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.put(f"{BASE}/999999", headers=superuser_token_headers, json={"name": "X"})
        assert r.status_code == 404

    def test_update_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        camera = _make_camera(db)
        r = client.put(
            f"{BASE}/{camera.camera_id}",
            headers=superuser_token_headers,
            json={"name": "Updated Camera", "brand": "NewBrand"},
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        db.refresh(camera)
        assert camera.name == "Updated Camera"
        assert camera.brand == "NewBrand"

    def test_update_rejects_cleared_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db)

        for value in (None, "   "):
            r = client.put(
                f"{BASE}/{camera.camera_id}",
                headers=superuser_token_headers,
                json={"name": value},
            )
            assert r.status_code == 422

    def test_update_null_clears_optional_field_and_omitted_name_is_preserved(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db)
        camera.name = "Old name"
        camera.version = "Old version"
        camera.brand = "Keep brand"
        db.add(camera)
        db.commit()

        r = client.put(
            f"{BASE}/{camera.camera_id}",
            headers=superuser_token_headers,
            json={"version": None},
        )

        assert r.status_code == 200
        db.refresh(camera)
        assert camera.name == "Old name"
        assert camera.version is None
        assert camera.brand == "Keep brand"


# DELETE /cameras/{camera_id}  (admin)

class TestDeleteCamera:
    def test_delete_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        camera = _make_camera(db, "DeleteCamera")
        r = client.delete(f"{BASE}/{camera.camera_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        r2 = client.get(f"{BASE}/{camera.camera_id}", headers=superuser_token_headers)
        assert r2.status_code == 404

    def test_delete_in_use_rejected(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "UsedCamera")
        lens = _make_lens(db, "LensForCamera")
        sensor = Sensor(name="PhotoSensor", sensor_type="photo",
                        camera_id=camera.camera_id, lens_id=lens.lens_id)
        db.add(sensor)
        db.commit()
        r = client.delete(f"{BASE}/{camera.camera_id}", headers=superuser_token_headers)
        assert r.status_code == 400


# POST /cameras/{camera_id}/lenses  (admin)

class TestAddCameraLens:
    def test_add_lens(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        camera = _make_camera(db, "AssocCamera")
        lens = _make_lens(db, "AssocLens")
        r = client.post(
            f"{BASE}/{camera.camera_id}/lenses",
            headers=superuser_token_headers,
            json={"lens_id": lens.lens_id, "is_default": True},
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        r2 = client.get(f"{BASE}/{camera.camera_id}", headers=superuser_token_headers)
        lenses = r2.json()["data"]["lenses"]
        assert any(l["lens_id"] == lens.lens_id for l in lenses)

    def test_add_default_lens_replaces_existing_default(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "ReplaceCameraDefault")
        old_lens = _make_lens(db, "ReplaceCameraOldLens")
        new_lens = _make_lens(db, "ReplaceCameraNewLens")
        old_association = CameraLens(
            camera_id=camera.camera_id,
            lens_id=old_lens.lens_id,
            is_default=True,
        )
        db.add(old_association)
        db.commit()

        response = client.post(
            f"{BASE}/{camera.camera_id}/lenses",
            headers=superuser_token_headers,
            json={"lens_id": new_lens.lens_id, "is_default": True},
        )

        assert response.status_code == 200
        db.refresh(old_association)
        assert old_association.is_default is False
        assert db.get(CameraLens, (camera.camera_id, new_lens.lens_id)).is_default is True

    def test_add_duplicate_rejected(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "DupCamera")
        lens = _make_lens(db, "DupLens")
        db.add(CameraLens(camera_id=camera.camera_id, lens_id=lens.lens_id))
        db.commit()
        r = client.post(
            f"{BASE}/{camera.camera_id}/lenses",
            headers=superuser_token_headers,
            json={"lens_id": lens.lens_id},
        )
        assert r.status_code == 400

    def test_add_lens_not_found(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        camera = _make_camera(db, "NoLensCamera")
        r = client.post(
            f"{BASE}/{camera.camera_id}/lenses",
            headers=superuser_token_headers,
            json={"lens_id": 999999},
        )
        assert r.status_code == 404


# DELETE /cameras/{camera_id}/lenses/{lens_id}  (admin)

class TestRemoveCameraLens:
    def test_remove_lens(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        camera = _make_camera(db, "RemoveCamera")
        lens = _make_lens(db, "RemoveLens")
        db.add(CameraLens(camera_id=camera.camera_id, lens_id=lens.lens_id))
        db.commit()
        r = client.delete(
            f"{BASE}/{camera.camera_id}/lenses/{lens.lens_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200

    def test_remove_not_found(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        camera = _make_camera(db, "RemoveNotFoundCamera")
        r = client.delete(
            f"{BASE}/{camera.camera_id}/lenses/999999",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404
