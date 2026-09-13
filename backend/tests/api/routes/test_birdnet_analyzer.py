"""Unit tests for BirdNETAnalyzer using in-process Python runtime."""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ai.birdnet.analyzer import BirdNETAnalyzer
from app.core.task_cancellation import CancellationToken, TaskCancelledError


class TestBirdNETAnalyzer:
    """Tests for BirdNETAnalyzer."""

    def test_version(self):
        analyzer = BirdNETAnalyzer()
        assert analyzer.version == "2.4"

    def test_analyze_invokes_birdnet_analyzer_and_parses_csv(self):
        """analyze() calls in-process birdnet_analyze and parses result CSV."""
        captured_kwargs: dict = {}

        def fake_birdnet_analyze(**kwargs):
            captured_kwargs.update(kwargs)
            out_dir = Path(kwargs["output"])
            # The analyzer expects output CSV named {audio_path.stem}.BirdNET.results.csv
            csv_path = out_dir / "test.BirdNET.results.csv"
            csv_path.write_text(
                "Start (s),End (s),Scientific name,Common name,Confidence,File\n"
                "0.0,3.0,Turdus merula,Common Blackbird,0.85,/fake/test.wav\n"
                "3.0,6.0,Parus major,Great Tit,0.92,/fake/test.wav\n",
                encoding="utf-8",
            )

        birdnet_module = types.ModuleType("birdnet_analyzer")
        birdnet_module.analyze = fake_birdnet_analyze

        analyzer = BirdNETAnalyzer()
        with patch.dict(sys.modules, {"birdnet_analyzer": birdnet_module}):
            detections = analyzer.analyze(
                Path("test.wav"),
                min_confidence=0.5,
                overlap=1.0,
                sensitivity=1.2,
                sf_thresh=0.05,
                lat=31.23,
                lon=121.47,
                week=15,
                locale="zh",
                top_n=5,
            )

        assert captured_kwargs["audio_input"] == "test.wav"
        assert captured_kwargs["min_conf"] == 0.5
        assert captured_kwargs["overlap"] == 1.0
        assert captured_kwargs["sensitivity"] == 1.2
        assert captured_kwargs["sf_thresh"] == 0.05
        assert captured_kwargs["lat"] == 31.23
        assert captured_kwargs["lon"] == 121.47
        assert captured_kwargs["week"] == 15
        assert captured_kwargs["locale"] == "zh"
        assert captured_kwargs["top_n"] == 5
        assert captured_kwargs["rtype"] == "csv"
        assert captured_kwargs["threads"] == 1

        assert len(detections) == 2
        assert detections[0] == {
            "start_time": 0.0,
            "end_time": 3.0,
            "species": "Turdus merula",
            "confidence": 0.85,
        }
        assert detections[1] == {
            "start_time": 3.0,
            "end_time": 6.0,
            "species": "Parus major",
            "confidence": 0.92,
        }

    def test_species_list_writes_file_and_passes_slist(self):
        """When species_list is provided, it is saved to a file and slist is passed."""
        captured_kwargs: dict = {}

        def fake_birdnet_analyze(**kwargs):
            captured_kwargs.update(kwargs)
            slist_path = Path(kwargs["slist"])
            assert slist_path.read_text(encoding="utf-8") == "Species A\nSpecies B"

        birdnet_module = types.ModuleType("birdnet_analyzer")
        birdnet_module.analyze = fake_birdnet_analyze

        analyzer = BirdNETAnalyzer()
        with patch.dict(sys.modules, {"birdnet_analyzer": birdnet_module}):
            detections = analyzer.analyze(
                Path("test.wav"),
                species_list=["Species A", "Species B"],
            )

        assert captured_kwargs["lat"] == -1
        assert captured_kwargs["lon"] == -1
        assert captured_kwargs["slist"] is not None
        assert detections == []

    def test_analyze_all_formats_direct(self):
        """FLAC, MP3, OGG, WAV are all passed directly to birdnet_analyzer."""
        captured_inputs: list[str] = []

        def fake_birdnet_analyze(**kwargs):
            captured_inputs.append(kwargs["audio_input"])

        birdnet_module = types.ModuleType("birdnet_analyzer")
        birdnet_module.analyze = fake_birdnet_analyze

        analyzer = BirdNETAnalyzer()
        with patch.dict(sys.modules, {"birdnet_analyzer": birdnet_module}):
            for audio_name in ("song.flac", "song.mp3", "song.ogg", "song.wav"):
                analyzer.analyze(Path(audio_name))

        assert captured_inputs == ["song.flac", "song.mp3", "song.ogg", "song.wav"]

    def test_analyze_not_installed_raises_runtime_error(self):
        """Raises RuntimeError if birdnet_analyzer cannot be imported."""
        analyzer = BirdNETAnalyzer()
        with patch.dict(sys.modules, {"birdnet_analyzer": None}):
            with pytest.raises(RuntimeError, match="birdnet_analyzer is required to run BirdNET"):
                analyzer.analyze(Path("test.wav"))

    def test_analyze_failure_raises_runtime_error(self):
        """Raises RuntimeError if birdnet_analyze encounters an unhandled exception."""
        birdnet_module = types.ModuleType("birdnet_analyzer")
        birdnet_module.analyze = MagicMock(side_effect=ValueError("Invalid audio sample rate"))

        analyzer = BirdNETAnalyzer()
        with patch.dict(sys.modules, {"birdnet_analyzer": birdnet_module}):
            with pytest.raises(RuntimeError, match="BirdNET analysis failed: Invalid audio sample rate"):
                analyzer.analyze(Path("test.wav"))

    def test_analyze_cancellation_token(self):
        """Raises TaskCancelledError when cancellation token is triggered."""
        analyzer = BirdNETAnalyzer()
        token = CancellationToken()
        token.cancel()

        birdnet_module = types.ModuleType("birdnet_analyzer")
        birdnet_module.analyze = MagicMock()

        with patch.dict(sys.modules, {"birdnet_analyzer": birdnet_module}):
            with pytest.raises(TaskCancelledError):
                analyzer.analyze(Path("test.wav"), cancellation_token=token)

        birdnet_module.analyze.assert_not_called()
