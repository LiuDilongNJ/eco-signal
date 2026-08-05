#!/usr/bin/env bash
# =============================================================================
# geo_init.sh (Standalone Script for geo_db container)
# =============================================================================

set -e

echo "[geo_init] 🚀 Monitoring database for initialization..."

PG_USER="${POSTGRES_USER:-postgres}"
PG_DB="${POSTGRES_DB:-geo_db}"
PG_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
export PGPASSWORD="$PG_PASSWORD"

DATA_DIR="/tmp/geo_data"
READY_ZIP="${DATA_DIR}/geo_db_ready.zip"
READY_SQL="${DATA_DIR}/geo_db_ready.sql"
XR_READY_ZIP="${DATA_DIR}/col_xr_seed.zip"
XR_READY_SQL="${DATA_DIR}/col_xr_seed.sql"
GEO_BASE_TABLES=(adm_0 adm_1 adm_2 iho_sea_area)

until pg_isready -h localhost -U "$PG_USER" -d "$PG_DB"; do
  echo "[geo_init] ⏳ Waiting for database to be ready..."
  sleep 2
done

run_sql() {
    psql -v ON_ERROR_STOP=1 -h localhost --username "$PG_USER" --dbname "$PG_DB" "$@"
}

table_exists() {
    run_sql -tAc "SELECT to_regclass('public.$1') IS NOT NULL"
}

table_count() {
    run_sql -tAc "SELECT COUNT(*) FROM $1"
}

is_table_ready() {
    local table_name="$1"
    local exists
    exists=$(table_exists "$table_name")
    if [ "$exists" != "t" ]; then
        echo "0"
        return
    fi

    local count
    count=$(table_count "$table_name")
    if [ "$count" -gt 0 ]; then
        echo "1"
    else
        echo "0"
    fi
}

is_geo_base_ready() {
    local table_name
    for table_name in "${GEO_BASE_TABLES[@]}"; do
        if [ "$(is_table_ready "$table_name")" != "1" ]; then
            echo "0"
            return
        fi
    done

    echo "1"
}

ensure_extensions() {
    echo "[geo_init] 🔍 Checking extensions..."
    run_sql -c "CREATE EXTENSION IF NOT EXISTS postgis;"
    run_sql -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
}

resolve_geo_sql_source() {
    mkdir -p "$DATA_DIR"

    if [ -f "/data/geo_db_ready.sql" ]; then
        echo "[geo_init] 📂 Found existing SQL dump in /data. Using it."
        cp "/data/geo_db_ready.sql" "$READY_SQL"
        return 0
    fi

    if [ -f "/data/geo_db_ready.zip" ] && unzip -t "/data/geo_db_ready.zip" >/dev/null 2>&1; then
        echo "[geo_init] 📂 Found valid ZIP archive in /data. Using it."
        echo "[geo_init] 📦 Extracting SQL dump directly from /data/geo_db_ready.zip..."
        unzip -o "/data/geo_db_ready.zip" -d "$DATA_DIR"
        return 0
    fi

    if [ -f "/data/gadm_410-levels.gpkg" ] || [ -f "/data/gadm_410-levels.zip" ]; then
        echo "[geo_init] 📂 Found local raw GADM source (/data/gadm_410-levels.gpkg or .zip)."
        echo "[geo_init] ⏭️ Skipping geo SQL import; backend prestart will import raw GADM."
        return 1
    fi

    if [ -n "${GEO_DB_READY_URL}" ]; then
        echo "[geo_init] ⬇️ Downloading pre-processed geo data from ${GEO_DB_READY_URL}..."
        wget -q --show-progress -c -O "$READY_ZIP" "${GEO_DB_READY_URL}"
        echo "[geo_init] 📦 Extracting SQL dump from downloaded ZIP..."
        unzip -o "$READY_ZIP" -d "$DATA_DIR"
        return 0
    fi

    echo "[geo_init] ❌ No geo data source found (/data/geo_db_ready.sql, /data/geo_db_ready.zip, /data/gadm_410-levels.gpkg, /data/gadm_410-levels.zip, or GEO_DB_READY_URL)."
    exit 1
}

import_geo_sql_if_needed() {
    local geo_ready="$1"
    if [ "$geo_ready" = "1" ]; then
        echo "[geo_init] ✅ Geo base tables already exist. Skipping geo SQL import."
        return
    fi

    if resolve_geo_sql_source; then
        if [ -f "$READY_SQL" ]; then
            echo "[geo_init] 📦 Importing geo SQL dump into geo_db..."
            run_sql -c "DROP TABLE IF EXISTS iho_sea_area, adm_0, adm_1, adm_2 CASCADE;"
            run_sql -f "$READY_SQL"
            echo "[geo_init] ✅ Geo SQL import complete."
            return
        fi

        echo "[geo_init] ❌ Geo SQL dump not found after extraction."
        exit 1
    fi
}

resolve_xr_sql_source() {
    mkdir -p "$DATA_DIR"

    if [ -f "/data/col_xr_seed.sql" ]; then
        echo "[geo_init] 📂 Found XR seed SQL in /data. Using it."
        cp "/data/col_xr_seed.sql" "$XR_READY_SQL"
        return
    fi

    if [ -f "/data/col_xr_seed.zip" ] && unzip -t "/data/col_xr_seed.zip" >/dev/null 2>&1; then
        echo "[geo_init] 📂 Found XR seed ZIP in /data. Using it."
        echo "[geo_init] 📦 Extracting XR seed from /data/col_xr_seed.zip..."
        unzip -o "/data/col_xr_seed.zip" -d "$DATA_DIR"
        return
    fi

    if [ -n "${GEO_DB_XR_SEED_URL}" ]; then
        echo "[geo_init] ⬇️ Downloading XR seed from ${GEO_DB_XR_SEED_URL}..."
        wget -q --show-progress -c -O "$XR_READY_ZIP" "${GEO_DB_XR_SEED_URL}"
        echo "[geo_init] 📦 Extracting XR seed ZIP..."
        unzip -o "$XR_READY_ZIP" -d "$DATA_DIR"
        return
    fi

    echo "[geo_init] ❌ No XR seed source found (/data/col_xr_seed.sql, /data/col_xr_seed.zip, or GEO_DB_XR_SEED_URL)."
    exit 1
}

import_xr_seed_if_needed() {
    local xr_ready="$1"
    if [ "$xr_ready" = "1" ]; then
        echo "[geo_init] ✅ XR seed tables already exist. Skipping XR import."
        return
    fi

    resolve_xr_sql_source

    if [ ! -f "$XR_READY_SQL" ]; then
        echo "[geo_init] ❌ XR seed SQL not found after extraction."
        exit 1
    fi

    echo "[geo_init] 📦 Importing XR seed into geo_db..."
    run_sql -c "DROP TABLE IF EXISTS col_xr_taxon_species, col_xr_import_run CASCADE;"
    run_sql -f "$XR_READY_SQL"
    echo "[geo_init] ✅ XR seed import complete."
}

cleanup() {
    rm -rf "$DATA_DIR"
    echo "[geo_init] ✨ Cleanup complete."
}

if [ "${GEO_DB_AUTO_DOWNLOAD:-false}" != "true" ]; then
    echo "[geo_init] ⏭️ GEO_DB_AUTO_DOWNLOAD is not true. Skipping."
    exit 0
fi

ensure_extensions

GEO_READY=$(is_geo_base_ready)
XR_TABLE_READY=$(is_table_ready "col_xr_taxon_species")
XR_RUN_TABLE_EXISTS=$(table_exists "col_xr_import_run")

echo "[geo_init] 📊 Geo ready=${GEO_READY}, XR species ready=${XR_TABLE_READY}, XR run table exists=${XR_RUN_TABLE_EXISTS}"

if [ "$GEO_READY" = "1" ] && [ "$XR_TABLE_READY" = "1" ] && [ "$XR_RUN_TABLE_EXISTS" = "t" ]; then
    echo "[geo_init] ✅ Geo base tables and XR seed tables already exist. Done."
    exit 0
fi

import_geo_sql_if_needed "$GEO_READY"
import_xr_seed_if_needed "$XR_TABLE_READY"

cleanup
