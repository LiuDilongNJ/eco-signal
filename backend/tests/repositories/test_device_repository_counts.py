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


def test_get_lenses_counts_filters_sorts_and_paginates(db: Session) -> None:
    low = Lens(name="RepositoryLensLow")
    high = Lens(name="RepositoryLensHigh")
    cameras = [Camera(name=f"RepositoryCamera{i}") for i in range(3)]
    db.add(low)
    db.add(high)
    db.add_all(cameras)
    db.commit()
    db.refresh(low)
    db.refresh(high)
    for camera in cameras:
        db.refresh(camera)
    db.add(CameraLens(camera_id=cameras[0].camera_id, lens_id=low.lens_id))
    db.add(CameraLens(camera_id=cameras[1].camera_id, lens_id=high.lens_id))
    db.add(CameraLens(camera_id=cameras[2].camera_id, lens_id=high.lens_id))
    db.commit()

    rows, total = device_repository.get_lenses(
        db,
        page=1,
        page_size=1,
        filters={"camera_count": 2},
        order_by="camera_count",
        order_dir="desc",
    )

    assert total == 1
    assert len(rows) == 1
    assert rows[0][0].lens_id == high.lens_id
    assert rows[0][1] == 2


def test_get_microphones_combines_recorder_filter_with_count_and_sort(db: Session) -> None:
    low = Microphone(name="RepositoryMicLow")
    high = Microphone(name="RepositoryMicHigh")
    recorders = [Recorder(name=f"RepositoryRecorder{i}") for i in range(3)]
    db.add(low)
    db.add(high)
    db.add_all(recorders)
    db.commit()
    db.refresh(low)
    db.refresh(high)
    for recorder in recorders:
        db.refresh(recorder)
    db.add(RecorderMicrophone(recorder_id=recorders[0].recorder_id, microphone_id=low.microphone_id))
    db.add(RecorderMicrophone(recorder_id=recorders[1].recorder_id, microphone_id=high.microphone_id))
    db.add(RecorderMicrophone(recorder_id=recorders[2].recorder_id, microphone_id=high.microphone_id))
    db.commit()

    rows, total = device_repository.get_microphones(
        db,
        page=1,
        page_size=10,
        filters={"recorder_id": recorders[1].recorder_id, "recorder_count": 2},
        order_by="recorder_count",
        order_dir="desc",
    )

    assert total == 1
    assert len(rows) == 1
    assert rows[0][0].microphone_id == high.microphone_id
    assert rows[0][1] == 2


def test_recorder_microphone_relationship_queries_are_symmetric_and_sorted(db: Session) -> None:
    recorder_a = Recorder(name="RepositoryRecorderA")
    recorder_b = Recorder(name="RepositoryRecorderB")
    microphone_a = Microphone(name="RepositoryMicrophoneA")
    microphone_b = Microphone(name="RepositoryMicrophoneB")
    db.add_all([recorder_a, recorder_b, microphone_a, microphone_b])
    db.commit()
    for item in [recorder_a, recorder_b, microphone_a, microphone_b]:
        db.refresh(item)
    db.add_all([
        RecorderMicrophone(recorder_id=recorder_a.recorder_id, microphone_id=microphone_b.microphone_id),
        RecorderMicrophone(recorder_id=recorder_a.recorder_id, microphone_id=microphone_a.microphone_id),
        RecorderMicrophone(recorder_id=recorder_b.recorder_id, microphone_id=microphone_a.microphone_id),
    ])
    db.commit()

    recorder_links = device_repository.get_recorder_microphones(db, recorder_a.recorder_id)
    microphone_links = device_repository.get_microphone_recorders(db, microphone_a.microphone_id)

    assert [link.microphone_id for link in recorder_links] == [microphone_a.microphone_id, microphone_b.microphone_id]
    assert [link.recorder_id for link in microphone_links] == [recorder_a.recorder_id, recorder_b.recorder_id]
    assert recorder_links[0].microphone.name == microphone_a.name
    assert microphone_links[0].recorder.name == recorder_a.name


def test_camera_lens_relationship_queries_are_symmetric_and_sorted(db: Session) -> None:
    camera_a = Camera(name="RepositoryCameraA")
    camera_b = Camera(name="RepositoryCameraB")
    lens_a = Lens(name="RepositoryLensA")
    lens_b = Lens(name="RepositoryLensB")
    db.add_all([camera_a, camera_b, lens_a, lens_b])
    db.commit()
    for item in [camera_a, camera_b, lens_a, lens_b]:
        db.refresh(item)
    db.add_all([
        CameraLens(camera_id=camera_a.camera_id, lens_id=lens_b.lens_id),
        CameraLens(camera_id=camera_a.camera_id, lens_id=lens_a.lens_id),
        CameraLens(camera_id=camera_b.camera_id, lens_id=lens_a.lens_id),
    ])
    db.commit()

    camera_links = device_repository.get_camera_lenses(db, camera_a.camera_id)
    lens_links = device_repository.get_lens_cameras(db, lens_a.lens_id)

    assert [link.lens_id for link in camera_links] == [lens_a.lens_id, lens_b.lens_id]
    assert [link.camera_id for link in lens_links] == [camera_a.camera_id, camera_b.camera_id]
    assert camera_links[0].lens.name == lens_a.name
    assert lens_links[0].camera.name == camera_a.name


def test_get_normalized_names_returns_lowercased_trimmed_names(db: Session) -> None:
    db.add(Recorder(name="  Normalized Recorder "))
    db.commit()

    names = device_repository.get_normalized_names(db, Recorder)

    assert "normalized recorder" in names
