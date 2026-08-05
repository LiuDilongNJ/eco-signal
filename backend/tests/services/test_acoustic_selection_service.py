from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.acoustic_selection_service import prepare_acoustic_selection


def test_full_unfiltered_selection_reuses_source(tmp_path: Path):
    source = tmp_path / "audio.flac"
    source.write_bytes(b"flac")
    info = MagicMock(frames=48000, samplerate=48000)

    with patch("app.services.acoustic_selection_service.sf.info", return_value=info):
        result = prepare_acoustic_selection(
            source,
            media_id=1,
            min_time=0,
            max_time=1,
            min_frequency=1,
            max_frequency=24000,
            filter_enabled=False,
        )

    assert result == source.resolve()


def test_selected_audio_keeps_source_extension(tmp_path: Path):
    source = tmp_path / "audio.flac"
    source.write_bytes(b"flac")
    info = MagicMock(frames=480000, samplerate=48000)

    with patch("app.services.acoustic_selection_service.sf.info", return_value=info), patch(
        "app.services.acoustic_selection_service._cache_root", return_value=tmp_path / "cache"
    ), patch("app.services.acoustic_selection_service.subprocess.run") as run:
        (tmp_path / "cache").mkdir()

        def create_output(command, **_kwargs):
            Path(command[2]).write_bytes(b"selected")

        run.side_effect = create_output
        result = prepare_acoustic_selection(
            source,
            media_id=1,
            min_time=1,
            max_time=5,
            min_frequency=100,
            max_frequency=8000,
            filter_enabled=True,
        )

    assert result.suffix == ".flac"
    command = run.call_args.args[0]
    assert command[:2] == ["sox", str(source.resolve())]
    assert "trim" in command
    assert "sinc" in command
