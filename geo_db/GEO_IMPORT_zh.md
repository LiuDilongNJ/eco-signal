# geo_db 导入说明

geo_db 数据有两类自动导入内容：**geo 基础 SQL 快照**（与 `geo_export.sh` 配套）和 **XR seed SQL**（与 `geo_export_xr_tables.sh` 配套）。当前自动导入会分别判断 geo 基础数据与 XR 表是否已就绪，并按优先级补齐缺失内容。

### 自动导入优先级（已实现）

当 `GEO_DB_AUTO_DOWNLOAD=true` 时，启动流程分两段处理：

1. geo 基础数据：
- 本地 SQL 快照：`data/geo_db_ready.sql` 或 `data/geo_db_ready.zip`
- 本地原始 GADM：`data/gadm_410-levels.gpkg` 或 `data/gadm_410-levels.zip`
- 远程 URL：`GEO_DB_READY_URL`（下载 geo SQL 压缩包）
2. XR seed 数据：
- 本地 XR SQL：`data/col_xr_seed.sql`
- 本地 XR ZIP：`data/col_xr_seed.zip`
- 远程 URL：`GEO_DB_XR_SEED_URL`（下载 XR seed ZIP）

说明：

- geo SQL 与 XR seed 的导入都由 `geo_db/geo_init.sh` 处理。
- 本地 raw GADM 仍由 backend `prestart.sh` 调用 `scripts/import_geo_data.py` 处理（默认导入 `ADM_0..ADM_2`）。
- 即使其他开发者本地已经有 `adm_0/1/2` 和 `iho_sea_area`，只要 XR 表缺失或为空，启动时仍会继续补导 XR seed。

### 一、从 SQL 快照恢复（推荐：与 `geo_export.sh` 配套）

适用于已拿到 `geo_db_ready.sql` 或 `geo_db_ready.zip` 的情况。

`geo_export.sh` **默认**仅导出 `adm_0`、`adm_1`、`adm_2`、`iho_sea_area` 四张表；若需整库快照，导出时使用 `GEO_EXPORT_ALL=1`。

#### 方式 A：把文件放进挂载目录后用 `psql` 执行

Compose 已将宿主机的 `./data` 挂载到容器内 `/data`。将 SQL 或 ZIP 解压后的 SQL 放到项目根目录的 `data/` 下，然后：

```bash
# 确保 geo_db 已启动
docker compose up -d geo_db

# 将快照导入当前 geo_db（ON_ERROR_STOP 遇错即停）
docker compose exec -T geo_db psql -U "${POSTGRES_USER:-postgres}" -d "${GEO_DB_NAME:-geo_db}" \
  -v ON_ERROR_STOP=1 -f /data/geo_db_ready.sql
```

若只有 ZIP，先在宿主机解压出 `geo_db_ready.sql` 到 `data/`，再执行上面命令。

#### 方式 B：容器首次启动时自动拉取/导入（可选）

在 `.env` 中设置 `GEO_DB_AUTO_DOWNLOAD=true`。系统会按优先级自动判断：

- `data/geo_db_ready.sql` / `data/geo_db_ready.zip`（最高优先）
- `data/gadm_410-levels.gpkg` / `data/gadm_410-levels.zip`（若无 SQL 快照）
- `GEO_DB_READY_URL`（最后回退）
- `data/col_xr_seed.sql` / `data/col_xr_seed.zip`（XR seed 本地优先）
- `GEO_DB_XR_SEED_URL`（XR seed 最后回退）

容器内的 `geo_init.sh` 负责 geo SQL 快照、XR seed 与 URL 回退分支；backend `prestart.sh` 负责本地 raw GADM 分支（调用 `import_geo_data.py`）。

#### 干净恢复（可选）

若希望完全丢弃旧数据再导入，可删除 `geo_db` 的数据卷后重建容器，再执行方式 A（会丢失该卷内所有 geo_db 数据，请谨慎）。

```bash
docker compose down
# 仅示例：删除名为 ..._geo_db_data 的卷，请用 docker volume ls 确认实际名称
# docker volume rm <your_stack>_geo_db_data
docker compose up -d geo_db
# 然后再执行 psql -f /data/geo_db_ready.sql
```

---

### 二、从原始文件导入（`import_geo_data.py`）

适用于手上有 IHO 海域 Shapefile 目录和 GADM GeoPackage，需要在 **backend 容器** 内跑 Python 脚本写入 geo_db。

数据文件需能被 backend 容器读到：本地开发时 `./data` 常挂载到 `/app/data`，请将文件放到项目根目录 `data/` 下。

```bash
docker compose up -d geo_db backend

# IHO + GADM（路径按你实际挂载调整）
docker compose exec backend python scripts/import_geo_data.py \
  --iho-dir /app/data/World_Seas_IHO_v3 \
  --gadm-file /app/data/gadm_410-levels.gpkg

# 仅 GADM；仅导入 ADM_0～ADM_2（与主库 FDW 常用表一致，可省空间）
docker compose exec backend python scripts/import_geo_data.py \
  --gadm-only \
  --gadm-file /app/data/gadm_410-levels.gpkg \
  --gadm-max-level 2 \
  --gadm-if-exists replace
```

常用参数简述：

| 参数 | 说明 |
|------|------|
| `--gadm-only` / `--iho-only` | 只导 GADM 或只导 IHO |
| `--gadm-max-level N` | 只导入图层名形如 `ADM_0`…`ADM_N` 的层 |
| `--gadm-layer NAME` | 只导入指定图层 |
| `--gadm-if-exists` | `replace` / `append` / `fail`，写入 PostGIS 表时行为 |

依赖：容器内需有 `geopandas`、`fiona`、`sqlalchemy` 等（见 `backend/scripts/import_geo_data.py` 文件头注释）。

---

### 三、导入后主库 FDW

主库通过 `postgres_fdw` 引用 geo_db 中的表。导入完成后重启或触发后端的 `setup_fdw`（通常在 `prestart` 流程中），确保外键表与 geo_db 实际表名一致（例如 `iho_sea_area`、`adm_0`、`adm_1`、`adm_2`）。详见 `backend/scripts/setup_fdw.py`。

### 英文版

见 [GEO_IMPORT_en.md](./GEO_IMPORT_en.md)。
