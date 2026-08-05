import csv
import io
from collections.abc import Iterable

from fastapi import HTTPException
from sqlmodel import Field, SQLModel


class CsvImportRowResult(SQLModel):
    """Outcome for one physical CSV data row."""

    row_number: int
    status: str
    field: str | None = None
    reason: str | None = None


class CsvImportResult(SQLModel):
    """Uniform report returned by every CSV import."""

    total: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    committed: bool = False
    rows: list[CsvImportRowResult] = Field(default_factory=list)
    global_errors: list[str] = Field(default_factory=list)

    def finalize(self) -> "CsvImportResult":
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
                    CsvImportRowResult(
                        row_number=row_number,
                        status="skipped",
                        reason="Blank row",
                    )
                )
            else:
                self.rows.append(
                    CsvImportRowResult(
                        row_number=row_number,
                        status="failed",
                        reason=reason,
                    )
                )
        self.committed = False
        self.finalize()

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

    None of the supported import schemas use multiline values, so a field that
    contains a newline signals an unclosed quote that swallowed the next
    record; such rows are rejected to prevent silent record merging.
    """
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        raise HTTPException(status_code=422, detail=f"Malformed CSV: {exc}") from exc
    for idx, row in enumerate(rows, start=1):
        if any("\n" in cell or "\r" in cell for cell in row):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Row {idx}: unexpected newline inside a field "
                    "(check for an unclosed quote)"
                ),
            )
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
