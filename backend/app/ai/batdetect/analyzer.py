"""Batdetect2 bat detection analyzer."""
import csv
import logging
import shutil
import subprocess
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from app.ai.exceptions import ModelDownloadError
from app.ai.cancellable_process import run_cancellable_process
from app.core.task_cancellation import CancellationToken, TaskCancelledError

logger = logging.getLogger(__name__)


class BatDetect2Analyzer:
    """
    Batdetect2 bat detection analyzer.
    
    Uses the batdetect2 CLI for WAV files and the Python API for FLAC.
    https://github.com/macaodha/batdetect2
    """
    
    def __init__(self):
        self._version: str | None = None
    
    @property
    def version(self) -> str:
        """Get batdetect2 version."""
        if self._version is None:
            try:
                self._version = version("batdetect2")
            except PackageNotFoundError:
                self._version = "unknown"
        return self._version
    
    def analyze(
        self,
        audio_path: Path,
        detection_threshold: float = 0.3,
        chunk_size: float = 2.0,
        cancellation_token: CancellationToken | None = None,
    ) -> list[dict[str, Any]]:
        """
        Analyze audio file for bat calls.
        
        Args:
            audio_path: Path to a WAV or FLAC audio file.
            detection_threshold: Detection confidence threshold (0.0-1.0)
            chunk_size: Audio chunk size in seconds.
        Returns:
            List of detections with time, frequency, species, and confidence
        """
        suffix = audio_path.suffix.lower()
        if suffix == ".flac":
            return self._analyze_flac_with_api(
                audio_path,
                detection_threshold=detection_threshold,
                chunk_size=chunk_size,
                cancellation_token=cancellation_token,
            )
        if suffix != ".wav":
            raise ValueError(f"Unsupported batdetect2 audio format: {audio_path.suffix}")

        return self._analyze_wav_with_cli(
            audio_path,
            detection_threshold=detection_threshold,
            chunk_size=chunk_size,
            cancellation_token=cancellation_token,
        )

    def _analyze_wav_with_cli(
        self,
        audio_path: Path,
        *,
        detection_threshold: float,
        chunk_size: float,
        cancellation_token: CancellationToken | None = None,
    ) -> list[dict[str, Any]]:
        """Run the CLI path used for WAV analysis."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_dir = temp_path / "input"
            output_dir = temp_path / "output"
            input_dir.mkdir()
            output_dir.mkdir()
            
            # Copy audio file to input directory
            input_file = input_dir / audio_path.name
            shutil.copy(audio_path, input_file)
            
            # Build batdetect2 command
            cmd = [
                "batdetect2", "detect",
                str(input_dir),
                str(output_dir),
                str(detection_threshold),
            ]
            cmd += ["--chunk_size", str(chunk_size)]
            logger.info(f"Running: {' '.join(cmd)}")
            
            try:
                result = run_cancellable_process(
                    cmd,
                    timeout=300,  # 5 minute timeout
                    cancellation_token=cancellation_token,
                )

                if result.returncode != 0:
                    stderr_lower = result.stderr.lower()
                    # Treat download/network-related failures as retriable
                    if any(kw in stderr_lower for kw in ("download", "connection", "timeout", "network", "http", "url")):
                        raise ModelDownloadError(
                            f"batdetect2 model download failed (exit {result.returncode}): {result.stderr}"
                        )
                    logger.error(f"batdetect2 failed: {result.stderr}")
                    raise RuntimeError(f"batdetect2 failed: {result.stderr}")

            except subprocess.TimeoutExpired:
                # Timeout most likely caused by model download on first run
                raise ModelDownloadError("batdetect2 timed out (300s) - likely waiting for model download")
            except FileNotFoundError:
                raise RuntimeError("batdetect2 not installed. Install via: pip install batdetect2")
            
            # Parse CSV output
            csv_file = output_dir / f"{input_file.stem}.wav.csv"
            
            if not csv_file.exists():
                logger.info("No detections found (no CSV output)")
                return []
            
            return self._parse_csv(csv_file)

    def _analyze_flac_with_api(
        self,
        audio_path: Path,
        *,
        detection_threshold: float,
        chunk_size: float,
        cancellation_token: CancellationToken | None = None,
    ) -> list[dict[str, Any]]:
        """Run FLAC files through the single-file batdetect2 Python API."""
        try:
            import batdetect2.api as api
        except ImportError as exc:
            raise RuntimeError("batdetect2 not installed. Install via: pip install batdetect2") from exc

        try:
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            model, params = api.load_model()
            config = api.get_config(**{
                **params,
                "time_expansion": 1,
                "spec_slices": False,
                "chunk_size": chunk_size,
                "detection_threshold": detection_threshold,
            })
            results = api.process_file(str(audio_path), model, config=config)
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
        except TaskCancelledError:
            raise
        except Exception as exc:
            logger.error(f"batdetect2 API failed: {exc}")
            raise RuntimeError(f"batdetect2 failed: {exc}") from exc

        annotations = results.get("pred_dict", {}).get("annotation", [])
        detections: list[dict[str, Any]] = []
        for annotation in annotations:
            try:
                detections.append({
                    "start_time": float(annotation["start_time"]),
                    "end_time": float(annotation["end_time"]),
                    "min_freq": float(annotation["low_freq"]),
                    "max_freq": float(annotation["high_freq"]),
                    "species": str(annotation.get("class", annotation.get("class_name", ""))),
                    "confidence": float(annotation.get("det_prob", annotation.get("class_prob", 0))),
                })
            except (TypeError, ValueError, KeyError) as exc:
                logger.warning(f"Failed to parse batdetect2 API annotation: {annotation}, error: {exc}")
                continue

        return detections
    
    def _parse_csv(self, csv_path: Path) -> list[dict[str, Any]]:
        """
        Parse batdetect2 CSV output.
        
        CSV columns:
        0: id
        1: detection_prob (confidence)
        2: start_time
        3: end_time
        4: high_freq
        5: low_freq
        6: class_name (species)
        """
        detections: list[dict[str, Any]] = []
        
        with open(csv_path, "r", newline="") as f:
            reader = csv.reader(f)
            next(reader, None)  # Skip header
            
            for row in reader:
                if len(row) < 7:
                    continue
                
                try:
                    detections.append({
                        "start_time": float(row[2]),
                        "end_time": float(row[3]),
                        "min_freq": float(row[5]),
                        "max_freq": float(row[4]),
                        "species": row[6],
                        "confidence": float(row[1]),
                    })
                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse row: {row}, error: {e}")
                    continue
        
        return detections
