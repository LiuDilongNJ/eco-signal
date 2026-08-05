"""Report media storage-key conflicts without modifying database or files."""

from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import text
from sqlmodel import Session

from app.core.db import engine


_CONFLICT_QUERY = text(
    """
    SELECT
        mc.collection_id,
        m.media_type,
        m.directory,
        m.filename,
        COUNT(*) AS record_count,
        COUNT(DISTINCT m.uuid) AS uuid_count,
        COUNT(DISTINCT m.md5_hash) FILTER (WHERE m.md5_hash IS NOT NULL) AS hash_count
    FROM media AS m
    JOIN media_collection AS mc ON mc.media_id = m.media_id
    WHERE m.filename IS NOT NULL AND m.directory IS NOT NULL
    GROUP BY mc.collection_id, m.media_type, m.directory, m.filename
    HAVING COUNT(*) > 1
    ORDER BY COUNT(*) DESC, mc.collection_id, m.media_type, m.directory, m.filename
    LIMIT :limit
    """
)

_SUMMARY_QUERY = text(
    """
    SELECT
        COUNT(*) AS conflict_group_count,
        COALESCE(SUM(grouped.record_count), 0) AS conflicting_record_count
    FROM (
        SELECT COUNT(*) AS record_count
        FROM media AS m
        JOIN media_collection AS mc ON mc.media_id = m.media_id
        WHERE m.filename IS NOT NULL AND m.directory IS NOT NULL
        GROUP BY mc.collection_id, m.media_type, m.directory, m.filename
        HAVING COUNT(*) > 1
    ) AS grouped
    """
)


def audit_media_storage(limit: int) -> dict[str, Any]:
    with Session(engine) as session:
        summary = session.exec(_SUMMARY_QUERY).mappings().one()
        conflicts = session.exec(_CONFLICT_QUERY, params={"limit": limit}).mappings().all()
    return {
        "conflict_group_count": int(summary["conflict_group_count"]),
        "conflicting_record_count": int(summary["conflicting_record_count"]),
        "reported_group_count": len(conflicts),
        "conflicts": [dict(row) for row in conflicts],
        "mutated": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="Maximum conflict groups to report")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    print(  # noqa: T201
        json.dumps(audit_media_storage(args.limit), ensure_ascii=False, indent=2, default=str)
    )


if __name__ == "__main__":
    main()
