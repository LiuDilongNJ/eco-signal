from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.file_service import FileService


def test_merge_and_validate_chunks_validates_photo_and_keeps_file(tmp_path, monkeypatch) -> None:
    service = FileService(base_dir=str(tmp_path))
    merged = tmp_path / "tmp" / "pending" / "7" / "photo.jpg"
    merged.parent.mkdir(parents=True)
    merged.write_bytes(b"image")
    calls: list[str] = []

    monkeypatch.setattr(service, "merge_chunks", lambda *args, **kwargs: merged)
    monkeypatch.setattr(
        "app.services.file_service.validate_photo_file",
        lambda path, filename: calls.append(filename),
    )

    result = service.merge_and_validate_chunks(
        filename="photo.jpg", user_id=7, batch_id="batch", media_type="photo"
    )

    assert result == merged
    assert merged.exists()
    assert calls == ["photo.jpg"]


def test_merge_and_validate_chunks_removes_invalid_photo(tmp_path, monkeypatch) -> None:
    service = FileService(base_dir=str(tmp_path))
    merged = tmp_path / "photo.jpg"
    merged.write_bytes(b"invalid")

    monkeypatch.setattr(service, "merge_chunks", lambda *args, **kwargs: merged)

    def reject(*args, **kwargs):
        raise HTTPException(status_code=400, detail="invalid_file_content")

    monkeypatch.setattr("app.services.file_service.validate_photo_file", reject)

    with pytest.raises(HTTPException, match="invalid_file_content"):
        service.merge_and_validate_chunks(
            filename="photo.jpg", user_id=7, batch_id="batch", media_type="photo"
        )
    assert not merged.exists()


@pytest.mark.parametrize(
    ("media_type", "validator"),
    [
        ("audio", "validate_audio_file"),
        ("zip", "validate_zip_file"),
    ],
)
def test_merge_and_validate_chunks_selects_non_photo_validator(
    tmp_path, monkeypatch, media_type: str, validator: str
) -> None:
    service = FileService(base_dir=str(tmp_path))
    merged = tmp_path / "payload"
    merged.write_bytes(b"payload")
    calls: list[str] = []
    monkeypatch.setattr(service, "merge_chunks", lambda *args, **kwargs: merged)
    monkeypatch.setattr(
        f"app.services.file_service.{validator}",
        lambda path, filename: calls.append(filename),
    )

    result = service.merge_and_validate_chunks(
        filename="payload.zip" if media_type == "zip" else "payload.wav",
        user_id=7,
        batch_id="batch",
        media_type=media_type,
    )

    assert result == merged
    assert calls == ["payload.zip" if media_type == "zip" else "payload.wav"]
