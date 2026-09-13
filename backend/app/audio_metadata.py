"""Audio metadata probing, embedded tag extraction, and transcoding utilities."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

try:
    import mutagen
except ImportError:
    mutagen = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_NON_CONTENT_AUDIO_TAG_KEYS = {"encoder", "tsse"}


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def json_tag_value(value: object) -> str | int | float | bool:
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        if len(value) > 2048:
            return f"{value[:2045]}..."
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"binary:{len(value)} bytes"

    # Handle mutagen frame objects containing binary payloads (e.g. APIC, Picture, GEOB, PRIV)
    data = getattr(value, "data", None)
    if isinstance(data, (bytes, bytearray, memoryview)):
        mime = getattr(value, "mime", None) or getattr(value, "mime_type", None)
        desc = getattr(value, "desc", None) or getattr(value, "description", None)
        class_name = value.__class__.__name__
        prefix = f"picture:{mime}" if mime else class_name
        suffix = f":{desc}" if desc else ""
        return f"{prefix}{suffix}:{len(data)} bytes"

    text = str(value)
    if len(text) > 2048:
        return f"{text[:2045]}..."
    return text


def missing_audio_tag_names(
    source_tags: dict[str, dict[str, list[str | int | float | bool]]],
    stored_tags: dict[str, dict[str, list[str | int | float | bool]]],
) -> list[str]:
    stored_values = {
        str(value).casefold()
        for namespace in stored_tags.values()
        for values in namespace.values()
        for value in values
    }
    missing: list[str] = []
    for namespace in source_tags.values():
        for name, values in namespace.items():
            if name.casefold() in _NON_CONTENT_AUDIO_TAG_KEYS:
                continue
            if any(str(value).casefold() not in stored_values for value in values):
                missing.append(name)
    return list(dict.fromkeys(missing))


def compute_file_md5(path: Path) -> str:
    hasher = hashlib.md5()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def probe_audio(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe", "-v", "error",
        "-show_format", "-show_streams",
        "-of", "json", str(path)
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
        payload = json.loads(completed.stdout)
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe is not installed") from exc
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read audio file format: {exc}") from exc

    stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "audio"), None)
    if not stream:
        raise ValueError("File does not contain an audio stream")

    fmt = payload.get("format") or {}
    container = str(fmt.get("format_name") or "").split(",")[0].lower()
    return {
        "container": container,
        "codec": str(stream.get("codec_name") or "").lower(),
        "bit_rate_bps": as_int(stream.get("bit_rate") or fmt.get("bit_rate")),
        "sampling_rate_hz": as_int(stream.get("sample_rate")),
        "bit_depth": as_int(stream.get("bits_per_raw_sample") or stream.get("bits_per_sample")),
        "channel_num": as_int(stream.get("channels")),
        "duration_s": as_float(stream.get("duration") or fmt.get("duration")),
    }


def extract_audio_tags(path: Path) -> tuple[dict[str, dict[str, list[str | int | float | bool]]], list[str]]:
    tags: dict[str, dict[str, list[str | int | float | bool]]] = {
        "id3v2": {}, "vorbis_comment": {}, "riff_info": {}, "other": {},
    }
    warnings: list[str] = []
    if mutagen is None:
        return {}, ["mutagen is not installed; embedded tags not extracted"]
    try:
        audio = mutagen.File(path, easy=False)
        raw_tags = getattr(audio, "tags", None)
        if not raw_tags:
            return {}, warnings
        tag_class = raw_tags.__class__.__module__.lower()
        namespace = (
            "id3v2" if "id3" in tag_class
            else "vorbis_comment" if ("vorbis" in tag_class or "flac" in tag_class)
            else "riff_info" if "wave" in tag_class
            else "other"
        )
        for key, value in raw_tags.items():
            values = value if isinstance(value, (list, tuple)) else [value]
            normalized = [json_tag_value(item) for item in values]
            tags[namespace][str(key)] = normalized
    except Exception as exc:
        logger.warning("Could not read embedded audio tags from %s: %s", path, exc)
        warnings.append(f"Embedded metadata could not be fully read: {exc}")
    return {key: val for key, val in tags.items() if val}, warnings


def build_audio_file_metadata(
    source_filename: str,
    target_filename: str,
    source_probe: dict[str, Any],
    stored_probe: dict[str, Any],
    tags: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": {"filename": source_filename, **source_probe},
        "stored": {"filename": target_filename, "container": stored_probe.get("container", ""), **stored_probe},
        "tags": tags,
        "warnings": warnings,
    }


def optimal_worker_count() -> int:
    """Calculate optimal concurrency based on available CPU cores."""
    return max(1, min(os.cpu_count() or 4, 8))


def transcode_to_flac(
    source_path: Path,
    target_path: Path,
    *,
    sampling_rate_hz: int | None = None,
) -> None:
    """Losslessly transcode audio to FLAC container and codec preserving metadata."""
    command = [
        "ffmpeg", "-y", "-nostdin",
        "-i", str(source_path),
        "-map", "0:a:0",
        "-vn", "-sn", "-dn",
        "-map_metadata", "0",
    ]
    if sampling_rate_hz:
        command.extend(["-ar", str(sampling_rate_hz)])
    command.extend(["-c:a", "flac", str(target_path)])
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not installed") from exc
    except subprocess.CalledProcessError as exc:
        err = exc.stderr.strip() if exc.stderr else str(exc)
        raise RuntimeError(f"ffmpeg conversion failed: {err}") from exc

