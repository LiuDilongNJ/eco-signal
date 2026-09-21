"""Insects analyzer - insect sound recognition using autrainer with insects-base-cnn10-96k-t model."""

import logging
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from app.core.task_cancellation import CancellationToken

logger = logging.getLogger(__name__)

# Default frequency range for insects (Hz)
INSECT_MIN_FREQ = 1
INSECT_MAX_FREQ = 96000

# Candidate local model paths (prioritizing persistent docker volume)
CACHED_MODEL_PATHS = [
    Path("/models/insects"),
    Path("/models/insects/AlexanderGbd--insects-base-cnn10-96k-t--main"),
    Path.home()
    / ".cache"
    / "torch"
    / "hub"
    / "autrainer"
    / "AlexanderGbd--insects-base-cnn10-96k-t--main",
    Path(
        "/root/.cache/torch/hub/autrainer/AlexanderGbd--insects-base-cnn10-96k-t--main"
    ),
    Path(
        "/var/www/.cache/torch/hub/autrainer/AlexanderGbd--insects-base-cnn10-96k-t--main"
    ),
]

# Required sample rate
SAMPLE_RATE = 96000


class InsectAnalyzer:
    """
    Insects sound analyzer using autrainer with insects-base-cnn10-96k-t model.

    Performs direct in-process Python inference with model instance caching for sub-2s execution.
    Classifies audio segments into 86 insect species from the Orthoptera and Hemiptera orders.
    Reference: https://huggingface.co/AlexanderGbd/insects-base-cnn10-96k-t
    """

    def __init__(self) -> None:
        self._version: str | None = None
        self._inference_cache: dict[tuple[str, float, float, int], Any] = {}

    @property
    def version(self) -> str:
        """Get autrainer version string."""
        if self._version is None:
            try:
                self._version = version("autrainer")
            except PackageNotFoundError:
                self._version = "unknown"
        return self._version

    def _resolve_model_path(self) -> str:
        """Resolve the local model directory path, automatically preparing it if missing."""
        for candidate in CACHED_MODEL_PATHS:
            if candidate.is_dir() and (candidate / "model.yaml").is_file():
                return str(candidate)

        target_dir = CACHED_MODEL_PATHS[0]
        try:
            from scripts.setup_insects_model import check_insects_files, prepare_insects_model

            logger.info("Insects model files not found, attempting on-demand preparation in %s", target_dir)
            prepare_insects_model(target_dir)
            if check_insects_files(target_dir):
                return str(target_dir)
        except Exception as exc:
            logger.warning("Failed to automatically prepare insects model: %s", exc)

        for candidate in CACHED_MODEL_PATHS:
            if candidate.is_dir() and (candidate / "model.yaml").is_file():
                return str(candidate)

        raise RuntimeError(
            f"Insects model files are missing from '{target_dir}' and automatic preparation failed. "
            "Ensure the server has internet connectivity to Hugging Face or run 'python /app/scripts/setup_insects_model.py' manually."
        )

    def _get_inference(
        self,
        model_path: str,
        window_size: float,
        stride_length: float,
        sample_rate: int,
    ) -> Any:
        """Get or initialize cached autrainer Inference instance."""
        cache_key = (model_path, window_size, stride_length, sample_rate)
        if cache_key not in self._inference_cache:
            from autrainer.serving import Inference

            self._inference_cache[cache_key] = Inference(
                model_path=model_path,
                window_length=window_size,
                stride_length=stride_length,
                sample_rate=sample_rate,
                device="cpu",
            )
        return self._inference_cache[cache_key]

    def _parse_predictions(
        self,
        predictions: dict[str, Any],
        probabilities: dict[str, dict],
    ) -> list[dict[str, Any]]:
        """Parse in-memory predictions and probabilities into detection dicts."""
        detections: list[dict[str, Any]] = []
        for offset, species_list in predictions.items():
            if offset == "majority":
                continue
            if not species_list:
                continue

            try:
                start_str, end_str = offset.split("-", 1)
                start_time = float(start_str)
                end_time = float(end_str)
            except (ValueError, AttributeError):
                logger.warning(f"Could not parse offset '{offset}', skipping")
                continue

            if start_time < 0 or end_time <= start_time:
                logger.warning(
                    f"Invalid time bounds for offset '{offset}' "
                    f"(start={start_time}, end={end_time}), skipping"
                )
                continue

            offset_probs = probabilities.get(offset, {}) if probabilities else {}
            for species in species_list:
                try:
                    confidence = float(offset_probs.get(species, 0.0))
                except (ValueError, TypeError):
                    confidence = 0.0

                detections.append(
                    {
                        "start_time": start_time,
                        "end_time": end_time,
                        "species": species,
                        "confidence": confidence,
                        "min_freq": INSECT_MIN_FREQ,
                        "max_freq": INSECT_MAX_FREQ,
                    }
                )
        return detections

    def analyze(
        self,
        audio_path: Path,
        window_size: float = 4.0,
        stride_length: float = 4.0,
        cancellation_token: CancellationToken | None = None,
    ) -> list[dict[str, Any]]:
        """
        Analyze an audio file for insect species using in-process Python inference.

        Args:
            audio_path: Path to an audio file (WAV, FLAC, OGG, MP3, etc.).
            window_size: Length of each analysis window in seconds (default 4.0).
            stride_length: Step between consecutive windows in seconds (default 4.0).
            cancellation_token: Optional token for task cancellation.

        Returns:
            List of detection dicts.
        """
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()

        model_path = self._resolve_model_path()
        inf = self._get_inference(
            model_path=model_path,
            window_size=window_size,
            stride_length=stride_length,
            sample_rate=SAMPLE_RATE,
        )

        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()

        res = inf.predict_file(str(audio_path))
        if res is None:
            return []

        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()

        predictions, _, probabilities = res
        return self._parse_predictions(predictions, probabilities)
