"""Disk-backed migration audit records and streaming CSV export helpers."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

AUDIT_COLUMNS = [
    "source_table", "source_id", "target_table", "target_id", "issue_type", "severity",
    "field_name", "source_value", "target_value", "reason", "recommended_action",
]


@dataclass(frozen=True)
class MigrationAuditIssue:
    source_table: str
    source_id: str
    target_table: str | None
    target_id: str | None
    issue_type: str
    severity: str
    field_name: str | None
    source_value: Any
    target_value: Any
    reason: str
    recommended_action: str


class MigrationAudit:
    """Append row-level audit issues to disk without retaining their values in memory."""

    def __init__(self) -> None:
        fd, name = tempfile.mkstemp(prefix="ecosignal-migration-audit-", suffix=".jsonl")
        os.close(fd)
        Path(name).touch(exist_ok=True)
        self._path = Path(name)
        self._keys: set[tuple[str, str, str, str | None]] = set()
        self.count = 0

    @property
    def issues(self) -> list[MigrationAuditIssue]:
        return list(self.iter_issues())

    def iter_issues(self) -> Iterator[MigrationAuditIssue]:
        with self._path.open(encoding="utf-8") as handle:
            for line in handle:
                yield MigrationAuditIssue(**json.loads(line))

    def add(self, issue: MigrationAuditIssue) -> None:
        key = (issue.source_table, issue.source_id, issue.issue_type, issue.field_name)
        if key in self._keys:
            return
        self._keys.add(key)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(issue), default=str, ensure_ascii=False) + "\n")
        self.count += 1

    def record(self, **kwargs: Any) -> None:
        self.add(MigrationAuditIssue(
            source_table=kwargs["source_table"], source_id=str(kwargs["source_id"]),
            target_table=kwargs.get("target_table"),
            target_id=None if kwargs.get("target_id") is None else str(kwargs["target_id"]),
            issue_type=kwargs["issue_type"], severity=kwargs["severity"],
            field_name=kwargs.get("field_name"), source_value=kwargs.get("source_value"),
            target_value=kwargs.get("target_value"), reason=kwargs["reason"],
            recommended_action=kwargs["recommended_action"],
        ))


def write_audit_csv(audit: MigrationAudit, output_path: Path) -> bool:
    """Stream the disk-backed audit into one CSV, keeping the order the issues were recorded in."""
    if audit.count == 0:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # BOM so spreadsheet tools detect UTF-8 when opening the file directly.
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_COLUMNS)
        writer.writeheader()
        for issue in audit.iter_issues():
            writer.writerow(asdict(issue))
    return True
