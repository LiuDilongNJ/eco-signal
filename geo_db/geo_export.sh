#!/usr/bin/env bash
# =============================================================================
# geo_export.sh
# Export the full geo_db database to a SQL dump for sharing.
# Saves the output to the project data/ directory as geo_db_ready.sql.
# Safe to run from any working directory (paths are resolved from this file).
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
EXPORT_FILE="$PROJECT_ROOT/data/geo_db_ready.sql"
ZIP_FILE="$PROJECT_ROOT/data/geo_db_ready.zip"

# Load environment variables if .env exists at project root
if [ -f "$PROJECT_ROOT/.env" ]; then
    # shellcheck disable=SC2046
    export $(grep -v '^#' "$PROJECT_ROOT/.env" | xargs)
fi

mkdir -p "$PROJECT_ROOT/data"

echo "[geo_export] Exporting full geo_db database (schema + data)..."

# docker compose must run from project root (where compose files live)
(cd "$PROJECT_ROOT" && docker compose exec -T geo_db pg_dump -U "${POSTGRES_USER:-postgres}" -d "${GEO_DB_NAME:-geo_db}" \
    --clean --if-exists \
    --no-owner --no-privileges \
    > "$EXPORT_FILE")

if [ -s "$EXPORT_FILE" ]; then
    echo "[geo_export] Data exported successfully to ${EXPORT_FILE}"
    
    echo "[geo_export] Compressing to ZIP for easier distribution..."
    export _GEO_EXPORT_SQL="$EXPORT_FILE"
    export _GEO_EXPORT_ZIP="$ZIP_FILE"
    python3 -c 'import os, zipfile
from pathlib import Path
sql, zpath = Path(os.environ["_GEO_EXPORT_SQL"]), Path(os.environ["_GEO_EXPORT_ZIP"])
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(sql, "geo_db_ready.sql")'
    unset _GEO_EXPORT_SQL _GEO_EXPORT_ZIP
    
    echo "[geo_export] SUCCESS! Files created:"
    ls -lh "$EXPORT_FILE" "$ZIP_FILE"
else
    echo "[geo_export] ERROR: Export file is empty. Check if geo_db is running and contains data."
    exit 1
fi
