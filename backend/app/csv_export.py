import csv
import io
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from pydantic import BaseModel

# Project-wide API/CSV datetime convention (matches schema field serializers).
_CSV_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_CSV_DATE_FORMAT = "%Y-%m-%d"


@dataclass(frozen=True)
class CsvColumn:
    """A CSV column that defaults to reading the field named by its header."""

    header: str
    value: str | Callable[[Any], Any] | None = None


def get_schema_csv_fields(schema_cls: type[BaseModel]) -> list[str]:
    """Return response fields in the same order as the API item schema."""
    fields = list(schema_cls.model_fields.keys())
    computed_fields = getattr(schema_cls, "model_computed_fields", {}) or {}
    return fields + [name for name in computed_fields if name not in fields]


def export_schema_csv(schema_cls: type[BaseModel], records: Iterable[Any]) -> str:
    """Serialize schema-shaped records to CSV using the schema's public fields."""
    fieldnames = get_schema_csv_fields(schema_cls)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for record in records:
        schema_obj = record if isinstance(record, schema_cls) else schema_cls.model_validate(record)
        data = schema_obj.model_dump(mode="json")
        writer.writerow({field: _csv_cell(data.get(field)) for field in fieldnames})

    return output.getvalue()


def export_columns_csv(columns: list[CsvColumn], records: Iterable[Any]) -> str:
    """Serialize records to CSV using display headers and explicit value mappings."""
    fieldnames = [column.header for column in columns]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for record in records:
        writer.writerow(
            {
                column.header: _csv_cell(
                    _column_value(record, column.value if column.value is not None else column.header)
                )
                for column in columns
            }
        )

    return output.getvalue()


def _column_value(record: Any, value: str | Callable[[Any], Any]) -> Any:
    if callable(value):
        return value(record)
    if not isinstance(value, str):
        return value
    current = record
    for part in value.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def _csv_cell(value: Any) -> Any:
    if value is None:
        return ""
    # Path-based exports read raw model attributes, so datetime/date must be
    # formatted here (schema field serializers only run on model_dump).
    if isinstance(value, datetime):
        return value.strftime(_CSV_DATETIME_FORMAT)
    if isinstance(value, date):
        return value.strftime(_CSV_DATE_FORMAT)
    if isinstance(value, list | dict):
        return json.dumps(value, ensure_ascii=False)
    return value
