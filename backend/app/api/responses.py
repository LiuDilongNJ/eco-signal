import re
from pathlib import Path
from urllib.parse import quote

from fastapi.responses import StreamingResponse

_HEADER_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")
_HEADER_SAFE_EXTENSION_RE = re.compile(r"[^A-Za-z0-9.]+")


def _build_ascii_fallback_filename(filename: str) -> str:
    """Build an ASCII-only fallback filename for Content-Disposition."""
    candidate = Path((filename or "").strip()).name or "download"
    suffix = Path(candidate).suffix
    stem = candidate[: -len(suffix)] if suffix else candidate

    safe_stem = _HEADER_SAFE_FILENAME_RE.sub("_", stem).strip(" ._")
    if not re.search(r"[A-Za-z0-9]", safe_stem):
        safe_stem = "download"

    safe_suffix = _HEADER_SAFE_EXTENSION_RE.sub("", suffix)
    if safe_suffix and not safe_suffix.startswith("."):
        safe_suffix = f".{safe_suffix}"

    return f"{safe_stem}{safe_suffix}"


def build_download_content_disposition(filename: str) -> str:
    """Return an RFC 5987 compatible attachment header for downloads."""
    original_name = Path((filename or "").strip()).name or "download"
    fallback_name = _build_ascii_fallback_filename(original_name)
    encoded_name = quote(original_name, safe="!#$&+-.^_`|~")
    return (
        f'attachment; filename="{fallback_name}"; '
        f"filename*=UTF-8''{encoded_name}"
    )


def csv_response(content: str, filename: str) -> StreamingResponse:
    """Return a CSV download response with consistent headers."""
    # Prefix UTF-8 BOM so spreadsheet apps on some systems detect Chinese text correctly.
    payload = "\ufeff" + content
    return StreamingResponse(
        iter([payload]),
        media_type="text/csv",
        headers={"Content-Disposition": build_download_content_disposition(filename)},
    )
