import csv
import io
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlmodel import Field, SQLModel

MAX_IMPORT_FILE_BYTES = 20 * 1024 * 1024
MAX_IMPORT_ROWS = 50_000
MAX_IMPORT_COLUMNS = 256
SUPPORTED_IMPORT_EXTENSIONS = {"csv", "txt", "json"}
SUPPORTED_DELIMITERS = (",", "\t", ";", "|")


class ImportRowResult(SQLModel):
    """Outcome for one physical source record."""

    row_number: int
    status: str
    field: str | None = None
    reason: str | None = None


class ImportResult(SQLModel):
    """Uniform report returned by every tabular import."""

    source_format: str = "delimited_text"
    delimiter: str | None = ","
    dry_run: bool = False
    total: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    committed: bool = False
    rows: list[ImportRowResult] = Field(default_factory=list)
    global_errors: list[str] = Field(default_factory=list)

    def finalize(self) -> "ImportResult":
        self.total = len(self.rows)
        self.succeeded = sum(row.status == "succeeded" for row in self.rows)
        self.skipped = sum(row.status == "skipped" for row in self.rows)
        self.failed = sum(row.status == "failed" for row in self.rows)
        return self

    def reject_candidates(self) -> None:
        """Make an atomic rollback visible in the per-row report."""
        for row in self.rows:
            if row.status == "succeeded":
                row.status = "failed"
                row.field = None
                row.reason = "No data was written because another row failed validation"
        self.committed = False
        self.finalize()

    def reject_data_rows(
        self,
        data_rows: Iterable[list[str]],
        reason: str,
        *,
        start_row: int = 2,
    ) -> None:
        """Report every non-blank data row rejected by a shared validation error."""
        for row_number, row in enumerate(data_rows, start=start_row):
            if not row or not any(value.strip() for value in row):
                self.rows.append(
                    ImportRowResult(
                        row_number=row_number,
                        status="skipped",
                        reason="Blank row",
                    )
                )
            else:
                self.rows.append(
                    ImportRowResult(
                        row_number=row_number,
                        status="failed",
                        reason=reason,
                    )
                )
        self.committed = False
        self.finalize()


@dataclass(frozen=True)
class ParsedImport:
    """Normalized upload consumed by existing and new resource importers."""

    text: str
    source_format: str
    delimiter: str | None


def _decode_import_content(content: bytes) -> str:
    if not content or len(content) > MAX_IMPORT_FILE_BYTES or b"\x00" in content:
        raise HTTPException(status_code=400, detail="invalid_file_content")
    for encoding in ("utf-8-sig", "utf-8", "iso-8859-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=400, detail="invalid_file_content")


def _detect_delimiter(text: str) -> str:
    if not text.strip():
        raise HTTPException(status_code=400, detail="empty_import_file")

    candidates: list[str] = []
    for delimiter in SUPPORTED_DELIMITERS:
        try:
            parsed = []
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
            for row in reader:
                if row and any(cell.strip() for cell in row):
                    parsed.append(row)
                if len(parsed) >= 20:
                    break
        except csv.Error:
            continue
        widths = {len(row) for row in parsed if row and any(cell.strip() for cell in row)}
        if len(widths) == 1 and next(iter(widths), 0) > 1:
            candidates.append(delimiter)
    if not candidates:
        raise HTTPException(status_code=400, detail="unknown_delimiter")
    if len(candidates) > 1:
        raise HTTPException(status_code=400, detail="ambiguous_delimiter")
    return candidates[0]


def _normalize_delimited_text(text: str) -> tuple[str, str]:
    delimiter = _detect_delimiter(text)
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True))
    except csv.Error as exc:
        raise HTTPException(status_code=400, detail="malformed_delimited_text") from exc
    data_rows = [row for row in rows[1:] if row and any(cell.strip() for cell in row)]
    if rows and len(rows[0]) > MAX_IMPORT_COLUMNS:
        raise HTTPException(status_code=400, detail="too_many_import_columns")
    if len(data_rows) > MAX_IMPORT_ROWS:
        raise HTTPException(status_code=400, detail="too_many_import_rows")
    output = io.StringIO(newline="")
    csv.writer(output).writerows(rows)
    return output.getvalue(), delimiter


def _normalize_json_text(text: str) -> str:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="malformed_json") from exc
    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="json_array_required")
    if len(payload) > MAX_IMPORT_ROWS:
        raise HTTPException(status_code=400, detail="too_many_import_rows")
    if any(not isinstance(item, dict) for item in payload):
        raise HTTPException(status_code=400, detail="json_object_rows_required")

    headers: list[str] = []
    for item in payload:
        for key in item:
            if not isinstance(key, str):
                raise HTTPException(status_code=400, detail="json_string_keys_required")
            if key not in headers:
                headers.append(key)
                if len(headers) > MAX_IMPORT_COLUMNS:
                    raise HTTPException(status_code=400, detail="too_many_import_columns")
    if not headers:
        return ""

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    for item in payload:
        values: list[str] = []
        for header in headers:
            value: Any = item.get(header)
            if value is None:
                values.append("")
            elif isinstance(value, (dict, list)):
                values.append(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
            elif isinstance(value, bool):
                values.append("true" if value else "false")
            else:
                values.append(str(value))
        writer.writerow(values)
    return output.getvalue()


def parse_import_upload(filename: str, content: bytes) -> ParsedImport:
    """Validate and normalize a CSV, delimited text, or JSON upload."""
    if not filename or filename != Path(filename).name:
        raise HTTPException(status_code=400, detail="invalid_filename")
    extension = Path(filename).suffix.lower().lstrip(".")
    if extension not in SUPPORTED_IMPORT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported_file_type")
    text = _decode_import_content(content).strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty_import_file")

    looks_like_json = text.startswith("[")
    if extension == "json":
        normalized = _normalize_json_text(text)
        return ParsedImport(normalized, "json", None)
    if extension == "csv" and looks_like_json:
        raise HTTPException(status_code=400, detail="file_type_mismatch")
    if extension == "txt" and looks_like_json:
        normalized = _normalize_json_text(text)
        return ParsedImport(normalized, "json", None)
    normalized, delimiter = _normalize_delimited_text(text)
    return ParsedImport(normalized, "delimited_text", delimiter)


def attach_import_metadata(
    report: ImportResult,
    parsed: ParsedImport,
    *,
    dry_run: bool,
) -> ImportResult:
    """Attach transport metadata and normalize JSON array positions."""
    report.source_format = parsed.source_format
    report.delimiter = parsed.delimiter
    report.dry_run = dry_run
    if parsed.source_format == "json":
        for row in report.rows:
            row.row_number = max(1, row.row_number - 1)
    return report.finalize()

# Shared CSV import header handling used by every settings/metadata importer.
# Columns are matched by display header name (case-insensitive) rather than by
# position, so exported files whose columns are reordered or carry extra
# display-only columns (ID, UUID, relationship counts, timestamps) can be
# re-imported directly: known extra columns are ignored, unknown or duplicated
# columns and missing required columns abort the import with HTTP 422.


def parse_csv(text: str) -> list[list[str]]:
    """
    Parse CSV text strictly (RFC 4180) into rows.

    Uses a strict reader over a real stream so quoted fields containing commas
    or newlines are handled correctly and malformed quoting is rejected instead
    of being silently "fixed". Malformed CSV raises HTTP 422.

    Quoted fields may contain line breaks as allowed by RFC 4180.
    """
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        raise HTTPException(status_code=422, detail=f"Malformed CSV: {exc}") from exc
    return rows


def effective_header_width(header: list[str]) -> int:
    """Column count ignoring trailing blank header cells (spreadsheet artifacts).

    Data rows are validated against this instead of len(header) so an extra
    trailing value cannot silently line up with a blank trailing header column.
    """
    width = len(header)
    while width > 0 and not header[width - 1].strip():
        width -= 1
    return width


def ensure_row_width(row: list[str], row_num: int, expected_width: int) -> None:
    """Reject a data row whose field count differs from the header column count."""
    if len(row) != expected_width:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Row {row_num}: expected {expected_width} columns to match "
                f"header, got {len(row)}"
            ),
        )


def resolve_header_positions(
    header: list[str],
    field_headers: dict[str, str],
    required_fields: Iterable[str],
    ignored_headers: Iterable[str] = (),
) -> dict[str, int]:
    """
    Map internal field keys to their column index in the CSV header.

    `field_headers` maps each importable field key to its display header.
    `ignored_headers` are extra headers (typically export-only columns) that are
    skipped without error. Unknown, duplicated or missing required headers raise
    HTTP 422 so field misalignment can never happen silently.
    """
    header_to_field = {label.lower(): field for field, label in field_headers.items()}
    ignored = {value.lower() for value in ignored_headers}
    positions: dict[str, int] = {}
    for idx, cell in enumerate(header):
        key = cell.strip().lower()
        if not key:
            # Tolerate trailing blank header cells produced by spreadsheet tools.
            continue
        if key in ignored:
            continue
        field = header_to_field.get(key)
        if field is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Header: unrecognized column {cell.strip()!r}; "
                    f"expected columns: {', '.join(field_headers.values())}"
                ),
            )
        if field in positions:
            raise HTTPException(
                status_code=422,
                detail=f"Header: duplicate column {cell.strip()!r}",
            )
        positions[field] = idx

    missing = [
        field_headers[field] for field in required_fields if field not in positions
    ]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Header: missing required column(s): {', '.join(missing)}",
        )
    return positions


def read_cell(row: list[str], positions: dict[str, int], field: str) -> str:
    """Read a cell by field key; absent column or short row yields an empty string."""
    idx = positions.get(field)
    if idx is None or idx >= len(row):
        return ""
    return row[idx].strip()
