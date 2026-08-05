#!/usr/bin/env bash
# =============================================================================
# geo_export_xr_tables.sh
# Export XR seed tables from geo_db for runtime initialization.
# Saves the output to the project data/ directory as SQL + ZIP.
# Safe to run from any working directory (paths are resolved from this file).
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
EXPORT_DIR="$PROJECT_ROOT/data"
EXPORT_FILE="$EXPORT_DIR/col_xr_seed.sql"
ZIP_FILE="$EXPORT_DIR/col_xr_seed.zip"

# Load environment variables if .env exists at project root
if [ -f "$PROJECT_ROOT/.env" ]; then
    # shellcheck disable=SC2046
    export $(grep -v '^#' "$PROJECT_ROOT/.env" | xargs)
fi

mkdir -p "$EXPORT_DIR"

echo "[geo_export_xr] Exporting XR tables from geo_db..."

# docker compose must run from project root (where compose files live)
(cd "$PROJECT_ROOT" && docker compose exec -T geo_db pg_dump \
    -U "${POSTGRES_USER:-postgres}" \
    -d "${GEO_DB_NAME:-geo_db}" \
    --clean --if-exists \
    --no-owner --no-privileges \
    -t public.col_xr_taxon_species \
    -t public.col_xr_import_run \
    > "$EXPORT_FILE")

if [ -s "$EXPORT_FILE" ]; then
    echo "[geo_export_xr] Data exported successfully to ${EXPORT_FILE}"

    echo "[geo_export_xr] Compressing to ZIP for easier distribution..."
    export _XR_EXPORT_SQL="$EXPORT_FILE"
    export _XR_EXPORT_ZIP="$ZIP_FILE"
    python3 -c 'import os, zipfile
from pathlib import Path
sql, zpath = Path(os.environ["_XR_EXPORT_SQL"]), Path(os.environ["_XR_EXPORT_ZIP"])
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(sql, "col_xr_seed.sql")'
    unset _XR_EXPORT_SQL _XR_EXPORT_ZIP

    echo "[geo_export_xr] SUCCESS! Files created:"
    ls -lh "$EXPORT_FILE" "$ZIP_FILE"
else
    echo "[geo_export_xr] ERROR: Export file is empty. Check if geo_db is running and XR tables contain data."
    exit 1
fi
