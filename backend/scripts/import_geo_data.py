"""
import_geo_data.py - One-time geo data import script.

Reads IHO Sea Areas (Shapefile) and GADM administrative boundaries (GeoPackage)
and inserts them into the geo_db PostgreSQL database.

Usage:
    docker compose exec backend python scripts/import_geo_data.py \
        --iho-dir  /app/data/World_Seas_IHO_v3 \
        --gadm-file /app/data/gadm_410.gpkg

    # Import all GADM layers in raw mode (keep source columns as-is)
    docker compose exec backend python scripts/import_geo_data.py \
        --gadm-only \
        --gadm-file /app/data/gadm_410-levels.gpkg \
        --gadm-if-exists replace

    # Only ADM_0 .. ADM_2 (skip ADM_3+ to save time and space; matches FDW usage)
    docker compose exec backend python scripts/import_geo_data.py \
        --gadm-only \
        --gadm-file /app/data/gadm_410-levels.gpkg \
        --gadm-max-level 2

Requirements (install in container or virtualenv):
    geopandas>=0.14, sqlalchemy, psycopg[binary], geoalchemy2, shapely
"""

import argparse
import logging
import os
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def get_geo_db_url() -> str:
    """Build the geo_db SQLAlchemy connection URL from environment variables."""
    host = os.getenv("GEO_DB_SERVER", "geo_db")
    port = os.getenv("GEO_DB_PORT", "5432")
    dbname = os.getenv("GEO_DB_NAME", "geo_db")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"


def import_iho(iho_source: Path, engine) -> None:
    """Import IHO World Seas v3 data into geo_db, keeping all source columns.

    Only minimal transformations are applied:
    - Column names lowercased for PostgreSQL convention.
    - Source 'ID' (string) renamed to 'iho_id' to avoid conflict with the
      integer primary key 'id' generated from the DataFrame index.
    - Polygon geometries converted to MultiPolygon (PostGIS constraint).
    - Reprojected to EPSG:4326 if the source CRS differs.

    Args:
        iho_source: Directory containing .shp files, or a .zip archive.
        engine: SQLAlchemy engine connected to geo_db.
    """
    import shutil
    import tempfile
    import zipfile

    import geopandas as gpd
    from shapely.geometry import MultiPolygon

    tmp_dir: Path | None = None

    try:
        if iho_source.suffix.lower() == ".zip":
            tmp_dir = Path(tempfile.mkdtemp(prefix="iho_"))
            log.info("Extracting IHO ZIP to %s ...", tmp_dir)
            with zipfile.ZipFile(iho_source, "r") as zf:
                zf.extractall(tmp_dir)
            shp_files = list(tmp_dir.rglob("*.shp"))
        else:
            shp_files = list(iho_source.glob("*.shp"))

        if not shp_files:
            log.error("No .shp file found in %s", iho_source)
            sys.exit(1)

        shp_path = shp_files[0]
        log.info("Reading IHO shapefile: %s", shp_path)

        gdf = gpd.read_file(shp_path)
        log.info("Loaded %d IHO features. Columns: %s", len(gdf), gdf.columns.tolist())

        # Reproject to WGS84 if needed (IHO v3 is already EPSG:4326)
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            log.info("Reprojecting IHO data to EPSG:4326 ...")
            gdf = gdf.to_crs(epsg=4326)

        # Lowercase all column names; rename 'id' (string field) to 'iho_id'
        # to avoid conflict with the integer primary key derived from the index.
        gdf.columns = [
            "iho_id" if c.lower() == "id" else c.lower()
            for c in gdf.columns
        ]
        log.info("Columns after normalisation: %s", gdf.columns.tolist())

        # Convert Polygon → MultiPolygon (required by geo_db schema)
        gdf["geometry"] = gdf["geometry"].apply(
            lambda g: MultiPolygon([g]) if g is not None and g.geom_type == "Polygon" else g
        )

        # Use DataFrame index as integer primary key 'id'
        gdf.index.name = "id"

        log.info("Writing %d IHO features to 'iho_sea_area' (replace) ...", len(gdf))
        gdf.to_postgis(
            name="iho_sea_area",
            con=engine,
            if_exists="replace",
            index=True,
        )
        log.info("IHO import complete: %d rows written to 'iho_sea_area'.", len(gdf))

    finally:
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _normalize_table_name(name: str) -> str:
    """Normalize layer name to a safe PostgreSQL table name."""
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_").lower()
    return normalized[:63] if normalized else "gadm_layer"


def _gadm_layer_admin_level(layer: str) -> int | None:
    """Infer admin level from GADM GeoPackage layer names (e.g. ADM_2 -> 2)."""
    m = re.search(r"(?i)ADM[_](\d+)\s*$", layer.strip())
    return int(m.group(1)) if m else None


def import_gadm(
    gadm_file: Path,
    engine,
    if_exists: str,
    layer_name: str | None = None,
    table_prefix: str = "",
    max_admin_level: int | None = None,
) -> None:
    """Import GADM from a GeoPackage without reshaping source columns.

    This mode keeps the source schema as-is:
    - no level splitting
    - no dissolve/merge
    - no parent/child backfill
    - no post-import schema adjustments
    """
    import geopandas as gpd
    import fiona

    # Discover available layers
    available_layers = fiona.listlayers(str(gadm_file))
    log.info("GADM layers in GeoPackage: %s", available_layers)

    if not available_layers:
        log.error("No layers found in GADM GeoPackage.")
        return

    layers_to_import = available_layers
    if layer_name:
        if layer_name not in available_layers:
            log.error("Layer '%s' not found. Available: %s", layer_name, available_layers)
            sys.exit(1)
        layers_to_import = [layer_name]

    if max_admin_level is not None:
        if layer_name:
            lvl = _gadm_layer_admin_level(layer_name)
            if lvl is None:
                log.error(
                    "Cannot infer admin level from layer '%s' (expected name like ADM_0).",
                    layer_name,
                )
                sys.exit(1)
            if lvl > max_admin_level:
                log.error(
                    "Layer '%s' is level %d, but --gadm-max-level is %d.",
                    layer_name,
                    lvl,
                    max_admin_level,
                )
                sys.exit(1)
        else:
            kept: list[str] = []
            for layer in layers_to_import:
                lvl = _gadm_layer_admin_level(layer)
                if lvl is None:
                    log.warning(
                        "Skipping layer '%s': cannot infer level (not ADM_<n>); "
                        "import explicitly with --gadm-layer if needed.",
                        layer,
                    )
                    continue
                if lvl <= max_admin_level:
                    kept.append(layer)
                else:
                    log.info(
                        "Skipping layer '%s' (admin level %d > %d).",
                        layer,
                        lvl,
                        max_admin_level,
                    )
            layers_to_import = kept

    if not layers_to_import:
        log.error("No GADM layers selected for import.")
        sys.exit(1)

    log.info("Will import %d GADM layer(s): %s", len(layers_to_import), layers_to_import)

    for layer in layers_to_import:
        table_name = _normalize_table_name(f"{table_prefix}{layer}")
        log.info("Reading GADM layer '%s' ...", layer)
        log.info("This may take a few minutes for large layers ...")
        gdf = gpd.read_file(str(gadm_file), layer=layer)
        log.info("Loaded %d features from '%s'.", len(gdf), layer)

        # Reproject to EPSG:4326 if needed
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            log.info("Reprojecting layer '%s' to EPSG:4326 ...", layer)
            gdf = gdf.to_crs(epsg=4326)

        log.info("Layer '%s' columns (first 20): %s", layer, list(gdf.columns)[:20])
        log.info(
            "Writing raw layer '%s' to table '%s' (if_exists=%s) ...",
            layer,
            table_name,
            if_exists,
        )
        gdf.to_postgis(
            name=table_name,
            con=engine,
            if_exists=if_exists,
            index=False,
        )
        log.info(
            "Raw import complete for layer '%s': %d rows written to '%s'.",
            layer,
            len(gdf),
            table_name,
        )



def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import IHO and GADM geo data into the geo_db PostgreSQL database."
    )
    parser.add_argument(
        "--iho-dir",
        type=Path,
        default=Path("/app/data/World_Seas_IHO_v3.zip"),
        help="Path to the IHO World Seas v3 shapefile directory or .zip archive.",
    )
    parser.add_argument(
        "--gadm-file",
        type=Path,
        default=Path("/app/data/gadm_410.gpkg"),
        help="Path to the GADM 4.1 GeoPackage file.",
    )
    parser.add_argument(
        "--iho-only", action="store_true", help="Import IHO data only."
    )
    parser.add_argument(
        "--gadm-only", action="store_true", help="Import GADM data only."
    )
    parser.add_argument(
        "--gadm-if-exists",
        type=str,
        default="replace",
        choices=["replace", "append", "fail"],
        help="Behavior when target table already exists.",
    )
    parser.add_argument(
        "--gadm-layer",
        type=str,
        default=None,
        help="Import only one specific GADM layer. Default imports all layers.",
    )
    parser.add_argument(
        "--gadm-table-prefix",
        type=str,
        default="",
        help="Optional prefix for output table names when importing GADM layers.",
    )
    parser.add_argument(
        "--gadm-max-level",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Only import GADM layers ADM_0 .. ADM_N (standard GeoPackage names). "
            "Example: --gadm-max-level 2 imports country / level-1 / level-2 only."
        ),
    )
    args = parser.parse_args()

    if args.gadm_max_level is not None and args.gadm_max_level < 0:
        log.error("--gadm-max-level must be >= 0.")
        sys.exit(1)

    # Validate paths
    if not args.iho_only and not args.gadm_file.exists():
        log.error("GADM file not found: %s", args.gadm_file)
        sys.exit(1)
    if not args.gadm_only and not args.iho_dir.exists():
        log.error("IHO source not found: %s", args.iho_dir)
        sys.exit(1)

    # Connect to geo_db
    try:
        from sqlalchemy import create_engine
        url = get_geo_db_url()
        log.info("Connecting to geo_db: %s", url.split("@")[-1])  # hide password
        engine = create_engine(url, pool_pre_ping=True)
    except Exception as e:
        log.error("Failed to connect to geo_db: %s", e)
        sys.exit(1)

    if not args.iho_only:
        log.info("=== Starting GADM import ===")
        import_gadm(
            args.gadm_file,
            engine,
            args.gadm_if_exists,
            args.gadm_layer,
            args.gadm_table_prefix,
            args.gadm_max_level,
        )

    if not args.gadm_only:
        log.info("=== Starting IHO import ===")
        import_iho(args.iho_dir, engine)

    log.info("All done! geo_db is ready.")


if __name__ == "__main__":
    main()
