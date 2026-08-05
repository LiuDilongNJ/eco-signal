"""Unit tests for BatDetect2Analyzer."""
import subprocess
import sys
import types
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ai.batdetect.analyzer import BatDetect2Analyzer


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

    @patch("shutil.copy")
    @patch("app.ai.batdetect.analyzer.run_cancellable_process")
    def test_analyze_success(self, mock_run, mock_copy):
        """analyze() calls batdetect2 and parses results."""
        mock_run.return_value = MagicMock(returncode=0)
        
        # We need to ensure the CSV file is "created" so _parse_csv can read it
        detections_csv_content = [
            ["id", "detection_prob", "start_time", "end_time", "high_freq", "low_freq", "class_name"],
            ["0", "0.95", "1.5", "2.5", "45000", "25000", "Pipistrellus_pipistrellus"]
        ]
        
        analyzer = BatDetect2Analyzer()
        
        # Mocking open to return our CSV content
        with patch("builtins.open", MagicMock()):
            with patch("csv.reader", return_value=iter(detections_csv_content)):
                # Mock Path.exists to return True for our CSV
                with patch.object(Path, "exists", return_value=True):
                    detections = analyzer.analyze(Path("test.wav"), detection_threshold=0.5)
        
        assert len(detections) == 1
        assert detections[0]["species"] == "Pipistrellus_pipistrellus"
        assert detections[0]["confidence"] == 0.95
        assert detections[0]["start_time"] == 1.5

    @patch("shutil.copy")
    @patch("app.ai.batdetect.analyzer.run_cancellable_process")
    def test_analyze_uses_default_cli_args(self, mock_run, mock_copy):
        """analyze() uses input, output, and threshold for default options."""
        mock_run.return_value = MagicMock(returncode=0)
        
        analyzer = BatDetect2Analyzer()
        
        with patch.object(Path, "exists", return_value=False): # No CSV case
            detections = analyzer.analyze(Path("test.wav"), detection_threshold=0.4)
        
        assert detections == []
        cmd = mock_run.call_args[0][0]
        assert cmd[:2] == ["batdetect2", "detect"]
        assert cmd[-3:] == ["0.4", "--chunk_size", "2.0"]

    @patch("shutil.copy")
    @patch("app.ai.batdetect.analyzer.run_cancellable_process")
    def test_analyze_uses_custom_cli_args_when_provided(self, mock_run, mock_copy):
        """Custom parameters are passed only when explicitly provided."""
        mock_run.return_value = MagicMock(returncode=0)

        analyzer = BatDetect2Analyzer()

        with patch.object(Path, "exists", return_value=False):
            detections = analyzer.analyze(
                Path("test.wav"),
                detection_threshold=0.4,
                chunk_size=5,
            )

        assert detections == []
        cmd = mock_run.call_args[0][0]
        assert cmd[-2:] == ["--chunk_size", "5"]

    @patch("app.ai.batdetect.analyzer.run_cancellable_process")
    def test_analyze_flac_uses_python_api(self, mock_run):
        """FLAC files should bypass the CLI directory scanner and use process_file."""
        api_module = types.ModuleType("batdetect2.api")
        api_module.load_model = MagicMock(return_value=("model", {"class_names": ["Bat"]}))
        api_module.get_config = MagicMock(return_value={"config": True})
        api_module.process_file = MagicMock(return_value={
            "pred_dict": {
                "annotation": [
                    {
                        "start_time": 1.0,
                        "end_time": 1.2,
                        "low_freq": 25000,
                        "high_freq": 45000,
                        "class": "Pipistrellus pipistrellus",
                        "det_prob": 0.91,
                    }
                ]
            }
        })
        batdetect2_module = types.ModuleType("batdetect2")
        batdetect2_module.api = api_module

        analyzer = BatDetect2Analyzer()
        with patch.dict(sys.modules, {"batdetect2": batdetect2_module, "batdetect2.api": api_module}):
            detections = analyzer.analyze(Path("test.flac"), detection_threshold=0.4, chunk_size=5)

        mock_run.assert_not_called()
        api_module.process_file.assert_called_once_with("test.flac", "model", config={"config": True})
        api_module.get_config.assert_called_once()
        assert detections == [
            {
                "start_time": 1.0,
                "end_time": 1.2,
                "min_freq": 25000.0,
                "max_freq": 45000.0,
                "species": "Pipistrellus pipistrellus",
                "confidence": 0.91,
            }
        ]

    @patch("shutil.copy")
    @patch("app.ai.batdetect.analyzer.run_cancellable_process")
    def test_analyze_failure(self, mock_run, mock_copy):
        """analyze() raises RuntimeError if batdetect2 fails."""
        mock_run.return_value = MagicMock(returncode=1, stderr="Low memory")
        
        analyzer = BatDetect2Analyzer()
        with pytest.raises(RuntimeError, match="batdetect2 failed: Low memory"):
            analyzer.analyze(Path("test.wav"))

    @patch("shutil.copy")
    @patch("app.ai.batdetect.analyzer.run_cancellable_process")
    def test_analyze_timeout(self, mock_run, mock_copy):
        """analyze() raises ModelDownloadError on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="batdetect2", timeout=300)
        
        analyzer = BatDetect2Analyzer()
        from app.ai.exceptions import ModelDownloadError
        with pytest.raises(ModelDownloadError, match="batdetect2 timed out"):
            analyzer.analyze(Path("test.wav"))

    @patch("shutil.copy")
    @patch("app.ai.batdetect.analyzer.run_cancellable_process")
    def test_analyze_not_installed(self, mock_run, mock_copy):
        """analyze() raises RuntimeError if batdetect2 is not found."""
        mock_run.side_effect = FileNotFoundError()
        
        analyzer = BatDetect2Analyzer()
        with pytest.raises(RuntimeError, match="batdetect2 not installed"):
            analyzer.analyze(Path("test.wav"))

    def test_parse_csv_invalid_row(self):
        """_parse_csv skips invalid or short rows."""
        analyzer = BatDetect2Analyzer()
        
        csv_content = [
            ["id", "prob", "start", "end", "high", "low", "class"],
            ["0", "invalid", "1.5", "2.5", "45000", "25000", "Bat"], # ValueError on float
            ["1"] # Too short
        ]
        
        with patch("builtins.open", MagicMock()):
            with patch("csv.reader", return_value=iter(csv_content)):
                results = analyzer._parse_csv(Path("fake.csv"))
        
        assert results == []
