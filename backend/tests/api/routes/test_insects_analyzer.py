"""Unit tests for InsectAnalyzer - insect sound recognition using in-process autrainer."""
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ai.insects.analyzer import (
    INSECT_MAX_FREQ,
    INSECT_MIN_FREQ,
    SAMPLE_RATE,
    InsectAnalyzer,
)
from app.core.task_cancellation import CancellationToken, TaskCancelledError


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
            _ = analyzer.version
            assert mock_version.call_count == 1


class TestInsectAnalyzerResolveModelPath:
    """Tests for _resolve_model_path."""

    def test_resolve_model_path_finds_valid_directory(self, tmp_path):
        """Returns the first candidate directory containing model.yaml."""
        analyzer = InsectAnalyzer()
        candidate = tmp_path / "model_candidate"
        candidate.mkdir()
        (candidate / "model.yaml").write_text("model: test")

        with patch("app.ai.insects.analyzer.CACHED_MODEL_PATHS", [candidate]):
            resolved = analyzer._resolve_model_path()

        assert resolved == str(candidate)

    def test_resolve_model_path_fallback(self, tmp_path):
        """Prepares model and returns target path if none initially exist with model.yaml."""
        analyzer = InsectAnalyzer()
        fallback = tmp_path / "fallback"

        with patch("app.ai.insects.analyzer.CACHED_MODEL_PATHS", [fallback]):
            with patch("scripts.setup_insects_model.prepare_insects_model") as mock_prep:
                with patch("scripts.setup_insects_model.check_insects_files", return_value=True):
                    resolved = analyzer._resolve_model_path()

        assert resolved == str(fallback)
        mock_prep.assert_called_once_with(fallback)


class TestInsectAnalyzerInferenceCaching:
    """Tests for _get_inference caching."""

    def test_inference_caching(self):
        """_get_inference caches instances by (model_path, window_size, stride_length, sample_rate)."""
        analyzer = InsectAnalyzer()
        mock_inf_cls = MagicMock(side_effect=[MagicMock(), MagicMock()])

        with patch.dict("sys.modules", {"autrainer.serving": MagicMock(Inference=mock_inf_cls)}):
            inf1 = analyzer._get_inference("/models/insects", 4.0, 4.0, 96000)
            inf2 = analyzer._get_inference("/models/insects", 4.0, 4.0, 96000)
            assert inf1 is inf2
            assert mock_inf_cls.call_count == 1

            # Different window size creates a new instance
            inf3 = analyzer._get_inference("/models/insects", 2.0, 2.0, 96000)
            assert inf3 is not inf1
            assert mock_inf_cls.call_count == 2


class TestInsectAnalyzerParsePredictions:
    """Tests for _parse_predictions logic."""

    def test_parse_predictions_valid(self):
        """Parses prediction and probability maps into detection dicts."""
        analyzer = InsectAnalyzer()
        predictions = {
            "0.00-4.00": ["Gryllus campestris"],
            "4.00-8.00": ["Tettigonia viridissima"],
        }
        probabilities = {
            "0.00-4.00": {"Gryllus campestris": 0.88},
            "4.00-8.00": {"Tettigonia viridissima": 0.76},
        }

        detections = analyzer._parse_predictions(predictions, probabilities)

        assert len(detections) == 2
        assert detections[0] == {
            "start_time": 0.0,
            "end_time": 4.0,
            "species": "Gryllus campestris",
            "confidence": pytest.approx(0.88),
            "min_freq": INSECT_MIN_FREQ,
            "max_freq": INSECT_MAX_FREQ,
        }
        assert detections[1] == {
            "start_time": 4.0,
            "end_time": 8.0,
            "species": "Tettigonia viridissima",
            "confidence": pytest.approx(0.76),
            "min_freq": INSECT_MIN_FREQ,
            "max_freq": INSECT_MAX_FREQ,
        }

    def test_skips_majority_offset(self):
        """Rows with offset='majority' are skipped."""
        analyzer = InsectAnalyzer()
        predictions = {
            "majority": ["Gryllus campestris"],
            "0.0-4.0": ["Gryllus campestris"],
        }
        probabilities = {
            "majority": {"Gryllus campestris": 0.9},
            "0.0-4.0": {"Gryllus campestris": 0.9},
        }
        detections = analyzer._parse_predictions(predictions, probabilities)
        assert len(detections) == 1
        assert detections[0]["start_time"] == 0.0

    def test_skips_empty_species_list(self):
        """Windows with empty species list produce no detections."""
        analyzer = InsectAnalyzer()
        predictions = {"0.0-4.0": []}
        probabilities = {"0.0-4.0": {}}
        detections = analyzer._parse_predictions(predictions, probabilities)
        assert detections == []

    def test_skips_invalid_offset_format(self):
        """Offsets that cannot be parsed as start-end are safely skipped."""
        analyzer = InsectAnalyzer()
        predictions = {"invalid_offset": ["Gryllus campestris"]}
        probabilities = {"invalid_offset": {"Gryllus campestris": 0.9}}
        detections = analyzer._parse_predictions(predictions, probabilities)
        assert detections == []

    def test_skips_negative_start_time(self):
        """Offsets where start_time < 0 are skipped."""
        analyzer = InsectAnalyzer()
        predictions = {"-1.0-3.0": ["Gryllus campestris"]}
        probabilities = {"-1.0-3.0": {"Gryllus campestris": 0.9}}
        detections = analyzer._parse_predictions(predictions, probabilities)
        assert detections == []

    def test_skips_end_time_before_or_equal_to_start(self):
        """Offsets where end_time <= start_time are skipped."""
        analyzer = InsectAnalyzer()
        predictions = {"4.0-2.0": ["Gryllus campestris"], "2.0-2.0": ["Gryllus campestris"]}
        probabilities = {}
        detections = analyzer._parse_predictions(predictions, probabilities)
        assert detections == []

    def test_multiple_species_in_one_window(self):
        """Windows with multiple predicted species generate distinct detections."""
        analyzer = InsectAnalyzer()
        predictions = {"0.0-4.0": ["Species A", "Species B"]}
        probabilities = {"0.0-4.0": {"Species A": 0.5, "Species B": 0.9}}
        detections = analyzer._parse_predictions(predictions, probabilities)

        assert len(detections) == 2
        assert detections[0]["species"] == "Species A"
        assert detections[0]["confidence"] == 0.5
        assert detections[1]["species"] == "Species B"
        assert detections[1]["confidence"] == 0.9


class TestInsectAnalyzerAnalyze:
    """Tests for the analyze() method."""

    def test_analyze_success(self):
        """analyze() calls in-process Inference and parses results."""
        analyzer = InsectAnalyzer()
        mock_inf = MagicMock()
        mock_inf.predict_file.return_value = (
            {"0.00-4.00": ["Gryllus campestris"]},
            {},
            {"0.00-4.00": {"Gryllus campestris": 0.91}},
        )

        with patch.object(analyzer, "_resolve_model_path", return_value="/models/insects"):
            with patch.object(analyzer, "_get_inference", return_value=mock_inf) as mock_get_inf:
                detections = analyzer.analyze(
                    Path("test.wav"),
                    window_size=4.0,
                    stride_length=2.0,
                )

        mock_get_inf.assert_called_once_with(
            model_path="/models/insects",
            window_size=4.0,
            stride_length=2.0,
            sample_rate=SAMPLE_RATE,
        )
        mock_inf.predict_file.assert_called_once_with("test.wav")
        assert len(detections) == 1
        assert detections[0]["species"] == "Gryllus campestris"
        assert detections[0]["confidence"] == pytest.approx(0.91)

    def test_analyze_handles_none_from_predict_file(self):
        """Returns empty list when predict_file returns None."""
        analyzer = InsectAnalyzer()
        mock_inf = MagicMock()
        mock_inf.predict_file.return_value = None

        with patch.object(analyzer, "_resolve_model_path", return_value="/models/insects"):
            with patch.object(analyzer, "_get_inference", return_value=mock_inf):
                detections = analyzer.analyze(Path("empty.ogg"))

        assert detections == []

    def test_analyze_all_formats_direct(self):
        """Audio formats (WAV, FLAC, OGG, MP3) are passed directly to predict_file."""
        analyzer = InsectAnalyzer()
        mock_inf = MagicMock()
        mock_inf.predict_file.return_value = ({}, {}, {})

        with patch.object(analyzer, "_resolve_model_path", return_value="/models/insects"):
            with patch.object(analyzer, "_get_inference", return_value=mock_inf):
                for audio_name in ("test.wav", "test.flac", "test.ogg", "test.mp3"):
                    analyzer.analyze(Path(audio_name))

        assert mock_inf.predict_file.call_count == 4

    def test_analyze_cancellation_token(self):
        """Raises TaskCancelledError when cancellation token is cancelled."""
        analyzer = InsectAnalyzer()
        token = CancellationToken()
        token.cancel()

        with pytest.raises(TaskCancelledError):
            analyzer.analyze(Path("sample.ogg"), cancellation_token=token)


class TestInsectsModelSetup:
    """Tests for setup_insects_model.py script functions."""

    def test_check_insects_files_all_present(self, tmp_path):
        """Returns True when all required model files exist."""
        from scripts.setup_insects_model import REQUIRED_FILES, check_insects_files

        for rel_path in REQUIRED_FILES:
            file_path = tmp_path / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text("dummy")

        assert check_insects_files(tmp_path) is True

    def test_check_insects_files_missing(self, tmp_path):
        """Returns False when any required file is missing."""
        from scripts.setup_insects_model import check_insects_files

        assert check_insects_files(tmp_path) is False

    def test_prepare_insects_model_already_ready(self, tmp_path):
        """When check_model returns True, prepare_insects_model returns False (no download)."""
        from scripts.setup_insects_model import prepare_insects_model

        mock_check = MagicMock(return_value=True)
        mock_download = MagicMock()

        downloaded = prepare_insects_model(
            model_dir=tmp_path,
            check_model=mock_check,
            download_model=mock_download,
        )

        assert downloaded is False
        mock_download.assert_not_called()


class TestResolveModelPath:
    """Tests for InsectAnalyzer._resolve_model_path()."""

    def test_resolve_model_path_cached_hit(self, tmp_path):
        """Returns the first existing cached directory containing model.yaml."""
        (tmp_path / "model.yaml").write_text("dummy")
        analyzer = InsectAnalyzer()

        with patch("app.ai.insects.analyzer.CACHED_MODEL_PATHS", [tmp_path]):
            with patch("scripts.setup_insects_model.prepare_insects_model") as mock_prep:
                resolved = analyzer._resolve_model_path()
                assert resolved == str(tmp_path)
                mock_prep.assert_not_called()

    def test_resolve_model_path_triggers_on_demand_preparation(self, tmp_path):
        """Triggers prepare_insects_model when model is missing and returns resolved path on success."""
        analyzer = InsectAnalyzer()

        def fake_prepare(target_dir):
            (target_dir / "model.yaml").write_text("dummy")
            return True

        with patch("app.ai.insects.analyzer.CACHED_MODEL_PATHS", [tmp_path]):
            with patch("scripts.setup_insects_model.prepare_insects_model", side_effect=fake_prepare) as mock_prep:
                with patch("scripts.setup_insects_model.check_insects_files", return_value=True):
                    resolved = analyzer._resolve_model_path()
                    assert resolved == str(tmp_path)
                    mock_prep.assert_called_once_with(tmp_path)

    def test_resolve_model_path_raises_clean_error_on_failure(self, tmp_path):
        """Raises a descriptive RuntimeError when model files are missing and preparation fails."""
        analyzer = InsectAnalyzer()

        with patch("app.ai.insects.analyzer.CACHED_MODEL_PATHS", [tmp_path]):
            with patch("scripts.setup_insects_model.prepare_insects_model", side_effect=RuntimeError("Network error")):
                with patch("scripts.setup_insects_model.check_insects_files", return_value=False):
                    with pytest.raises(RuntimeError) as exc_info:
                        analyzer._resolve_model_path()

                    assert "Insects model files are missing" in str(exc_info.value)
                    assert "setup_insects_model.py" in str(exc_info.value)

