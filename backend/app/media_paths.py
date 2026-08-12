from __future__ import annotations

from pathlib import Path, PurePosixPath

from app.core.config import settings

_TOP_LEVEL_MEDIA_DIRS = {"sounds", "images", "projects", "tmp"}


def media_root() -> Path:
    return Path(settings.MEDIA_ROOT)


def normalize_media_relative_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None

    raw = str(value).replace("\\", "/").strip()
    if not raw:
        return None

    if raw.startswith(("http://", "https://")):
        return Path(raw)

    normalized_roots = [
        str(media_root()).replace("\\", "/").rstrip("/"),
    ]
    for root in normalized_roots:
        if root and raw == root:
            return Path(".")
        if root and raw.startswith(f"{root}/"):
            raw = raw[len(root) + 1 :]
            break

    while "//" in raw:
        raw = raw.replace("//", "/")
    raw = raw.lstrip("/")

    parts = [part for part in PurePosixPath(raw).parts if part not in {"", "."}]
    if not parts:
        return None
    if ".." in parts:
        raise ValueError(f"Invalid media path: {value}")

    while len(parts) > 1 and parts[0] == "sounds" and parts[1] in _TOP_LEVEL_MEDIA_DIRS:
        parts = parts[1:]

    return Path(*parts)


def build_media_public_url(value: str | Path | None) -> str:
    if not value:
        return ""

    raw = str(value).strip()
    if raw.startswith(("http://", "https://")):
        return raw

    relative = normalize_media_relative_path(value)
    if relative is None:
        return ""

    return f"/sounds/{relative.as_posix()}"


def logical_audio_media_path(collection_id: int | str, directory: int | str, filename: str) -> Path:
    return Path("sounds") / str(collection_id) / str(directory) / filename


def logical_photo_media_path(collection_id: int | str, directory: int | str, filename: str) -> Path:
    return Path("images") / str(collection_id) / str(directory) / filename


def logical_preview_image_path(
    collection_id: int | str, directory: int | str, filename: str
) -> Path:
    return Path("images") / str(collection_id) / str(directory) / filename


def audio_filename_candidates(filename: str | None) -> list[str]:
    """
    Build audio lookup filename candidates in compatibility order.

    Order:
    1. Stored database filename as-is
    2. Same stem with .flac extension
    3. Same stem with .wav extension
    """
    if not filename:
        return []

    raw = filename.strip()
    if not raw:
        return []

    stem = Path(raw).stem
    candidates: list[str] = [raw, f"{stem}.flac", f"{stem}.wav"]
    deduped: list[str] = []
    for item in candidates:
        if item not in deduped:
            deduped.append(item)
    return deduped


def analysis_audio_filename_candidates(filename: str | None) -> list[str]:
    """
    Build AI analysis lookup candidates for supported audio formats only.

    Unsupported stored formats prefer a same-stem WAV companion before any
    FLAC fallback.
    """
    if not filename:
        return []

    raw = filename.strip()
    if not raw:
        return []

    path = Path(raw)
    stem = path.stem
    suffix = path.suffix.lower()

    if suffix == ".wav":
        candidates = [raw, f"{stem}.flac"]
    elif suffix == ".flac":
        candidates = [raw, f"{stem}.wav"]
    else:
        candidates = [f"{stem}.wav", f"{stem}.flac"]

    deduped: list[str] = []
    for item in candidates:
        if item not in deduped:
            deduped.append(item)
    return deduped


def resolve_existing_audio_media_path(
    collection_id: int | str,
    directory: int | str,
    filename: str | None,
) -> Path | None:
    """Resolve an existing audio file path using filename candidates."""
    for candidate in audio_filename_candidates(filename):
        resolved = resolve_existing_media_path(
            logical_audio_media_path(collection_id, directory, candidate)
        )
        if resolved is not None:
            return resolved
    return None


def resolve_existing_analysis_audio_media_path(
    collection_id: int | str,
    directory: int | str,
    filename: str | None,
) -> Path | None:
    """Resolve an existing WAV/FLAC path for AI analysis."""
    for candidate in analysis_audio_filename_candidates(filename):
        resolved = resolve_existing_media_path(
            logical_audio_media_path(collection_id, directory, candidate)
        )
        if resolved is not None:
            return resolved
    return None


def resolve_existing_preview_image_path(
    collection_id: int | str,
    directory: int | str,
    filename: str | None,
) -> Path | None:
    if not filename:
        return None
    return resolve_existing_media_path(
        logical_preview_image_path(collection_id, directory, filename)
    )


def logical_project_media_path(filename: str) -> Path:
    return Path("projects") / filename


def logical_category_media_path(category: str, filename: str) -> Path:
    return Path(category) / filename


def logical_pending_upload_path(user_id: int | str, filename: str) -> Path:
    return Path("tmp") / "pending" / str(user_id) / filename


def logical_chunk_dir_path(filename: str, batch_id: str | None = None) -> Path:
    base = Path("tmp") / "chunks"
    if batch_id:
        return base / str(batch_id) / filename
    return base / filename


def primary_media_path(value: str | Path) -> Path:
    relative = normalize_media_relative_path(value)
    if relative is None:
        raise ValueError("Media path cannot be empty")
    return media_root() / relative


def resolve_existing_media_path(value: str | Path) -> Path | None:
    relative = normalize_media_relative_path(value)
    if relative is None:
        return None

    primary = media_root() / relative
    if primary.exists():
        return primary
    return None


def is_safe_public_media_request_path(value: str) -> bool:
    try:
        relative = normalize_media_relative_path(value)
    except ValueError:
        return False
    # Upload chunks, pending files and offline-import extraction are quarantine
    # storage and must never be reachable through the public media endpoint.
    return (
        relative is not None
        and not str(relative).startswith("http")
        and relative.parts[0] != "tmp"
    )
