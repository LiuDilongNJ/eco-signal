"""
Import Catalogue of Life XR data into geo_db.

This script is designed for large XR TSV bundles and supports:
- validate: verify files and headers
- normalize: extract accepted species rows from NameUsage.tsv
- import: load normalized data + vernacular names into geo_db
- run-all: validate + normalize + import
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from import_geo_data import get_geo_db_url

log = logging.getLogger(__name__)

DEFAULT_INPUT_DIR = Path("/Volumes/code/python/ecoSignal/data/col_xr_263")
DEFAULT_RUN_ID = "col_xr_263"
DEFAULT_BATCH_SIZE = 20_000
WORKING_ROOT = Path("/app/data/col/working")
LOG_ROOT = Path("/app/data/col/logs")

REQUIRED_FILES = ("NameUsage.tsv", "VernacularName.tsv", "metadata.yaml")
REQUIRED_NAMEUSAGE_COLS = {
    "col:ID",
    "col:parentID",
    "col:status",
    "col:scientificName",
    "col:rank",
    "col:genus",
    "col:family",
    "col:order",
    "col:class",
}
REQUIRED_VERNACULAR_COLS = {
    "col:taxonID",
    "col:name",
    "col:language",
    "col:preferred",
}

RANK_SPECIES = "species"
RANK_GENUS = "genus"
RANK_FAMILY = "family"
RANK_ORDER = "order"
RANK_CLASS = "class"
TARGET_LINEAGE_RANKS = (RANK_GENUS, RANK_FAMILY, RANK_ORDER, RANK_CLASS)


@dataclass
class RunStats:
    run_id: str
    source_alias: str
    input_dir: str
    nameusage_rows: int = 0
    accepted_species_rows: int = 0
    vernacular_rows: int = 0
    vernacular_matched_rows: int = 0
    vernacular_assigned_rows: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    started_at: datetime = datetime.now(UTC)
    finished_at: datetime | None = None
    status: str = "running"
    error_message: str | None = None

    def as_log_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "source_alias": self.source_alias,
            "input_dir": self.input_dir,
            "nameusage_rows": self.nameusage_rows,
            "accepted_species_rows": self.accepted_species_rows,
            "vernacular_rows": self.vernacular_rows,
            "vernacular_matched_rows": self.vernacular_matched_rows,
            "vernacular_assigned_rows": self.vernacular_assigned_rows,
            "rows_inserted": self.rows_inserted,
            "rows_updated": self.rows_updated,
            "status": self.status,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


def _bool_from_text(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"true", "1", "yes", "y"}


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def _score_vernacular(language: str | None, preferred: bool) -> int:
    # Higher score wins.
    lang = (language or "").strip().lower()
    if lang == "eng" and preferred:
        return 4
    if lang == "eng":
        return 3
    if preferred:
        return 2
    return 1


def _configure_csv_field_limit() -> None:
    # XR bundles can contain very large text fields; raise parser limit defensively.
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def _read_metadata_alias(metadata_file: Path) -> str:
    alias = "COL-XR"
    for line in metadata_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith("alias:"):
            parsed = line.split(":", 1)[1].strip()
            if parsed:
                alias = parsed
            break
    return alias


def _normalize_rank(value: str | None) -> str | None:
    cleaned = _normalize_text(value)
    return cleaned.lower() if cleaned else None


def _build_nameusage_index(nameusage_file: Path) -> dict[str, dict[str, str | None]]:
    index: dict[str, dict[str, str | None]] = {}
    with nameusage_file.open("r", encoding="utf-8", newline="") as src:
        reader = csv.DictReader(src, delimiter="\t")
        for row in reader:
            taxon_id = _normalize_text(row.get("col:ID"))
            if not taxon_id:
                continue
            index[taxon_id] = {
                "parent_id": _normalize_text(row.get("col:parentID")),
                "rank": _normalize_rank(row.get("col:rank")),
                "scientific_name": _normalize_text(row.get("col:scientificName")),
            }
    return index


def _resolve_lineage_ids(
    taxon_id: str,
    nameusage_index: dict[str, dict[str, str | None]],
) -> dict[str, str | None]:
    resolved = {
        "col_genus_id": None,
        "col_family_id": None,
        "col_order_id": None,
        "col_class_id": None,
    }
    current_id = taxon_id
    visited: set[str] = set()

    while current_id and current_id not in visited:
        visited.add(current_id)
        node = nameusage_index.get(current_id)
        if node is None:
            break

        rank = node.get("rank")
        if rank == RANK_GENUS:
            resolved["col_genus_id"] = current_id
        elif rank == RANK_FAMILY:
            resolved["col_family_id"] = current_id
        elif rank == RANK_ORDER:
            resolved["col_order_id"] = current_id
        elif rank == RANK_CLASS:
            resolved["col_class_id"] = current_id

        if all(resolved[f"col_{rank_name}_id"] for rank_name in TARGET_LINEAGE_RANKS):
            break

        parent_id = node.get("parent_id")
        if not parent_id:
            break
        current_id = parent_id

    return resolved


def _resolve_lineage(
    taxon_id: str,
    nameusage_index: dict[str, dict[str, str | None]],
) -> dict[str, str | None]:
    resolved = {
        "col_genus_id": None,
        "col_genus_name": None,
        "col_family_id": None,
        "col_family_name": None,
        "col_order_id": None,
        "col_order_name": None,
        "col_class_id": None,
        "col_class_name": None,
    }
    current_id = taxon_id
    visited: set[str] = set()

    while current_id and current_id not in visited:
        visited.add(current_id)
        node = nameusage_index.get(current_id)
        if node is None:
            break

        rank = node.get("rank")
        scientific_name = node.get("scientific_name")
        if rank == RANK_GENUS:
            resolved["col_genus_id"] = current_id
            resolved["col_genus_name"] = scientific_name
        elif rank == RANK_FAMILY:
            resolved["col_family_id"] = current_id
            resolved["col_family_name"] = scientific_name
        elif rank == RANK_ORDER:
            resolved["col_order_id"] = current_id
            resolved["col_order_name"] = scientific_name
        elif rank == RANK_CLASS:
            resolved["col_class_id"] = current_id
            resolved["col_class_name"] = scientific_name

        if all(resolved[f"col_{rank_name}_id"] for rank_name in TARGET_LINEAGE_RANKS):
            break

        parent_id = node.get("parent_id")
        if not parent_id:
            break
        current_id = parent_id

    return resolved


def _ensure_input_files(input_dir: Path) -> None:
    for filename in REQUIRED_FILES:
        path = input_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing required file: {path}")


def _validate_headers(input_dir: Path) -> tuple[list[str], list[str]]:
    nameusage_file = input_dir / "NameUsage.tsv"
    vernacular_file = input_dir / "VernacularName.tsv"

    with nameusage_file.open("r", encoding="utf-8", newline="") as f:
        nameusage_header = f.readline().rstrip("\n").split("\t")
    with vernacular_file.open("r", encoding="utf-8", newline="") as f:
        vernacular_header = f.readline().rstrip("\n").split("\t")

    missing_nameusage = sorted(REQUIRED_NAMEUSAGE_COLS - set(nameusage_header))
    missing_vernacular = sorted(REQUIRED_VERNACULAR_COLS - set(vernacular_header))
    if missing_nameusage:
        raise ValueError(f"NameUsage.tsv missing columns: {missing_nameusage}")
    if missing_vernacular:
        raise ValueError(f"VernacularName.tsv missing columns: {missing_vernacular}")
    return nameusage_header, vernacular_header


def validate(input_dir: Path) -> dict[str, Any]:
    _ensure_input_files(input_dir)
    nameusage_header, vernacular_header = _validate_headers(input_dir)
    alias = _read_metadata_alias(input_dir / "metadata.yaml")
    payload = {
        "input_dir": str(input_dir),
        "source_alias": alias,
        "nameusage_header_columns": len(nameusage_header),
        "vernacular_header_columns": len(vernacular_header),
        "required_files_ok": True,
    }
    log.info("Validation completed: %s", payload)
    return payload


def normalize(input_dir: Path, run_id: str, stats: RunStats) -> Path:
    working_dir = WORKING_ROOT / run_id
    working_dir.mkdir(parents=True, exist_ok=True)
    output_file = working_dir / "species_accepted.tsv"
    nameusage_file = input_dir / "NameUsage.tsv"
    nameusage_index = _build_nameusage_index(nameusage_file)

    with (
        nameusage_file.open("r", encoding="utf-8", newline="") as src,
        output_file.open("w", encoding="utf-8", newline="") as dst,
    ):
        reader = csv.DictReader(src, delimiter="\t")
        fieldnames = [
            "col_species_id",
            "cached_scientific_name",
            "cached_common_name",
            "col_genus_id",
            "col_genus_name",
            "col_family_id",
            "col_family_name",
            "col_order_id",
            "col_order_name",
            "col_class_id",
            "col_class_name",
        ]
        writer = csv.DictWriter(dst, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()

        for row in reader:
            stats.nameusage_rows += 1
            rank = _normalize_rank(row.get("col:rank"))
            status = _normalize_rank(row.get("col:status"))
            if rank != RANK_SPECIES or status != "accepted":
                continue

            species_id = _normalize_text(row.get("col:ID"))
            if not species_id:
                continue
            lineage = _resolve_lineage(species_id, nameusage_index)

            writer.writerow(
                {
                    "col_species_id": species_id,
                    "cached_scientific_name": _normalize_text(row.get("col:scientificName")) or "",
                    "cached_common_name": "",
                    "col_genus_id": lineage["col_genus_id"] or "",
                    "col_genus_name": lineage["col_genus_name"] or "",
                    "col_family_id": lineage["col_family_id"] or "",
                    "col_family_name": lineage["col_family_name"] or "",
                    "col_order_id": lineage["col_order_id"] or "",
                    "col_order_name": lineage["col_order_name"] or "",
                    "col_class_id": lineage["col_class_id"] or "",
                    "col_class_name": lineage["col_class_name"] or "",
                }
            )
            stats.accepted_species_rows += 1

    log.info(
        "Normalization completed. accepted species=%d output=%s",
        stats.accepted_species_rows,
        output_file,
    )
    return output_file


def _ensure_geo_tables(conn) -> None:
    species_table_exists = bool(conn.execute(text("SELECT to_regclass('public.col_xr_taxon_species') IS NOT NULL")).scalar_one())
    import_run_table_exists = bool(conn.execute(text("SELECT to_regclass('public.col_xr_import_run') IS NOT NULL")).scalar_one())

    conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    if not species_table_exists:
        conn.execute(
            text(
                """
                CREATE TABLE col_xr_taxon_species (
                  col_species_id VARCHAR(64) PRIMARY KEY,
                  cached_scientific_name VARCHAR(255),
                  cached_common_name VARCHAR(255),
                  col_genus_id VARCHAR(64),
                  col_genus_name VARCHAR(255),
                  col_family_id VARCHAR(64),
                  col_family_name VARCHAR(255),
                  col_order_id VARCHAR(64),
                  col_order_name VARCHAR(255),
                  col_class_id VARCHAR(64),
                  col_class_name VARCHAR(255),
                  taxonomy_source VARCHAR(50) NOT NULL DEFAULT 'CatalogueOfLife-XR',
                  run_id VARCHAR(64) NOT NULL,
                  imported_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    if not import_run_table_exists:
        conn.execute(
            text(
                """
                CREATE TABLE col_xr_import_run (
                  id BIGSERIAL PRIMARY KEY,
                  run_id VARCHAR(64) NOT NULL,
                  source_alias VARCHAR(100) NOT NULL,
                  input_dir TEXT NOT NULL,
                  started_at TIMESTAMP WITH TIME ZONE NOT NULL,
                  finished_at TIMESTAMP WITH TIME ZONE,
                  status VARCHAR(20) NOT NULL,
                  nameusage_rows BIGINT NOT NULL DEFAULT 0,
                  accepted_species_rows BIGINT NOT NULL DEFAULT 0,
                  vernacular_rows BIGINT NOT NULL DEFAULT 0,
                  vernacular_matched_rows BIGINT NOT NULL DEFAULT 0,
                  vernacular_assigned_rows BIGINT NOT NULL DEFAULT 0,
                  rows_inserted BIGINT NOT NULL DEFAULT 0,
                  rows_updated BIGINT NOT NULL DEFAULT 0,
                  error_message TEXT
                )
                """
            )
        )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_col_xr_species_name ON col_xr_taxon_species (cached_scientific_name)"))
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_col_xr_species_name_trgm ON col_xr_taxon_species "
            "USING gin (cached_scientific_name gin_trgm_ops)"
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_col_xr_common_name ON col_xr_taxon_species (cached_common_name)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_col_xr_class_id ON col_xr_taxon_species (col_class_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_col_xr_order_id ON col_xr_taxon_species (col_order_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_col_xr_family_id ON col_xr_taxon_species (col_family_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_col_xr_genus_id ON col_xr_taxon_species (col_genus_id)"))


def import_normalized(
    input_dir: Path,
    normalized_file: Path,
    run_id: str,
    batch_size: int,
    dry_run: bool,
    stats: RunStats,
) -> None:
    if not normalized_file.exists():
        raise FileNotFoundError(f"Normalized file not found: {normalized_file}")

    db_url = get_geo_db_url()
    engine = create_engine(db_url, pool_pre_ping=True)
    now_utc = datetime.now(UTC)

    species_ids: set[str] = set()
    species_batch: list[dict[str, Any]] = []

    with normalized_file.open("r", encoding="utf-8", newline="") as src:
        reader = csv.DictReader(src, delimiter="\t")
        for row in reader:
            species_id = _normalize_text(row.get("col_species_id"))
            if not species_id:
                continue
            species_ids.add(species_id)
            species_batch.append(
                {
                    "col_species_id": species_id,
                    "cached_scientific_name": _normalize_text(row.get("cached_scientific_name")),
                    "cached_common_name": _normalize_text(row.get("cached_common_name")),
                    "col_genus_id": _normalize_text(row.get("col_genus_id")),
                    "col_genus_name": _normalize_text(row.get("col_genus_name")),
                    "col_family_id": _normalize_text(row.get("col_family_id")),
                    "col_family_name": _normalize_text(row.get("col_family_name")),
                    "col_order_id": _normalize_text(row.get("col_order_id")),
                    "col_order_name": _normalize_text(row.get("col_order_name")),
                    "col_class_id": _normalize_text(row.get("col_class_id")),
                    "col_class_name": _normalize_text(row.get("col_class_name")),
                    "taxonomy_source": "CatalogueOfLife-XR",
                    "run_id": run_id,
                    "imported_at": now_utc,
                }
            )

    best_vernacular: dict[str, tuple[int, str]] = {}
    vernacular_file = input_dir / "VernacularName.tsv"
    with vernacular_file.open("r", encoding="utf-8", newline="") as src:
        reader = csv.DictReader(src, delimiter="\t")
        for row in reader:
            stats.vernacular_rows += 1
            taxon_id = _normalize_text(row.get("col:taxonID"))
            if not taxon_id or taxon_id not in species_ids:
                continue
            stats.vernacular_matched_rows += 1
            name = _normalize_text(row.get("col:name"))
            if not name:
                continue
            score = _score_vernacular(row.get("col:language"), _bool_from_text(row.get("col:preferred")))
            current = best_vernacular.get(taxon_id)
            if current is None or score > current[0]:
                best_vernacular[taxon_id] = (score, name)

    for item in species_batch:
        best = best_vernacular.get(item["col_species_id"])
        if best:
            item["cached_common_name"] = best[1]
            stats.vernacular_assigned_rows += 1

    if dry_run:
        log.info("Dry-run import stats: %s", stats.as_log_payload())
        return

    with engine.begin() as conn:
        _ensure_geo_tables(conn)
        conn.execute(text("DROP TABLE IF EXISTS col_xr_taxon_species_stage"))
        conn.execute(
            text(
                """
                CREATE TABLE col_xr_taxon_species_stage (
                  col_species_id VARCHAR(64) PRIMARY KEY,
                  cached_scientific_name VARCHAR(255),
                  cached_common_name VARCHAR(255),
                  col_genus_id VARCHAR(64),
                  col_genus_name VARCHAR(255),
                  col_family_id VARCHAR(64),
                  col_family_name VARCHAR(255),
                  col_order_id VARCHAR(64),
                  col_order_name VARCHAR(255),
                  col_class_id VARCHAR(64),
                  col_class_name VARCHAR(255),
                  taxonomy_source VARCHAR(50),
                  run_id VARCHAR(64),
                  imported_at TIMESTAMP WITH TIME ZONE
                )
                """
            )
        )

        insert_stage_sql = text(
            """
            INSERT INTO col_xr_taxon_species_stage (
              col_species_id, cached_scientific_name, cached_common_name,
              col_genus_id, col_genus_name, col_family_id, col_family_name,
              col_order_id, col_order_name, col_class_id, col_class_name,
              taxonomy_source, run_id, imported_at
            ) VALUES (
              :col_species_id, :cached_scientific_name, :cached_common_name,
              :col_genus_id, :col_genus_name, :col_family_id, :col_family_name,
              :col_order_id, :col_order_name, :col_class_id, :col_class_name,
              :taxonomy_source, :run_id, :imported_at
            )
            ON CONFLICT (col_species_id) DO UPDATE SET
              cached_scientific_name = EXCLUDED.cached_scientific_name,
              cached_common_name = EXCLUDED.cached_common_name,
              col_genus_id = EXCLUDED.col_genus_id,
              col_genus_name = EXCLUDED.col_genus_name,
              col_family_id = EXCLUDED.col_family_id,
              col_family_name = EXCLUDED.col_family_name,
              col_order_id = EXCLUDED.col_order_id,
              col_order_name = EXCLUDED.col_order_name,
              col_class_id = EXCLUDED.col_class_id,
              col_class_name = EXCLUDED.col_class_name,
              taxonomy_source = EXCLUDED.taxonomy_source,
              run_id = EXCLUDED.run_id,
              imported_at = EXCLUDED.imported_at
            """
        )

        for i in range(0, len(species_batch), batch_size):
            conn.execute(insert_stage_sql, species_batch[i:i + batch_size])

        before_count = conn.execute(text("SELECT COUNT(*) FROM col_xr_taxon_species")).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO col_xr_taxon_species (
                  col_species_id, cached_scientific_name, cached_common_name,
                  col_genus_id, col_genus_name, col_family_id, col_family_name,
                  col_order_id, col_order_name, col_class_id, col_class_name,
                  taxonomy_source, run_id, imported_at
                )
                SELECT
                  col_species_id, cached_scientific_name, cached_common_name,
                  col_genus_id, col_genus_name, col_family_id, col_family_name,
                  col_order_id, col_order_name, col_class_id, col_class_name,
                  taxonomy_source, run_id, imported_at
                FROM col_xr_taxon_species_stage
                ON CONFLICT (col_species_id) DO UPDATE SET
                  cached_scientific_name = EXCLUDED.cached_scientific_name,
                  cached_common_name = EXCLUDED.cached_common_name,
                  col_genus_id = EXCLUDED.col_genus_id,
                  col_genus_name = EXCLUDED.col_genus_name,
                  col_family_id = EXCLUDED.col_family_id,
                  col_family_name = EXCLUDED.col_family_name,
                  col_order_id = EXCLUDED.col_order_id,
                  col_order_name = EXCLUDED.col_order_name,
                  col_class_id = EXCLUDED.col_class_id,
                  col_class_name = EXCLUDED.col_class_name,
                  taxonomy_source = EXCLUDED.taxonomy_source,
                  run_id = EXCLUDED.run_id,
                  imported_at = EXCLUDED.imported_at
                """
            )
        )
        after_count = conn.execute(text("SELECT COUNT(*) FROM col_xr_taxon_species")).scalar_one()
        stats.rows_inserted = max(int(after_count - before_count), 0)
        stats.rows_updated = max(int(len(species_batch) - stats.rows_inserted), 0)

        conn.execute(text("DROP TABLE IF EXISTS col_xr_taxon_species_stage"))


def _write_run_log(stats: RunStats) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    log_file = LOG_ROOT / f"{stats.run_id}.json"
    log_file.write_text(json.dumps(stats.as_log_payload(), ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        db_url = get_geo_db_url()
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.begin() as conn:
            _ensure_geo_tables(conn)
            conn.execute(
                text(
                    """
                    INSERT INTO col_xr_import_run (
                      run_id, source_alias, input_dir, started_at, finished_at, status,
                      nameusage_rows, accepted_species_rows, vernacular_rows,
                      vernacular_matched_rows, vernacular_assigned_rows, rows_inserted, rows_updated,
                      error_message
                    ) VALUES (
                      :run_id, :source_alias, :input_dir, :started_at, :finished_at, :status,
                      :nameusage_rows, :accepted_species_rows, :vernacular_rows,
                      :vernacular_matched_rows, :vernacular_assigned_rows, :rows_inserted, :rows_updated,
                      :error_message
                    )
                    """
                ),
                {
                    "run_id": stats.run_id,
                    "source_alias": stats.source_alias,
                    "input_dir": stats.input_dir,
                    "started_at": stats.started_at,
                    "finished_at": stats.finished_at,
                    "status": stats.status,
                    "nameusage_rows": stats.nameusage_rows,
                    "accepted_species_rows": stats.accepted_species_rows,
                    "vernacular_rows": stats.vernacular_rows,
                    "vernacular_matched_rows": stats.vernacular_matched_rows,
                    "vernacular_assigned_rows": stats.vernacular_assigned_rows,
                    "rows_inserted": stats.rows_inserted,
                    "rows_updated": stats.rows_updated,
                    "error_message": stats.error_message,
                },
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not persist import run log into geo_db: %s", exc)


def run_all(input_dir: Path, run_id: str, batch_size: int, dry_run: bool) -> RunStats:
    input_dir = input_dir.resolve()
    validate(input_dir)
    source_alias = _read_metadata_alias(input_dir / "metadata.yaml")
    stats = RunStats(run_id=run_id, source_alias=source_alias, input_dir=str(input_dir))
    try:
        normalized_file = normalize(input_dir=input_dir, run_id=run_id, stats=stats)
        import_normalized(
            input_dir=input_dir,
            normalized_file=normalized_file,
            run_id=run_id,
            batch_size=batch_size,
            dry_run=dry_run,
            stats=stats,
        )
        stats.status = "success"
        return stats
    except Exception as exc:  # noqa: BLE001
        stats.status = "failed"
        stats.error_message = str(exc)
        raise
    finally:
        stats.finished_at = datetime.now(UTC)
        _write_run_log(stats)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import CoL XR taxonomy into geo_db.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("normalize")
    subparsers.add_parser("import")
    subparsers.add_parser("run-all")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    _configure_csv_field_limit()
    parser = _build_parser()
    args = parser.parse_args()

    input_dir: Path = args.input_dir.resolve()
    run_id: str = args.run_id
    batch_size: int = args.batch_size
    dry_run: bool = bool(args.dry_run)

    if args.command == "validate":
        payload = validate(input_dir)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    alias = _read_metadata_alias(input_dir / "metadata.yaml")
    stats = RunStats(run_id=run_id, source_alias=alias, input_dir=str(input_dir))
    try:
        if args.command == "normalize":
            validate(input_dir)
            out_file = normalize(input_dir=input_dir, run_id=run_id, stats=stats)
            stats.status = "success"
            print(json.dumps({"normalized_file": str(out_file), **stats.as_log_payload()}, ensure_ascii=False, indent=2))
            return

        if args.command == "import":
            normalized_file = WORKING_ROOT / run_id / "species_accepted.tsv"
            import_normalized(
                input_dir=input_dir,
                normalized_file=normalized_file,
                run_id=run_id,
                batch_size=batch_size,
                dry_run=dry_run,
                stats=stats,
            )
            stats.status = "success"
            print(json.dumps(stats.as_log_payload(), ensure_ascii=False, indent=2))
            return

        final_stats = run_all(input_dir=input_dir, run_id=run_id, batch_size=batch_size, dry_run=dry_run)
        print(json.dumps(final_stats.as_log_payload(), ensure_ascii=False, indent=2))
    finally:
        if stats.finished_at is None and args.command != "run-all":
            stats.finished_at = datetime.now(UTC)
            _write_run_log(stats)


if __name__ == "__main__":
    main()
