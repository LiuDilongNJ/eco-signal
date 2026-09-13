"""Unit tests for BatDetect2Analyzer using in-process Python API."""
import sys
import types
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ai.batdetect.analyzer import BatDetect2Analyzer
from app.core.task_cancellation import CancellationToken, TaskCancelledError


class TestBatDetect2Analyzer:
    """Tests for BatDetect2Analyzer."""

    def test_version_from_importlib(self):
        """Version is extracted using importlib.metadata.version."""
        with patch("app.ai.batdetect.analyzer.version", return_value="0.1.2"):
            analyzer = BatDetect2Analyzer()
            assert analyzer.version == "0.1.2"

    def test_version_fallback_on_exception(self):
        """Falls back to 'unknown' when version() raises PackageNotFoundError."""
        with patch("app.ai.batdetect.analyzer.version", side_effect=PackageNotFoundError):
            analyzer = BatDetect2Analyzer()
            assert analyzer.version == "unknown"

    def test_version_cached(self):
        """Version is cached after first access."""
        with patch("app.ai.batdetect.analyzer.version", return_value="1.0.0") as mock_version:
            analyzer = BatDetect2Analyzer()
            _ = analyzer.version
            _ = analyzer.version
            assert mock_version.call_count == 1

    def test_model_caching(self):
        """Model and parameters are cached in memory across multiple calls."""
        analyzer = BatDetect2Analyzer()
        mock_api = types.ModuleType("batdetect2.api")
        mock_api.load_model = MagicMock(return_value=("fake_model", {"class_names": ["Bat"]}))

        with patch.dict(sys.modules, {"batdetect2.api": mock_api}):
            model1, params1 = analyzer._get_model()
            model2, params2 = analyzer._get_model()

        assert model1 == "fake_model"
        assert params1 == {"class_names": ["Bat"]}
        assert model1 is model2
        assert params1 is params2
        assert mock_api.load_model.call_count == 1

    def test_analyze_success(self):
        """analyze() calls batdetect2 in-process API and parses detection results."""
        api_module = types.ModuleType("batdetect2.api")
        api_module.load_model = MagicMock(return_value=("model_obj", {"features": 128}))
        api_module.get_config = MagicMock(return_value={"configured": True})
        api_module.process_file = MagicMock(return_value={
            "pred_dict": {
                "annotation": [
                    {
                        "start_time": 1.5,
                        "end_time": 2.5,
                        "low_freq": 25000,
                        "high_freq": 45000,
                        "class": "Pipistrellus pipistrellus",
                        "det_prob": 0.95,
                    }
                ]
            }
        })
        batdetect2_module = types.ModuleType("batdetect2")
        batdetect2_module.api = api_module

        analyzer = BatDetect2Analyzer()
        with patch.dict(sys.modules, {"batdetect2": batdetect2_module, "batdetect2.api": api_module}):
            detections = analyzer.analyze(
                Path("test.wav"),
                detection_threshold=0.5,
                chunk_size=3.0,
            )

        api_module.get_config.assert_called_once_with(
            features=128,
            time_expansion=1,
            spec_slices=False,
            chunk_size=3.0,
            detection_threshold=0.5,
            quiet=True,
        )
        api_module.process_file.assert_called_once_with(
            "test.wav",
            "model_obj",
            config={"configured": True},
        )

        assert len(detections) == 1
        assert detections[0]["species"] == "Pipistrellus pipistrellus"
        assert detections[0]["confidence"] == 0.95
        assert detections[0]["start_time"] == 1.5
        assert detections[0]["end_time"] == 2.5
        assert detections[0]["min_freq"] == 25000.0
        assert detections[0]["max_freq"] == 45000.0

    def test_analyze_passes_max_duration(self):
        """analyze() forwards max_duration to batdetect2 get_config."""
        api_module = types.ModuleType("batdetect2.api")
        api_module.load_model = MagicMock(return_value=("model_obj", {"features": 64}))
        api_module.get_config = MagicMock(return_value={"configured": True})
        api_module.process_file = MagicMock(return_value={"pred_dict": {"annotation": []}})
        batdetect2_module = types.ModuleType("batdetect2")
        batdetect2_module.api = api_module

        analyzer = BatDetect2Analyzer()
        with patch.dict(sys.modules, {"batdetect2": batdetect2_module, "batdetect2.api": api_module}):
            detections = analyzer.analyze(
                Path("test.mp3"),
                detection_threshold=0.3,
                chunk_size=2.0,
                max_duration=101.5,
            )

        api_module.get_config.assert_called_once_with(
            features=64,
            time_expansion=1,
            spec_slices=False,
            chunk_size=2.0,
            detection_threshold=0.3,
            quiet=True,
            max_duration=101.5,
        )
        assert detections == []

    def test_analyze_all_audio_formats_direct(self):
        """All audio formats (WAV, FLAC, OGG, MP3) are analyzed directly without format conversion."""
        analyzer = BatDetect2Analyzer()
        api_module = types.ModuleType("batdetect2.api")
        api_module.load_model = MagicMock(return_value=("model", {}))
        api_module.get_config = MagicMock(return_value={})
        api_module.process_file = MagicMock(return_value={"pred_dict": {"annotation": []}})
        batdetect2_module = types.ModuleType("batdetect2")
        batdetect2_module.api = api_module

        with patch.dict(sys.modules, {"batdetect2": batdetect2_module, "batdetect2.api": api_module}):
            for audio_name in ("test.wav", "test.flac", "test.ogg", "test.mp3"):
                res = analyzer.analyze(Path(audio_name))
                assert res == []

        assert api_module.process_file.call_count == 4

    def test_analyze_not_installed_raises_runtime_error(self):
        """Raises RuntimeError when batdetect2 is not installed."""
        analyzer = BatDetect2Analyzer()
        with patch.dict(sys.modules, {"batdetect2": None, "batdetect2.api": None}):
            with pytest.raises(RuntimeError, match="batdetect2 not installed"):
                analyzer.analyze(Path("test.wav"))

    def test_analyze_failure_raises_runtime_error(self):
        """Raises RuntimeError when process_file raises an exception."""
        analyzer = BatDetect2Analyzer()
        api_module = types.ModuleType("batdetect2.api")
        api_module.load_model = MagicMock(return_value=("model", {}))
        api_module.get_config = MagicMock(return_value={})
        api_module.process_file = MagicMock(side_effect=RuntimeError("Corrupt audio stream"))
        batdetect2_module = types.ModuleType("batdetect2")
        batdetect2_module.api = api_module

        with patch.dict(sys.modules, {"batdetect2": batdetect2_module, "batdetect2.api": api_module}):
            with pytest.raises(RuntimeError, match="batdetect2 failed: Corrupt audio stream"):
                analyzer.analyze(Path("test.wav"))

    def test_analyze_cancellation_token(self):
        """Raises TaskCancelledError when cancellation token is triggered."""
        analyzer = BatDetect2Analyzer()
        token = CancellationToken()
        token.cancel()

        api_module = types.ModuleType("batdetect2.api")
        api_module.load_model = MagicMock(return_value=("model", {}))
        batdetect2_module = types.ModuleType("batdetect2")
        batdetect2_module.api = api_module

        with patch.dict(sys.modules, {"batdetect2": batdetect2_module, "batdetect2.api": api_module}):
            with pytest.raises(TaskCancelledError):
                analyzer.analyze(Path("test.wav"), cancellation_token=token)

    def test_ensure_optimal_torch_threads(self):
        """_ensure_optimal_torch_threads sets PyTorch threads based on env var."""
        from app.ai.batdetect.analyzer import _ensure_optimal_torch_threads

        mock_torch = MagicMock()
        mock_torch.get_num_threads.return_value = 8
        with patch.dict(sys.modules, {"torch": mock_torch}), patch.dict("os.environ", {"TORCH_NUM_THREADS": "2"}):
            _ensure_optimal_torch_threads()
            mock_torch.set_num_threads.assert_called_once_with(2)

