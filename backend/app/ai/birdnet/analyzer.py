"""BirdNET analyzer backed by the configured BirdNET-Analyzer runtime."""
import atexit
import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from app.ai.cancellable_process import terminate_process_group
from app.ai.exceptions import ModelDownloadError
from app.core.task_cancellation import CancellationToken

_ACTIVE_PROCESSES: set[subprocess.Popen[str]] = set()
def _cleanup_active_processes() -> None:
    for process in list(_ACTIVE_PROCESSES):
        terminate_process_group(process)


atexit.register(_cleanup_active_processes)


class BirdNETAnalyzer:
    """Run BirdNET through a subprocess CLI."""

    MODEL_VERSION = "2.4"

    @property
    def version(self) -> str:
        return self.MODEL_VERSION

    def _parse_csv(self, csv_path: Path) -> list[dict[str, Any]]:
        detections: list[dict[str, Any]] = []
        with csv_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            for row in reader:
                if not row or row[0] in ("Start (s)", "filepath"):
                    continue
                if len(row) < 5:
                    continue
                try:
                    detections.append(
                        {
                            "start_time": float(row[0]),
                            "end_time": float(row[1]),
                            "species": row[2],
                            "confidence": float(row[4]),
                        }
                    )
                except (TypeError, ValueError):
                    continue
        return detections

    def analyze(
        self,
        audio_path: Path,
        min_confidence: float = 0.1,
        overlap: float = 0.0,
        sensitivity: float = 1.0,
        sf_thresh: float = 0.03,
        lat: float | None = None,
        lon: float | None = None,
        week: int | None = None,
        species_list: list[str] | None = None,
        locale: str = "en_us",
        top_n: int | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> list[dict[str, Any]]:
        """Analyze audio by invoking the configured BirdNET-Analyzer CLI."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            output_csv = temp_path / f"{audio_path.stem}.BirdNET.results.csv"
            cmd = [
                sys.executable,
                "-m",
                "birdnet_analyzer.analyze",
                str(audio_path),
                "-o",
                str(temp_path),
                "--rtype",
                "csv",
            ]

            if species_list:
                species_file = temp_path / "species.txt"
                species_file.write_text("\n".join(species_list), encoding="utf-8")
                cmd.extend(["--slist", str(species_file)])
            else:
                if lat is not None:
                    cmd.extend(["--lat", str(lat)])
                if lon is not None:
                    cmd.extend(["--lon", str(lon)])

            if week is not None:
                cmd.extend(["--week", str(week)])
            cmd.extend(["--sensitivity", str(sensitivity)])
            cmd.extend(["--min_conf", str(min_confidence)])
            cmd.extend(["--overlap", str(overlap)])
            cmd.extend(["--sf_thresh", str(sf_thresh)])
            cmd.extend(["--locale", locale])
            if top_n is not None:
                cmd.extend(["--top_n", str(top_n)])

            process: subprocess.Popen[str] | None = None
            env = os.environ.copy()
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                    env=env,
                )
                _ACTIVE_PROCESSES.add(process)
                def cancel_process() -> None:
                    terminate_process_group(process)
                if cancellation_token is not None:
                    cancellation_token.add_callback(cancel_process)
                try:
                    stdout, stderr = process.communicate(timeout=3600)
                    if cancellation_token is not None:
                        cancellation_token.raise_if_cancelled()
                finally:
                    if cancellation_token is not None:
                        cancellation_token.remove_callback(cancel_process)
            except subprocess.TimeoutExpired as exc:
                if process is not None:
                    terminate_process_group(process)
                raise ModelDownloadError("BirdNET CLI timed out") from exc
            except FileNotFoundError as exc:
                raise RuntimeError("Python is required to run BirdNET CLI") from exc
            except BaseException:
                if process is not None:
                    terminate_process_group(process)
                raise
            finally:
                if process is not None:
                    _ACTIVE_PROCESSES.discard(process)

            if process.returncode != 0:
                stderr_lower = stderr.lower()
                if any(word in stderr_lower for word in ("download", "connection", "timeout", "network", "http", "url")):
                    raise ModelDownloadError(
                        f"BirdNET model download failed: {stderr}"
                    )
                raise RuntimeError(
                    f"BirdNET CLI failed with exit {process.returncode}: {stderr or stdout}"
                )

            if not output_csv.exists():
                return []
            return self._parse_csv(output_csv)
