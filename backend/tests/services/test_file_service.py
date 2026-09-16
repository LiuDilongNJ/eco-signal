import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services.file_service import (
    FileService,
    _missing_audio_tag_names,
    is_target_sampling_rate_supported,
)


@pytest.mark.parametrize(
    ("codec", "rate", "expected"),
    [
        ("opus", 24000, True),
        ("opus", 44100, False),
        ("mp3", 44100, True),
        ("mp3", 88200, False),
        ("vorbis", 200000, True),
        ("vorbis", 200001, False),
        ("flac", 384000, True),
        ("pcm_s16le", 384000, True),
    ],
)
def test_target_sampling_rate_support_matches_encoder_capabilities(
    codec: str,
    rate: int,
    expected: bool,
) -> None:
    assert is_target_sampling_rate_supported(codec, rate) is expected


@pytest.mark.parametrize(
    ("filename", "encoder", "expected_codec"),
    [
        ("sample.wav", "pcm_s16le", "pcm_s16le"),
        ("sample.flac", "flac", "flac"),
        ("sample.mp3", "libmp3lame", "mp3"),
        ("sample-vorbis.ogg", "libvorbis", "vorbis"),
        ("sample-opus.ogg", "libopus", "opus"),
    ],
)
def test_resample_stored_audio_preserves_supported_codec(
    tmp_path: Path,
    filename: str,
    encoder: str,
    expected_codec: str,
) -> None:
    source_path = tmp_path / filename
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000:duration=0.25",
            "-c:a",
            encoder,
            str(source_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    service = FileService(base_dir=str(tmp_path))

    metadata = service.resample_stored_audio(
        source_path,
        target_sampling_rate_hz=16000,
        file_metadata={"source": {"filename": filename}},
    )

    assert source_path.is_file()
    assert metadata["stored"]["sampling_rate_hz"] == 16000
    assert metadata["stored"]["codec"] == expected_codec
    probed_rate = service._probe_audio(source_path)["sampling_rate_hz"]
    if expected_codec == "opus":
        assert probed_rate == 48000
        assert metadata["stored"]["codec_sampling_rate_hz"] == 48000
    else:
        assert probed_rate == 16000


def test_missing_audio_tag_names_matches_values_across_tag_namespaces() -> None:
    source_tags = {
        "id3v2": {
            "TIT2": ["Field recording"],
            "TPE1": ["Researcher"],
            "TSSE": ["Source encoder"],
        }
    }
    stored_tags = {
        "vorbis_comment": {
            "title": ["Field recording"],
            "artist": ["Researcher"],
            "encoder": ["Stored encoder"],
        }
    }

    assert _missing_audio_tag_names(source_tags, stored_tags) == []


def test_missing_audio_tag_names_reports_only_unretained_content_tags() -> None:
    source_tags = {
        "id3v2": {
            "TIT2": ["Field recording"],
            "TPE1": ["Researcher"],
            "TXXX:comment": ["Dawn survey"],
        }
    }
    stored_tags = {"vorbis_comment": {"title": ["Field recording"]}}

    assert _missing_audio_tag_names(source_tags, stored_tags) == ["TPE1", "TXXX:comment"]


def test_extract_audio_tags_returns_empty_mapping_when_file_has_no_tags(
    tmp_path, monkeypatch
) -> None:
    service = FileService(base_dir=str(tmp_path))
    audio = MagicMock(tags=None)
    monkeypatch.setattr("app.services.file_service.mutagen.File", lambda *args, **kwargs: audio)

    tags, warnings = service._extract_audio_tags(tmp_path / "untagged.wav")

    assert tags == {}
    assert warnings == []


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
