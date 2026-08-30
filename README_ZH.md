# ecoSignal

[English documentation](README.md)

ecoSignal 是一个用于协作管理、浏览、可视化、标注和分析生物多样性监测音频与照片的 Web 应用，支持在线与离线连续开展的野外工作。

## 技术栈

- 后端：[FastAPI](https://fastapi.tiangolo.com/) + PostgreSQL/PostGIS
- 前端：React 与 TypeScript
- 基础设施：Docker Compose
- 可观测性：Sentry 与 Prometheus

## 快速开始

### 环境要求

- Docker Engine 23.0 或更高版本
- Docker Compose v2.22 或更高版本
- 已启用 BuildKit 的 Docker Buildx
- 首次安装至少 50 GB 可用磁盘空间

检查 Docker 安装：

```bash
docker version
docker compose version
docker buildx version
docker buildx inspect --bootstrap
```

Dockerfile 使用 BuildKit 缓存挂载。旧环境如有需要，可在当前 shell 启用 BuildKit：

```bash
export DOCKER_BUILDKIT=1
```

如果 `docker buildx version` 不可用，或构建报告 `the --mount option requires BuildKit`，请通过官方软件包安装包含 `docker-buildx-plugin` 和 `docker-compose-plugin` 的 Docker。在 Ubuntu 上：

```bash
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 配置和运行

在仓库根目录创建本地环境文件：

```bash
cp .env.example .env
```

至少检查 `SECRET_KEY`、`FIRST_SUPERUSER`、`FIRST_SUPERUSER_PASSWORD` 和 `POSTGRES_PASSWORD`。`.env.example` 是可提交的模板；`.env` 是环境专属文件，不能提交。

启动开发运行栈：

```bash
docker compose watch
```

如需后台启动，使用 `docker compose up --build -d`；使用 `docker compose down` 停止运行栈。Docker Compose 使用 `STACK_NAME` 作为项目名称，默认是 `ecosignal`；针对同一运行栈的命令应保持一致。

首次启动时，worker 会将 BirdNET 资源下载到共享模型卷。地理数据库会在后台导入参考数据，可用以下命令查看进度：

```bash
docker compose logs -f geo_db
```

地理数据导入未完成时后端仍可启动。Docker Hub 不可用时，可在 `.env` 中配置镜像镜像地址。

### 服务地址

使用默认 `FRONTEND_PORT=80` 时：

| 服务 | 地址 |
| --- | --- |
| Web 应用 | http://localhost |
| API | http://localhost:28000 |
| API 文档 | http://localhost:28000/docs |
| Traefik 控制台 | http://localhost:8090 |

如需更换前端宿主机端口，请在 `.env` 中设置 `FRONTEND_PORT`。

### 本地开发说明

- worker 首次启动会下载模型资源一次，后续重启会复用共享模型卷。
- 地理数据库会在后台导入参考数据，导入持续时间超过后端首次启动属于正常情况。
- BuildKit 缓存挂载指令失败时，应安装包含 Buildx 和 Compose 插件的新版 Docker Engine，而不是使用独立 Buildx 二进制文件。
- Docker Hub 无法访问时，可在 `.env` 中配置镜像地址，例如：

  ```dotenv
  PYTHON_BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
  PYTHON_DEV_BASE_IMAGE=docker.m.daocloud.io/library/python:3.12
  NODE_BASE_IMAGE=docker.m.daocloud.io/library/node:22-alpine
  NGINX_BASE_IMAGE=docker.m.daocloud.io/library/nginx:alpine
  POSTGIS_BASE_IMAGE=docker.m.daocloud.io/imresamu/postgis:17-3.5
  DOCKER_IMAGE_POSTGIS=docker.m.daocloud.io/imresamu/postgis:17-3.5
  DOCKER_IMAGE_REDIS=docker.m.daocloud.io/library/redis:7-alpine
  DOCKER_IMAGE_RABBITMQ=docker.m.daocloud.io/library/rabbitmq:3-management
  ```
- 使用 `docker compose config --environment` 查看解析后的环境变量，不会启动或改变服务。
- RabbitMQ 数据卷使用期间必须保持 `RABBITMQ_ERLANG_COOKIE` 不变；修改它会导致 RabbitMQ 节点无法启动。

## 测试

所有测试在 Docker 中运行：

```bash
docker compose exec -T backend pytest
docker compose exec -T backend pytest tests/api/routes/test_media.py
docker compose exec -T backend pytest tests/api/routes/test_media.py::test_create_media
docker compose exec -T frontend npm run test -- --run
docker compose exec -T frontend npm run build
```

后端测试使用同一 PostgreSQL 实例中的独立 `ecosignal_test` 数据库。测试会创建或复用该数据库、执行迁移并初始化测试数据，不会写入应用数据库（`ecosignal`）。测试数据库会在测试后保留，可另行清理。`./scripts/test-local.sh` 会在重建前删除当前运行栈的数据库、媒体、Redis 和 RabbitMQ 卷；仅可在允许丢弃全部运行栈数据的环境中使用。

> 警告：`./scripts/test-local.sh` 重建前会执行 `docker-compose down -v --remove-orphans`，删除当前 Compose 项目的数据库、媒体、Redis 和 RabbitMQ 卷。不要对包含需要保留数据的本地或部署运行栈执行该脚本。

## 生产环境说明

`docker compose watch` 和本地 `docker compose up` 命令仅用于开发。公开部署、迁移、备份、恢复、HTTPS 和 GitHub Actions 配置请使用[运维指南](docs/operations-guide.zh.md)。

## 文档导航

| 文档 | 面向对象 | 内容 |
| --- | --- | --- |
| [用户指南](docs/user-guide.zh.md) | 研究人员、上传人员、标注人员、审核人员 | 项目、媒体、标注、审核、导入、离线包和 Queue |
| [管理员指南](docs/admin-guide.zh.md) | 系统、项目和集合管理者 | 权限、公开访问、设置、数据管理和应用运维 |
| [运维指南](docs/operations-guide.zh.md) | 部署与数据迁移人员 | 生产配置、发布、迁移、备份和恢复 |
| [可观测性操作文档](docs/observability.zh.md) | 运维团队 | Sentry、Prometheus 与 Grafana |
| [地理数据文档](geo_db/GEO_IMPORT_zh.md) | 地理数据维护人员 | 地理参考数据的导入与导出 |

## 鸣谢和许可

本项目是 **ecoSound-web** 的重构版本。

- **原始设计**: [Kevin Darras](http://kevindarras.weebly.com/index.html)
- **原始开发**: [Noemi Perez](https://github.com/nperezg) 和 Dilong Liu。
- **许可证**: 根据 [GNU General Public License, v3](https://www.gnu.org/licenses/gpl-3.0.en.html) 许可。

相应的可更新科学出版物位于 [F1000Research](https://f1000research.com/articles/9-1224/v3)。
