from pathlib import Path

import pytest
from PIL import Image

from app.workers.tasks.media import (
    _EXIF_IFD_TAG,
    _TAG_DATETIME_ORIGINAL,
    _TAG_EXPOSURE_TIME,
    _TAG_F_NUMBER,
    _TAG_ISO,
    _generate_photo_thumbnail,
    _photo_metadata,
)


@pytest.mark.parametrize("suffix, format_name", [(".jpg", "JPEG"), (".png", "PNG"), (".tiff", "TIFF")])
def test_photo_metadata_accepts_supported_images_and_generates_thumbnail(tmp_path: Path, suffix: str, format_name: str) -> None:
    source = tmp_path / f"photo{suffix}"
    thumbnail = tmp_path / "thumbnail.png"
    Image.new("RGB", (1600, 900), "green").save(source, format=format_name)

    _metadata, captured_at, dimensions = _photo_metadata(source)
    _generate_photo_thumbnail(source, thumbnail)

    assert captured_at is None
    assert dimensions == (1600, 900)
    with Image.open(thumbnail) as generated:
        assert generated.format == "PNG"
        assert max(generated.size) <= 640


def test_photo_metadata_rejects_non_image_content(tmp_path: Path) -> None:
    source = tmp_path / "not-a-photo.jpg"
    source.write_text("not an image")

    with pytest.raises(ValueError, match="valid image"):
        _photo_metadata(source)


def test_photo_metadata_uses_first_frame_for_mpo_jpeg(tmp_path: Path) -> None:
    source = tmp_path / "camera.jpg"
    thumbnail = tmp_path / "thumbnail.png"
    primary = Image.new("RGB", (1600, 900), "green")
    secondary = Image.new("RGB", (800, 600), "blue")
    primary.save(source, "MPO", save_all=True, append_images=[secondary])

    with Image.open(source) as image:
        assert image.format == "MPO"
        assert image.n_frames == 2

    _metadata, captured_at, dimensions = _photo_metadata(source)
    _generate_photo_thumbnail(source, thumbnail)

    assert captured_at is None
    assert dimensions == (1600, 900)
    with Image.open(thumbnail) as generated:
        assert generated.format == "PNG"
        assert generated.size == (640, 360)


def test_photo_metadata_reads_camera_fields_from_exif_ifd(tmp_path: Path) -> None:
    source = tmp_path / "camera.jpg"
    image = Image.new("RGB", (120, 80), "blue")
    exif = image.getexif()
    exif_ifd = exif.get_ifd(_EXIF_IFD_TAG) if exif else {}
    if not isinstance(exif_ifd, dict):
        exif_ifd = dict(exif_ifd)
    exif_ifd[_TAG_EXPOSURE_TIME] = 0.01
    exif_ifd[_TAG_F_NUMBER] = 1.8
    exif_ifd[_TAG_ISO] = 200
    exif_ifd[_TAG_DATETIME_ORIGINAL] = "2026:07:24 12:00:00"
    exif[_EXIF_IFD_TAG] = exif_ifd
    image.save(source, format="JPEG", exif=exif)

    metadata, captured_at, dimensions = _photo_metadata(source)

    assert metadata == {"exposure_ms": 10.0, "aperture": 1.8, "iso": 200}
    assert captured_at is not None
    assert dimensions == (120, 80)
