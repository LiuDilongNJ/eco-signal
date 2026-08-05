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
from app.repositories.taxon_repository import RemoteTaxonLookupError, taxon_repository
from app.schemas.taxon import TaxonImportRow, TaxonListItem

_TAXON_EXPORT_COLUMNS = [
    CsvColumn("taxon_id"), CsvColumn("cached_scientific_name"),
    CsvColumn("cached_common_name"), CsvColumn("col_species_id"),
    CsvColumn("col_genus_id"), CsvColumn("col_family_id"),
    CsvColumn("col_order_id"), CsvColumn("col_class_id"),
    CsvColumn("col_species_name"), CsvColumn("col_genus_name"),
    CsvColumn("col_family_name"), CsvColumn("col_order_name"),
    CsvColumn("col_class_name"), CsvColumn("taxonomy_source"),
    CsvColumn("creation_date"), CsvColumn("last_synced"),
]


def export_taxons_csv(
    session: Session,
    filters: dict | None = None,
    order_by: str = "scientific_name",
    order_dir: str = "asc",
) -> str:
    try:
        records = taxon_repository.export_taxons(
            session=session,
            filters=filters,
            order_by=order_by,
            order_dir=order_dir,
        )
    except RemoteTaxonLookupError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    items = [TaxonListItem.model_validate(item) for item in records]
    return export_columns_csv(_TAXON_EXPORT_COLUMNS, items)


def import_taxons_csv(session: Session, text: str) -> CsvImportResult:
    # CSV headers use the settings list display labels and are matched by name,
    # so an exported taxon CSV (with extra ID/Species/timestamp columns) can be
    # re-imported directly.
    field_headers = {
        "binomial": "cached_scientific_name",
        "common_name": "cached_common_name",
        "genus": "col_genus_name",
        "family": "col_family_name",
        "taxon_order": "col_order_name",
        "class": "col_class_name",
        "source": "taxonomy_source",
    }
    fields = list(field_headers.keys())
    template_headers = {header for header in field_headers.values()}
    ignored_headers = [
        column.header
        for column in _TAXON_EXPORT_COLUMNS
        if column.header not in template_headers
    ]
    report = CsvImportResult()
    try:
        parsed_rows = parse_csv(text)
    except HTTPException as exc:
        report.global_errors.append(str(exc.detail))
        return report.finalize()
    if not parsed_rows:
        report.global_errors.append("CSV file is empty")
        return report.finalize()
    header, *data_rows = parsed_rows
    try:
        width = effective_header_width(header)
        positions = resolve_header_positions(header, field_headers, fields, ignored_headers)
    except HTTPException as exc:
        report.global_errors.append(str(exc.detail))
        report.reject_data_rows(data_rows, str(exc.detail))
        return report.finalize()
    rows: list[tuple[int, TaxonImportRow]] = []
    for row_number, row in enumerate(data_rows, start=2):
        if not row or not any(value.strip() for value in row):
            report.rows.append(CsvImportRowResult(row_number=row_number, status="skipped", reason="Blank row"))
            continue
        try:
            ensure_row_width(row, row_number, width)
        except HTTPException as exc:
            report.rows.append(CsvImportRowResult(row_number=row_number, status="failed", reason=str(exc.detail)))
            continue
        payload = {field: read_cell(row, positions, field) for field in fields}
        try:
            rows.append((row_number, TaxonImportRow(**payload)))
            report.rows.append(CsvImportRowResult(row_number=row_number, status="succeeded"))
        except ValidationError as exc:
            error = exc.errors()[0]
            report.rows.append(CsvImportRowResult(row_number=row_number, status="failed", field=str(error["loc"][-1]), reason=str(error["msg"])))
    if report.failed:
        report.reject_candidates()
        return report
    if not rows:
        report.committed = True
        return report.finalize()

    # Probe the remote dictionary and fetch all COL candidates once, instead of one
    # remote lookup per row. / 一次性探测远端字典并批量拉取候选，替代逐行远程查询。
    try:
        taxon_repository.ensure_import_dictionary(session)
        candidates = taxon_repository.prefetch_import_candidates(
            session, {row.binomial for _, row in rows}
        )
    except RemoteTaxonLookupError as exc:
        report.global_errors.append(exc.detail)
        report.reject_candidates()
        return report

    resolved_rows: list[dict[str, object]] = []
    results = {item.row_number: item for item in report.rows}
    seen: set[str] = set()
    lowest_col_ids: list[tuple[int, str]] = []
    for row_number, row in rows:
        try:
            values = taxon_repository.match_import_taxon(row, candidates)
        except RemoteTaxonLookupError as exc:
            result = results[row_number]
            result.status, result.field, result.reason = "failed", "binomial", exc.detail
            continue
        key = str(values["lowest_col_id"]).casefold()
        if key in seen:
            results[row_number].status, results[row_number].field, results[row_number].reason = "skipped", "binomial", "Duplicate taxon in file"
            continue
        seen.add(key)
        resolved_rows.append(values)
        lowest_col_ids.append((row_number, key))

    # Single existence query for the whole batch, still reporting the first conflicting row.
    existing = taxon_repository.get_existing_lowest_col_ids(session, {key for _, key in lowest_col_ids})
    kept_rows: list[dict[str, object]] = []
    for (row_number, key), values in zip(lowest_col_ids, resolved_rows):
        if key in existing:
            results[row_number].status, results[row_number].field, results[row_number].reason = "skipped", "binomial", "Taxon already exists"
            continue
        kept_rows.append(values)
    report.finalize()
    if report.failed:
        report.reject_candidates()
        return report
    if kept_rows:
        taxon_repository.create_imported_taxons(session, kept_rows)
    report.committed = True
    return report.finalize()
