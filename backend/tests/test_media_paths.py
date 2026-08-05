from pathlib import Path

from app.core.config import settings
from app.media_paths import (
    analysis_audio_filename_candidates,
    audio_filename_candidates,
    build_media_public_url,
    logical_audio_media_path,
    normalize_media_relative_path,
    resolve_existing_analysis_audio_media_path,
    resolve_existing_media_path,
)


def test_normalize_media_relative_path_handles_supported_variants() -> None:
    assert normalize_media_relative_path("sounds/sounds/12/88/demo.wav") == Path("sounds/12/88/demo.wav")
    assert normalize_media_relative_path("/app/sounds/projects/demo.png") == Path("projects/demo.png")
    assert normalize_media_relative_path("sounds//images\\cover.png") == Path("images/cover.png")


def test_build_media_public_url_uses_normalized_relative_path() -> None:
    url = build_media_public_url("sounds/sounds/12/88/demo_thumbnail.png")
    assert url.endswith("/sounds/12/88/demo_thumbnail.png")
    assert "/sounds/sounds/sounds/" not in url


def test_logical_audio_media_path_builds_public_storage_url() -> None:
    rel = logical_audio_media_path(12, 88, "demo.flac")
    assert rel == Path("sounds/12/88/demo.flac")

    url = build_media_public_url(rel)
    assert url.endswith("/sounds/sounds/12/88/demo.flac")
    assert "/sounds/sounds/sounds/" not in url


def test_public_origin_omits_default_http_port(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DOMAIN", "ecoSignal.local")
    monkeypatch.setattr(settings, "FRONTEND_PORT", 80)
    monkeypatch.setattr(settings, "ENABLE_HTTPS", False)

    assert settings.public_origin == "http://ecoSignal.local"
    assert settings.media_base_url == "http://ecoSignal.local/sounds"


def test_public_origin_keeps_non_default_port(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DOMAIN", "ecoSignal.local")
    monkeypatch.setattr(settings, "FRONTEND_PORT", 3001)
    monkeypatch.setattr(settings, "ENABLE_HTTPS", False)

    assert settings.public_origin == "http://ecoSignal.local:3001"
    assert settings.media_base_url == "http://ecoSignal.local:3001/sounds"


def test_public_origin_uses_https_and_omits_default_port(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DOMAIN", "ecoSignal.local")
    monkeypatch.setattr(settings, "FRONTEND_PORT", 443)
    monkeypatch.setattr(settings, "ENABLE_HTTPS", True)

    assert settings.public_origin == "https://ecoSignal.local"
    assert settings.media_base_url == "https://ecoSignal.local/sounds"


def test_public_origin_keeps_non_default_https_port(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DOMAIN", "ecoSignal.local")
    monkeypatch.setattr(settings, "FRONTEND_PORT", 8443)
    monkeypatch.setattr(settings, "ENABLE_HTTPS", True)

    assert settings.public_origin == "https://ecoSignal.local:8443"
    assert settings.media_base_url == "https://ecoSignal.local:8443/sounds"


def test_resolve_existing_media_path_returns_none_when_primary_missing(tmp_path, monkeypatch) -> None:
    primary = tmp_path / "primary"

    monkeypatch.setattr(settings, "MEDIA_ROOT", str(primary))

    resolved = resolve_existing_media_path("projects/demo.png")
    assert resolved is None


def test_analysis_audio_candidates_keep_supported_filename_first() -> None:
    assert analysis_audio_filename_candidates("clip.wav") == ["clip.wav", "clip.flac"]
    assert analysis_audio_filename_candidates("clip.flac") == ["clip.flac", "clip.wav"]


def test_audio_filename_candidates_try_recorded_name_before_companions() -> None:
    assert audio_filename_candidates("clip.flac") == ["clip.flac", "clip.wav"]
    assert audio_filename_candidates("clip.wav") == ["clip.wav", "clip.flac"]
    assert audio_filename_candidates("clip.mp3") == ["clip.mp3", "clip.flac", "clip.wav"]


def test_analysis_audio_candidates_prefer_companion_wav_for_unsupported_filename() -> None:
    assert analysis_audio_filename_candidates("clip.mp3") == ["clip.wav", "clip.flac"]


def test_resolve_existing_analysis_audio_prefers_companion_wav_for_non_wav_db_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
    media_dir = tmp_path / "sounds" / "12" / "34"
    media_dir.mkdir(parents=True)
    (media_dir / "clip.mp3").write_bytes(b"source")
    wav_path = media_dir / "clip.wav"
    wav_path.write_bytes(b"wav")
    (media_dir / "clip.flac").write_bytes(b"flac")

    resolved = resolve_existing_analysis_audio_media_path(12, 34, "clip.mp3")

    assert resolved == wav_path


def test_resolve_existing_analysis_audio_falls_back_to_flac(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
    media_dir = tmp_path / "sounds" / "12" / "34"
    media_dir.mkdir(parents=True)
    flac_path = media_dir / "clip.flac"
    flac_path.write_bytes(b"flac")

    resolved = resolve_existing_analysis_audio_media_path(12, 34, "clip.mp3")

    assert resolved == flac_path
