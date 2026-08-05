"""
setup_geo_data.py - Ensure geo_db has the required geo base data.

This script is intended to run during backend prestart.
It is idempotent:
- If adm_0, adm_1, adm_2, and iho_sea_area all exist and contain data,
  geo setup is skipped.
- Otherwise, it imports the missing geo base data from local files.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import zipfile
from pathlib import Path

from sqlalchemy import create_engine, text

from import_geo_data import get_geo_db_url, import_gadm, import_iho

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

_GADM_TABLES: tuple[str, ...] = ("adm_0", "adm_1", "adm_2")
_IHO_TABLES: tuple[str, ...] = ("iho_sea_area",)
_GEO_BASE_TABLES: tuple[str, ...] = _GADM_TABLES + _IHO_TABLES


def _table_exists(conn, table_name: str) -> bool:
    return bool(
        conn.execute(
            text("SELECT to_regclass(:name) IS NOT NULL"),
            {"name": f"public.{table_name}"},
        ).scalar()
    )


def _table_count(conn, table_name: str) -> int:
    return int(conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar() or 0)


def _has_ready_table_data(conn, table_name: str) -> bool:
    if not _table_exists(conn, table_name):
        log.info("Table %s does not exist in geo_db.", table_name)
        return False

    count = _table_count(conn, table_name)
    log.info("Table %s row count: %d", table_name, count)
    return count > 0


def _has_ready_tables(conn, table_names: tuple[str, ...]) -> bool:
    return all(_has_ready_table_data(conn, table_name) for table_name in table_names)


def _has_ready_gadm_data(conn) -> bool:
    for table in _GADM_TABLES:
        if not _table_exists(conn, table):
            log.info("Table %s does not exist in geo_db.", table)
            return False
        count = _table_count(conn, table)
        log.info("Table %s row count: %d", table, count)
        if count <= 0:
            return False
    return True


def _has_ready_iho_data(conn) -> bool:
    return _has_ready_tables(conn, _IHO_TABLES)


def _has_ready_geo_base_data(conn) -> bool:
    return _has_ready_tables(conn, _GEO_BASE_TABLES)


def _resolve_gadm_file() -> Path | None:
    gpkg = Path("/app/data/gadm_410-levels.gpkg")
    zip_path = Path("/app/data/gadm_410-levels.zip")

    if gpkg.exists():
        return gpkg

    if zip_path.exists():
        persistent = Path("/tmp/gadm_410-levels.gpkg")
        with zipfile.ZipFile(zip_path, "r") as zf:
            member = next((n for n in zf.namelist() if n.lower().endswith(".gpkg")), None)
            if member is None:
                log.warning("ZIP exists but contains no .gpkg file: %s", zip_path)
                return None
            with zf.open(member) as src, persistent.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        return persistent

    return None


def _resolve_iho_source() -> Path | None:
    """Return the IHO data source path (ZIP or extracted directory)."""
    zip_path = Path("/app/data/World_Seas_IHO_v3.zip")
    directory = Path("/app/data/World_Seas_IHO_v3")

    if zip_path.exists():
        return zip_path
    if directory.exists() and list(directory.glob("*.shp")):
        return directory
    return None


def _run_gadm_import(engine) -> None:
    gadm_file = _resolve_gadm_file()
    if gadm_file is None:
        log.warning(
            "No local GADM source found (/app/data/gadm_410-levels.gpkg or .zip). "
            "Skipping GADM auto import."
        )
        return

    log.info("Starting automatic GADM import from: %s", gadm_file)
    try:
        import_gadm(
            gadm_file=gadm_file,
            engine=engine,
            if_exists="replace",
            layer_name=None,
            table_prefix="",
            max_admin_level=2,
        )
    except Exception as e:
        log.error("Automatic GADM import failed: %s", e)
        sys.exit(1)
    finally:
        if str(gadm_file) == "/tmp/gadm_410-levels.gpkg" and gadm_file.exists():
            gadm_file.unlink()

    with engine.connect() as conn:
        if _has_ready_gadm_data(conn):
            log.info("Automatic GADM import complete.")
        else:
            log.error("GADM import finished but ADM tables are still missing/empty.")
            sys.exit(1)


def _run_iho_import(engine) -> None:
    iho_source = _resolve_iho_source()
    if iho_source is None:
        log.warning(
            "No local IHO source found (/app/data/World_Seas_IHO_v3.zip or directory). "
            "Skipping IHO auto import."
        )
        return

    log.info("Starting automatic IHO import from: %s", iho_source)
    try:
        import_iho(iho_source=iho_source, engine=engine)
    except Exception as e:
        log.error("Automatic IHO import failed: %s", e)
        sys.exit(1)

    with engine.connect() as conn:
        if _has_ready_iho_data(conn):
            log.info("Automatic IHO import complete.")
        else:
            log.error("IHO import finished but iho_sea_area table is still missing/empty.")
            sys.exit(1)


def main() -> None:
    auto_download = os.getenv("GEO_DB_AUTO_DOWNLOAD", "false").lower() == "true"
    if not auto_download:
        log.info("GEO_DB_AUTO_DOWNLOAD is not true, skipping geo auto import.")
        return

    engine = create_engine(get_geo_db_url(), pool_pre_ping=True)

    try:
        with engine.connect() as conn:
            geo_base_ready = _has_ready_geo_base_data(conn)
    except Exception as e:
        log.error("Failed to inspect geo_db tables: %s", e)
        sys.exit(1)

    if geo_base_ready:
        log.info("geo_db already has all required geo base data, skip import.")
        return

    with engine.connect() as conn:
        gadm_ready = _has_ready_gadm_data(conn)
        iho_ready = _has_ready_iho_data(conn)

    if not gadm_ready:
        _run_gadm_import(engine)

    if not iho_ready:
        _run_iho_import(engine)

    log.info("geo_db setup complete.")


if __name__ == "__main__":
    main()
