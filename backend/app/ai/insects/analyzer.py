"""Insects analyzer - insect sound recognition using autrainer CLI with insects-base-cnn10-96k-t model."""
import csv
import logging
import os
import shutil
import subprocess
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from app.ai.exceptions import ModelDownloadError
from app.ai.cancellable_process import run_cancellable_process
from app.core.task_cancellation import CancellationToken

logger = logging.getLogger(__name__)

# Default frequency range for insects (Hz)
INSECT_MIN_FREQ = 1
INSECT_MAX_FREQ = 96000

# HuggingFace model identifier
HF_MODEL_ID = "hf:AlexanderGbd/insects-base-cnn10-96k-t"
LEGACY_CACHED_MODEL_PATH = Path(
    "/var/www/.cache/torch/hub/autrainer/AlexanderGbd--insects-base-cnn10-96k-t--main"
)

# Required sample rate
SAMPLE_RATE = 96000


class InsectAnalyzer:
    """
    Insects sound analyzer using autrainer CLI.

    Uses the autrainer inference command with the insects-base-cnn10-96k-t model
    from HuggingFace to classify audio segments into 86 insect species from
    the Orthoptera and Hemiptera orders.

    Reference: https://huggingface.co/AlexanderGbd/insects-base-cnn10-96k-t
    """

    def __init__(self) -> None:
        self._version: str | None = None

    @property
    def version(self) -> str:
        """Get autrainer version string."""
        if self._version is None:
            try:
                self._version = version("autrainer")
            except PackageNotFoundError:
                self._version = "unknown"
        return self._version

    def _resolve_model_spec(self) -> tuple[str, dict[str, str]]:
        """Prefer the locally cached model and force offline mode when available."""
        env = os.environ.copy()
        if LEGACY_CACHED_MODEL_PATH.exists():
            env["HF_HUB_OFFLINE"] = "1"
            return str(LEGACY_CACHED_MODEL_PATH), env

        return HF_MODEL_ID, env

    def analyze(
        self,
        audio_path: Path,
        window_size: float = 4.0,
        stride_length: float = 4.0,
        cancellation_token: CancellationToken | None = None,
    ) -> list[dict[str, Any]]:
        """
        Analyze an audio file for insect species using autrainer CLI.

        Args:
            audio_path: Path to a WAV or FLAC audio file.
            window_size: Length of each analysis window in seconds (default 4.0).
            stride_length: Step between consecutive windows in seconds (default 4.0).

        Returns:
            List of detection dicts, each with:
                - start_time (float): Segment start in seconds.
                - end_time   (float): Segment end in seconds.
                - species    (str):   Detected insect species name.
                - confidence (float): Detection confidence score.
                - min_freq   (int):   Fixed minimum frequency (1 Hz).
                - max_freq   (int):   Fixed maximum frequency (96000 Hz).
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_dir = temp_path / "input"
            output_dir = temp_path / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            suffix = audio_path.suffix.lower().lstrip(".")
            if suffix not in {"wav", "flac"}:
                raise ValueError(f"Unsupported insects audio format: {audio_path.suffix}")

            input_file = input_dir / audio_path.name
            shutil.copy(audio_path, input_file)

            model_spec, env = self._resolve_model_spec()
            cmd = [
                "autrainer", "inference",
                model_spec,
                "-sr", str(SAMPLE_RATE),
                "-w", str(window_size),
                "-s", str(stride_length),
            ]
            if suffix != "wav":
                cmd += ["-e", suffix]
            cmd += [str(input_dir), str(output_dir)]

            logger.info(f"Running: {' '.join(cmd)}")

            try:
                result = run_cancellable_process(
                    cmd,
                    timeout=600,  # 10-minute timeout for model download + inference
                    env=env,
                    cancellation_token=cancellation_token,
                )

                if result.returncode != 0:
                    stderr_lower = result.stderr.lower()
                    # Treat download/network-related failures as retriable
                    if any(kw in stderr_lower for kw in ("download", "connection", "timeout", "network", "http", "url")):
                        raise ModelDownloadError(
                            f"autrainer model download failed (exit {result.returncode}): {result.stderr}"
                        )
                    logger.error(f"autrainer inference failed: {result.stderr}")
                    raise RuntimeError(
                        f"autrainer inference failed (exit {result.returncode}): {result.stderr}"
                    )

            except subprocess.TimeoutExpired:
                # Timeout most likely caused by model download on first run
                raise ModelDownloadError("autrainer inference timed out (600s) - likely waiting for model download")
            except FileNotFoundError:
                raise RuntimeError(
                    "autrainer is not installed. Install via: pip install autrainer"
                )

            results_csv = output_dir / "results.csv"
            if not results_csv.exists():
                # Search recursively in case autrainer writes to a subdirectory
                found = list(output_dir.rglob("results.csv"))
                if found:
                    results_csv = found[0]
                else:
                    logger.info("No detections found (results.csv not produced)")
                    return []

            return self._parse_csv(results_csv)

    def _parse_csv(self, csv_path: Path) -> list[dict[str, Any]]:
        """
        Parse autrainer results.csv output.

        CSV format (header-based):
            filename  - source audio filename
            offset    - time range as "start-end" (e.g. "0.0-4.0")
            prediction - JSON-like list of predicted species (e.g. "['Gryllus campestris']")
            <species> - one column per species containing its confidence score

        Rows where offset == 'majority' represent aggregated results and are skipped.
        Rows where prediction == '[]' have no detections and are skipped.
        Segments with invalid time coordinates (start >= end, or start < 0) are skipped.
        """
        detections: list[dict[str, Any]] = []

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                offset = row.get("offset", "")
                prediction_raw = row.get("prediction", "[]")

                # Skip aggregated majority-vote row
                if offset == "majority":
                    continue

                # Skip rows with no predictions
                if prediction_raw in ("[]", "", None):
                    continue

                # Parse time range "start-end"
                try:
                    start_str, end_str = offset.split("-", 1)
                    start_time = float(start_str)
                    end_time = float(end_str)
                except (ValueError, AttributeError):
                    logger.warning(f"Could not parse offset '{offset}', skipping row")
                    continue

                # Validate time coordinates
                if start_time < 0 or end_time <= start_time:
                    logger.warning(
                        f"Invalid time bounds for offset '{offset}' "
                        f"(start={start_time}, end={end_time}), skipping"
                    )
                    continue

                # Parse prediction list: convert single-quoted JSON to actual list
                prediction_clean = prediction_raw.strip().replace("'", '"')
                try:
                    import json
                    species_list: list[str] = json.loads(prediction_clean)
                except (ValueError, Exception):
                    logger.warning(f"Could not parse prediction '{prediction_raw}', skipping row")
                    continue

                for species in species_list:
                    # Confidence is stored as a column named after the species
                    try:
                        confidence = float(row.get(species, 0.0))
                    except (ValueError, TypeError):
                        confidence = 0.0

                    detections.append({
                        "start_time": start_time,
                        "end_time": end_time,
                        "species": species,
                        "confidence": confidence,
                        "min_freq": INSECT_MIN_FREQ,
                        "max_freq": INSECT_MAX_FREQ,
                    })

        return detections
