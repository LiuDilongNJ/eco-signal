"""Unit tests for InsectAnalyzer - insects-base-cnn10-96k-t model wrapper."""
import csv
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ai.insects.analyzer import (
    HF_MODEL_ID,
    INSECT_MAX_FREQ,
    INSECT_MIN_FREQ,
    SAMPLE_RATE,
    InsectAnalyzer,
)


# Helpers

def _write_results_csv(path: Path, rows: list[dict]) -> None:
    """Write a mock results.csv file for testing parsing."""
    if not rows:
        return
    # Collect all unique field names across all rows
    all_fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                all_fields.append(key)
                seen.add(key)
    with open(path / "results.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# InsectAnalyzer unit tests

from importlib.metadata import PackageNotFoundError

class TestInsectAnalyzerVersion:
    """Tests for version detection."""

    def test_version_from_importlib(self):
        """Version is extracted using importlib.metadata.version."""
        with patch("app.ai.insects.analyzer.version", return_value="0.5.1"):
            analyzer = InsectAnalyzer()
            assert analyzer.version == "0.5.1"

    def test_version_fallback_on_exception(self):
        """Falls back to 'unknown' when version() raises PackageNotFoundError."""
        with patch("app.ai.insects.analyzer.version", side_effect=PackageNotFoundError):
            analyzer = InsectAnalyzer()
            assert analyzer.version == "unknown"

    def test_version_cached(self):
        """Version property is lazy-loaded and cached on second access."""
        with patch("app.ai.insects.analyzer.version", return_value="1.0.0") as mock_version:
            analyzer = InsectAnalyzer()
            _ = analyzer.version
            _ = analyzer.version  # second access should not call version() again
            assert mock_version.call_count == 1


class TestInsectAnalyzerAnalyze:
    """Tests for the analyze() method."""

    def _mock_success_run(self, output_dir: Path):
        """Return a subprocess mock that writes a results.csv in output_dir."""
        rows = [
            {
                "filename": "test.wav",
                "offset": "0.0-4.0",
                "prediction": "['Gryllus campestris']",
                "Gryllus campestris": "0.87",
            },
        ]
        _write_results_csv(output_dir, rows)
        mock_result = MagicMock()
        mock_result.returncode = 0
        return mock_result

    def test_calls_autrainer_with_correct_args(self):
        """analyze() calls autrainer inference with the correct CLI arguments."""
        analyzer = InsectAnalyzer()

        captured_cmd: list[list] = []

        def fake_run(cmd, **kwargs):
            captured_cmd.append(cmd)
            # Create the expected results.csv in output dir
            output_dir = Path(cmd[-1])
            rows = [{"filename": "a.wav", "offset": "0.0-4.0", "prediction": "['Gryllus campestris']", "Gryllus campestris": "0.9"}]
            _write_results_csv(output_dir, rows)
            m = MagicMock()
            m.returncode = 0
            return m

        with patch("app.ai.insects.analyzer.run_cancellable_process", side_effect=fake_run):
            with tempfile.NamedTemporaryFile(suffix=".wav") as f:
                analyzer.analyze(Path(f.name), window_size=4.0, stride_length=2.0)

        assert len(captured_cmd) == 1
        cmd = captured_cmd[0]
        assert cmd[0] == "autrainer"
        assert cmd[1] == "inference"
        assert cmd[2] == HF_MODEL_ID
        assert "-sr" in cmd
        assert str(SAMPLE_RATE) in cmd
        assert "-w" in cmd
        assert "4.0" in cmd
        assert "-s" in cmd
        assert "2.0" in cmd
        assert "-e" not in cmd

    def test_prefers_cached_model_and_enables_offline_mode(self):
        """Execution should use a cached local model when available."""
        analyzer = InsectAnalyzer()

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env", {})
            output_dir = Path(cmd[-1])
            rows = [{"filename": "a.wav", "offset": "0.0-4.0", "prediction": "['Gryllus campestris']", "Gryllus campestris": "0.9"}]
            _write_results_csv(output_dir, rows)
            m = MagicMock()
            m.returncode = 0
            return m

        with patch("app.ai.insects.analyzer.run_cancellable_process", side_effect=fake_run):
            with patch.object(analyzer, "_resolve_model_spec", return_value=("/cached/model", {"HF_HUB_OFFLINE": "1"})):
                with tempfile.NamedTemporaryFile(suffix=".wav") as f:
                    analyzer.analyze(Path(f.name))

        assert captured["cmd"][2] == "/cached/model"
        assert captured["env"]["HF_HUB_OFFLINE"] == "1"

    def test_flac_uses_extension_argument(self):
        """FLAC inputs should keep their extension and pass -e flac to autrainer."""
        analyzer = InsectAnalyzer()
        captured_cmd: list[list] = []

        def fake_run(cmd, **kwargs):
            captured_cmd.append(cmd)
            input_dir = Path(cmd[-2])
            assert any(path.suffix == ".flac" for path in input_dir.iterdir())
            output_dir = Path(cmd[-1])
            rows = [{"filename": "a.flac", "offset": "0.0-4.0", "prediction": "['Gryllus campestris']", "Gryllus campestris": "0.9"}]
            _write_results_csv(output_dir, rows)
            m = MagicMock()
            m.returncode = 0
            return m

        with patch("app.ai.insects.analyzer.run_cancellable_process", side_effect=fake_run):
            with tempfile.NamedTemporaryFile(suffix=".flac") as f:
                analyzer.analyze(Path(f.name))

        cmd = captured_cmd[0]
        extension_index = cmd.index("-e")
        assert cmd[extension_index + 1] == "flac"

    def test_returns_detections_from_csv(self):
        """analyze() parses results.csv and returns detection dicts."""
        analyzer = InsectAnalyzer()

        def fake_run(cmd, **kwargs):
            output_dir = Path(cmd[-1])
            rows = [
                {
                    "filename": "test.wav",
                    "offset": "0.0-4.0",
                    "prediction": "['Gryllus campestris']",
                    "Gryllus campestris": "0.87",
                },
                {
                    "filename": "test.wav",
                    "offset": "4.0-8.0",
                    "prediction": "['Tettigonia viridissima']",
                    "Tettigonia viridissima": "0.72",
                },
            ]
            _write_results_csv(output_dir, rows)
            m = MagicMock()
            m.returncode = 0
            return m

        with patch("app.ai.insects.analyzer.run_cancellable_process", side_effect=fake_run):
            with tempfile.NamedTemporaryFile(suffix=".wav") as f:
                detections = analyzer.analyze(Path(f.name))

        assert len(detections) == 2
        # Sorted by confidence descending
        assert detections[0]["species"] == "Gryllus campestris"
        assert detections[0]["confidence"] == pytest.approx(0.87)
        assert detections[0]["start_time"] == 0.0
        assert detections[0]["end_time"] == 4.0
        assert detections[0]["min_freq"] == INSECT_MIN_FREQ
        assert detections[0]["max_freq"] == INSECT_MAX_FREQ

    def test_returns_empty_list_when_no_csv(self):
        """If autrainer produces no results.csv, an empty list is returned."""
        analyzer = InsectAnalyzer()

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            return m  # No CSV written

        with patch("app.ai.insects.analyzer.run_cancellable_process", side_effect=fake_run):
            with tempfile.NamedTemporaryFile(suffix=".wav") as f:
                detections = analyzer.analyze(Path(f.name))

        assert detections == []

    def test_raises_on_nonzero_returncode(self):
        """RuntimeError is raised when autrainer exits with non-zero code."""
        analyzer = InsectAnalyzer()

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 1
            m.stderr = "Model download failed"
            return m

        with patch("app.ai.insects.analyzer.run_cancellable_process", side_effect=fake_run):
            from app.ai.exceptions import ModelDownloadError
            with pytest.raises(ModelDownloadError, match="autrainer model download failed"):
                with tempfile.NamedTemporaryFile(suffix=".wav") as f:
                    analyzer.analyze(Path(f.name))

    def test_raises_when_autrainer_not_installed(self):
        """RuntimeError is raised when autrainer is not found."""
        analyzer = InsectAnalyzer()
        with patch("app.ai.insects.analyzer.run_cancellable_process", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="autrainer is not installed"):
                with tempfile.NamedTemporaryFile(suffix=".wav") as f:
                    analyzer.analyze(Path(f.name))

    def test_raises_on_timeout(self):
        """ModelDownloadError is raised on subprocess timeout."""
        analyzer = InsectAnalyzer()
        with patch("app.ai.insects.analyzer.run_cancellable_process", side_effect=subprocess.TimeoutExpired(cmd="autrainer", timeout=600)):
            from app.ai.exceptions import ModelDownloadError
            with pytest.raises(ModelDownloadError, match="timed out"):
                with tempfile.NamedTemporaryFile(suffix=".wav") as f:
                    analyzer.analyze(Path(f.name))


class TestInsectAnalyzerParseCsv:
    """Tests for _parse_csv() logic."""

    def _make_analyzer(self) -> InsectAnalyzer:
        return InsectAnalyzer()

    def test_skips_majority_row(self):
        """Rows with offset='majority' are skipped."""
        analyzer = self._make_analyzer()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            rows = [
                {
                    "filename": "a.wav",
                    "offset": "0.0-4.0",
                    "prediction": "['Gryllus campestris']",
                    "Gryllus campestris": "0.9",
                },
                {
                    "filename": "a.wav",
                    "offset": "majority",
                    "prediction": "['Gryllus campestris']",
                    "Gryllus campestris": "0.9",
                },
            ]
            _write_results_csv(path, rows)
            results = analyzer._parse_csv(path / "results.csv")

        assert len(results) == 1
        assert results[0]["start_time"] == 0.0

    def test_skips_empty_prediction(self):
        """Rows with prediction='[]' produce no detections."""
        analyzer = self._make_analyzer()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            rows = [
                {"filename": "a.wav", "offset": "0.0-4.0", "prediction": "[]"},
            ]
            _write_results_csv(path, rows)
            results = analyzer._parse_csv(path / "results.csv")

        assert results == []

    def test_skips_invalid_offset(self):
        """Rows with unparseable offset are skipped."""
        analyzer = self._make_analyzer()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            rows = [
                {
                    "filename": "a.wav",
                    "offset": "bad-offset-format",
                    "prediction": "['Gryllus campestris']",
                    "Gryllus campestris": "0.9",
                },
            ]
            _write_results_csv(path, rows)
            results = analyzer._parse_csv(path / "results.csv")

        assert results == []

    def test_skips_negative_start_time(self):
        """Rows where start_time < 0 are skipped."""
        analyzer = self._make_analyzer()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            rows = [
                {
                    "filename": "a.wav",
                    "offset": "-1.0-3.0",
                    "prediction": "['Gryllus campestris']",
                    "Gryllus campestris": "0.9",
                },
            ]
            _write_results_csv(path, rows)
            results = analyzer._parse_csv(path / "results.csv")

        assert results == []

    def test_skips_end_before_start(self):
        """Rows where end_time <= start_time are skipped."""
        analyzer = self._make_analyzer()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            rows = [
                {
                    "filename": "a.wav",
                    "offset": "4.0-2.0",
                    "prediction": "['Gryllus campestris']",
                    "Gryllus campestris": "0.9",
                },
            ]
            _write_results_csv(path, rows)
            results = analyzer._parse_csv(path / "results.csv")

        assert results == []

    def test_multiple_species_in_one_row(self):
        """A row with multiple predicted species produces multiple detections."""
        analyzer = self._make_analyzer()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            rows = [
                {
                    "filename": "a.wav",
                    "offset": "0.0-4.0",
                    "prediction": "['Gryllus campestris', 'Tettigonia viridissima']",
                    "Gryllus campestris": "0.85",
                    "Tettigonia viridissima": "0.60",
                },
            ]
            _write_results_csv(path, rows)
            results = analyzer._parse_csv(path / "results.csv")

        assert len(results) == 2
        species_names = {r["species"] for r in results}
        assert "Gryllus campestris" in species_names
        assert "Tettigonia viridissima" in species_names

    def test_results_preserve_source_prediction_order(self):
        """Results should keep the source row and prediction order."""
        analyzer = self._make_analyzer()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            rows = [
                {
                    "filename": "a.wav",
                    "offset": "0.0-4.0",
                    "prediction": "['Species A', 'Species B']",
                    "Species A": "0.50",
                    "Species B": "0.90",
                },
            ]
            _write_results_csv(path, rows)
            results = analyzer._parse_csv(path / "results.csv")

        assert results[0]["species"] == "Species A"
        assert results[0]["confidence"] == 0.5
        assert results[1]["species"] == "Species B"
        assert results[1]["confidence"] == 0.9
