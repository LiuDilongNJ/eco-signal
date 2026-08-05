# geo_db Import Guide

There are two runtime import payloads for **geo_db**: the **geo base SQL snapshot** (from `geo_export.sh`) and the **XR seed SQL** (from `geo_export_xr_tables.sh`). The current auto-import checks geo base readiness and XR table readiness separately, then fills in whatever is missing.

### Auto-import priority (implemented)

When `GEO_DB_AUTO_DOWNLOAD=true`, startup resolves data in two stages:

1. Geo base data:
- Local SQL snapshot: `data/geo_db_ready.sql` or `data/geo_db_ready.zip`
- Local raw GADM: `data/gadm_410-levels.gpkg` or `data/gadm_410-levels.zip`
- Remote URL: `GEO_DB_READY_URL`
2. XR seed data:
- Local SQL snapshot: `data/col_xr_seed.sql`
- Local ZIP snapshot: `data/col_xr_seed.zip`
- Remote URL: `GEO_DB_XR_SEED_URL`

Notes:

- Geo SQL and XR seed import are handled by `geo_db/geo_init.sh`.
- Local raw GADM is still handled by backend `prestart.sh`, which calls `scripts/import_geo_data.py` (default `ADM_0..ADM_2` import).
- Even if another developer already has `adm_0/1/2` and `iho_sea_area`, startup will still import XR seed whenever the XR tables are missing or empty.

### 1. Restore from a SQL snapshot (recommended)

#### Option A: Place files under `./data` and run `psql`

The host directory `./data` is mounted at `/data` in the `geo_db` container. Put `geo_db_ready.sql` (or extract the SQL from the ZIP) into the project-root `data/` folder, then:

By default, `geo_export.sh` only dumps the four tables `adm_0`, `adm_1`, `adm_2`, and `iho_sea_area`. Use `GEO_EXPORT_ALL=1` when exporting if you need a full-database snapshot.

```bash
docker compose up -d geo_db

docker compose exec -T geo_db psql -U "${POSTGRES_USER:-postgres}" -d "${GEO_DB_NAME:-geo_db}" \
  -v ON_ERROR_STOP=1 -f /data/geo_db_ready.sql
```

#### Option B: Auto-import on first boot (optional)

Set `GEO_DB_AUTO_DOWNLOAD=true` in `.env`. The startup flow resolves sources by priority:

- `data/geo_db_ready.sql` / `data/geo_db_ready.zip` (highest priority)
- `data/gadm_410-levels.gpkg` / `data/gadm_410-levels.zip` (if no SQL snapshot)
- `GEO_DB_READY_URL` (final fallback)
- `data/col_xr_seed.sql` / `data/col_xr_seed.zip` (XR local priority)
- `GEO_DB_XR_SEED_URL` (XR final fallback)

`geo_init.sh` handles geo SQL snapshots, XR seed snapshots, and both remote URL fallbacks; backend `prestart.sh` handles local raw GADM by calling `import_geo_data.py`.

#### Clean restore (optional)

To discard existing geo_db data entirely, remove the `geo_db` volume (verify the volume name with `docker volume ls`), recreate the service, then run Option A.

---

### 2. Import from raw files (`import_geo_data.py`)

Run inside the **backend** container. In local dev, `./data` is often mounted at `/app/data`.

```bash
docker compose up -d geo_db backend

docker compose exec backend python scripts/import_geo_data.py \
  --iho-dir /app/data/World_Seas_IHO_v3 \
  --gadm-file /app/data/gadm_410-levels.gpkg

docker compose exec backend python scripts/import_geo_data.py \
  --gadm-only \
  --gadm-file /app/data/gadm_410-levels.gpkg \
  --gadm-max-level 2 \
  --gadm-if-exists replace
```

See `backend/scripts/import_geo_data.py` for flags and Python dependencies.

---

### 3. FDW on the main database after import

The main DB uses `postgres_fdw` to reference tables in geo_db. After loading data, ensure FDW is refreshed (typically via backend prestart / `setup_fdw.py`) so foreign table names match what exists in geo_db (e.g. `iho_sea_area`, `adm_0`, `adm_1`, `adm_2`).

### Chinese version

See [GEO_IMPORT_zh.md](./GEO_IMPORT_zh.md).
