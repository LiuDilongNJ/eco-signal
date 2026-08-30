# ecoSignal 运维指南

[English](operations-guide.md) · [文档首页](../README_ZH.md)

**适用对象：** 部署、维护、迁移或恢复共享 ecoSignal 环境的运维人员。  
**开始前：** 请准备 Docker 主机、安全的环境变量值，并在变更已部署系统前确认备份可用。

## 目录

- [配置生产环境](#配置生产环境)
- [部署和验证](#部署和验证)
- [使用 GitHub Actions](#使用-github-actions)
- [迁移数据](#迁移数据)
- [恢复数据](#恢复数据)

## 配置生产环境

从 `.env.example` 创建 `.env`，并设置 `SECRET_KEY`、`FIRST_SUPERUSER`、`FIRST_SUPERUSER_PASSWORD`、`POSTGRES_PASSWORD`、`REDIS_PASSWORD`、`RABBITMQ_ERLANG_COOKIE` 以及所需域名、邮件、Sentry 和集成配置的真实值。

显式设置 `ENVIRONMENT=staging` 或 `ENVIRONMENT=production`。`AUTH_SESSION_IDLE_EXPIRE_MINUTES` 控制空闲过期时间，默认 30 分钟。一个部署运行栈应使用稳定的 `STACK_NAME`。部署前检查解析后的配置：

```bash
docker compose -f docker-compose.yml config --environment | grep '^ENVIRONMENT='
```

HTTP 是默认方式。公开 HTTPS 部署需要 `ENABLE_HTTPS=true`、`dashboard.DOMAIN`、`api.DOMAIN`、`EMAIL` 以及公开入站端口 80 和 443。HTTP 模式使用同一来源上的 `DOMAIN` 和 `FRONTEND_PORT`。

## 部署和验证

使用生产脚本。该脚本不加载本地开发覆盖配置，会构建前端生产包、串行化发布、等待依赖并检查健康状态：

```bash
chmod +x ./deploy.sh ./rollback.sh
./deploy.sh --dry-run
sudo ./deploy.sh
```

公共部署不要使用 `docker compose up`、`docker compose up -d` 或 `docker compose watch`，它们会加载本地开发覆盖配置。Windows 使用 `deploy.ps1` 或 `deploy.bat`。

部署后验证当前环境和空闲超时：

```bash
STACK_NAME="$(docker compose -f docker-compose.yml config --environment | awk -F= '$1 == "STACK_NAME" { print tolower($2); exit }')"
docker compose --project-name "${STACK_NAME:-ecosignal}" --profile production -f docker-compose.yml exec backend python -c \
  'from app.core.config import settings; print(settings.ENVIRONMENT, settings.auth_session_idle_timeout_seconds)'
```

默认生产环境输出为 `production 1800`。仅在确认 `.deploy/deploy.lock` 已过期后使用 `--force-unlock`。只有观察 CPU、内存、队列深度和连接使用情况后，才调整 worker 与数据库设置。

## 使用 GitHub Actions

staging 在推送到 `main` 时运行，production 在发布 Release 时运行。将 `SECRET_KEY`、`FIRST_SUPERUSER`、`FIRST_SUPERUSER_PASSWORD`、`POSTGRES_PASSWORD`、`REDIS_PASSWORD` 和 `RABBITMQ_ERLANG_COOKIE` 配置为环境 Secrets；启用时增加 `SENTRY_DSN`。

`DOMAIN`、`FRONTEND_PORT`、`STACK_NAME`、`BACKEND_CORS_ORIGINS`、`AUTH_SESSION_IDLE_EXPIRE_MINUTES` 等可选值应在 staging 与 production 环境中分别配置。不要把 `ENVIRONMENT` 定义为 GitHub 变量。安装带有对应环境标签的自托管 Runner。

## 迁移数据

迁移前应运行目标 `backend` 和 `db` 容器，提供来源项目目录，并在启用数据库迁移时确认来源 MySQL 连通。在 Linux 上，后端可通过 `host.docker.internal` 访问同机 MySQL；其他主机请设置 `MYSQL_HOST`。

任何写入前都必须预演：

```bash
chmod +x ./migrate-data.sh
./migrate-data.sh --dry-run
./migrate-data.sh --reset-target
```

完整命令形式为：

```bash
sudo ./migrate-data.sh <source-project-dir> [options]
```

示例：

```bash
# 备份后重置新部署的目标环境
./migrate-data.sh --reset-target

# 指定来源项目目录
./migrate-data.sh /path/to/ecoSound-web --reset-target

# 仅迁移文件或仅迁移数据库
./migrate-data.sh --skip-db
./migrate-data.sh --skip-files

# 将文件复制到受管理的媒体卷
./migrate-data.sh --copy-files

# 显式设置来源公开地址
./migrate-data.sh --reset-target --legacy-app-url https://ecosound-web.example.com/ecosound_web
```

`--reset-target` 会备份目标数据库和媒体、清理业务数据后开始迁移。`--skip-db`、`--skip-files` 和 `--copy-files` 用于限定或选择迁移方式。默认方式在迁移期间挂载来源媒体；复制方式将媒体存入目标受管理的数据卷。不要手动执行破坏性数据库操作替代 reset 流程。

常用选项包括：

- `--dry-run`：预演迁移，不写入数据
- `--skip-db`：跳过数据库迁移
- `--skip-files`：跳过静态文件迁移
- `--copy-files`：将来源静态文件复制到 `app-media-data` 卷
- `--reset-target`：备份目标数据库和媒体、清理业务数据后迁移
- `--legacy-app-url <url>`：提供用于识别联邦节点的来源公开地址

脚本会在容器内迁移开始前从宿主机检查来源 MySQL 连通性。新部署目标首次迁移时，预置的 Demo Project、集合和站点要求使用 `--reset-target`。修改 `LEGACY_PROJECT_DIR` 后必须重建容器；普通 `docker compose restart` 不会刷新绑定挂载。默认直接挂载方式会在数据库处理前验证 `/app/sounds/sounds`、`/app/sounds/images` 和 `/app/sounds/projects`。复制方式将文件放入 `app-media-data`，迁移后不再依赖来源目录保持挂载。

无法自动解析来源公开地址时，传入 `--legacy-app-url <url>` 或设置 `LEGACY_APP_URL`。若没有有效的 `http://` 或 `https://` 候选值，地址解析会在写入前停止。

来源地址按第一个非空值优先：命令行 `--legacy-app-url <url>`、shell 或 `.env` 中的 `LEGACY_APP_URL`、来源 `src/config/config.ini` 中的 `APP_URL`、来源数据库保存的 `app_url`，最后是在已知联邦节点中根据服务器名称和坐标得到的唯一匹配。`LEGACY_HOST_URL` 同样遵循环境变量优先于配置的规则，并默认使用来源 `HOST_URL`。解析失败时，preflight 会报告服务器名称、坐标和候选地址，不会留下部分迁移数据。

## 恢复数据

使用以下命令恢复迁移备份：

```bash
./rollback.sh latest
./rollback.sh backup_20260411_133000
./rollback.sh target_backup_20260420_210000 --force
```

备份位于 `.upgrade-backup/`。恢复前请确认备份名称和影响。`--force` 跳过确认；恢复来源备份时，`--keep-new` 会保留当前目标卷。

`backup_*` 用于将来源数据恢复到来源安装环境；`target_backup_*` 是 reset 迁移前保存的目标数据库和媒体备份。请将备份目录置于不会被测试环境清理的位置，并在恢复后确认服务正常，再允许用户继续工作。

## 生产部署细节

生产脚本只使用生产 Compose 文件，会构建前端生产包、通过 nginx 提供服务、执行一次初始化、等待依赖和健康检查，并串行化并发发布。只有需要自定义镜像标签时才设置 `TAG`，否则 Compose 使用 `latest`。macOS 和 Linux 使用 `./deploy.sh`，不需要 `flock`。

staging 工作流为 `.github/workflows/deploy-staging.yml`，在推送到 `main` 时运行；production 工作流为 `.github/workflows/deploy-production.yml`，在发布 Release 时运行。必需 Secrets 为 `SECRET_KEY`、`FIRST_SUPERUSER`、`FIRST_SUPERUSER_PASSWORD`、`POSTGRES_PASSWORD`、`REDIS_PASSWORD`、`RABBITMQ_ERLANG_COOKIE`，启用时增加 `SENTRY_DSN`。

可选 GitHub 变量包括 `DOMAIN`、`FRONTEND_PORT`、`STACK_NAME`、`BACKEND_CORS_ORIGINS`、`AUTH_SESSION_IDLE_EXPIRE_MINUTES`、`PROJECT_NAME`、`POSTGRES_USER`、`POSTGRES_DB`、`DOCKER_IMAGE_BACKEND`、`DOCKER_IMAGE_FRONTEND`、`LEGACY_PROJECT_DIR`、`LEGACY_APP_URL`、`LEGACY_HOST_URL`、`GEO_DB_READY_URL` 和 `GEO_DB_XR_SEED_URL`。staging 与 production 应分别设置域名、运行栈和 CORS 值。工作流直接设置 `ENVIRONMENT`，并在追加环境配置前复制 `.env.example`。

主要默认值为 `FRONTEND_PORT=80`、`PROJECT_NAME=ecoSignal`、`POSTGRES_USER=postgres`、`POSTGRES_DB=ecosignal`、staging 和 production 中默认 30 分钟的 `AUTH_SESSION_IDLE_EXPIRE_MINUTES`，以及地理数据 URL 的内置默认值。虽然本地开发有默认值，staging 和 production 仍必须替换 `REDIS_PASSWORD`。

| 变量 | 默认值或含义 |
| --- | --- |
| `DOMAIN` | 无默认值；部署域名 |
| `FRONTEND_PORT` | `80`；前端宿主机端口 |
| `STACK_NAME` | Compose 项目名称 |
| `BACKEND_CORS_ORIGINS` | 无默认值；允许的后端来源 |
| `AUTH_SESSION_IDLE_EXPIRE_MINUTES` | staging/production 为 `30`；`0` 禁用过期 |
| `PROJECT_NAME` | `ecoSignal` |
| `POSTGRES_USER` / `POSTGRES_DB` | `postgres` / `ecosignal` |
| `DOCKER_IMAGE_BACKEND` / `DOCKER_IMAGE_FRONTEND` | `backend` / `frontend` |
| `LEGACY_PROJECT_DIR` | `./ecoSound-web`；来源媒体路径 |
| `LEGACY_APP_URL` / `LEGACY_HOST_URL` | 来源公开地址 / 联邦中心 |
| `GEO_DB_READY_URL` / `GEO_DB_XR_SEED_URL` | 内置地理数据默认地址 |

生产默认使用三个 Web worker，并分离交互和分析消费者。交互消费者还负责启动同步和定时维护。只有观察资源使用、队列深度和 PostgreSQL 连接后，才调整 `WEB_CONCURRENCY` 与 `DB_*` 连接池参数。

指标、错误和仪表盘请参阅[可观测性操作文档](observability.zh.md)。生产环境应通过内部网络或网关保护指标。

## 相关文档

- [管理员指南](admin-guide.zh.md)：应用层运维
- [用户指南](user-guide.zh.md)：日常工作流
- [文档首页](../README_ZH.md)
