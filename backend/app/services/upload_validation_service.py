"""Central, content-based validation for every user supplied upload."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import subprocess
import zipfile
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, ImageSequence, UnidentifiedImageError

logger = logging.getLogger(__name__)

MAX_FILENAME_BYTES = 255
MAX_IMAGE_PIXELS = 80_000_000
MAX_GIF_FRAMES = 500
MAX_CSV_COLUMNS = 256
MAX_CSV_CELL_CHARS = 100_000

IMAGE_EXTENSIONS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "gif": "GIF", "webp": "WEBP"}
PHOTO_EXTENSIONS = {
    "png": frozenset({"PNG"}),
    "jpg": frozenset({"JPEG", "MPO"}),
    "jpeg": frozenset({"JPEG", "MPO"}),
    "tif": frozenset({"TIFF"}),
    "tiff": frozenset({"TIFF"}),
}
AUDIO_EXTENSIONS = {"wav", "flac", "mp3", "ogg"}
_IMAGE_MIME_TYPES = {
    "png": {"image/png"}, "jpg": {"image/jpeg"}, "jpeg": {"image/jpeg"},
    "gif": {"image/gif"}, "webp": {"image/webp"},
}


def upload_error(code: str) -> HTTPException:
    return HTTPException(status_code=400, detail=code)


def validate_filename(filename: str) -> str:
    if not filename or filename != Path(filename).name or "/" in filename or "\\" in filename:
        raise upload_error("invalid_filename")
    if ".." in filename or any(ord(char) < 32 or ord(char) == 127 for char in filename):
        raise upload_error("invalid_filename")
    if len(filename.encode("utf-8")) > MAX_FILENAME_BYTES:
        raise upload_error("invalid_filename")
    return filename


def extension_for(filename: str, allowed: set[str]) -> str:
    validate_filename(filename)
    suffix = Path(filename).suffix.lower().lstrip(".")
    if not suffix or suffix not in allowed:
        raise upload_error("unsupported_file_type")
    return suffix


def validate_audio_filename(filename: str) -> str:
    return extension_for(filename, AUDIO_EXTENSIONS)


def validate_photo_filename(filename: str) -> str:
    return extension_for(filename, set(PHOTO_EXTENSIONS))


def _audio_signature(path: Path) -> str | None:
    with path.open("rb") as source:
        header = source.read(16)
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "wav"
    if header.startswith(b"fLaC"):
        return "flac"
    if header.startswith(b"OggS"):
        return "ogg"
    if header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0):
        return "mp3"
    return None


def validate_audio_file(path: Path, filename: str) -> None:
    expected = validate_audio_filename(filename)
    detected = _audio_signature(path)
    if detected != expected:
        raise upload_error("file_type_mismatch")
    command = [
        "ffprobe", "-v", "error", "-show_entries", "format=format_name:stream=codec_type",
        "-of", "json", "-i", str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
        payload = json.loads(result.stdout)
    except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        logger.info("Rejected audio upload after probe failure: %s", type(exc).__name__)
        raise upload_error("invalid_file_content") from exc
    format_names = set((payload.get("format", {}).get("format_name") or "").split(","))
    compatible = {"wav": {"wav"}, "flac": {"flac"}, "mp3": {"mp3"}, "ogg": {"ogg"}}
    stream_types = {stream.get("codec_type") for stream in payload.get("streams", [])}
    if not compatible[expected].intersection(format_names) or stream_types != {"audio"}:
        raise upload_error("file_type_mismatch")


def validate_photo_file(path: Path, filename: str) -> None:
    expected = validate_photo_filename(filename)
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(path) as source:
            if source.format not in PHOTO_EXTENSIONS[expected]:
                raise upload_error("file_type_mismatch")
            frames = list(ImageSequence.Iterator(source))
            if not frames or len(frames) > MAX_GIF_FRAMES:
                raise upload_error("invalid_file_content")
            for frame in frames:
                frame.load()
                if frame.width * frame.height > MAX_IMAGE_PIXELS:
                    raise upload_error("invalid_file_content")
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
        raise upload_error("invalid_file_content") from exc


def sanitize_image(path: Path, filename: str, content_type: str | None) -> str:
    extension = extension_for(filename, set(IMAGE_EXTENSIONS))
    if isinstance(content_type, str) and content_type and content_type.lower() not in _IMAGE_MIME_TYPES[extension]:
        raise upload_error("file_type_mismatch")
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(path) as source:
            if source.format != IMAGE_EXTENSIONS[extension]:
                raise upload_error("file_type_mismatch")
            frames = list(ImageSequence.Iterator(source))
            if not frames or len(frames) > MAX_GIF_FRAMES:
                raise upload_error("invalid_file_content")
            sanitized = []
            for frame in frames:
                frame.load()
                if frame.width * frame.height > MAX_IMAGE_PIXELS:
                    raise upload_error("invalid_file_content")
                sanitized.append(frame.convert("RGBA") if extension in {"png", "webp"} else frame.convert("RGB"))
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
        raise upload_error("invalid_file_content") from exc

    output = path.with_name(f".{path.name}.sanitized")
    try:
        if extension == "gif" and len(sanitized) > 1:
            sanitized[0].save(output, "GIF", save_all=True, append_images=sanitized[1:], loop=0, disposal=2)
        else:
            sanitized[0].save(output, IMAGE_EXTENSIONS[extension])
        output.replace(path)
    finally:
        output.unlink(missing_ok=True)
    return extension


def validate_csv_content(content: bytes) -> str:
    if b"\x00" in content:
        raise upload_error("invalid_file_content")
    for encoding in ("utf-8-sig", "utf-8", "iso-8859-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise upload_error("invalid_file_content")
    try:
        # Strict, RFC 4180 parsing over a real stream: quoted commas/newlines are
        # handled correctly and malformed quoting is rejected, not silently fixed.
        for row in csv.reader(io.StringIO(text, newline=""), strict=True):
            if len(row) > MAX_CSV_COLUMNS or any(len(cell) > MAX_CSV_CELL_CHARS for cell in row):
                raise upload_error("invalid_file_content")
    except csv.Error as exc:
        raise upload_error("invalid_file_content") from exc
    return text


def validate_zip_file(path: Path, filename: str) -> None:
    if extension_for(filename, {"zip"}) != "zip":  # explicit for clarity at callers
        raise upload_error("unsupported_file_type")
    with path.open("rb") as source:
        signature = source.read(4)
    if signature not in {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"}:
        raise upload_error("unsafe_archive")
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise upload_error("unsafe_archive")
    except (OSError, zipfile.BadZipFile) as exc:
        raise upload_error("unsafe_archive") from exc


def audit_rejection(*, entrypoint: str, filename: str, reason: str, content: bytes | None = None) -> None:
    digest = hashlib.sha256(content).hexdigest() if content is not None else None
    logger.warning("upload_rejected entrypoint=%s filename=%s reason=%s sha256=%s", entrypoint, filename, reason, digest)
