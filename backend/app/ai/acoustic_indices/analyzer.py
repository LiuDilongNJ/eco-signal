"""Acoustic index analyzer backed by the bundled getMaad.py runtime."""
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

from app.ai.cancellable_process import run_cancellable_process
from app.core.task_cancellation import CancellationToken


class AcousticIndexAnalyzer:
    """Run acoustic index calculations through the bundled CLI."""

    GET_MAAD_SCRIPT = (
        Path(__file__).resolve().parents[1]
        / "legacy_runtime"
        / "bin"
        / "getMaad.py"
    )

    def _serialize_params(self, params: dict[str, Any]) -> str:
        parts: list[str] = []
        for key, value in params.items():
            serialized = "None" if value is None else str(value)
            parts.append(f"{key}?{serialized}")
        return "@".join(parts)

    def _parse_output(self, output: str) -> dict[str, Any]:
        last_line = ""
        for line in output.splitlines():
            if line.strip():
                last_line = line.strip()
        if not last_line or last_line == "0":
            return {}
        if "?" not in last_line:
            return {"value": last_line}

        results: dict[str, Any] = {}
        for part in last_line.split("!"):
            if "?" not in part:
                continue
            name, value = part.split("?", 1)
            results[name] = value
        return results

    def run_index(
        self,
        audio_path: Path,
        *,
        index_name: str,
        params: dict[str, Any] | None = None,
        channel: str = "left",
        min_time: str | int | float = 0,
        max_time: str | int | float | None = None,
        min_frequency: str | int | float = 1,
        max_frequency: str | int | float | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> dict[str, Any]:
        """Execute a single acoustic index through the bundled wrapper."""
        cmd = [
            sys.executable,
            str(self.GET_MAAD_SCRIPT),
            "-f",
            str(audio_path),
            "--ch",
            channel,
            "--mint",
            str(min_time),
            "--maxt",
            "" if max_time is None else str(max_time),
            "--minf",
            str(min_frequency),
            "--maxf",
            "" if max_frequency is None else str(max_frequency),
            "--it",
            index_name,
        ]
        if params:
            cmd.extend(["--pa", self._serialize_params(params)])

        try:
            result = run_cancellable_process(
                cmd,
                timeout=3600,
                cancellation_token=cancellation_token,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Python is required to run acoustic index CLI") from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"Acoustic index CLI failed with exit {result.returncode}: {result.stderr or result.stdout}"
            )
        return self._parse_output(result.stdout)

    def get_version(self) -> str:
        """Get the installed scikit-maad version."""
        return version("scikit-maad")
