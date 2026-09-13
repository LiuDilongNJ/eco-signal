"""BirdNET analyzer using in-process Python runtime."""

import csv
import logging
import tempfile
from pathlib import Path
from typing import Any

from app.core.task_cancellation import CancellationToken, TaskCancelledError

logger = logging.getLogger(__name__)


class BirdNETAnalyzer:
    """Run BirdNET through the in-process Python API."""

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
        """Analyze audio using in-process BirdNET-Analyzer."""
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()

        try:
            from birdnet_analyzer import analyze as birdnet_analyze
        except ImportError as exc:
            raise RuntimeError("birdnet_analyzer is required to run BirdNET") from exc

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            output_csv = temp_path / f"{audio_path.stem}.BirdNET.results.csv"

            species_file: Path | None = None
            if species_list:
                species_file = temp_path / "species.txt"
                species_file.write_text("\n".join(species_list), encoding="utf-8")

            try:
                birdnet_analyze(
                    audio_input=str(audio_path),
                    output=str(temp_path),
                    min_conf=min_confidence,
                    sensitivity=sensitivity,
                    overlap=overlap,
                    sf_thresh=sf_thresh,
                    lat=lat if lat is not None else -1,
                    lon=lon if lon is not None else -1,
                    week=week if week is not None else -1,
                    slist=str(species_file) if species_file else None,
                    locale=locale,
                    top_n=top_n,
                    rtype="csv",
                    threads=1,
                )
            except TaskCancelledError:
                raise
            except Exception as exc:
                logger.error(f"BirdNET analysis failed: {exc}")
                raise RuntimeError(f"BirdNET analysis failed: {exc}") from exc

            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()

            if not output_csv.exists():
                return []
            return self._parse_csv(output_csv)
