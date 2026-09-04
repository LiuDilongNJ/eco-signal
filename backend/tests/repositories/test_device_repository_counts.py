from sqlmodel import Session

from app.models.device import (
    Camera,
    CameraLens,
    Lens,
    Microphone,
    Recorder,
    RecorderMicrophone,
)
from app.repositories import device_repository


def test_get_lenses_filters_sorts_and_paginates(db: Session) -> None:
    alpha = Lens(name="RepositoryLensAlpha")
    beta = Lens(name="RepositoryLensBeta")
    db.add(alpha)
    db.add(beta)
    db.commit()

    rows, total = device_repository.get_lenses(
        db,
        page=1,
        page_size=1,
        filters={"name": "Alpha"},
        order_by="name",
        order_dir="asc",
    )

    assert total == 1
    assert len(rows) == 1
    assert rows[0].lens_id == alpha.lens_id


def test_get_microphones_filters_sorts_and_paginates(db: Session) -> None:
    alpha = Microphone(name="RepositoryMicAlpha")
    beta = Microphone(name="RepositoryMicBeta")
    db.add(alpha)
    db.add(beta)
    db.commit()

    rows, total = device_repository.get_microphones(
        db,
        page=1,
        page_size=1,
        filters={"name": "Alpha"},
        order_by="name",
        order_dir="asc",
    )

    assert total == 1
    assert len(rows) == 1
    assert rows[0].microphone_id == alpha.microphone_id


def test_recorder_microphone_relationship_query_is_sorted(db: Session) -> None:
    recorder_a = Recorder(name="RepositoryRecorderA")
    microphone_a = Microphone(name="RepositoryMicrophoneA")
    microphone_b = Microphone(name="RepositoryMicrophoneB")
    db.add_all([recorder_a, microphone_a, microphone_b])
    db.commit()
    for item in [recorder_a, microphone_a, microphone_b]:
        db.refresh(item)
    db.add_all([
        RecorderMicrophone(recorder_id=recorder_a.recorder_id, microphone_id=microphone_b.microphone_id),
        RecorderMicrophone(recorder_id=recorder_a.recorder_id, microphone_id=microphone_a.microphone_id),
    ])
    db.commit()

    recorder_links = device_repository.get_recorder_microphones(db, recorder_a.recorder_id)

    assert [link.microphone_id for link in recorder_links] == [microphone_a.microphone_id, microphone_b.microphone_id]
    assert recorder_links[0].microphone.name == microphone_a.name


def test_camera_lens_relationship_query_is_sorted(db: Session) -> None:
    camera_a = Camera(name="RepositoryCameraA")
    lens_a = Lens(name="RepositoryLensA")
    lens_b = Lens(name="RepositoryLensB")
    db.add_all([camera_a, lens_a, lens_b])
    db.commit()
    for item in [camera_a, lens_a, lens_b]:
        db.refresh(item)
    db.add_all([
        CameraLens(camera_id=camera_a.camera_id, lens_id=lens_b.lens_id),
        CameraLens(camera_id=camera_a.camera_id, lens_id=lens_a.lens_id),
    ])
    db.commit()

    camera_links = device_repository.get_camera_lenses(db, camera_a.camera_id)

    assert [link.lens_id for link in camera_links] == [lens_a.lens_id, lens_b.lens_id]
    assert camera_links[0].lens.name == lens_a.name


def test_get_normalized_names_returns_lowercased_trimmed_names(db: Session) -> None:
    db.add(Recorder(name="  Normalized Recorder "))
    db.commit()

    names = device_repository.get_normalized_names(db, Recorder)

    assert "normalized recorder" in names
