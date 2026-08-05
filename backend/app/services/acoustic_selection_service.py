"""Prepare reusable audio selections for acoustic calculations."""

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import soundfile as sf

from app.core.config import settings
from app.spectrogram import build_sox_sinc_frequency_spec

_CACHE_TTL_SECONDS = 24 * 60 * 60


def _cache_root() -> Path:
    root = Path(settings.MEDIA_ROOT) / "tmp" / "acoustic-selections"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_expired(root: Path) -> None:
    cutoff = time.time() - _CACHE_TTL_SECONDS
    for path in root.iterdir():
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


def prepare_acoustic_selection(
    source_path: Path,
    *,
    media_id: int,
    min_time: float,
    max_time: float | None,
    min_frequency: float,
    max_frequency: float | None,
    filter_enabled: bool,
) -> Path:
    """Return the source file or a cached, same-format selected audio file."""
    source_path = source_path.resolve()
    info = sf.info(source_path)
    duration = info.frames / info.samplerate
    start = max(0.0, min(float(min_time), duration))
    end = duration if max_time is None else max(start, min(float(max_time), duration))
    is_full_time = start == 0.0 and abs(end - duration) < (1 / info.samplerate)
    if is_full_time and not filter_enabled:
        return source_path

    payload = {
        "media_id": media_id,
        "source": str(source_path),
        "source_mtime_ns": source_path.stat().st_mtime_ns,
        "start": start,
        "end": end,
        "min_frequency": float(min_frequency),
        "max_frequency": None if max_frequency is None else float(max_frequency),
        "filter_enabled": filter_enabled,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    root = _cache_root()
    _cleanup_expired(root)
    destination = root / f"{media_id}-{digest}{source_path.suffix.lower()}"
    if destination.exists() and destination.stat().st_size > 0:
        os.utime(destination, None)
        return destination

    temporary = destination.with_name(f".{destination.name}.tmp{destination.suffix}")
    command = ["sox", str(source_path), str(temporary)]
    if not is_full_time:
        command.extend(["trim", f"{start:.9f}", f"{end - start:.9f}"])
    if filter_enabled:
        nyquist = info.samplerate / 2
        high = nyquist if max_frequency is None else float(max_frequency)
        command.extend(
            [
                "sinc",
                build_sox_sinc_frequency_spec(info.samplerate, min_frequency, high),
            ]
        )

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination
