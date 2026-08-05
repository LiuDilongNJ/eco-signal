# geo_db Export Guide

### Purpose

Export the **geo_db** tables used by the app and FDW to a SQL file and a ZIP archive, so others can restore them in their environment.

**Default tables (`public` schema):** `adm_0`, `adm_1`, `adm_2`, `iho_sea_area`.

For a **full database** dump, set `GEO_EXPORT_ALL=1` (or `true`) before running the script.

### Prerequisites

- `.env` at the project root with at least `POSTGRES_USER` and `POSTGRES_PASSWORD` (optional `GEO_DB_NAME`, default `geo_db`).
- The `geo_db` service is running, e.g. `docker compose up -d geo_db`.

### Script location

- `geo_db/geo_export.sh`

### How to run

The script resolves the **project root** from its own location and runs `docker compose` from there, so you can invoke it **from any current working directory** (use a path that resolves to the script).

```bash
# From repo root (default: the four tables above)
./geo_db/geo_export.sh

# Full database export
GEO_EXPORT_ALL=1 ./geo_db/geo_export.sh

# Or with an absolute path
bash /path/to/ecoSignal/geo_db/geo_export.sh
```

### Output files

Written under the project root **`data/`**:

| File | Description |
|------|-------------|
| `data/geo_db_ready.sql` | SQL from `pg_dump` (with `--clean --if-exists`) |
| `data/geo_db_ready.zip` | ZIP of the SQL file for easy sharing |

### Technical notes

- Runs `pg_dump` inside the container: `docker compose exec -T geo_db pg_dump ...` with multiple `-t public.<table>` by default.
- Uses `--no-owner --no-privileges` for portable restores.
- Default: **four tables** above; with `GEO_EXPORT_ALL=1`, exports the **full database**.

### Troubleshooting

- **`docker compose` cannot find services**: ensure the script lives at `<project-root>/geo_db/geo_export.sh` so the resolved project root contains your `docker-compose.yml`.

### Chinese version

See [GEO_EXPORT_zh.md](./GEO_EXPORT_zh.md).
