"""
Tests for Lens CRUD endpoints.

Covers: list, create, get, update, delete, permissions.
"""
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models.device import Camera, CameraLens, Lens, Sensor
from tests.utils.csv import read_csv_rows

BASE = f"{settings.API_V1_STR}/lenses"
OPTIONS = f"{settings.API_V1_STR}/lens-options"


# Helpers

def _make_lens(
    db: Session,
    name: str = "Wide Angle",
    focal_length: str = "3.1mm",
    max_aperture: str = "f/2.0",
    brand: str = "Reconyx",
) -> Lens:
    obj = Lens(name=name, focal_length=focal_length, max_aperture=max_aperture, brand=brand)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# GET /lens-options  (login required)

class TestGetLensOptions:
    def test_options_requires_auth(self, client: TestClient) -> None:
        r = client.get(OPTIONS)
        assert r.status_code in (401, 403)

    def test_options_returns_list(self, client: TestClient, normal_user_token_headers: dict, db: Session) -> None:
        _make_lens(db, name="OptionLensA")
        _make_lens(db, name="OptionLensB")
        r = client.get(OPTIONS, headers=normal_user_token_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert isinstance(data, list)
        names = [item["name"] for item in data]
        assert "OptionLensA" in names
        assert "OptionLensB" in names

    def test_options_item_structure(self, client: TestClient, normal_user_token_headers: dict, db: Session) -> None:
        lens = _make_lens(db, name="StructureLens")
        r = client.get(OPTIONS, headers=normal_user_token_headers)
        assert r.status_code == 200
        items = r.json()["data"]
        match = next((i for i in items if i["lens_id"] == lens.lens_id), None)
        assert match is not None
        assert match["name"] == "StructureLens"
        assert set(match.keys()) == {"lens_id", "name"}

    def test_options_sorted_by_name(self, client: TestClient, normal_user_token_headers: dict, db: Session) -> None:
        _make_lens(db, name="Zebra Lens")
        _make_lens(db, name="Alpha Lens")
        r = client.get(OPTIONS, headers=normal_user_token_headers)
        assert r.status_code == 200
        names = [item["name"] for item in r.json()["data"]]
        relevant = [n for n in names if n in ("Alpha Lens", "Zebra Lens")]
        assert relevant == sorted(relevant)


# GET /lenses  (admin)

class TestListLenses:
    def test_list_requires_auth(self, client: TestClient) -> None:
        r = client.get(BASE)
        assert r.status_code in (401, 403)

    def test_list_normal_user_forbidden(self, client: TestClient, normal_user_token_headers: dict) -> None:
        r = client.get(BASE, headers=normal_user_token_headers)
        assert r.status_code == 403

    def test_list_admin(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        _make_lens(db)
        r = client.get(BASE, headers=superuser_token_headers)
        assert r.status_code == 200
        assert r.json()["page_info"]["total"] >= 1

    def test_list_includes_camera_count_and_zero_default(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        unused = _make_lens(db, name="UnusedCountLens")
        linked = _make_lens(db, name="LinkedCountLens")
        first = Camera(name="CountCameraA")
        second = Camera(name="CountCameraB")
        db.add(first)
        db.add(second)
        db.commit()
        db.refresh(first)
        db.refresh(second)
        db.add(CameraLens(camera_id=first.camera_id, lens_id=linked.lens_id))
        db.add(CameraLens(camera_id=second.camera_id, lens_id=linked.lens_id))
        db.commit()

        r = client.get(f"{BASE}?page_size=100", headers=superuser_token_headers)

        assert r.status_code == 200
        items = {item["lens_id"]: item for item in r.json()["data"]}
        assert items[unused.lens_id]["camera_count"] == 0
        assert items[linked.lens_id]["camera_count"] == 2

    def test_list_filters_and_sorts_by_camera_count(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        low = _make_lens(db, name="CameraCountLow")
        high = _make_lens(db, name="CameraCountHigh")
        cameras = [Camera(name=f"LensCountCamera{i}") for i in range(3)]
        db.add_all(cameras)
        db.commit()
        for camera in cameras:
            db.refresh(camera)
        db.add(CameraLens(camera_id=cameras[0].camera_id, lens_id=low.lens_id))
        db.add(CameraLens(camera_id=cameras[1].camera_id, lens_id=high.lens_id))
        db.add(CameraLens(camera_id=cameras[2].camera_id, lens_id=high.lens_id))
        db.commit()

        filtered = client.get(
            f"{BASE}?lens_id={high.lens_id}&camera_count=2",
            headers=superuser_token_headers,
        )
        sorted_response = client.get(
            f"{BASE}?order_by=camera_count&order_dir=desc&page_size=100",
            headers=superuser_token_headers,
        )

        assert filtered.status_code == 200
        assert [item["lens_id"] for item in filtered.json()["data"]] == [high.lens_id]
        relevant = [
            item for item in sorted_response.json()["data"]
            if item["lens_id"] in {low.lens_id, high.lens_id}
        ]
        assert [item["lens_id"] for item in relevant] == [high.lens_id, low.lens_id]

    def test_list_rejects_negative_camera_count(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        r = client.get(f"{BASE}?camera_count=-1", headers=superuser_token_headers)

        assert r.status_code == 422

    def test_list_pagination(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        for i in range(3):
            _make_lens(db, name=f"Lens{i}")
        r = client.get(f"{BASE}?page=1&page_size=2", headers=superuser_token_headers)
        assert r.status_code == 200
        assert len(r.json()["data"]) <= 2

    def test_list_filter_by_lens_id_and_uuid(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        target = _make_lens(db, name="FilterTargetLens")
        _make_lens(db, name="OtherLens")
        r = client.get(
            f"{BASE}?lens_id={target.lens_id}&uuid={target.uuid}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        items = r.json()["data"]
        assert len(items) == 1
        assert items[0]["lens_id"] == target.lens_id

    def test_list_invalid_uuid_is_ignored(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        _make_lens(db, name="InvalidUuidLens")
        r = client.get(f"{BASE}?uuid=not-a-uuid", headers=superuser_token_headers)
        assert r.status_code == 200
        assert r.json()["page_info"]["total"] >= 1

    def test_list_sort_by_max_aperture(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        fast = _make_lens(db, name="FastLens", max_aperture="f/1.4")
        slow = _make_lens(db, name="SlowLens", max_aperture="f/4.0")

        r = client.get(
            f"{BASE}?order_by=max_aperture&order_dir=asc&page_size=100",
            headers=superuser_token_headers,
        )

        assert r.status_code == 200
        items = [item for item in r.json()["data"] if item["lens_id"] in {fast.lens_id, slow.lens_id}]
        assert items[0]["lens_id"] == fast.lens_id
        assert items[1]["lens_id"] == slow.lens_id


class TestExportLenses:
    def test_export_lenses_with_filters(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        lens = _make_lens(db, name="ExportLensTarget")
        camera = Camera(name="ExportLensCamera")
        db.add(camera)
        db.commit()
        db.refresh(camera)
        db.add(CameraLens(camera_id=camera.camera_id, lens_id=lens.lens_id))
        db.commit()
        _make_lens(db, name="OtherExportLens")
        r = client.get(
            f"{BASE}/exports?lens_id={lens.lens_id}&uuid={lens.uuid}&order_by=brand",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.headers.get("content-disposition") == (
            'attachment; filename="lenses.csv"; '
            "filename*=UTF-8''lenses.csv"
        )
        rows = read_csv_rows(r.text)
        assert rows[0] == ["lens_id", "uuid", "name", "focal_length", "max_aperture", "brand"]
        assert len(rows) == 2
        assert rows[1][0] == str(lens.lens_id)
        assert rows[1][-1] == lens.brand

    def test_export_sorts_by_camera_count(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        low = _make_lens(db, name="ExportCameraCountLow")
        high = _make_lens(db, name="ExportCameraCountHigh")
        cameras = [Camera(name=f"ExportCountCamera{i}") for i in range(3)]
        db.add_all(cameras)
        db.commit()
        for camera in cameras:
            db.refresh(camera)
        db.add(CameraLens(camera_id=cameras[0].camera_id, lens_id=low.lens_id))
        db.add(CameraLens(camera_id=cameras[1].camera_id, lens_id=high.lens_id))
        db.add(CameraLens(camera_id=cameras[2].camera_id, lens_id=high.lens_id))
        db.commit()

        r = client.get(
            f"{BASE}/exports?order_by=camera_count&order_dir=desc",
            headers=superuser_token_headers,
        )

        assert r.status_code == 200
        rows = read_csv_rows(r.text)
        relevant = [row for row in rows[1:] if int(row[0]) in {low.lens_id, high.lens_id}]
        assert [int(row[0]) for row in relevant] == [high.lens_id, low.lens_id]


# POST /lenses  (admin)

class TestCreateLens:
    def test_create_requires_auth(self, client: TestClient) -> None:
        r = client.post(BASE, json={"name": "X"})
        assert r.status_code in (401, 403)

    def test_create_normal_user_forbidden(self, client: TestClient, normal_user_token_headers: dict) -> None:
        r = client.post(BASE, headers=normal_user_token_headers, json={"name": "X"})
        assert r.status_code == 403

    def test_create_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        payload = {"name": "Telephoto", "focal_length": "50mm", "max_aperture": "f/1.8", "brand": "Canon"}
        r = client.post(BASE, headers=superuser_token_headers, json=payload)
        assert r.status_code == 200
        assert r.json()["data"] is None
        lens = db.exec(select(Lens).where(Lens.name == "Telephoto").order_by(Lens.lens_id.desc())).first()
        assert lens is not None
        assert lens.focal_length == "50mm"
        assert lens.uuid is not None

    def test_create_requires_non_blank_name(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        for payload in ({}, {"name": None}, {"name": "   "}):
            r = client.post(BASE, headers=superuser_token_headers, json=payload)
            assert r.status_code == 422


# GET /lenses/{lens_id}  (admin)

class TestGetLens:
    def test_get_requires_auth(self, client: TestClient, db: Session) -> None:
        lens = _make_lens(db, name="PrivateLens")
        r = client.get(f"{BASE}/{lens.lens_id}")
        assert r.status_code in (401, 403)

    def test_get_normal_user_forbidden(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        lens = _make_lens(db, name="RestrictedLens")
        r = client.get(f"{BASE}/{lens.lens_id}", headers=normal_user_token_headers)
        assert r.status_code == 403

    def test_get_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.get(f"{BASE}/999999", headers=superuser_token_headers)
        assert r.status_code == 404

    def test_get_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        obj = _make_lens(db)
        r = client.get(f"{BASE}/{obj.lens_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["lens_id"] == obj.lens_id
        assert data["name"] == obj.name
        assert data["focal_length"] == obj.focal_length
        assert data["max_aperture"] == obj.max_aperture
        assert data["cameras"] == []

    def test_get_returns_linked_cameras_in_id_order(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        lens = _make_lens(db, name="LinkedLens")
        camera_a = Camera(name="Camera A")
        camera_b = Camera(name="Camera B")
        db.add_all([camera_a, camera_b])
        db.commit()
        db.refresh(camera_a)
        db.refresh(camera_b)
        db.add_all([
            CameraLens(
                camera_id=camera_b.camera_id,
                lens_id=lens.lens_id,
                notes="Secondary camera",
            ),
            CameraLens(
                camera_id=camera_a.camera_id,
                lens_id=lens.lens_id,
                notes="Primary camera",
            ),
        ])
        db.commit()

        r = client.get(f"{BASE}/{lens.lens_id}", headers=superuser_token_headers)

        assert r.status_code == 200
        cameras = r.json()["data"]["cameras"]
        assert [item["camera_id"] for item in cameras] == [camera_a.camera_id, camera_b.camera_id]
        assert cameras[0] == {
            "camera_id": camera_a.camera_id,
            "name": "Camera A",
            "notes": "Primary camera",
        }


# PUT /lenses/{lens_id}  (admin)

class TestUpdateLens:
    def test_update_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.put(f"{BASE}/999999", headers=superuser_token_headers, json={"name": "X"})
        assert r.status_code == 404

    def test_update_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        obj = _make_lens(db)
        r = client.put(
            f"{BASE}/{obj.lens_id}",
            headers=superuser_token_headers,
            json={"name": "Updated Lens", "max_aperture": "f/1.4"},
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        db.refresh(obj)
        assert obj.name == "Updated Lens"
        assert obj.max_aperture == "f/1.4"

    def test_update_rejects_cleared_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        obj = _make_lens(db)

        for value in (None, "   "):
            r = client.put(
                f"{BASE}/{obj.lens_id}",
                headers=superuser_token_headers,
                json={"name": value},
            )
            assert r.status_code == 422

    def test_update_null_clears_fields_and_omitted_field_is_preserved(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        obj = _make_lens(db)
        obj.focal_length = "50mm"
        obj.max_aperture = "f/1.8"
        obj.brand = "Keep brand"
        db.add(obj)
        db.commit()

        r = client.put(
            f"{BASE}/{obj.lens_id}",
            headers=superuser_token_headers,
            json={"focal_length": None, "max_aperture": None},
        )

        assert r.status_code == 200
        db.refresh(obj)
        assert obj.focal_length is None
        assert obj.max_aperture is None
        assert obj.brand == "Keep brand"


# DELETE /lenses/{lens_id}  (admin)

class TestDeleteLens:
    def test_delete_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.delete(f"{BASE}/999999", headers=superuser_token_headers)
        assert r.status_code == 404

    def test_delete_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        obj = _make_lens(db, name="DeleteLens")
        r = client.delete(f"{BASE}/{obj.lens_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        r2 = client.get(f"{BASE}/{obj.lens_id}", headers=superuser_token_headers)
        assert r2.status_code == 404

    def test_delete_in_use_rejected(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        from app.models.device import Camera
        lens = _make_lens(db, name="UsedLens")
        camera = Camera(name="CamForLens")
        db.add(camera)
        db.commit()
        db.refresh(camera)
        sensor = Sensor(name="LensSensor", sensor_type="photo",
                        lens_id=lens.lens_id, camera_id=camera.camera_id)
        db.add(sensor)
        db.commit()
        r = client.delete(f"{BASE}/{lens.lens_id}", headers=superuser_token_headers)
        assert r.status_code == 400
