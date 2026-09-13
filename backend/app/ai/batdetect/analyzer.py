"""Batdetect2 bat detection analyzer using in-process Python API."""

import logging
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from app.core.task_cancellation import CancellationToken, TaskCancelledError

import os

logger = logging.getLogger(__name__)


def _ensure_optimal_torch_threads() -> None:
    """
    Configure PyTorch thread count for containerized CPU execution.

    In containers constrained by CPU limits (e.g. 1.0 or 2.0 vCPUs), PyTorch's
    default thread count (which detects the host machine's total cores, e.g. 8)
    causes excessive thread contention and Linux CFS quota throttling.
    Restricting threads to min(2, os.cpu_count() or 1) provides multi-fold speedups.
    """
    try:
        import torch

        desired = int(os.environ.get("TORCH_NUM_THREADS", "2"))
        if torch.get_num_threads() != desired:
            torch.set_num_threads(desired)
    except Exception:
        pass


class BatDetect2Analyzer:
    """
    Batdetect2 bat detection analyzer.

    Uses the batdetect2 Python API directly for in-process audio analysis.
    https://github.com/macaodha/batdetect2
    """

    def __init__(self) -> None:
        self._version: str | None = None
        self._model: Any = None
        self._params: dict[str, Any] | None = None

    @property
    def version(self) -> str:
        """Get batdetect2 version."""
        if self._version is None:
            try:
                self._version = version("batdetect2")
            except PackageNotFoundError:
                self._version = "unknown"
        return self._version

    def _get_model(self) -> tuple[Any, dict[str, Any]]:
        """Lazy-load and cache the BatDetect2 model and parameters in memory."""
        if self._model is None or self._params is None:
            try:
                import batdetect2.api as api
            except ImportError as exc:
                raise RuntimeError(
                    "batdetect2 not installed. Install via: pip install batdetect2"
                ) from exc
            self._model, self._params = api.load_model()
        return self._model, self._params

    def analyze(
        self,
        audio_path: Path,
        detection_threshold: float = 0.3,
        chunk_size: float = 2.0,
        max_duration: float | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> list[dict[str, Any]]:
        """
        Analyze audio file for bat calls using the in-process Python API.

        Args:
            audio_path: Path to audio file (WAV, FLAC, OGG, MP3, etc.).
            detection_threshold: Detection confidence threshold (0.0-1.0).
            chunk_size: Audio chunk size in seconds.
            max_duration: Optional audio duration limit in seconds.
            cancellation_token: Optional cancellation token.

        Returns:
            List of detections with time, frequency, species, and confidence.
        """
        try:
            import batdetect2.api as api
        except ImportError as exc:
            raise RuntimeError(
                "batdetect2 not installed. Install via: pip install batdetect2"
            ) from exc

        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()

        _ensure_optimal_torch_threads()

        model, params = self._get_model()
        config_kwargs: dict[str, Any] = {
            **params,
            "time_expansion": 1,
            "spec_slices": False,
            "chunk_size": chunk_size,
            "detection_threshold": detection_threshold,
            "quiet": True,
        }
        if max_duration is not None:
            config_kwargs["max_duration"] = max_duration

        config = api.get_config(**config_kwargs)

        try:
            results = api.process_file(str(audio_path), model, config=config)
        except TaskCancelledError:
            raise
        except Exception as exc:
            logger.error(f"batdetect2 API failed: {exc}")
            raise RuntimeError(f"batdetect2 failed: {exc}") from exc

        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()

        annotations = results.get("pred_dict", {}).get("annotation", [])
        detections: list[dict[str, Any]] = []
        for annotation in annotations:
            try:
                detections.append(
                    {
                        "start_time": float(annotation["start_time"]),
                        "end_time": float(annotation["end_time"]),
                        "min_freq": float(annotation["low_freq"]),
                        "max_freq": float(annotation["high_freq"]),
                        "species": str(
                            annotation.get("class", annotation.get("class_name", ""))
                        ),
                        "confidence": float(
                            annotation.get("det_prob", annotation.get("class_prob", 0))
                        ),
                    }
                )
            except (TypeError, ValueError, KeyError) as exc:
                logger.warning(
                    f"Failed to parse batdetect2 annotation: {annotation}, error: {exc}"
                )
                continue

        return detections
