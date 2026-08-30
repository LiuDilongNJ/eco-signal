"""
Tests for Sensor CRUD endpoints.

Covers: list, create, get, update, delete, options, permissions.
"""
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models.device import Camera, CameraLens, Lens, Microphone, Recorder, RecorderMicrophone, Sensor
from tests.utils.csv import read_csv_rows

BASE = f"{settings.API_V1_STR}/sensors"
OPTIONS = f"{settings.API_V1_STR}/sensor-options"
LENSES = f"{settings.API_V1_STR}/lenses"


# Helpers

def _make_recorder(db: Session, name: str = "SM4") -> Recorder:
    obj = Recorder(name=name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _make_microphone(db: Session, name: str = "SMM-A2") -> Microphone:
    obj = Microphone(name=name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _make_sensor_audio(db: Session, name: str = "Test Sensor") -> Sensor:
    """Create a valid audio sensor (requires recorder + microphone)."""
    recorder = _make_recorder(db, f"Rec-{name}")
    mic = _make_microphone(db, f"Mic-{name}")
    obj = Sensor(name=name, sensor_type="audio",
                 recorder_id=recorder.recorder_id, microphone_id=mic.microphone_id)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _make_camera(db: Session, name: str = "Test Camera") -> Camera:
    obj = Camera(name=name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _make_lens(db: Session, name: str = "Test Lens") -> Lens:
    obj = Lens(name=name, focal_length="35mm", max_aperture="f/2.0", brand="SeedBrand")
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# GET /sensor-options  (public)

class TestSensorOptions:
    def test_options_public(self, client: TestClient, db: Session) -> None:
        _make_sensor_audio(db, "OptionSensor")
        r = client.get(OPTIONS)
        assert r.status_code == 200
        data = r.json()["data"]
        assert any(item["name"] == "OptionSensor" for item in data)
        option = next(item for item in data if item["name"] == "OptionSensor")
        assert "serial_number" in option
        assert option["serial_number"] is None


# GET /sensors  (admin)

class TestListSensors:
    def test_list_requires_auth(self, client: TestClient) -> None:
        r = client.get(BASE)
        assert r.status_code in (401, 403)

    def test_list_normal_user_forbidden(self, client: TestClient, normal_user_token_headers: dict) -> None:
        r = client.get(BASE, headers=normal_user_token_headers)
        assert r.status_code == 403

    def test_list_admin(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        _make_sensor_audio(db)
        r = client.get(BASE, headers=superuser_token_headers)
        assert r.status_code == 200
        assert r.json()["page_info"]["total"] >= 1

    def test_list_includes_device_names(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "SensorRecorder")
        mic = _make_microphone(db, "SensorMic")
        sensor = Sensor(name="LinkedSensor", sensor_type="audio",
                        recorder_id=recorder.recorder_id, microphone_id=mic.microphone_id)
        db.add(sensor)
        db.commit()
        r = client.get(BASE, headers=superuser_token_headers)
        items = r.json()["data"]
        found = next((i for i in items if i["name"] == "LinkedSensor"), None)
        assert found is not None
        assert found["recorder_name"] == "SensorRecorder"
        assert found["microphone_name"] == "SensorMic"

    def test_list_omits_camera_lens_default(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "ListDefaultCamera")
        lens = _make_lens(db, "ListDefaultLens")
        sensor = Sensor(
            name="ListDefaultSensor",
            sensor_type="photo",
            camera_id=camera.camera_id,
            lens_id=lens.lens_id,
        )
        db.add_all([
            sensor,
            CameraLens(camera_id=camera.camera_id, lens_id=lens.lens_id),
        ])
        db.commit()

        response = client.get(BASE, headers=superuser_token_headers)

        assert response.status_code == 200
        item = next(item for item in response.json()["data"] if item["name"] == "ListDefaultSensor")
        assert "is_default" not in item

    def test_list_omits_recorder_microphone_default(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "ListDefaultRecorder")
        mic = _make_microphone(db, "ListDefaultMic")
        sensor = Sensor(
            name="ListDefaultAudioSensor",
            sensor_type="audio",
            recorder_id=recorder.recorder_id,
            microphone_id=mic.microphone_id,
        )
        db.add_all([
            sensor,
            RecorderMicrophone(
                recorder_id=recorder.recorder_id,
                microphone_id=mic.microphone_id,
            ),
        ])
        db.commit()

        response = client.get(BASE, headers=superuser_token_headers)

        assert response.status_code == 200
        item = next(
            item for item in response.json()["data"] if item["name"] == "ListDefaultAudioSensor"
        )
        assert "is_default" not in item

    def test_list_filter_by_sensor_id_and_uuid(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        target = _make_sensor_audio(db, "SensorByIdUuid")
        _make_sensor_audio(db, "OtherSensorByIdUuid")
        r = client.get(
            f"{BASE}?sensor_id={target.sensor_id}&uuid={target.uuid}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        items = r.json()["data"]
        assert len(items) == 1
        assert items[0]["sensor_id"] == target.sensor_id

    def test_list_filter_by_description_uses_fuzzy_match(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        matching = _make_sensor_audio(db, "DescriptionMatch")
        matching.description = "Rainforest canopy recorder"
        non_matching = _make_sensor_audio(db, "DescriptionMiss")
        non_matching.description = "Coastal monitoring device"
        db.add(matching)
        db.add(non_matching)
        db.commit()

        response = client.get(
            f"{BASE}?description=canopy&page_size=100",
            headers=superuser_token_headers,
        )

        assert response.status_code == 200, response.json()
        sensor_ids = {item["sensor_id"] for item in response.json()["data"]}
        assert matching.sensor_id in sensor_ids
        assert non_matching.sensor_id not in sensor_ids

    def test_list_filter_by_serial_number_uses_fuzzy_match(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        matching = _make_sensor_audio(db, "SerialMatch")
        matching.serial_number = "AM-2048"
        non_matching = _make_sensor_audio(db, "SerialMiss")
        non_matching.serial_number = "SM4-001"
        db.add(matching)
        db.add(non_matching)
        db.commit()

        response = client.get(
            f"{BASE}?serial_number=2048&page_size=100",
            headers=superuser_token_headers,
        )

        assert response.status_code == 200, response.json()
        sensor_ids = {item["sensor_id"] for item in response.json()["data"]}
        assert matching.sensor_id in sensor_ids
        assert non_matching.sensor_id not in sensor_ids

    def test_list_filter_by_recorder_name_and_camera_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        rec = _make_recorder(db, "FilterRecorderName")
        mic = _make_microphone(db, "FilterRecorderMic")
        cam = _make_camera(db, "FilterCameraName")
        lens = _make_lens(db, "FilterCameraLens")
        audio_sensor = Sensor(
            name="SensorWithRecorderName",
            sensor_type="audio",
            recorder_id=rec.recorder_id,
            microphone_id=mic.microphone_id,
        )
        photo_sensor = Sensor(
            name="SensorWithCameraName",
            sensor_type="photo",
            camera_id=cam.camera_id,
            lens_id=lens.lens_id,
        )
        db.add(audio_sensor)
        db.add(photo_sensor)
        db.commit()

        r1 = client.get(f"{BASE}?recorder_name=FilterRecorderName", headers=superuser_token_headers)
        assert r1.status_code == 200
        data1 = r1.json()
        assert data1["page_info"]["total"] == len(data1["data"])
        assert any(i["name"] == "SensorWithRecorderName" for i in data1["data"])

        r2 = client.get(f"{BASE}?camera_name=FilterCameraName", headers=superuser_token_headers)
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["page_info"]["total"] == len(data2["data"])
        assert any(i["name"] == "SensorWithCameraName" for i in data2["data"])

    def test_list_filter_by_sensor_type_uses_fuzzy_match(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        audio_sensor = _make_sensor_audio(db, "FuzzyAudioSensor")
        photo_camera = _make_camera(db, "FuzzyTypeCamera")
        photo_lens = _make_lens(db, "FuzzyTypeLens")
        photo_sensor = Sensor(
            name="FuzzyPhotoSensor",
            sensor_type="photo",
            camera_id=photo_camera.camera_id,
            lens_id=photo_lens.lens_id,
        )
        db.add(photo_sensor)
        db.commit()
        db.refresh(photo_sensor)

        r = client.get(f"{BASE}?sensor_type=aud&page_size=100", headers=superuser_token_headers)
        assert r.status_code == 200, r.json()
        ids = {item["sensor_id"] for item in r.json()["data"]}
        assert audio_sensor.sensor_id in ids
        assert photo_sensor.sensor_id not in ids

    def test_list_invalid_uuid_is_ignored(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        _make_sensor_audio(db, "InvalidUuidSensor")
        r = client.get(f"{BASE}?uuid=not-a-uuid", headers=superuser_token_headers)
        assert r.status_code == 200
        assert r.json()["page_info"]["total"] >= 1

    def test_list_sort_by_recorder_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        rec_b = _make_recorder(db, "ZuluRecorder")
        mic_b = _make_microphone(db, "ZuluMic")
        rec_a = _make_recorder(db, "AlphaRecorder")
        mic_a = _make_microphone(db, "AlphaMic")
        sensor_b = Sensor(name="ZuluSensor", sensor_type="audio", recorder_id=rec_b.recorder_id, microphone_id=mic_b.microphone_id)
        sensor_a = Sensor(name="AlphaSensor", sensor_type="audio", recorder_id=rec_a.recorder_id, microphone_id=mic_a.microphone_id)
        db.add(sensor_b)
        db.add(sensor_a)
        db.commit()

        r = client.get(
            f"{BASE}?order_by=recorder_name&order_dir=asc&page_size=100",
            headers=superuser_token_headers,
        )

        assert r.status_code == 200
        items = [item for item in r.json()["data"] if item["sensor_id"] in {sensor_a.sensor_id, sensor_b.sensor_id}]
        assert items[0]["sensor_id"] == sensor_a.sensor_id
        assert items[1]["sensor_id"] == sensor_b.sensor_id

    def test_list_filter_by_creation_date_range(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        inside = _make_sensor_audio(db, "SensorDateInside")
        outside = _make_sensor_audio(db, "SensorDateOutside")
        inside.creation_date = datetime(2026, 6, 27, 9, 30, tzinfo=UTC)
        outside.creation_date = datetime(2026, 6, 30, 9, 30, tzinfo=UTC)
        db.add(inside)
        db.add(outside)
        db.commit()

        r = client.get(
            f"{BASE}?creation_date_from=2026-06-26&creation_date_to=2026-06-29&page_size=100",
            headers=superuser_token_headers,
        )

        assert r.status_code == 200, r.json()
        items = r.json()["data"]
        ids = {item["sensor_id"] for item in items}
        assert inside.sensor_id in ids
        assert outside.sensor_id not in ids
        inside_item = next(item for item in items if item["sensor_id"] == inside.sensor_id)
        assert inside_item["creation_date"] == "2026-06-27 09:30:00"


class TestExportSensors:
    def test_export_sensors_with_filters(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "ExportSensorRecorder")
        mic = _make_microphone(db, "ExportSensorMic")
        sensor = Sensor(
            name="ExportSensor",
            sensor_type="audio",
            recorder_id=recorder.recorder_id,
            microphone_id=mic.microphone_id,
        )
        db.add(sensor)
        db.add(
            RecorderMicrophone(
                recorder_id=recorder.recorder_id,
                microphone_id=mic.microphone_id,
            )
        )
        db.commit()
        db.refresh(sensor)

        r = client.get(
            f"{BASE}/exports?sensor_id={sensor.sensor_id}&uuid={sensor.uuid}&recorder_name=ExportSensorRecorder&microphone_name=ExportSensorMic&order_by=creation_date",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.headers.get("content-disposition") == (
            'attachment; filename="sensors.csv"; '
            "filename*=UTF-8''sensors.csv"
        )
        rows = read_csv_rows(r.text)
        assert rows[0] == [
            "sensor_id", "uuid", "name", "serial_number", "sensor_type", "recorder_id", "recorder_name",
            "microphone_id", "microphone_name", "camera_id", "camera_name", "lens_id",
            "lens_name", "description", "creation_date",
        ]
        assert len(rows) == 2
        assert rows[1][0] == str(sensor.sensor_id)


# POST /sensors  (admin)

class TestCreateSensor:
    def test_create_requires_auth(self, client: TestClient) -> None:
        r = client.post(BASE, json={"name": "X", "sensor_type": "audio"})
        assert r.status_code in (401, 403)

    def test_create_normal_user_forbidden(self, client: TestClient, normal_user_token_headers: dict) -> None:
        r = client.post(BASE, headers=normal_user_token_headers, json={"name": "X", "sensor_type": "audio"})
        assert r.status_code == 403

    def test_create_success_minimal(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        recorder = _make_recorder(db, "MinRecorder")
        mic = _make_microphone(db, "MinMic")
        r = client.post(BASE, headers=superuser_token_headers, json={
            "name": "MinimalSensor",
            "sensor_type": "audio",
            "recorder_id": recorder.recorder_id,
            "microphone_id": mic.microphone_id,
        })
        assert r.status_code == 200
        assert r.json()["data"] is None
        row = db.exec(select(Sensor).where(Sensor.name == "MinimalSensor").order_by(Sensor.sensor_id.desc())).first()
        assert row is not None
        assert row.sensor_type == "audio"
        assert row.uuid is not None
        assert row.serial_number is None

    def test_create_with_serial_number(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "SerialRecorder")
        mic = _make_microphone(db, "SerialMic")
        r = client.post(BASE, headers=superuser_token_headers, json={
            "name": "SerialSensor",
            "sensor_type": "audio",
            "recorder_id": recorder.recorder_id,
            "microphone_id": mic.microphone_id,
            "serial_number": "  AM-1001  ",
        })
        assert r.status_code == 200
        row = db.exec(select(Sensor).where(Sensor.name == "SerialSensor").order_by(Sensor.sensor_id.desc())).first()
        assert row is not None
        assert row.serial_number == "AM-1001"

    def test_create_blank_serial_number_stores_null(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "BlankSerialRecorder")
        mic = _make_microphone(db, "BlankSerialMic")
        r = client.post(BASE, headers=superuser_token_headers, json={
            "name": "BlankSerialSensor",
            "sensor_type": "audio",
            "recorder_id": recorder.recorder_id,
            "microphone_id": mic.microphone_id,
            "serial_number": "   ",
        })
        assert r.status_code == 200
        row = db.exec(
            select(Sensor).where(Sensor.name == "BlankSerialSensor").order_by(Sensor.sensor_id.desc())
        ).first()
        assert row is not None
        assert row.serial_number is None

    def test_create_rejects_normalized_duplicate_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        _make_sensor_audio(db, "Forest Sensor")
        recorder = _make_recorder(db, "DuplicateSensorRecorder")
        microphone = _make_microphone(db, "DuplicateSensorMicrophone")

        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={
                "name": " forest sensor ",
                "sensor_type": "audio",
                "recorder_id": recorder.recorder_id,
                "microphone_id": microphone.microphone_id,
            },
        )

        assert response.status_code == 409
        assert response.json()["message"] == "Sensor name already exists"

    def test_create_with_devices(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        recorder = _make_recorder(db, "CreateRecorder")
        mic = _make_microphone(db, "CreateMic")
        payload = {
            "name": "FullSensor",
            "sensor_type": "audio",
            "recorder_id": recorder.recorder_id,
            "microphone_id": mic.microphone_id,
            "description": "Full config sensor",
        }
        r = client.post(BASE, headers=superuser_token_headers, json=payload)
        assert r.status_code == 200
        assert r.json()["data"] is None
        row = db.exec(select(Sensor).where(Sensor.name == "FullSensor").order_by(Sensor.sensor_id.desc())).first()
        assert row is not None
        assert row.recorder_id == recorder.recorder_id
        assert row.microphone_id == mic.microphone_id
        db.refresh(recorder)
        db.refresh(mic)
        assert recorder.name == "CreateRecorder"
        assert mic.name == "CreateMic"

    def test_create_photo_sensor_adds_camera_lens_and_updates_count(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "CreatePhotoCamera")
        lens = _make_lens(db, "CreatePhotoLens")

        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={
                "name": "CreatePhotoSensor",
                "sensor_type": "photo",
                "camera_id": camera.camera_id,
                "lens_id": lens.lens_id,
            },
        )

        assert response.status_code == 200
        association = db.get(CameraLens, (camera.camera_id, lens.lens_id))
        assert association is not None
        assert association.notes is None

        list_response = client.get(
            f"{LENSES}?lens_id={lens.lens_id}",
            headers=superuser_token_headers,
        )
        assert list_response.status_code == 200
        assert list_response.json()["data"][0]["camera_count"] == 1

    def test_create_rejects_retired_camera_lens_default_field(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "DefaultPhotoCamera")
        lens = _make_lens(db, "DefaultPhotoLens")

        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={
                "name": "DefaultPhotoSensor",
                "sensor_type": "photo",
                "camera_id": camera.camera_id,
                "lens_id": lens.lens_id,
                "camera_lens_is_default": True,
            },
        )

        assert response.status_code == 422

    def test_create_rejects_retired_camera_lens_default_with_existing_link(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "ReplaceDefaultCamera")
        old_lens = _make_lens(db, "ReplaceDefaultOldLens")
        new_lens = _make_lens(db, "ReplaceDefaultNewLens")
        old_association = CameraLens(
            camera_id=camera.camera_id,
            lens_id=old_lens.lens_id,
        )
        db.add(old_association)
        db.commit()

        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={
                "name": "ReplaceDefaultSensor",
                "sensor_type": "photo",
                "camera_id": camera.camera_id,
                "lens_id": new_lens.lens_id,
                "camera_lens_is_default": True,
            },
        )

        assert response.status_code == 422

    def test_create_photo_sensor_preserves_existing_camera_lens(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "ExistingLinkCamera")
        lens = _make_lens(db, "ExistingLinkLens")
        association = CameraLens(
            camera_id=camera.camera_id,
            lens_id=lens.lens_id,
            notes="Keep this metadata",
        )
        db.add(association)
        db.commit()

        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={
                "name": "ExistingLinkPhotoSensor",
                "sensor_type": "photo",
                "camera_id": camera.camera_id,
                "lens_id": lens.lens_id,
            },
        )

        assert response.status_code == 200
        db.refresh(association)
        assert association.notes == "Keep this metadata"
        links = db.exec(
            select(CameraLens).where(
                CameraLens.camera_id == camera.camera_id,
                CameraLens.lens_id == lens.lens_id,
            )
        ).all()
        assert len(links) == 1

    def test_create_invalid_photo_sensor_does_not_add_camera_lens(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "InvalidPhotoCamera")

        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={
                "name": "InvalidPhotoSensor",
                "sensor_type": "photo",
                "camera_id": camera.camera_id,
                "lens_id": 999999,
            },
        )

        assert response.status_code == 404
        assert db.get(CameraLens, (camera.camera_id, 999999)) is None

    def test_create_invalid_recorder_ref(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        mic = _make_microphone(db, "ValidMic")
        r = client.post(BASE, headers=superuser_token_headers, json={
            "name": "Bad", "sensor_type": "audio",
            "recorder_id": 999999,
            "microphone_id": mic.microphone_id,
        })
        assert r.status_code == 404

    def test_create_audio_sensor_adds_recorder_microphone(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "CreateAudioRecorder")
        mic = _make_microphone(db, "CreateAudioMic")

        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={
                "name": "CreateAudioSensorLink",
                "sensor_type": "audio",
                "recorder_id": recorder.recorder_id,
                "microphone_id": mic.microphone_id,
            },
        )

        assert response.status_code == 200
        association = db.get(RecorderMicrophone, (recorder.recorder_id, mic.microphone_id))
        assert association is not None
        assert association.notes is None

    def test_create_rejects_retired_recorder_microphone_default_field(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "DefaultAudioRecorder")
        mic = _make_microphone(db, "DefaultAudioMic")

        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={
                "name": "DefaultAudioSensor",
                "sensor_type": "audio",
                "recorder_id": recorder.recorder_id,
                "microphone_id": mic.microphone_id,
                "recorder_microphone_is_default": True,
            },
        )

        assert response.status_code == 422

    def test_create_rejects_retired_recorder_microphone_default_with_existing_link(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "ReplaceDefaultRecorder")
        old_mic = _make_microphone(db, "ReplaceDefaultOldMic")
        new_mic = _make_microphone(db, "ReplaceDefaultNewMic")
        old_association = RecorderMicrophone(
            recorder_id=recorder.recorder_id,
            microphone_id=old_mic.microphone_id,
        )
        db.add(old_association)
        db.commit()

        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={
                "name": "ReplaceDefaultAudioSensor",
                "sensor_type": "audio",
                "recorder_id": recorder.recorder_id,
                "microphone_id": new_mic.microphone_id,
                "recorder_microphone_is_default": True,
            },
        )

        assert response.status_code == 422

    def test_create_audio_sensor_preserves_existing_recorder_microphone(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "ExistingLinkRecorder")
        mic = _make_microphone(db, "ExistingLinkMic")
        association = RecorderMicrophone(
            recorder_id=recorder.recorder_id,
            microphone_id=mic.microphone_id,
            notes="Keep this metadata",
        )
        db.add(association)
        db.commit()

        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={
                "name": "ExistingLinkAudioSensor",
                "sensor_type": "audio",
                "recorder_id": recorder.recorder_id,
                "microphone_id": mic.microphone_id,
            },
        )

        assert response.status_code == 200
        db.refresh(association)
        assert association.notes == "Keep this metadata"
        links = db.exec(
            select(RecorderMicrophone).where(
                RecorderMicrophone.recorder_id == recorder.recorder_id,
                RecorderMicrophone.microphone_id == mic.microphone_id,
            )
        ).all()
        assert len(links) == 1

    def test_create_photo_sensor_rejects_recorder_microphone_default(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "PhotoRejectMicDefaultCamera")
        lens = _make_lens(db, "PhotoRejectMicDefaultLens")

        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={
                "name": "PhotoRejectMicDefaultSensor",
                "sensor_type": "photo",
                "camera_id": camera.camera_id,
                "lens_id": lens.lens_id,
                "recorder_microphone_is_default": True,
            },
        )

        assert response.status_code == 422

    def test_create_audio_sensor_rejects_camera_lens_default(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "AudioDefaultRecorder")
        microphone = _make_microphone(db, "AudioDefaultMicrophone")

        response = client.post(
            BASE,
            headers=superuser_token_headers,
            json={
                "name": "AudioDefaultSensor",
                "sensor_type": "audio",
                "recorder_id": recorder.recorder_id,
                "microphone_id": microphone.microphone_id,
                "camera_lens_is_default": True,
            },
        )

        assert response.status_code == 422

    def test_create_missing_name(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.post(BASE, headers=superuser_token_headers, json={"sensor_type": "audio"})
        assert r.status_code == 422


# GET /sensors/{sensor_id}  (admin)

class TestGetSensor:
    def test_get_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.get(f"{BASE}/999999", headers=superuser_token_headers)
        assert r.status_code == 404

    def test_get_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        obj = _make_sensor_audio(db, "GetSensor")
        r = client.get(f"{BASE}/{obj.sensor_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["sensor_id"] == obj.sensor_id
        assert data["name"] == "GetSensor"
        assert datetime.strptime(data["creation_date"], "%Y-%m-%d %H:%M:%S")

    def test_get_omits_camera_lens_default(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "GetDefaultCamera")
        lens = _make_lens(db, "GetDefaultLens")
        sensor = Sensor(
            name="GetDefaultSensor",
            sensor_type="photo",
            camera_id=camera.camera_id,
            lens_id=lens.lens_id,
        )
        db.add_all([
            sensor,
            CameraLens(camera_id=camera.camera_id, lens_id=lens.lens_id),
        ])
        db.commit()
        db.refresh(sensor)

        response = client.get(f"{BASE}/{sensor.sensor_id}", headers=superuser_token_headers)

        assert response.status_code == 200
        assert "is_default" not in response.json()["data"]

    def test_get_omits_recorder_microphone_default(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "GetDefaultRecorder")
        mic = _make_microphone(db, "GetDefaultMic")
        sensor = Sensor(
            name="GetDefaultAudioSensor",
            sensor_type="audio",
            recorder_id=recorder.recorder_id,
            microphone_id=mic.microphone_id,
        )
        db.add_all([
            sensor,
            RecorderMicrophone(
                recorder_id=recorder.recorder_id,
                microphone_id=mic.microphone_id,
            ),
        ])
        db.commit()
        db.refresh(sensor)

        response = client.get(f"{BASE}/{sensor.sensor_id}", headers=superuser_token_headers)

        assert response.status_code == 200
        assert "is_default" not in response.json()["data"]


# PUT /sensors/{sensor_id}  (admin)

class TestUpdateSensor:
    def test_update_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.put(f"{BASE}/999999", headers=superuser_token_headers,
                       json={"name": "X", "sensor_type": "audio"})
        assert r.status_code == 404

    def test_update_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        obj = _make_sensor_audio(db)
        r = client.put(
            f"{BASE}/{obj.sensor_id}",
            headers=superuser_token_headers,
            json={"name": "Updated Sensor", "description": "New desc"},
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        db.refresh(obj)
        assert obj.name == "Updated Sensor"
        assert obj.description == "New desc"

    def test_update_serial_number(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        obj = _make_sensor_audio(db)
        r = client.put(
            f"{BASE}/{obj.sensor_id}",
            headers=superuser_token_headers,
            json={"serial_number": " SM4-77 "},
        )
        assert r.status_code == 200
        db.refresh(obj)
        assert obj.serial_number == "SM4-77"

        r = client.put(
            f"{BASE}/{obj.sensor_id}",
            headers=superuser_token_headers,
            json={"serial_number": "  "},
        )
        assert r.status_code == 200
        db.refresh(obj)
        assert obj.serial_number is None

    def test_update_rejects_normalized_duplicate_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        _make_sensor_audio(db, "Forest Sensor")
        target = _make_sensor_audio(db, "River Sensor")

        response = client.put(
            f"{BASE}/{target.sensor_id}",
            headers=superuser_token_headers,
            json={"name": " forest sensor "},
        )

        assert response.status_code == 409
        db.refresh(target)
        assert target.name == "River Sensor"

    def test_update_own_name_normalizes_and_succeeds(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        target = _make_sensor_audio(db, "Forest Sensor")

        response = client.put(
            f"{BASE}/{target.sensor_id}",
            headers=superuser_token_headers,
            json={"name": " forest sensor "},
        )

        assert response.status_code == 200
        db.refresh(target)
        assert target.name == "forest sensor"

    def test_update_null_clears_description(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        obj = _make_sensor_audio(db)
        obj.description = "Old description"
        db.add(obj)
        db.commit()

        r = client.put(
            f"{BASE}/{obj.sensor_id}",
            headers=superuser_token_headers,
            json={"description": None},
        )

        assert r.status_code == 200
        db.refresh(obj)
        assert obj.description is None

    def test_update_invalid_device_ref(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Updating with non-existent recorder should return 404."""
        obj = _make_sensor_audio(db)
        # We need to also pass a valid microphone to satisfy type constraint
        mic = _make_microphone(db, "ValidMic2")
        r = client.put(
            f"{BASE}/{obj.sensor_id}",
            headers=superuser_token_headers,
            json={"recorder_id": 999999, "microphone_id": mic.microphone_id},
        )
        assert r.status_code == 404

    def test_update_photo_sensor_adds_new_link_and_keeps_old_link(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        old_camera = _make_camera(db, "OldPhotoCamera")
        old_lens = _make_lens(db, "OldPhotoLens")
        new_camera = _make_camera(db, "NewPhotoCamera")
        new_lens = _make_lens(db, "NewPhotoLens")
        sensor = Sensor(
            name="ChangePhotoSensor",
            sensor_type="photo",
            camera_id=old_camera.camera_id,
            lens_id=old_lens.lens_id,
        )
        old_link = CameraLens(camera_id=old_camera.camera_id, lens_id=old_lens.lens_id)
        db.add_all([sensor, old_link])
        db.commit()
        db.refresh(sensor)

        response = client.put(
            f"{BASE}/{sensor.sensor_id}",
            headers=superuser_token_headers,
            json={"camera_id": new_camera.camera_id, "lens_id": new_lens.lens_id},
        )

        assert response.status_code == 200
        assert db.get(CameraLens, (old_camera.camera_id, old_lens.lens_id)) is not None
        new_link = db.get(CameraLens, (new_camera.camera_id, new_lens.lens_id))
        assert new_link is not None
        assert new_link.notes is None

    def test_update_rejects_retired_camera_lens_default_field(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "UpdateDefaultCamera")
        lens = _make_lens(db, "UpdateDefaultLens")
        sensor = Sensor(
            name="UpdateDefaultSensor",
            sensor_type="photo",
            camera_id=camera.camera_id,
            lens_id=lens.lens_id,
        )
        association = CameraLens(
            camera_id=camera.camera_id,
            lens_id=lens.lens_id,
        )
        db.add_all([sensor, association])
        db.commit()
        db.refresh(sensor)

        response = client.put(
            f"{BASE}/{sensor.sensor_id}",
            headers=superuser_token_headers,
            json={"camera_lens_is_default": False},
        )

        assert response.status_code == 422

    def test_update_photo_sensor_preserves_camera_lens_notes_when_default_is_omitted(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "PreserveDefaultCamera")
        lens = _make_lens(db, "PreserveDefaultLens")
        sensor = Sensor(
            name="PreserveDefaultSensor",
            sensor_type="photo",
            camera_id=camera.camera_id,
            lens_id=lens.lens_id,
        )
        association = CameraLens(
            camera_id=camera.camera_id,
            lens_id=lens.lens_id,
            notes="Keep this metadata",
        )
        db.add_all([sensor, association])
        db.commit()
        db.refresh(sensor)

        response = client.put(
            f"{BASE}/{sensor.sensor_id}",
            headers=superuser_token_headers,
            json={"name": "PreserveDefaultSensorUpdated"},
        )

        assert response.status_code == 200
        db.refresh(association)
        assert association.notes == "Keep this metadata"

    def test_update_audio_sensor_rejects_camera_lens_default(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        sensor = _make_sensor_audio(db, "UpdateAudioDefault")

        response = client.put(
            f"{BASE}/{sensor.sensor_id}",
            headers=superuser_token_headers,
            json={"camera_lens_is_default": True},
        )

        assert response.status_code == 422

    def test_update_rejects_retired_recorder_microphone_default_field(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "UpdateDefaultRecorder")
        mic = _make_microphone(db, "UpdateDefaultMic")
        sensor = Sensor(
            name="UpdateDefaultAudioSensor",
            sensor_type="audio",
            recorder_id=recorder.recorder_id,
            microphone_id=mic.microphone_id,
        )
        association = RecorderMicrophone(
            recorder_id=recorder.recorder_id,
            microphone_id=mic.microphone_id,
        )
        db.add_all([sensor, association])
        db.commit()
        db.refresh(sensor)

        response = client.put(
            f"{BASE}/{sensor.sensor_id}",
            headers=superuser_token_headers,
            json={"recorder_microphone_is_default": False},
        )

        assert response.status_code == 422

    def test_update_audio_sensor_preserves_recorder_microphone_notes_when_default_is_omitted(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "PreserveDefaultRecorder")
        mic = _make_microphone(db, "PreserveDefaultMic")
        sensor = Sensor(
            name="PreserveDefaultAudioSensor",
            sensor_type="audio",
            recorder_id=recorder.recorder_id,
            microphone_id=mic.microphone_id,
        )
        association = RecorderMicrophone(
            recorder_id=recorder.recorder_id,
            microphone_id=mic.microphone_id,
            notes="Keep this metadata",
        )
        db.add_all([sensor, association])
        db.commit()
        db.refresh(sensor)

        response = client.put(
            f"{BASE}/{sensor.sensor_id}",
            headers=superuser_token_headers,
            json={"name": "PreserveDefaultAudioSensorUpdated"},
        )

        assert response.status_code == 200
        db.refresh(association)
        assert association.notes == "Keep this metadata"

    def test_update_photo_sensor_rejects_recorder_microphone_default(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "UpdatePhotoRejectMicCamera")
        lens = _make_lens(db, "UpdatePhotoRejectMicLens")
        sensor = Sensor(
            name="UpdatePhotoRejectMicSensor",
            sensor_type="photo",
            camera_id=camera.camera_id,
            lens_id=lens.lens_id,
        )
        db.add_all([
            sensor,
            CameraLens(camera_id=camera.camera_id, lens_id=lens.lens_id),
        ])
        db.commit()
        db.refresh(sensor)

        response = client.put(
            f"{BASE}/{sensor.sensor_id}",
            headers=superuser_token_headers,
            json={"recorder_microphone_is_default": True},
        )

        assert response.status_code == 422

    def test_update_audio_sensor_repairs_missing_link_on_non_device_edit(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "RepairAudioRecorder")
        mic = _make_microphone(db, "RepairAudioMic")
        sensor = Sensor(
            name="RepairAudioSensor",
            sensor_type="audio",
            recorder_id=recorder.recorder_id,
            microphone_id=mic.microphone_id,
        )
        db.add(sensor)
        db.commit()
        db.refresh(sensor)

        response = client.put(
            f"{BASE}/{sensor.sensor_id}",
            headers=superuser_token_headers,
            json={"name": "RepairedAudioSensor"},
        )

        assert response.status_code == 200
        assert db.get(RecorderMicrophone, (recorder.recorder_id, mic.microphone_id)) is not None

    def test_update_photo_sensor_repairs_missing_link_on_non_device_edit(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        camera = _make_camera(db, "RepairPhotoCamera")
        lens = _make_lens(db, "RepairPhotoLens")
        sensor = Sensor(
            name="RepairPhotoSensor",
            sensor_type="photo",
            camera_id=camera.camera_id,
            lens_id=lens.lens_id,
        )
        db.add(sensor)
        db.commit()
        db.refresh(sensor)

        response = client.put(
            f"{BASE}/{sensor.sensor_id}",
            headers=superuser_token_headers,
            json={"name": "RepairedPhotoSensor"},
        )

        assert response.status_code == 200
        assert db.get(CameraLens, (camera.camera_id, lens.lens_id)) is not None

    def test_update_audio_sensor_does_not_add_camera_lens(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        sensor = _make_sensor_audio(db, "UpdateAudioWithoutCameraLens")
        link_count_before = len(db.exec(select(CameraLens)).all())

        response = client.put(
            f"{BASE}/{sensor.sensor_id}",
            headers=superuser_token_headers,
            json={"name": "UpdatedAudioWithoutCameraLens"},
        )

        assert response.status_code == 200
        assert len(db.exec(select(CameraLens)).all()) == link_count_before


# DELETE /sensors/{sensor_id}  (admin)

class TestDeleteSensor:
    def test_delete_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.delete(f"{BASE}/999999", headers=superuser_token_headers)
        assert r.status_code == 404

    def test_delete_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        obj = _make_sensor_audio(db, "DeleteSensor")
        r = client.delete(f"{BASE}/{obj.sensor_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        r2 = client.get(f"{BASE}/{obj.sensor_id}", headers=superuser_token_headers)
        assert r2.status_code == 404

    def test_delete_in_use_rejected(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        from app.models import User
        from app.models.media import AudioSetting, Media

        sensor = _make_sensor_audio(db, "UsedSensor")
        user = db.exec(select(User)).first()
        audio_setting = AudioSetting(sampling_rate_hz=44100, duration_s=60.0)
        db.add(audio_setting)
        db.commit()
        db.refresh(audio_setting)
        media = Media(
            media_type="audio",
            sensor_id=sensor.sensor_id,
            uploader_id=user.user_id,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.commit()
        r = client.delete(f"{BASE}/{sensor.sensor_id}", headers=superuser_token_headers)
        assert r.status_code == 400
