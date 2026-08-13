import csv
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from migration_audit import AUDIT_COLUMNS, MigrationAudit, write_audit_csv  # noqa: E402


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_audit_deduplicates_by_source_issue_and_field():
    audit = MigrationAudit()
    for target_value in ("first", "second"):
        audit.record(
            source_table="recording", source_id=1, target_table="media", target_id=1,
            issue_type="field_mismatch", severity="error", field_name="filename",
            source_value="source.wav", target_value=target_value, reason="Different values.",
            recommended_action="Repair the target value.",
        )

    assert len(audit.issues) == 1
    assert audit.issues[0].target_value == "first"


def test_write_audit_csv_writes_header_and_all_rows(tmp_path):
    audit = MigrationAudit()
    audit.record(
        source_table="recording", source_id=5, target_table="media", target_id=5,
        issue_type="file_missing", severity="error", field_name="filename",
        source_value="missing.wav", reason="Audio file missing.",
        recommended_action="Restore the file.",
    )
    audit.record(
        source_table="queue", source_id=7, target_table="queue", target_id=7,
        issue_type="unsupported_value", severity="warning", field_name="status",
        source_value=99, target_value=3, reason="Unknown status.",
        recommended_action="Review the target status.",
    )
    output = tmp_path / "audit.csv"

    assert write_audit_csv(audit, output) is True

    with output.open(encoding="utf-8-sig", newline="") as handle:
        assert next(csv.reader(handle)) == AUDIT_COLUMNS

    rows = _read_csv_rows(output)
    assert [row["source_table"] for row in rows] == ["recording", "queue"]
    assert rows[0]["issue_type"] == "file_missing"
    assert rows[0]["target_value"] == ""
    assert rows[1]["source_value"] == "99"


def test_write_audit_csv_preserves_non_ascii_values(tmp_path):
    audit = MigrationAudit()
    audit.record(
        source_table="site", source_id=3, target_table="site", target_id=3,
        issue_type="enrichment_unresolved", severity="warning", field_name="gadm0",
        source_value="Côte d'Ivoire", reason="未能解析该地理名称。",
        recommended_action="Correct the geographic name.",
    )
    output = tmp_path / "audit.csv"

    assert write_audit_csv(audit, output) is True

    rows = _read_csv_rows(output)
    assert rows[0]["source_value"] == "Côte d'Ivoire"
    assert rows[0]["reason"] == "未能解析该地理名称。"


def test_write_audit_csv_skips_empty_audit(tmp_path):
    output = tmp_path / "audit.csv"

    assert write_audit_csv(MigrationAudit(), output) is False
    assert not output.exists()
