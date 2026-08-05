"""Unit tests for the BirdNET analyzer subprocess wrapper."""
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ai.birdnet.analyzer import BirdNETAnalyzer
from app.ai.exceptions import ModelDownloadError


class TestBirdNETAnalyzer:
    def test_version(self):
        analyzer = BirdNETAnalyzer()
        assert analyzer.version == "2.4"

    def test_official_runtime_exposes_supported_cli_parameters(self):
        result = subprocess.run(
            [sys.executable, "-m", "birdnet_analyzer.analyze", "--help"],
            check=True,
            capture_output=True,
            text=True,
        )

        assert "--top_n" in result.stdout
        assert "--birdnet" not in result.stdout

    @patch("subprocess.Popen")
    def test_analyze_invokes_official_birdnet_analyzer_and_parses_csv(self, mock_popen):
        process = MagicMock()
        process.returncode = 0

        def fake_popen(cmd, **_kwargs):
            output_dir = Path(cmd[cmd.index("-o") + 1])
            output_path = output_dir / "test.BirdNET.results.csv"
            output_path.write_text(
                "Start (s),End (s),Scientific name,Common name,Confidence,File\n"
                "0.0,3.0,Alpha beta,,0.85,/fake/test.wav\n",
                encoding="utf-8",
            )
            process.communicate.return_value = ("", "")
            return process

        mock_popen.side_effect = fake_popen
        detections = BirdNETAnalyzer().analyze(
            Path("test.wav"),
            min_confidence=0.5,
            overlap=1.0,
            sensitivity=1.2,
            sf_thresh=0.05,
            lat=1.0,
            lon=2.0,
            week=12,
            locale="zh",
            top_n=3,
        )

        assert detections == [
            {
                "start_time": 0.0,
                "end_time": 3.0,
                "species": "Alpha beta",
                "confidence": 0.85,
            }
        ]
        cmd = mock_popen.call_args.args[0]
        assert cmd[:3] == [sys.executable, "-m", "birdnet_analyzer.analyze"]
        assert cmd[3] == "test.wav"
        assert mock_popen.call_args.kwargs["start_new_session"] is True
        assert "--birdnet" not in cmd
        assert cmd[cmd.index("--rtype") + 1] == "csv"
        assert "--fmin" not in cmd
        assert "--fmax" not in cmd
        assert cmd[cmd.index("--min_conf") + 1] == "0.5"
        assert cmd[cmd.index("--overlap") + 1] == "1.0"
        assert cmd[cmd.index("--sensitivity") + 1] == "1.2"
        assert cmd[cmd.index("--sf_thresh") + 1] == "0.05"
        assert cmd[cmd.index("--lat") + 1] == "1.0"
        assert cmd[cmd.index("--lon") + 1] == "2.0"
        assert cmd[cmd.index("--week") + 1] == "12"
        assert cmd[cmd.index("--locale") + 1] == "zh"
        assert cmd[cmd.index("--top_n") + 1] == "3"

    @patch("subprocess.Popen")
    def test_species_list_uses_slist_and_skips_coordinates(self, mock_popen):
        process = MagicMock()
        process.returncode = 0

        def fake_popen(cmd, **_kwargs):
            species_path = Path(cmd[cmd.index("--slist") + 1])
            assert species_path.read_text(encoding="utf-8") == "Alpha beta\nGamma delta"
            output_dir = Path(cmd[cmd.index("-o") + 1])
            output_path = output_dir / "test.BirdNET.results.csv"
            output_path.write_text(
                "Start (s),End (s),Scientific name,Common name,Confidence,File\n",
                encoding="utf-8",
            )
            process.communicate.return_value = ("", "")
            return process

        mock_popen.side_effect = fake_popen
        detections = BirdNETAnalyzer().analyze(
            Path("test.wav"),
            species_list=["Alpha beta", "Gamma delta"],
            lat=1.0,
            lon=2.0,
        )

        assert detections == []
        cmd = mock_popen.call_args.args[0]
        assert "--slist" in cmd
        assert "--lat" not in cmd
        assert "--lon" not in cmd

    @patch("subprocess.Popen")
    def test_analyze_passes_flac_path_to_cli(self, mock_popen):
        """FLAC inputs should be passed directly to the BirdNET CLI."""
        process = MagicMock()
        process.returncode = 0

        def fake_popen(cmd, **_kwargs):
            output_dir = Path(cmd[cmd.index("-o") + 1])
            output_path = output_dir / "test.BirdNET.results.csv"
            output_path.write_text(
                "Start (s),End (s),Scientific name,Common name,Confidence,File\n",
                encoding="utf-8",
            )
            process.communicate.return_value = ("", "")
            return process

        mock_popen.side_effect = fake_popen

        BirdNETAnalyzer().analyze(Path("/fake/test.flac"))

        cmd = mock_popen.call_args.args[0]
        assert cmd[3] == "/fake/test.flac"
        assert "--top_n" not in cmd

    @patch("subprocess.Popen")
    def test_cli_download_failure_is_retriable(self, mock_popen):
        process = MagicMock()
        process.returncode = 1
        process.communicate.return_value = ("", "network download timeout")
        mock_popen.return_value = process

        with pytest.raises(ModelDownloadError):
            BirdNETAnalyzer().analyze(Path("test.wav"))

    @patch("subprocess.Popen")
    def test_cli_runtime_failure_raises_runtime_error(self, mock_popen):
        process = MagicMock()
        process.returncode = 1
        process.communicate.return_value = ("", "bad audio")
        mock_popen.return_value = process

        with pytest.raises(RuntimeError, match="BirdNET CLI failed"):
            BirdNETAnalyzer().analyze(Path("test.wav"))

    @patch("app.ai.birdnet.analyzer.os.killpg")
    @patch("subprocess.Popen")
    def test_cli_timeout_terminates_process_group(self, mock_popen, mock_killpg):
        process = MagicMock()
        process.pid = 123
        process.poll.return_value = None
        process.communicate.side_effect = subprocess.TimeoutExpired(["python3"], 1)
        process.wait.return_value = None
        mock_popen.return_value = process

        with pytest.raises(ModelDownloadError):
            BirdNETAnalyzer().analyze(Path("test.wav"))

        mock_killpg.assert_called()
