from sqlalchemy import inspect
from sqlmodel import Session, func, select

from app.models.device import Microphone, Recorder, RecorderMicrophone


def test_device_catalog_migration_removes_default_columns_and_seeds_catalog(db: Session) -> None:
    inspector = inspect(db.connection())

    assert "is_default" not in {column["name"] for column in inspector.get_columns("recorder_microphone")}
    assert "is_default" not in {column["name"] for column in inspector.get_columns("camera_lens")}
    assert db.exec(select(func.count()).select_from(Recorder)).one() >= 110
    assert db.exec(select(func.count()).select_from(Microphone)).one() >= 92
    assert db.exec(select(func.count()).select_from(RecorderMicrophone)).one() >= 150
