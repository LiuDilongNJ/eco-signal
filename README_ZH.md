# ecoSignal

[English](README.md)

**ecoSignal** 是 [ecoSound-web](https://github.com/ecomontec/ecoSound-web/) 的现代化重构版本，使用高性能的现代 Web 技术构建，支持照片和离线在线同步。

## 描述

用于协作管理、浏览、可视化、标注和分析生物多样性监测调查中音频与照片的 Web 应用程序。

## 技术栈

本项目采用现代且经过优化的全栈架构：

- **后端**: [FastAPI](https://fastapi.tiangolo.com/) (Python)
-   **主数据库**: [PostgreSQL](https://www.postgresql.org/) (附带 PostGIS 扩展)。
-   **地理数据库**: 独立的 PostGIS 实例，用于存储全球地理空间数据（IHO/GADM）。
- **基础设施**: [Docker Compose](https://www.docker.com/)
- **可观测性**: Sentry（错误跟踪）+ Prometheus（指标监控）

详细配置与使用说明见 [docs/observability.zh.md](docs/observability.zh.md)。

## 快速开始

本项目实现了全自动化。地理数据初始化和数据库迁移在首次启动时会自动处理。

### 先决条件

-   已克隆的代码仓库
-   首次安装时请确保至少有 50 GB 可用磁盘空间，以避免构建失败；若同一主机还保留用于后续迁移的 `ecoSound-web` 目录，则需要额外预留空间。
-   建议使用 23.0 或更高版本的 [Docker Engine](https://docs.docker.com/engine/install/)。
-   使用 2.22 或更高版本的 [Docker Compose](https://docs.docker.com/compose/install/)。
-   必须安装 [Docker Buildx 插件](https://docs.docker.com/build/buildx/) 和 BuildKit。当前版本的 Docker Engine 和 Docker Desktop 已自带这些组件，并默认使用 BuildKit。本项目的 Dockerfile 使用了仅由 BuildKit 支持的 `RUN --mount` 指令，用于依赖和构建缓存。

    启动项目前请检查相关组件：

    ```bash
    docker version
    docker compose version
    docker buildx version
    docker buildx inspect --bootstrap
    ```

    如果 `docker buildx version` 不可用，或者构建时出现 `the --mount option requires BuildKit`，请从 Docker 官方软件源安装 Docker，并同时安装 `docker-buildx-plugin` 和 `docker-compose-plugin`。Ubuntu 下可以执行：

    ```bash
    sudo apt-get update
    sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    ```

    对于较旧的 Docker 安装，在启动项目之前，可以为当前 Shell 启用 BuildKit。Docker Compose v2 使用 `DOCKER_BUILDKIT`；`COMPOSE_DOCKER_CLI_BUILD` 仅适用于旧版 Compose v1：

    ```bash
    export DOCKER_BUILDKIT=1
    ```

    除非系统管理员明确要求，否则不建议手动下载独立的 Buildx 二进制文件。优先使用版本化的 Docker 软件包，以确保 Docker Engine、Buildx 和 Compose 版本兼容。

### 运行项目（本地开发模式）

1.  **初始化环境变量文件**:

    请在已克隆的代码仓库根目录执行：
    ```bash
    cp .env.example .env
    ```

    然后打开 `.env`，按当前环境填写实际配置后再启动项目。
    至少需要重点检查 `SECRET_KEY`、`FIRST_SUPERUSER`、`FIRST_SUPERUSER_PASSWORD` 和 `POSTGRES_PASSWORD`。
    如果你要部署项目或启用可选集成，还需要按场景补充域名、邮箱、Sentry、RabbitMQ、旧项目路径等配置。

    `RABBITMQ_ERLANG_COOKIE` 提供本地开发默认值。每个部署环境都应替换为唯一且稳定的随机值，例如：

    ```bash
    openssl rand -hex 32
    ```

    只要 RabbitMQ 数据卷仍在使用，就必须保持该部署值不变；修改它会使 RabbitMQ 节点无法启动。

    Docker Compose 使用 `STACK_NAME` 作为项目名，默认值为 `ecosignal`，不会根据仓库所在目录自动变化。启动项目和迁移数据时必须保持该值一致。如果使用自定义项目名：

    ```bash
    STACK_NAME=eco-signal docker compose up -d
    STACK_NAME=eco-signal ./migrate-data.sh /path/to/source
    ```

    `.env.example` 是可提交的初始化模板，`.env` 仅用于本地或部署环境，不能提交真实密钥、密码或其他敏感配置。

2.  **启动堆栈**:

    ```bash
    docker compose watch
    ```

    *或者使用 `docker compose up --build -d` 进行标准的后台启动。*

    首次启动时，由 `worker` 容器把 BirdNET 所需模型下载到共享的 `app-ai-models` volume 中。`backend` 会跳过这一步，避免健康检查被模型下载阻塞。后续重新构建或重启会直接复用该 volume；只要所需模型文件仍然存在，就不会重复下载。

    如果当前网络无法访问 Docker Hub，请在启动前于 `.env` 中配置镜像源。例如：

    ```bash
    PYTHON_BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
    PYTHON_DEV_BASE_IMAGE=docker.m.daocloud.io/library/python:3.12
    NODE_BASE_IMAGE=docker.m.daocloud.io/library/node:22-alpine
    NGINX_BASE_IMAGE=docker.m.daocloud.io/library/nginx:alpine
    POSTGIS_BASE_IMAGE=docker.m.daocloud.io/imresamu/postgis:17-3.5
    DOCKER_IMAGE_POSTGIS=docker.m.daocloud.io/imresamu/postgis:17-3.5
    DOCKER_IMAGE_REDIS=docker.m.daocloud.io/library/redis:7-alpine
    DOCKER_IMAGE_RABBITMQ=docker.m.daocloud.io/library/rabbitmq:3-management
    ```

3.  **地理数据初始化**:
    首次启动时，`geo_db` 容器会在后台自动下载并导入地理空间数据（IHO/GADM）。您可以通过以下命令查看进度：
    ```bash
    docker compose logs -f geo_db
    ```
    *注意：后端服务会立即启动。一旦后台导入完成，后端功能将自动连接到这些地理数据表。*

4.  **访问服务**:

    **默认（`FRONTEND_PORT=80`）**:

    | 服务               | URL                        |
    | ------------------ | -------------------------- |
    | 前端               | http://localhost           |
    | 后端 API           | http://localhost:28000      |
    | API 文档 (Swagger) | http://localhost:28000/docs |
    | Traefik 界面       | http://localhost:8090      |

    如果希望把 Docker 前端暴露到别的宿主机端口，请修改根目录 `.env` 里的 `FRONTEND_PORT`，例如 `http://localhost:3001`。

5.  **停止堆栈**:
    ```bash
    docker compose down
    ```

## 媒体上传处理

普通音频和照片上传时，可选择一个或多个文件；所有分块上传完成后，即可在上传抽屉中保存该批文件。

- 分块上传仅创建暂存记录，不会为每个文件单独创建 Queue 记录。
- 保存后会为本次受理的文件创建一条 `upload` Queue 记录。`total` 为提交文件总数，`completed` 仅统计成功创建媒体的数量。
- 文件合并、内容校验、重复检测、媒体创建和预览生成会在该后台批处理中按顺序执行。
- 只有重复文件的批次会以 warning 结束；任一文件处理失败时会以 error 结束。请在 Queue 页面查看每次提交的最终结果。

## 离线实地工作

EcoSignal 支持基于签名集合包的离线实地工作流，离线包可包含音频、图片、标注、审核和标签。

### 导出集合离线包

在 Web 界面进入 `Data > Collections`，选择一个集合后点击 `Export Bundle`。系统会在后台生成始终包含媒体文件的完整 zip；任务完成后可在导出抽屉中下载，文件保留 24 小时。

### 导入集合离线包

选择目标项目，在 `Data > Collections` 点击 `Import Bundle`，选择一个 zip。Web 会分块上传，并显示后台导入状态、创建/跳过数量、冲突和警告；关闭抽屉后任务仍会继续，可在 Queue 页面查看。

规则：

- 目标 `project_id` 必须已存在。
- 调用者必须对该项目拥有 `project:write`。
- 离线导入批次只接受 `.zip` 文件。
- 服务端会在导入前校验离线包签名和 SHA-256 校验和。
- 媒体以 UUID 作为身份键：UUID 与文件内容均一致时复用媒体并关联到目标集合；UUID 相同但内容不同时终止整次导入。
- 文件哈希相同但 UUID 不同的媒体仍作为独立记录导入。
- 导入永不覆盖已有文件；文件名冲突时使用确定性的 UUID 后缀。
- 导入后重新生成音频与图片预览；预览生成失败只记录警告，不会丢弃已导入媒体。
- 底层导出接口为 `POST /api/v1/collection-bundle-exports`，导入会话接口为 `POST /api/v1/data-imports`。

## 数据迁移与回滚脚本

如需将老项目 `ecoSound-web` 的数据一次性迁移到 `ecoSignal`，请使用仓库根目录脚本。

### 前置条件

- `ecoSignal` 的 `backend` 和 `db` 容器已运行（`docker compose watch` 或 `docker compose up -d`）。
- 老项目 `ecoSound-web` 目录存在（默认 `./ecoSound-web`，可通过 `.env` 中 `LEGACY_PROJECT_DIR` 配置）。
- 若启用数据库迁移，老项目 MySQL 需可连通。
- 在 Linux 下，`backend` 容器通过 `host.docker.internal` 访问宿主机 MySQL，本仓库已在 Compose 中通过 `host-gateway` 提供该映射。

### 迁移老数据到 ecoSignal

```bash
chmod +x ./migrate-data.sh
sudo ./migrate-data.sh <old-project-dir> [options]
```

示例：

```bash
# 全新部署后的推荐首次迁移：先备份并清空 Demo/种子数据，再迁移
./migrate-data.sh --reset-target

# 显式指定老项目路径（全新部署后仍需加 --reset-target）
./migrate-data.sh /path/to/ecoSound-web --reset-target

# 仅预演（不写入）
./migrate-data.sh --dry-run

# 仅适用于空目标库（没有 Demo Project / collection / site）
./migrate-data.sh

# 显式指定被迁移实例的公开访问地址
./migrate-data.sh --reset-target --legacy-app-url https://ecosound-web.example.com/ecosound_web
```

常用参数：

- `--dry-run`：预演迁移流程，不写入数据
- `--skip-db`：跳过数据库迁移
- `--skip-files`：跳过静态文件迁移
- `--copy-files`：将老项目静态文件直接复制到 `app-media-data` 卷（应急模式）
- `--reset-target`：全新部署后必须使用。先备份当前 ecoSignal 的 DB/媒体，再清空业务数据（含 Demo Project / collection / site）并迁移
- `--legacy-app-url <url>`：被迁移实例的公开访问地址，用于在联邦网络中标识其自身节点

### 老实例访问地址的解析顺序

迁移过程必须知道被迁移实例的公开访问地址，因为该地址是联邦网络中本机节点的身份标识。老项目安装包中 `APP_URL` 默认为空，运行时按请求动态推导主机名，因此这个地址往往无法自动探测到。

解析顺序，取第一个非空值：

1. 命令行参数 `--legacy-app-url <url>`
2. shell 环境变量或 `.env` 中的 `LEGACY_APP_URL`
3. 老项目 `src/config/config.ini` 中的 `APP_URL`
4. 从老项目数据库推断：先取存储的 `app_url` 设置，再按服务器名称与经纬度在已知联邦节点中查找唯一匹配

`LEGACY_HOST_URL` 遵循同样的「环境变量优先于配置文件」规则，默认取老项目的 `HOST_URL`。非 `http://` 或 `https://` 的取值会在迁移开始前被拒绝。

以上都无法解析时，迁移会在预检阶段中止，此时尚未写入任何数据，并输出实际读取到的服务器名称、经纬度与候选地址。在 `.env` 中配置 `LEGACY_APP_URL` 后按原参数重新执行即可；预检中止不会留下半迁移状态。

迁移说明：

- 首次启动会写入 Demo Project、Demo collection 和 Demo site。全新部署后的第一次迁移如果不加 `--reset-target` 会失败。
- 脚本会先在宿主机侧检查老项目 MySQL 的连通性，再启动容器内迁移流程。
- 默认媒体迁移策略为 `direct-mount`：脚本会基于当前 `LEGACY_PROJECT_DIR` 重新创建 `backend` 和 `worker` 容器，并在数据库迁移开始前校验 `/app/sounds/sounds`、`/app/sounds/images` 和 `/app/sounds/projects` 是否可用。
- 修改 `LEGACY_PROJECT_DIR` 后，单纯执行 `docker compose restart` 不足以刷新 legacy 目录的 bind mount；迁移脚本会使用重建容器的方式确保挂载生效。
- `--copy-files` 会切换到复制模式：将老项目媒体文件复制进 `app-media-data`，迁移完成后的访问将不再依赖老项目目录持续挂载。
- 实际数据库迁移运行在 `backend` 容器内，默认通过 `host.docker.internal` 连接老项目 MySQL。
- 如果老项目 MySQL 不在当前 Docker 宿主机上，请在执行脚本前通过 `MYSQL_HOST` 显式指定可访问地址。

### 从备份执行回滚

```bash
./rollback.sh <backup_name> [options]
```

示例：

```bash
# 使用 .upgrade-backup/ 中最新备份
./rollback.sh latest

# 回滚到指定备份
./rollback.sh backup_20260411_133000

# 回滚到 target 备份并跳过确认
./rollback.sh target_backup_20260420_210000 --force
```

常用参数：

- `--force`：跳过确认提示
- `--keep-new`：回滚到 legacy 备份时保留当前 ecoSignal 卷数据

说明：

- 备份统一存放在 `./.upgrade-backup/`。
- `target_backup_*` 表示 ecoSignal 目标备份（DB + 媒体），通常由 reset 迁移前生成。
- `backup_*` 表示用于回滚到 ecoSound-web 的 legacy 备份集。

## 运行测试

在已运行的本地 Docker 堆栈中执行测试：

```bash
# 后端完整测试
docker compose exec -T backend pytest

# 指定后端测试模块或测试用例
docker compose exec -T backend pytest tests/api/routes/test_media.py
docker compose exec -T backend pytest tests/api/routes/test_media.py::test_create_media

# 前端测试和生产构建
docker compose exec -T frontend npm run test -- --run
docker compose exec -T frontend npm run build
```

后端 pytest 会在同一 PostgreSQL 实例中使用独立的 `ecosignal_test` 数据库：创建或复用该数据库，在其中执行迁移并初始化测试数据；不会向业务数据库 `ecosignal` 写入数据。`ecosignal_test` 会在测试结束后保留，可在不再需要时单独清理。

> 警告：`./scripts/test-local.sh` 会在重建堆栈前执行 `docker-compose down -v --remove-orphans`，并删除当前 Compose 项目的数据库、媒体、Redis 和 RabbitMQ 卷。它只能用于数据可丢弃的隔离环境；不得对需要保留数据的本地或部署堆栈执行。

## 监控

- **Sentry**：用于采集 API 未处理异常与 worker 任务异常（开启时）。
- **Prometheus**：通过 `GET /metrics` 暴露服务指标。
- 生产环境建议将 `/metrics` 放在内网或网关保护后访问。
- 完整文档见 [docs/observability.zh.md](docs/observability.zh.md)

## 部署

本项目使用 Docker Compose 进行部署，默认使用 HTTP；设置 `ENABLE_HTTPS=true` 后才启用由 Traefik 管理的 HTTPS 部署。

### 先决条件

1. 已安装 Docker 的远程服务器
2. 一条指向服务器的域名解析记录，或本机 `hosts` 映射

### 部署步骤

1. **基于模板创建环境变量文件**：

   ```bash
   cp .env.example .env
   ```

   然后编辑 `.env`，填入部署环境所需的真实配置。
   请重点确认 `SECRET_KEY`、`FIRST_SUPERUSER`、`FIRST_SUPERUSER_PASSWORD`、`POSTGRES_PASSWORD`、`REDIS_PASSWORD`，以及当前环境需要的域名、邮箱、Sentry、旧项目路径等变量。
   HTTP 模式使用 `DOMAIN` 和 `FRONTEND_PORT` 在同一来源提供前端、API 与媒体。仅在公网部署时设置 `ENABLE_HTTPS=true`：前端使用 `dashboard.DOMAIN`，API 使用 `api.DOMAIN`，并要求配置 `EMAIL`、域名解析及公网 80/443 入站端口。

   `./deploy.sh` 从根目录 `.env` 读取 `ENVIRONMENT`。允许值为 `local`、`staging`、`production`；`.env.example` 与后端代码的默认值都是 `local`。测试服务器应明确设置为 `staging`，正式服务器应明确设置为 `production`。`local` 环境始终关闭登录空闲超时；`staging` 和 `production` 使用 `AUTH_SESSION_IDLE_EXPIRE_MINUTES` 控制超时时间，默认 30 分钟。

   `ENVIRONMENT=production` 只配置后端，不能解决前端 Vite 错误覆盖层问题，也不会将 Vite 开发服务器切换为生产模式。下面的命令只检查 Compose 最终解析出的环境变量值，不会启动或修改任何服务。

   部署前可检查 Compose 最终解析的值：

   ```bash
   docker compose -f docker-compose.yml config --environment | grep '^ENVIRONMENT='
   ```

   `.env.example` 用于版本管理中的模板分发；`.env` 属于环境专用文件，必须保持未提交状态。

2. **以生产模式部署前端**。这是解决 Vite 开发错误覆盖层出现在已打开浏览器标签页中的方法。该脚本会排除 `docker-compose.override.yml`、构建前端生产包，并通过 nginx 提供服务；同时串行化发布、等待依赖就绪、单次执行初始化，并等待服务健康：
   ```bash
   chmod +x ./deploy.sh ./rollback.sh
   ./deploy.sh --dry-run
   sudo ./deploy.sh
   ```

   不要使用 `docker compose up`、`docker compose up -d` 或 `docker compose watch` 作为公网/生产部署方式：这些命令会自动加载 `docker-compose.override.yml`，并通过 5173 端口上的 Vite 开发服务器启动前端。Windows PowerShell 请使用 `.\deploy.ps1`；命令提示符可使用 `deploy.bat`。

   部署后可在后端容器中确认实际环境和有效空闲超时时间：

   ```bash
   STACK_NAME="$(docker compose -f docker-compose.yml config --environment | awk -F= '$1 == "STACK_NAME" { print tolower($2); exit }')"
   docker compose --project-name "${STACK_NAME:-ecosignal}" --profile production -f docker-compose.yml exec backend python -c \
   'from app.core.config import settings; print(settings.ENVIRONMENT, settings.auth_session_idle_timeout_seconds)'
   ```

   当 `ENVIRONMENT=production` 且使用默认超时时间时，预期输出为 `production 1800`。

   macOS 和 Linux 使用 `./deploy.sh`，两者均不再依赖 `flock`。

   使用 `--dry-run` 验证生产配置，只有确认 `.deploy/deploy.lock` 是遗留锁时才使用 `--force-unlock`。只有需要自定义镜像标签时才设置 `TAG`，否则 Compose 使用 `latest`。脚本只使用生产 Compose 文件；`docker-compose.override.yml` 仍是本地 `docker compose up` 和 `docker compose watch` 使用的开发覆盖配置。

   生产默认使用三个 Web worker，并分离交互任务和分析任务消费者。交互任务消费者同时执行启动同步和定时维护。仅应在观察 CPU、内存、队列深度和 PostgreSQL 连接使用情况后调整 `WEB_CONCURRENCY` 与 `DB_*` 连接池参数。

### 使用 GitHub Actions 进行 CI/CD

本项目使用 **GitHub Actions** 进行自动化部署。

| 环境                      | 触发条件             | 工作流文件                                |
| ------------------------- | -------------------- | ----------------------------------------- |
| **预发布 (Staging)**      | 推送到 `main` 分支   | `.github/workflows/deploy-staging.yml`    |
| **生产环境 (Production)** | 发布新的 Release     | `.github/workflows/deploy-production.yml` |

工作流会直接设置 `ENVIRONMENT`：staging 工作流使用 `staging`，production 工作流使用 `production`，无需将 `ENVIRONMENT` 配置为 GitHub Variable。

#### 必需的 GitHub Secrets

| Secret                                         | 说明            |
| ---------------------------------------------- | --------------- |
| `SECRET_KEY`                                   | 应用程序密钥    |
| `FIRST_SUPERUSER`                              | 管理员邮箱      |
| `FIRST_SUPERUSER_PASSWORD`                     | 管理员密码      |
| `POSTGRES_PASSWORD`                            | 数据库密码      |
| `REDIS_PASSWORD`                               | Redis 密码（本地默认 `ecosignal`；staging/production 须通过 secret 覆盖） |
| `RABBITMQ_ERLANG_COOKIE`                       | RabbitMQ 节点 cookie（每个部署环境均须以唯一且稳定的 secret 替换本地默认值） |
| `SENTRY_DSN`                                   | Sentry DSN（可选） |

#### 可选 GitHub Variables

| Variable               | 默认值            | 说明                    |
| ---------------------- | ----------------- | ----------------------- |
| `DOMAIN`               | 无                | 部署域名                |
| `FRONTEND_PORT`        | `80`              | 前端宿主机端口          |
| `STACK_NAME`           | 无                | Docker Compose 项目名   |
| `BACKEND_CORS_ORIGINS` | 无                | 后端 CORS 来源          |
| `AUTH_SESSION_IDLE_EXPIRE_MINUTES` | `30` | staging/production 登录空闲超时分钟数；设为 `0` 可关闭 |
| `PROJECT_NAME`         | `ecoSignal`       | 应用名称                |
| `POSTGRES_USER`        | `postgres`        | PostgreSQL 用户名       |
| `POSTGRES_DB`          | `ecosignal`       | PostgreSQL 数据库名     |
| `DOCKER_IMAGE_BACKEND` | `backend`         | 后端镜像名              |
| `DOCKER_IMAGE_FRONTEND`| `frontend`        | 前端镜像名              |
| `LEGACY_PROJECT_DIR`   | `./ecoSound-web`  | 旧项目媒体目录挂载路径  |
| `LEGACY_APP_URL`       | 无                | 被迁移实例的公开访问地址，迁移时用于标识联邦节点身份 |
| `LEGACY_HOST_URL`      | 旧项目 `HOST_URL` | 老实例注册到的联邦中心节点地址 |
| `GEO_DB_READY_URL`     | 内置默认值        | Geo DB ready 压缩包地址 |
| `GEO_DB_XR_SEED_URL`   | 内置默认值        | Geo DB XR seed 压缩包地址 |
请在 GitHub 的 `staging` 和 `production` 两个 environment 中分别定义 `DOMAIN`、`STACK_NAME`、`BACKEND_CORS_ORIGINS`，这样变量名就能和 `.env` 保持一致，同时每个环境仍可使用不同的值。

#### 安装 GitHub Actions Runner

按照 [GitHub Actions 自托管运行器指南](https://docs.github.com/en/actions/hosting-your-own-runners) 在您的服务器上设置运行器，并使用适当的环境标签（`staging` 或 `production`）。

部署工作流会先在 runner 上把 `.env.example` 复制为 `.env`，再追加 GitHub Actions secrets 和 variables 中的环境差异配置进行覆盖。

## 鸣谢和许可

本项目是 **ecoSound-web** 的重构版本。

- **原始设计**: [Kevin Darras](http://kevindarras.weebly.com/index.html)
- **原始开发**: [Noemi Perez](https://github.com/nperezg) 和 Dilong Liu。
- **许可证**: 根据 [GNU General Public License, v3](https://www.gnu.org/licenses/gpl-3.0.en.html) 许可。

相应的可更新科学出版物位于 [F1000Research](https://f1000research.com/articles/9-1224/v3)。
