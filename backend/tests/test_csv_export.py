import csv
from datetime import UTC, date, datetime

from app.csv_export import CsvColumn, export_columns_csv


def test_export_columns_csv_uses_default_headers_and_nested_values() -> None:
    records = [
        {
            "creator": {"name": "Admin"},
            "creator_id": 1,
            "tags": ["bird", "rain"],
            "empty": None,
        }
    ]

    content = export_columns_csv(
        [
            CsvColumn("Creator", "creator.name"),
            CsvColumn("creator_id"),
            CsvColumn("tags"),
            CsvColumn("empty"),
        ],
        records,
    )

    rows = list(csv.reader(content.splitlines()))
    assert rows[0] == ["Creator", "creator_id", "tags", "empty"]
    assert rows[1] == ["Admin", "1", '["bird", "rain"]', ""]


def test_export_columns_csv_formats_datetime_and_date_values() -> None:
    """CSV exports must use the project datetime convention, not str(datetime)."""
    records = [
        {
            "created": datetime(2026, 3, 17, 14, 30, 0, tzinfo=UTC),
            "synced": datetime(2026, 4, 19, 8, 15, 30, 123456),
            "day": date(2026, 5, 1),
            "missing": None,
        }
    ]

    content = export_columns_csv(
        [
            CsvColumn("Created", "created"),
            CsvColumn("Last synced", "synced"),
            CsvColumn("Day", "day"),
            CsvColumn("Missing", "missing"),
        ],
        records,
    )

    rows = list(csv.reader(content.splitlines()))
    assert rows[1] == [
        "2026-03-17 14:30:00",
        "2026-04-19 08:15:30",
        "2026-05-01",
        "",
    ]
