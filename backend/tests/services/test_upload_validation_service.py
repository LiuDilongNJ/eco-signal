from pathlib import Path
from subprocess import CompletedProcess

import pytest
from fastapi import HTTPException
from PIL import Image

from app.media_paths import is_safe_public_media_request_path
from app.services.upload_validation_service import (
    sanitize_image,
    validate_audio_file,
    validate_audio_filename,
    validate_csv_content,
    validate_filename,
    validate_photo_file,
    validate_photo_filename,
    validate_zip_file,
)


@pytest.mark.parametrize("filename", ["../sound.wav", "nested/sound.wav", "bad\x00.wav", "a" * 300 + ".wav"])
def test_filename_validation_rejects_paths_and_controls(filename: str) -> None:
    with pytest.raises(HTTPException, match="invalid_filename"):
        validate_filename(filename)


def test_audio_filename_whitelist() -> None:
    assert validate_audio_filename("recording.FLAC") == "flac"
    with pytest.raises(HTTPException, match="unsupported_file_type"):
        validate_audio_filename("payload.exe")


def test_audio_content_validation_requires_matching_probe_result(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "recording.wav"
    path.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    monkeypatch.setattr(
        "app.services.upload_validation_service.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, '{"format":{"format_name":"wav"},"streams":[{"codec_type":"audio"}]}'),
    )
    validate_audio_file(path, path.name)

    monkeypatch.setattr(
        "app.services.upload_validation_service.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, '{"format":{"format_name":"wav"},"streams":[{"codec_type":"audio"},{"codec_type":"video","disposition":{"attached_pic":0}}]}'),
    )
    with pytest.raises(HTTPException, match="file_type_mismatch"):
        validate_audio_file(path, path.name)


def test_audio_content_validation_accepts_embedded_cover_art(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "recording.flac"
    path.write_bytes(b"fLaC" + b"\x00" * 12)
    monkeypatch.setattr(
        "app.services.upload_validation_service.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(
            args[0],
            0,
            '{"format":{"format_name":"flac"},"streams":[{"codec_type":"audio"},{"codec_type":"video","disposition":{"attached_pic":1}}]}',
        ),
    )

    validate_audio_file(path, path.name)


@pytest.mark.parametrize(
    ("suffix", "format_name"),
    [(".jpg", "JPEG"), (".png", "PNG"), (".tif", "TIFF"), (".tiff", "TIFF")],
)
def test_photo_validation_accepts_supported_content(
    tmp_path: Path, suffix: str, format_name: str
) -> None:
    path = tmp_path / f"photo{suffix}"
    Image.new("RGB", (4, 3), "green").save(path, format_name)

    assert validate_photo_filename(path.name) == suffix.lstrip(".")
    validate_photo_file(path, path.name)


def test_photo_validation_rejects_mismatched_or_invalid_content(tmp_path: Path) -> None:
    mismatched = tmp_path / "photo.jpg"
    Image.new("RGB", (4, 3), "green").save(mismatched, "PNG")
    with pytest.raises(HTTPException, match="file_type_mismatch"):
        validate_photo_file(mismatched, mismatched.name)

    invalid = tmp_path / "invalid.png"
    invalid.write_bytes(b"not an image")
    with pytest.raises(HTTPException, match="invalid_file_content"):
        validate_photo_file(invalid, invalid.name)


def test_photo_validation_accepts_mpo_content_with_jpeg_extension(tmp_path: Path) -> None:
    path = tmp_path / "camera.jpg"
    primary = Image.new("RGB", (4, 3), "green")
    secondary = Image.new("RGB", (2, 2), "blue")
    primary.save(path, "MPO", save_all=True, append_images=[secondary])

    with Image.open(path) as image:
        assert image.format == "MPO"
        assert image.n_frames == 2

    validate_photo_file(path, path.name)


def test_image_sanitization_rejects_content_type_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "cover.png"
    image = Image.new("RGB", (1, 1), "white")
    image.save(path, "PNG")
    with pytest.raises(HTTPException, match="file_type_mismatch"):
        sanitize_image(path, "cover.png", "image/jpeg")


def test_image_sanitization_reencodes_valid_image(tmp_path: Path) -> None:
    path = tmp_path / "cover.png"
    image = Image.new("RGB", (1, 1), "white")
    image.save(path, "PNG", pnginfo=None)
    assert sanitize_image(path, "cover.png", "image/png") == "png"
    with Image.open(path) as saved:
        assert saved.format == "PNG"


def test_csv_validation_rejects_binary_content() -> None:
    with pytest.raises(HTTPException, match="invalid_file_content"):
        validate_csv_content(b"name\x00,value")
    assert "name" in validate_csv_content(b"name,value\nrecording,1")


def test_csv_validation_rejects_malformed_quoting() -> None:
    # Strict RFC 4180 parsing: text after a closing quote is malformed.
    with pytest.raises(HTTPException, match="invalid_file_content"):
        validate_csv_content(b'name,value\n"a"b,1\n')


def test_zip_validation_rejects_non_zip(tmp_path: Path) -> None:
    path = tmp_path / "bundle.zip"
    path.write_bytes(b"not an archive")
    with pytest.raises(HTTPException, match="unsafe_archive"):
        validate_zip_file(path, "bundle.zip")


def test_quarantine_paths_are_not_public() -> None:
    assert not is_safe_public_media_request_path("tmp/pending/1/payload.wav")
    assert is_safe_public_media_request_path("projects/logo.png")
