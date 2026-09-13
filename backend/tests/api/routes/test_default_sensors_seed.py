"""
Integration tests for the seeded default test sensors.
"""
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models.device import Camera, CameraLens, Lens, Microphone, Recorder, RecorderMicrophone, Sensor


def test_default_test_sensors_seeded_in_db(db: Session) -> None:
    """Verify default audio and photo sensors and their device combinations exist in database."""
    # 1. Verify Audio Sensor
    audio_sensor = db.exec(
        select(Sensor).where(Sensor.name == "Test Audio Sensor", Sensor.sensor_type == "audio")
    ).first()
    assert audio_sensor is not None
    assert audio_sensor.serial_number == "TEST-AUDIO-001"
    assert audio_sensor.recorder_id is not None
    assert audio_sensor.microphone_id is not None
    assert audio_sensor.camera_id is None
    assert audio_sensor.lens_id is None

    # Check referenced recorder & microphone
    recorder = db.get(Recorder, audio_sensor.recorder_id)
    assert recorder is not None
    assert recorder.name == "Test Recorder"
    assert recorder.brand == "ecoSignal"

    microphone = db.get(Microphone, audio_sensor.microphone_id)
    assert microphone is not None
    assert microphone.name == "Test Microphone"

    # Check recorder_microphone link
    rec_mic_link = db.exec(
        select(RecorderMicrophone).where(
            RecorderMicrophone.recorder_id == audio_sensor.recorder_id,
            RecorderMicrophone.microphone_id == audio_sensor.microphone_id,
        )
    ).first()
    assert rec_mic_link is not None

    # 2. Verify Photo Sensor
    photo_sensor = db.exec(
        select(Sensor).where(Sensor.name == "Test Photo Sensor", Sensor.sensor_type == "photo")
    ).first()
    assert photo_sensor is not None
    assert photo_sensor.serial_number == "TEST-PHOTO-001"
    assert photo_sensor.camera_id is not None
    assert photo_sensor.lens_id is not None
    assert photo_sensor.recorder_id is None
    assert photo_sensor.microphone_id is None

    # Check referenced camera & lens
    camera = db.get(Camera, photo_sensor.camera_id)
    assert camera is not None
    assert camera.name == "Test Camera"
    assert camera.brand == "ecoSignal"

    lens = db.get(Lens, photo_sensor.lens_id)
    assert lens is not None
    assert lens.name == "Test Lens"
    assert lens.brand == "ecoSignal"

    # Check camera_lens link
    cam_lens_link = db.exec(
        select(CameraLens).where(
            CameraLens.camera_id == photo_sensor.camera_id,
            CameraLens.lens_id == photo_sensor.lens_id,
        )
    ).first()
    assert cam_lens_link is not None


def test_default_test_sensors_available_in_sensor_options(client: TestClient) -> None:
    """Verify default sensors appear in GET /sensor-options for immediate upload use."""
    r = client.get(f"{settings.API_V1_STR}/sensor-options")
    assert r.status_code == 200
    json_resp = r.json()
    assert json_resp["code"] == 0
    data = json_resp["data"]

    audio_opt = next((s for s in data if s["name"] == "Test Audio Sensor"), None)
    assert audio_opt is not None
    assert audio_opt["sensor_type"] == "audio"
    assert audio_opt["serial_number"] == "TEST-AUDIO-001"

    photo_opt = next((s for s in data if s["name"] == "Test Photo Sensor"), None)
    assert photo_opt is not None
    assert photo_opt["sensor_type"] == "photo"
    assert photo_opt["serial_number"] == "TEST-PHOTO-001"
