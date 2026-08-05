from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from PIL import Image

from app.models import AudioSetting, Media
from app.models.media import Preview
from app.services import media_preview_service


def _png_bytes(mode: str = "RGB") -> bytes:
    stream = BytesIO()
    color = (10, 20, 30, 120) if mode == "RGBA" else (10, 20, 30)
    Image.new(mode, (12, 8), color=color).save(stream, format="PNG")
    return stream.getvalue()


def test_generate_photo_thumbnail_converts_rgba(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    target = tmp_path / "thumbnail.png"
    source.write_bytes(_png_bytes("RGBA"))

    media_preview_service.generate_photo_thumbnail(source, target)

    with Image.open(target) as image:
        assert image.mode == "RGB"
        assert image.size == (12, 8)


def test_generate_media_previews_creates_atomic_audio_assets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(media_preview_service, "media_root", lambda: tmp_path)
    source = tmp_path / "sounds" / "10" / "2" / "field.flac"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    existing_thumbnail = source.parent / "field_thumbnail.png"
    existing_thumbnail.write_bytes(b"existing")
    media = Media(
        media_id=5,
        uuid=uuid4(),
        media_type="audio",
        directory=2,
        filename="field.flac",
        uploader_id=1,
        creator_id=1,
    )
    media.audio_setting = AudioSetting(
        sampling_rate_hz=48000,
        duration_s=1,
        channel_num=2,
    )
    session = MagicMock()

    result = media_preview_service.generate_media_previews(
        session,
        media=media,
        collection_id=10,
        source_path=source,
        thumbnail_generator=lambda **_kwargs: b"thumbnail",
        player_generator=lambda *_args, **_kwargs: b"player",
    )

    assert result.created_count == 2
    assert result.warnings == []
    assert existing_thumbnail.read_bytes() == b"existing"
    assert any(str(media.uuid) in path.name for path in result.created_paths)
    assert all(path.is_file() for path in result.created_paths)
    assert all(isinstance(call.args[0], Preview) for call in session.add.call_args_list)


def test_generate_media_previews_reports_generator_failures(tmp_path: Path) -> None:
    source = tmp_path / "failed.flac"
    source.write_bytes(b"audio")
    media = Media(
        media_id=6,
        media_type="audio",
        directory=1,
        filename="failed.flac",
        uploader_id=1,
        creator_id=1,
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("generation failed")

    result = media_preview_service.generate_media_previews(
        MagicMock(),
        media=media,
        collection_id=10,
        source_path=source,
        thumbnail_generator=fail,
        player_generator=fail,
    )

    assert len(result.warnings) == 2
    assert all("generation failed" in warning for warning in result.warnings)


def test_generate_media_previews_reports_photo_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(media_preview_service, "media_root", lambda: tmp_path)
    source = tmp_path / "photo.png"
    source.write_bytes(_png_bytes())
    media = Media(
        media_id=7,
        media_type="photo",
        directory=3,
        filename="photo.png",
        uploader_id=1,
        creator_id=1,
    )

    result = media_preview_service.generate_media_previews(
        MagicMock(),
        media=media,
        collection_id=10,
        source_path=source,
        photo_generator=lambda *_args: (_ for _ in ()).throw(RuntimeError("photo failed")),
    )

    assert result.created_count == 0
    assert result.warnings == ["Photo thumbnail generation failed: photo failed"]
