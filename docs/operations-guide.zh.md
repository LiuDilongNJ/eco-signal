# ecoSignal 运维指南

[English](operations-guide.md) · [文档首页](../README_ZH.md)

**适用对象：** 部署、维护、迁移或恢复共享 ecoSignal 环境的运维人员。  
**开始前：** 请准备 Docker 主机、安全的环境变量值，并在变更已部署系统前确认备份可用。

## 昆虫模型准备

构建前在 `.env` 中设置 `INSECTS_MODEL_MODE`：

| 值 | 行为 |
|---|---|
| `download`（默认） | 构建镜像时下载并校验模型，失败终止构建。 |
| `local` | 从 `backend/model-assets/insects/` 复制完整模型，不访问 Hugging Face；缺失或空文件终止构建。 |
| `disabled` | 跳过模型准备，并警告昆虫识别已关闭；其他功能仍可使用。 |

使用 `local` 时，提供 `model.yaml`、`file_handler.yaml`、`target_transform.yaml`、`inference_transform.yaml` 和 `_best/model.pt`，保留相对路径及配置引用的其他文件。模型文件已排除 Git 提交。然后运行 `./deploy.sh` 或 `./deploy.ps1`；直接构建镜像时须传入 `--build-arg INSECTS_MODEL_MODE=local`。

准备模式记录在镜像内，单独修改 `.env` 不会改变现有镜像。切换模式后需要重新构建并部署。模型安装在 `/app/models/insects`。本地模式下，已安装文件缺失会直接导致分析失败，不触发下载；关闭模式直接拒绝昆虫分析，不搜索缓存或下载。原因通过现有任务错误信息展示。

下载模式会在准备错误及日志中保留连接重置、超时等底层原因。重试前先检查构建环境到 Hugging Face 的网络连通性。下载失败不会自动关闭模型。也可在可联网机器构建镜像，再用 `docker save` / `docker load` 转移。本地模式仅保证昆虫模型准备不联网，依赖、基础镜像及其他模型仍可能需要网络。

## 目录

- [配置生产环境](#配置生产环境)
- [自定义域名与 HTTPS 配置](#自定义域名与-https-配置)
- [部署和验证](#部署和验证)
- [使用 GitHub Actions](#使用-github-actions)
- [迁移数据](#迁移数据)
- [媒体存储（S3）](#媒体存储s3)
- [恢复数据](#恢复数据)

## 配置生产环境

从 `.env.example` 创建 `.env`，并设置 `SECRET_KEY`、`FIRST_SUPERUSER`、`FIRST_SUPERUSER_PASSWORD`、`POSTGRES_PASSWORD`、`REDIS_PASSWORD`、`RABBITMQ_ERLANG_COOKIE` 以及所需域名、邮件、Sentry 和集成配置的真实值。

显式设置 `ENVIRONMENT=staging` 或 `ENVIRONMENT=production`。`AUTH_SESSION_IDLE_EXPIRE_MINUTES` 控制空闲过期时间，默认 30 分钟。一个部署运行栈应使用稳定的 `STACK_NAME`。部署前检查解析后的配置：

```bash
docker compose -f docker-compose.yml config --environment | grep '^ENVIRONMENT='
```

## 自定义域名与 HTTPS 配置

三种模式均使用一个 `DOMAIN`：首页 `/`、API `/api/`、媒体 `/sounds/`。DNS 的 A/AAAA 记录指向服务器地址；CNAME 指向另一个域名。无需 `api.`、`dashboard.` 子域名，默认不公开 Traefik 管理面板。

### 1. 自有证书：Nginx 直接提供 HTTPS

```ini
DOMAIN=ecosignal.example.org
ENABLE_HTTPS=true
HTTPS_MODE=static
TLS_CERT_FILE=/etc/ssl/certs/ecosignal-fullchain.pem
TLS_KEY_FILE=/etc/ssl/private/ecosignal.key
BACKEND_CORS_ORIGINS="https://ecosignal.example.org"
```

- 证书文件允许在 PEM 块外包含空白行及 `subject=` / `issuer=` 说明行。部署自动从安装副本中清理说明行，并向 stderr 输出提示，源文件保持不变，证书顺序保持不变。未知文本、其他 PEM 类型、不完整边界及无效证书仍会被拒绝。配置预检、证书热加载及到期检查使用相同解析规则。
- 提供 PEM 格式的完整证书链，顺序为站点证书、中间证书；私钥必须匹配且无需交互密码。证书必须覆盖 `DOMAIN`，处于有效期内。私钥源文件只允许部署账户和管理员读取。
- 前端 Nginx 直接监听宿主机 80/443，将 HTTP 重定向至 `https://DOMAIN`；反向代理 `/api/` 至后端，并直接读取挂载目录提供 `/sounds/`。后端不发布宿主机端口。
- 脚本通过 Docker 工具容器校验证书格式、有效期、域名及私钥匹配；临期 30 天告警，校验失败终止。无需在宿主机安装 OpenSSL。
- 内部 CA 证书可以使用；浏览器、调用方需要自行安装机构信任链。部署验证会固定匹配已校验的站点证书，不以工具容器是否信任内部 CA 作为判断依据。
- 经校验的证书复制到 `.deploy/tls`，整个目录只读挂载给 Nginx。该目录包含私钥及上一组备份，应限制访问、排除 Git 和镜像、保留于稳定部署路径。不要手工修改运行目录中的证书。

仅更新证书时，替换配置指向的源文件，然后执行：

```bash
./deploy.sh --reload-certs
# Windows PowerShell:
./deploy.ps1 -ReloadCerts
```

更新与部署共用锁。工具备份并安装新证书，执行 `nginx -t` 后 `nginx -s reload`，在 30 秒内用新 TLS 连接检查证书指纹与域名。失败恢复上一组证书并验证恢复结果，命令返回非零。更新不启用维护模式、不重启容器、不构建应用；已有请求由旧 worker 完成。常规应用发布仍可能有维护窗口。

#### 独立到期检查

静态 HTTPS 支持独立检查已安装的 `.deploy/tls/cert.pem`：

```bash
./deploy.sh --check-certs
# Windows PowerShell:
./deploy.ps1 -CheckCerts
```

命令校验 PEM 格式、站点证书域名及证书链中每张证书的有效期，输出 `DOMAIN`、链中最早到期时间（`YYYY-MM-DD HH:mm:ss UTC`）和剩余天数。支持内部 CA，无需加入系统信任库。检查不要求配置指向的源证书和私钥文件仍然存在。检查对象是已安装文件，不验证远端 TLS 握手。

| 退出码 | 结果 |
|---|---|
| `0` | 校验通过，距离到期超过 30 天 |
| `2` | 校验通过，距离到期不超过 30 天；提醒输出至 stderr |
| `1` | 已过期、尚未生效、证书损坏或缺失、模式不支持，或检查无法完成 |

命令使用短生命周期 Docker 容器，禁用网络，证书目录只读挂载。不创建或删除部署锁，不进入维护模式，不构建镜像，不安装或热加载证书，不启动或停止应用服务。存在部署锁时返回 `1`，应在部署完成后重试。不要与其他部署选项组合。检查仅支持静态 HTTPS，且需要已有 TLS 工具镜像。更新工具代码后，或镜像缺失时，在项目目录中执行一次准备命令：

```bash
docker build -t ecosignal-tls-tools:local scripts/tls
```

#### 使用 cron 或 systemd 每日检查

选择一种定时方式。将 `/opt/ecosignal`、部署账户 `ecosignal` 和 Docker 命令目录替换为服务器实际值。执行账户需要读取项目配置和已安装证书，并有权限使用 Docker。示例假设 Docker 位于 `/usr/bin/docker`，可用 `command -v docker` 确认。检查命令不自动安装定时任务，也不发送邮件或 webhook 通知；由现有监控接收非零结果，区分提醒 `2` 和故障 `1`。

使用 cron 时，先创建 `/var/log/ecosignal`，并确保部署账户可写其中的 `certificate-check.log`，再将以下配置加入该账户的 crontab。按宿主机时区每天 08:15 执行，记录输出和退出码。cron 本身不会将退出码转为通知，应由监控采集日志。

```cron
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
15 8 * * * cd /opt/ecosignal && (/bin/bash ./deploy.sh --check-certs; status=$?; echo "certificate-check exit=$status"; exit "$status") >> /var/log/ecosignal/certificate-check.log 2>&1
```

也可以保存 `/etc/systemd/system/ecosignal-certificate-check.service`：

```ini
[Unit]
Description=ecoSignal certificate expiry check
After=docker.service

[Service]
Type=oneshot
User=ecosignal
WorkingDirectory=/opt/ecosignal
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/bin/bash /opt/ecosignal/deploy.sh --check-certs
```

保存 `/etc/systemd/system/ecosignal-certificate-check.timer`：

```ini
[Unit]
Description=Daily ecoSignal certificate expiry check

[Timer]
OnCalendar=*-*-* 08:15:00
RandomizedDelaySec=10m
Persistent=true

[Install]
WantedBy=timers.target
```

启用并检查：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ecosignal-certificate-check.timer
systemctl list-timers ecosignal-certificate-check.timer
sudo systemctl start ecosignal-certificate-check.service
journalctl -u ecosignal-certificate-check.service --since today
systemctl status ecosignal-certificate-check.service
```

退出码 `1` 和 `2` 均使 service 标记为失败。将现有 systemd 监控接入此状态，并根据进程退出码区分严重程度。收到提醒后，获取新证书、更新配置指向的源文件，执行 `./deploy.sh --reload-certs`（或 `./deploy.ps1 -ReloadCerts`），再运行独立检查。只替换源文件不会更新已安装证书。

### 2. 自动证书：Traefik + Let's Encrypt

```ini
DOMAIN=ecosignal.example.org
ENABLE_HTTPS=true
HTTPS_MODE=letsencrypt
EMAIL=admin@example.org
BACKEND_CORS_ORIGINS="https://ecosignal.example.org"
```

Traefik 监听宿主机 80/443，终结 HTTPS 后转发至前端 Nginx；前端和 API 均使用 `https://ecosignal.example.org`。TLS-ALPN-01 验证要求公网 443 能直接到达 Traefik，80 用于 HTTP 重定向。确保服务器能出站访问 ACME 服务；上游代理不得拦截 TLS 验证。Traefik 持久化 ACME 账户和证书并自动续期，不使用 `--reload-certs`。

首次签发最多等待 180 秒；失败输出诊断日志且不会报告部署成功。测试使用 `ACME_CA_SERVER=https://acme-staging-v02.api.letsencrypt.org/directory` 和独立 Compose 项目/证书卷，不能复用生产 ACME 数据。测试 CA 不受普通客户端信任；正式部署恢复默认生产目录，不跳过生产信任验证。

### 3. HTTP：内网或外部 HTTPS 网关

```ini
DOMAIN=ecosignal.example.org
ENABLE_HTTPS=false
FRONTEND_PORT=80
BACKEND_CORS_ORIGINS="http://ecosignal.example.org"
```

Nginx 通过 `http://DOMAIN:FRONTEND_PORT` 提供服务。外部网关负责 TLS 时，按实际浏览器访问来源设置 CORS，并由可信网关设置 `X-Forwarded-Proto`。

### 模式切换与验证

- 在维护窗口切换模式。脚本仅在确认 Traefik 的部署目录和所属运行栈后停止入口容器并交接端口，不删除 ACME 卷；无法确认归属时拒绝操作。不要在多个项目之间共享此入口实例。
- `--dry-run` / `-DryRun` 解析应用、入口和维护配置，静态模式同时验证源证书。可能构建工具镜像、运行短生命周期校验容器，但不启动应用、不替换已安装证书。
- 正式部署在退出维护前验证入口 TLS，退出后验证首页和 API 健康地址；失败保留或恢复维护状态。验证从入口容器网络发起并携带正确 SNI；公网 DNS、防火墙和客户端 CA 信任仍须从外部客户端验证。

### 部署回归测试

执行 `./scripts/test-tls.sh` 验证证书校验、脚本失败处理和 Nginx 热重载；`./scripts/test-tls.sh --integration` 还会构建生产前端，并测试隔离的 HTTP/静态证书/ACME 运行栈，使用本地 ACME 测试 CA Pebble 验证签发与续期。测试运行栈名称唯一、不发布宿主机端口，使用独立可清理的证书卷。`./scripts/test-tls.sh --powershell` 在 Linux 容器内通过 Bash 与 PowerShell 7 执行同一组命令测试；Windows Docker Desktop 的原生路径和 ACL 行为仍需在目标主机验证。

自托管 Actions 检出代码时保留 `.deploy`，避免更新代码时删除正在挂载的证书目录、证书备份和部署锁。部署目录路径必须保持稳定；源私钥放在检出目录之外。

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

`DOMAIN`、`ENABLE_HTTPS`、`HTTPS_MODE`、`TLS_CERT_FILE`、`TLS_KEY_FILE`、`FRONTEND_PORT`、`STACK_NAME`、`BACKEND_CORS_ORIGINS`、`AUTH_SESSION_IDLE_EXPIRE_MINUTES` 等可选值应在 staging 与 production 环境中分别配置。不要把 `ENVIRONMENT` 定义为 GitHub 变量。安装带有对应环境标签的自托管 Runner。

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
- `--copy-files`：将来源静态文件复制到 `app-media-data` 卷，将 WAV 音频无损压缩转换为 FLAC 格式，并提取内嵌音频元数据入库
- `--reset-target`：备份目标数据库和媒体、清理业务数据后迁移
- `--repair-permissions`：在已迁移的目标环境中重新将历史权限修复映射至 `user_scope_role` 访问角色架构
- `--legacy-app-url <url>`：提供用于识别联邦节点的来源公开地址

脚本会在容器内迁移开始前从宿主机检查来源 MySQL 连通性。新部署目标首次迁移时，预置的 Demo Project、集合和站点要求使用 `--reset-target`。默认直接挂载方式会在数据库处理前验证 `/app/sounds/sounds`、`/app/sounds/images` 和 `/app/sounds/projects`，并在数据库迁移后补齐音频元数据。复制方式会自动将 WAV 转为 FLAC、提取元数据、校验已复制的目录、设置 `MEDIA_STORAGE_MODE=managed` 并重建正在运行的媒体服务；之后已有媒体访问和新上传均使用 `app-media-data`，脚本不会自动删除来源目录。

无法自动解析来源公开地址时，传入 `--legacy-app-url <url>` 或设置 `LEGACY_APP_URL`。若没有有效的 `http://` 或 `https://` 候选值，地址解析会在写入前停止。

来源地址按第一个非空值优先：命令行 `--legacy-app-url <url>`、shell 或 `.env` 中的 `LEGACY_APP_URL`、来源 `src/config/config.ini` 中的 `APP_URL`、来源数据库保存的 `app_url`，最后是在已知联邦节点中根据服务器名称和坐标得到的唯一匹配。`LEGACY_HOST_URL` 同样遵循环境变量优先于配置的规则，并默认使用来源 `HOST_URL`。解析失败时，preflight 会报告服务器名称、坐标和候选地址，不会留下部分迁移数据。

## 媒体存储（S3）

默认情况下 ecoSignal 将媒体存储在各服务自己的磁盘上。在无法在不同服务之间共享持久卷的平台上，可以启用**混合 S3 存储**：以 S3 兼容存储桶（AWS S3、MinIO、Cloudflare R2 等）作为唯一数据源，每个服务（backend、worker、worker-analysis）各自在 `MEDIA_ROOT`（`/app/sounds`）下维护一个独立的持久本地缓存。

- **读取**走本地缓存；缺失或过期的条目会从 S3 拉取。文件在 `MEDIA_CACHE_TTL` 秒内（默认 `300`）视为新鲜。
- **写入**先写本地（转码与原子重命名保持不变），随后上传到 S3。
- **删除**同时移除本地副本和 S3 对象。
- 前端不再挂载媒体卷；nginx 将 `/sounds/` 反向代理到 backend，由 backend 从缓存中提供。

在 `.env` 中设置以下变量即可启用（作用于 backend、worker 和 worker-analysis）：

```dotenv
MEDIA_S3_MODE=s3
S3_ENDPOINT=https://s3.example.com   # 使用 AWS 时留空
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
S3_BUCKET=ecosignal-media
S3_REGION=us-east-1
MEDIA_CACHE_TTL=300
```

### 本地开发（内置 MinIO）

`docker-compose.yml` 自带一个本地 MinIO 服务（`minio`），以及一个一次性任务
`minio-init`，用于在首次启动时创建媒体存储桶。compose 中的 S3 默认值已经指向
它（`http://minio:9000`，存储桶 `ecosignal-media`，凭据
`minioadmin`/`minioadmin`），因此要在本地测试混合存储，只需在 `.env` 中设置
`MEDIA_S3_MODE=s3` 并启动整个栈即可。S3 API 可通过 `127.0.0.1:9000` 访问，
Web 控制台在 `127.0.0.1:9001`（均仅绑定到本机）。可在 `.env` 中通过
`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` 修改凭据；应用的
`S3_ACCESS_KEY` / `S3_SECRET_KEY` 必须与之一致。

`MEDIA_S3_MODE=local`（默认值）保持原有的本地磁盘行为，所有 S3 操作变为空操作。注意它与迁移工具使用的 `MEDIA_STORAGE_MODE`（`managed`/`direct-mount`）标志不同。

每个服务使用各自的缓存卷（`app-media-cache-backend`、`app-media-cache-worker`、`app-media-cache-worker-analysis`），因此没有卷在服务之间共享。缓存是可丢弃的：删除后下次访问会从 S3 完整重新拉取。

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

可选 GitHub 变量包括 `DOMAIN`、`ENABLE_HTTPS`、`HTTPS_MODE`、`TLS_CERT_FILE`、`TLS_KEY_FILE`、`FRONTEND_PORT`、`STACK_NAME`、`BACKEND_CORS_ORIGINS`、`AUTH_SESSION_IDLE_EXPIRE_MINUTES`、`PROJECT_NAME`、`POSTGRES_USER`、`POSTGRES_DB`、`DOCKER_IMAGE_BACKEND`、`DOCKER_IMAGE_FRONTEND`、`LEGACY_PROJECT_DIR`、`LEGACY_APP_URL`、`LEGACY_HOST_URL`、`GEO_DB_READY_URL` 和 `GEO_DB_XR_SEED_URL`。staging 与 production 应分别设置域名、运行栈和 CORS 值。工作流直接设置 `ENVIRONMENT`，并在追加环境配置前复制 `.env.example`。

主要默认值为 `FRONTEND_PORT=80`、`PROJECT_NAME=ecoSignal`、`POSTGRES_USER=postgres`、`POSTGRES_DB=ecosignal`、staging 和 production 中默认 30 分钟的 `AUTH_SESSION_IDLE_EXPIRE_MINUTES`，以及地理数据 URL 的内置默认值。虽然本地开发有默认值，staging 和 production 仍必须替换 `REDIS_PASSWORD`。

| 变量 | 默认值或含义 |
| --- | --- |
| `DOMAIN` | 无默认值；部署域名 |
| `FRONTEND_PORT` | HTTP 默认为 `80`；HTTPS 公开地址端口统一覆盖为 `443` |
| `STACK_NAME` | Compose 项目名称 |
| `BACKEND_CORS_ORIGINS` | 无默认值；允许的后端来源 |
| `AUTH_SESSION_IDLE_EXPIRE_MINUTES` | staging/production 为 `30`；`0` 禁用过期 |
| `PROJECT_NAME` | `ecoSignal` |
| `POSTGRES_USER` / `POSTGRES_DB` | `postgres` / `ecosignal` |
| `DOCKER_IMAGE_BACKEND` / `DOCKER_IMAGE_FRONTEND` | `backend` / `frontend` |
| `MEDIA_STORAGE_MODE` | `managed`；仅在持续挂载来源媒体时使用 `direct-mount` |
| `MEDIA_S3_MODE` | `local`；设为 `s3` 启用混合 S3 媒体存储（见[媒体存储（S3）](#媒体存储s3)） |
| `S3_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_BUCKET` / `S3_REGION` | `MEDIA_S3_MODE=s3` 时使用的 S3 兼容存储桶配置 |
| `ENABLE_HTTPS` | 示例中为 `false`；Actions 默认 `true` |
| `ACME_CA_SERVER` | 默认使用 Let's Encrypt 生产目录；测试 CA 数据需隔离 |
| `HTTPS_MODE` | `letsencrypt`；自备静态证书时设为 `static` |
| `TLS_CERT_FILE` / `TLS_KEY_FILE` | 宿主机静态 TLS 证书与私钥路径 |
| `LEGACY_PROJECT_DIR` | `./ecoSound-web`；来源媒体路径 |
| `LEGACY_APP_URL` / `LEGACY_HOST_URL` | 来源公开地址 / 联邦中心 |
| `GEO_DB_READY_URL` / `GEO_DB_XR_SEED_URL` | 内置地理数据默认地址 |

生产默认使用三个 Web worker，并分离交互和分析消费者。交互消费者还负责启动同步和定时维护。只有观察资源使用、队列深度和 PostgreSQL 连接后，才调整 `WEB_CONCURRENCY` 与 `DB_*` 连接池参数。

指标、错误和仪表盘请参阅[可观测性操作文档](observability.zh.md)。生产环境应通过内部网络或网关保护指标。

## 相关文档

- [管理员指南](admin-guide.zh.md)：应用层运维
- [用户指南](user-guide.zh.md)：日常工作流
- [文档首页](../README_ZH.md)
