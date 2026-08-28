from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.csv_import import ImportResult, ImportRowResult
from app.services.tabular_import_service import _execute


def _report_with_succeeded_rows(*row_numbers: int) -> ImportResult:
    return ImportResult(
        rows=[ImportRowResult(row_number=number, status="succeeded") for number in row_numbers]
    )


def test_execute_keeps_write_error_on_failing_row() -> None:
    session = MagicMock()
    report = _report_with_succeeded_rows(2, 3)
    rows = [(2, SimpleNamespace(value=1)), (3, SimpleNamespace(value=2))]

    def writer(item: SimpleNamespace) -> None:
        if item.value == 2:
            raise HTTPException(status_code=404, detail="Assignee not found")

    result = _execute(session, report, rows, writer, dry_run=False)
    by_row = {row.row_number: row for row in result.rows}

    assert result.committed is False
    assert by_row[3].status == "failed"
    assert by_row[3].reason == "Assignee not found"
    assert by_row[2].status == "failed"
    assert by_row[2].reason == "No data was written because another row failed validation"
    session.rollback.assert_called_once()
    session.commit.assert_not_called()


def test_execute_reports_constraint_violation_on_write() -> None:
    session = MagicMock()
    report = _report_with_succeeded_rows(2)

    def writer(_item: SimpleNamespace) -> None:
        raise IntegrityError("INSERT", {}, Exception("fk"))

    result = _execute(session, report, [(2, SimpleNamespace())], writer, dry_run=False)

    assert result.rows[0].status == "failed"
    assert result.rows[0].reason == "Record violates a data constraint"
    session.rollback.assert_called_once()
    session.commit.assert_not_called()
