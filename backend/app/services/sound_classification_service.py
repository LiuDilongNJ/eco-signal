from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session

from app.csv_export import CsvColumn, export_columns_csv
from app.csv_import import (
    CsvImportResult,
    CsvImportRowResult,
    effective_header_width,
    ensure_row_width,
    parse_csv,
    read_cell,
    resolve_header_positions,
)
from app.repositories.sound_classification_repository import (
    sound_classification_repository,
)
from app.schemas.sound_classification import (
    SoundClassificationCreate,
    SoundClassificationPublic,
    SoundClassificationUpdate,
    SoundClassificationWrite,
)

# Import CSV headers use the settings list display labels; field key -> header.
_IMPORT_FIELD_HEADERS = {
    "soundscape_component": "soundscape_component",
    "sound_type": "sound_type",
}

_EXPORT_COLUMNS = [
    CsvColumn("sound_id"),
    CsvColumn("soundscape_component"),
    CsvColumn("sound_type"),
]

# Export-only display columns tolerated (ignored) on import.
_IMPORT_IGNORED_HEADERS = [
    column.header
    for column in _EXPORT_COLUMNS
    if column.header not in set(_IMPORT_FIELD_HEADERS.values())
]


def list_sound_classifications(
    session: Session,
    page: int,
    page_size: int,
    filters: dict,
    order_by: str,
    order_dir: str,
) -> tuple[list[SoundClassificationPublic], int]:
    items, total = sound_classification_repository.list_page(
        session, page, page_size, filters, order_by, order_dir
    )
    return [SoundClassificationPublic.model_validate(item) for item in items], total


def get_sound_classification(session: Session, sound_id: int) -> SoundClassificationPublic:
    item = sound_classification_repository.get(session, sound_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Sound classification not found")
    return SoundClassificationPublic.model_validate(item)


def create_sound_classification(
    session: Session,
    data: SoundClassificationCreate,
) -> SoundClassificationPublic:
    if sound_classification_repository.has_duplicate(session, data):
        raise HTTPException(status_code=409, detail="Sound classification already exists")
    item = sound_classification_repository.create(session, data)
    return SoundClassificationPublic.model_validate(item)


def update_sound_classification(
    session: Session,
    sound_id: int,
    data: SoundClassificationUpdate,
) -> SoundClassificationPublic:
    item = sound_classification_repository.get(session, sound_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Sound classification not found")
    if sound_classification_repository.is_referenced(session, sound_id):
        raise HTTPException(
            status_code=409,
            detail="Sound classification is referenced by annotation records",
        )
    if sound_classification_repository.has_duplicate(session, data, exclude_id=sound_id):
        raise HTTPException(status_code=409, detail="Sound classification already exists")
    item = sound_classification_repository.update(session, item, data)
    return SoundClassificationPublic.model_validate(item)


def delete_sound_classification(session: Session, sound_id: int) -> None:
    item = sound_classification_repository.get(session, sound_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Sound classification not found")
    if sound_classification_repository.is_referenced(session, sound_id):
        raise HTTPException(
            status_code=409,
            detail="Sound classification is referenced by annotation records",
        )
    sound_classification_repository.delete(session, item)


def export_sound_classifications_csv(
    session: Session,
    order_by: str,
    order_dir: str,
) -> str:
    items = sound_classification_repository.list_for_export(session, order_by, order_dir)
    return export_columns_csv(_EXPORT_COLUMNS, [SoundClassificationPublic.model_validate(item) for item in items])


def import_sound_classifications_csv(
    session: Session,
    text: str,
) -> CsvImportResult:
    report = CsvImportResult()
    try:
        parsed = parse_csv(text)
    except HTTPException as exc:
        report.global_errors.append(str(exc.detail))
        return report.finalize()
    if not parsed:
        report.global_errors.append("CSV file is empty")
        return report.finalize()
    header, *data_rows = parsed
    try:
        width = effective_header_width(header)
        positions = resolve_header_positions(header, _IMPORT_FIELD_HEADERS, _IMPORT_FIELD_HEADERS.keys(), _IMPORT_IGNORED_HEADERS)
    except HTTPException as exc:
        report.global_errors.append(str(exc.detail))
        report.reject_data_rows(data_rows, str(exc.detail))
        return report.finalize()
    rows: list[tuple[int, SoundClassificationWrite]] = []
    for row_number, row in enumerate(data_rows, start=2):
        if not row or not any(cell.strip() for cell in row):
            report.rows.append(CsvImportRowResult(row_number=row_number, status="skipped", reason="Blank row"))
            continue
        try:
            ensure_row_width(row, row_number, width)
            item = SoundClassificationWrite(soundscape_component=read_cell(row, positions, "soundscape_component"), sound_type=read_cell(row, positions, "sound_type"))
        except HTTPException as exc:
            report.rows.append(CsvImportRowResult(row_number=row_number, status="failed", reason=str(exc.detail)))
        except ValidationError as exc:
            error = exc.errors()[0]
            report.rows.append(CsvImportRowResult(row_number=row_number, status="failed", field=str(error["loc"][-1]), reason=str(error["msg"])))
        else:
            rows.append((row_number, item))
            report.rows.append(CsvImportRowResult(row_number=row_number, status="succeeded"))
    if report.failed:
        report.reject_candidates()
        return report
    # Bulk-load existing normalized keys once instead of one COUNT query per CSV row.
    existing = sound_classification_repository.get_existing_keys(session)
    seen: set[tuple[str, str | None]] = set()
    results = {item.row_number: item for item in report.rows}
    accepted: list[SoundClassificationWrite] = []
    for row_number, row in rows:
        key = (row.soundscape_component.casefold(), row.sound_type.casefold() if row.sound_type else None)
        if key in seen:
            results[row_number].status, results[row_number].field, results[row_number].reason = "skipped", "soundscape_component", "Duplicate sound classification in file"
            continue
        seen.add(key)
        if key in existing:
            results[row_number].status, results[row_number].field, results[row_number].reason = "skipped", "soundscape_component", "Sound classification already exists"
            continue
        accepted.append(row)
    report.finalize()
    if report.failed:
        report.reject_candidates()
        return report
    try:
        sound_classification_repository.create_many(session, accepted)
    except Exception:
        session.rollback()
        raise
    report.committed = True
    return report.finalize()
