# geo_db 导出说明

### 用途

将 **geo_db** 中与应用/FDW 相关的四张表导出为 SQL 文件，并打包 ZIP，便于分发给其他同事或环境直接恢复。

**默认导出的表（`public` 架构）：** `adm_0`、`adm_1`、`adm_2`、`iho_sea_area`。

若需要**整库**导出，可在运行前设置环境变量：`GEO_EXPORT_ALL=1`（或 `true`）。

### 前置条件

- 已在项目根目录配置好 `.env`（至少包含 `POSTGRES_USER`、`POSTGRES_PASSWORD`；可选 `GEO_DB_NAME`，默认 `geo_db`）。
- 已启动 Compose 中的 `geo_db` 服务，例如：`docker compose up -d geo_db`。

### 脚本位置

- `geo_db/geo_export.sh`

### 如何运行

脚本会根据自身所在位置解析**项目根目录**，并从项目根执行 `docker compose`，因此**可在任意当前工作目录下执行**（需使用可解析的路径调用脚本）。

```bash
# 在仓库根目录（默认仅上述 4 张表）
./geo_db/geo_export.sh

# 整库导出
GEO_EXPORT_ALL=1 ./geo_db/geo_export.sh

# 或使用绝对路径
bash /path/to/ecoSignal/geo_db/geo_export.sh
```

### 输出文件

生成于项目根目录的 **`data/`**：

| 文件 | 说明 |
|------|------|
| `data/geo_db_ready.sql` | `pg_dump` 生成的 SQL（含 `--clean --if-exists`） |
| `data/geo_db_ready.zip` | 上述 SQL 的压缩包，便于传输 |

### 技术说明

- 在容器内执行：`docker compose exec -T geo_db pg_dump ...`；默认带多个 `-t public.<表名>`。
- 使用 `--no-owner --no-privileges`，便于在不同机器上恢复。
- 默认仅上述 **4 张表**；`GEO_EXPORT_ALL=1` 时为**整库**。

### 常见问题

- **`docker compose` 找不到服务**：请确认脚本位于 `<项目根>/geo_db/geo_export.sh`，且项目根目录下存在 `docker-compose.yml`（脚本将「脚本所在目录的上一级」视为项目根）。

### 英文版

见 [GEO_EXPORT_en.md](./GEO_EXPORT_en.md)。
