import wave
from pathlib import Path
from unittest.mock import MagicMock
from sqlmodel import Session, select

from app.models import AudioSetting, Media, MediaCollection
from scripts import backfill_audio_file_metadata


def _create_wav(path: Path, duration_s: float = 0.2, sample_rate: int = 44100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        n_frames = int(duration_s * sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)


def test_probe_and_extract_tags_success(tmp_path: Path) -> None:
    wav_path = tmp_path / "sound.wav"
    _create_wav(wav_path)
    meta, warnings = backfill_audio_file_metadata._probe_and_extract_tags(str(wav_path), "sound.wav")
    assert meta is not None
    assert meta["source"]["filename"] == "sound.wav"
    assert meta["stored"]["sampling_rate_hz"] == 44100
    assert "Source file details are unavailable for this existing recording" in warnings


def test_probe_and_extract_tags_failure(tmp_path: Path) -> None:
    bad_path = tmp_path / "broken.wav"
    bad_path.write_bytes(b"not an audio")
    meta, warnings = backfill_audio_file_metadata._probe_and_extract_tags(str(bad_path), "broken.wav")
    assert meta is None
    assert warnings == []


def test_backfill_metadata_runs(tmp_path: Path, monkeypatch) -> None:
    # Test when no rows need backfill
    counts = backfill_audio_file_metadata.backfill_metadata()
    assert isinstance(counts, dict)


def test_backfill_metadata_with_items(tmp_path: Path, monkeypatch) -> None:
    wav_path = tmp_path / "survey.wav"
    _create_wav(wav_path)

    fake_setting = AudioSetting(audio_setting_id=999, file_metadata=None)
    fake_rows = [(101, 999, "dir", "survey.wav", 10)]

    mock_session = MagicMock()
    mock_session.exec.return_value.all.return_value = fake_rows
    mock_session.get.return_value = fake_setting

    monkeypatch.setattr(backfill_audio_file_metadata, "resolve_existing_audio_media_path", lambda c, d, f: wav_path)
    monkeypatch.setattr(backfill_audio_file_metadata, "optimal_worker_count", lambda: 1)

    class MockSessionContext:
        def __enter__(self):
            return mock_session
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(backfill_audio_file_metadata, "Session", lambda engine: MockSessionContext())

    counts = backfill_audio_file_metadata.backfill_metadata(batch_size=1)
    assert counts["success"] == 1
    assert fake_setting.file_metadata is not None
    mock_session.commit.assert_called()


def test_backfill_metadata_missing_files(tmp_path: Path, monkeypatch) -> None:
    fake_rows = [(101, 999, "dir", "nonexistent.wav", 10)]

    mock_session = MagicMock()
    mock_session.exec.return_value.all.return_value = fake_rows

    monkeypatch.setattr(backfill_audio_file_metadata, "resolve_existing_audio_media_path", lambda c, d, f: None)

    class MockSessionContext:
        def __enter__(self):
            return mock_session
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(backfill_audio_file_metadata, "Session", lambda engine: MockSessionContext())

    counts = backfill_audio_file_metadata.backfill_metadata()
    assert counts["missing"] == 1


def test_backfill_metadata_parse_failed(tmp_path: Path, monkeypatch) -> None:
    bad_wav = tmp_path / "broken.wav"
    bad_wav.write_bytes(b"bad")

    fake_rows = [(101, 999, "dir", "broken.wav", 10)]
    mock_session = MagicMock()
    mock_session.exec.return_value.all.return_value = fake_rows

    monkeypatch.setattr(backfill_audio_file_metadata, "resolve_existing_audio_media_path", lambda c, d, f: bad_wav)
    monkeypatch.setattr(backfill_audio_file_metadata, "optimal_worker_count", lambda: 1)
    monkeypatch.setattr(backfill_audio_file_metadata, "_probe_and_extract_tags", lambda p, f: (None, []))

    class MockSessionContext:
        def __enter__(self):
            return mock_session
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(backfill_audio_file_metadata, "Session", lambda engine: MockSessionContext())

    counts = backfill_audio_file_metadata.backfill_metadata()
    assert counts["parse_failed"] == 1


def test_backfill_metadata_parallel(tmp_path: Path, monkeypatch) -> None:
    wav_path = tmp_path / "survey2.wav"
    _create_wav(wav_path)

    fake_setting = AudioSetting(audio_setting_id=888, file_metadata=None)
    fake_rows = [(102, 888, "dir", "survey2.wav", 10)]

    mock_session = MagicMock()
    mock_session.exec.return_value.all.return_value = fake_rows
    mock_session.get.return_value = fake_setting

    monkeypatch.setattr(backfill_audio_file_metadata, "resolve_existing_audio_media_path", lambda c, d, f: wav_path)
    monkeypatch.setattr(backfill_audio_file_metadata, "optimal_worker_count", lambda: 2)

    class MockSessionContext:
        def __enter__(self):
            return mock_session
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(backfill_audio_file_metadata, "Session", lambda engine: MockSessionContext())

    counts = backfill_audio_file_metadata.backfill_metadata(batch_size=1)
    assert counts["success"] == 1


def test_backfill_main_cli(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["backfill_audio_file_metadata.py", "--batch-size", "100"])
    monkeypatch.setattr(backfill_audio_file_metadata, "backfill_metadata", lambda batch_size: {"success": 5})
    backfill_audio_file_metadata.main()
