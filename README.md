# ecoSignal

[中文文档](README_ZH.md)

**ecoSignal** is a modern refactor of [ecoSound-web](https://github.com/ecomontec/ecoSound-web/), built with high-performance modern web technologies. It adds support for photos and offline-online synchronisation.

## Description

Web application for collaboratively managing, navigating, visualising, annotating, and analysing audios and photos from biodiversity monitoring surveys.

## Technology Stack

This project uses a modern, optimized full-stack architecture:

- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) (Python)
-   **Main Database**: [PostgreSQL](https://www.postgresql.org/) with PostGIS.
-   **Geo Database**: Dedicated PostGIS instance for global spatial data (IHO/GADM).
- **Infrastructure**: [Docker Compose](https://www.docker.com/)
- **Observability**: Sentry (error tracking) + Prometheus (metrics)

See [docs/observability.md](docs/observability.md) for setup and usage details.

## Quick Start

This project is completely automated. Geographical data and database migrations are handled during the first startup.

### Prerequisites

-   cloned repository
-   For a first-time install, ensure 50 GB of free disk space to avoid build failures, plus extra free space if you also keep a legacy `ecoSound-web` directory on the same host for later migration.
-   [Docker Engine](https://docs.docker.com/engine/install/) 23.0 or newer is recommended.
-   [Docker Compose](https://docs.docker.com/compose/install/) v2.22 or newer.
-   The [Docker Buildx plugin](https://docs.docker.com/build/buildx/) and BuildKit must be available. Current Docker Engine and Docker Desktop installations include them and use BuildKit by default. The project Dockerfiles use BuildKit-only `RUN --mount` instructions for dependency and build caches.

    Check the installed components before starting:

    ```bash
    docker version
    docker compose version
    docker buildx version
    docker buildx inspect --bootstrap
    ```

    If `docker buildx version` is unavailable, or the build fails with `the --mount option requires BuildKit`, install Docker from the official Docker repository, including `docker-buildx-plugin` and `docker-compose-plugin`. On Ubuntu, the package installation is:

    ```bash
    sudo apt-get update
    sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    ```

    On older Docker installations, enable BuildKit for the current shell before starting the project. Docker Compose v2 uses `DOCKER_BUILDKIT`; `COMPOSE_DOCKER_CLI_BUILD` is only relevant to legacy Compose v1:

    ```bash
    export DOCKER_BUILDKIT=1
    ```

    Do not download a standalone Buildx binary manually unless it is required by your system administrator. Prefer the versioned Docker packages so the Docker Engine, Buildx, and Compose versions remain compatible.

### Running the Project (Local Development Mode)

1.  **Initialize the environment file**:

    From the cloned repository root:
    ```bash
    cp .env.example .env
    ```

    Then open `.env` and fill in the values for your environment before starting the stack.
    At minimum, review `SECRET_KEY`, `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD`, and `POSTGRES_PASSWORD`.
    If you are deploying or using optional integrations, also fill in domain, email, Sentry, RabbitMQ, and legacy project path settings as needed.

    `RABBITMQ_ERLANG_COOKIE` has a local-development default. For each deployment, replace it with a unique, stable random value, for example:

    ```bash
    openssl rand -hex 32
    ```

    Keep the deployed value unchanged while its RabbitMQ data volume is in use; changing it prevents the RabbitMQ node from starting.

    `.env.example` is the committed template for project setup. `.env` is for local or deployment-specific secrets and must not be committed.

3.  **Start the stack**:

    ```bash
    docker compose watch
    ```

    *Alternatively, use `docker compose up --build -d` for a standard background startup.*

    On first startup, the `worker` container populates the shared `app-ai-models` volume with the required BirdNET assets. The `backend` skips this step so its health check is not blocked by model downloads. Later rebuilds and restarts reuse that volume and skip the download as long as the required model files are already present.

    If Docker Hub is unreachable in your network, set mirror-backed image values in `.env` before starting. For example:

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

4.  **Geographical Data Initialization**:
    On the first boot, the `geo_db` container automatically downloads and imports spatial data (IHO/GADM) in the background. You can monitor progress with:
    ```bash
    docker compose logs -f geo_db
    ```
    *Note: The backend will start immediately and will connect to these tables once the background import completes.*

5.  **Access the services**:

    **Default (`FRONTEND_PORT=80`)**:

    | Service            | URL                        |
    | ------------------ | -------------------------- |
    | Frontend           | http://localhost           |
    | Backend API        | http://localhost:28000      |
    | API Docs (Swagger) | http://localhost:28000/docs |
    | Traefik UI         | http://localhost:8090      |

    Change `FRONTEND_PORT` in the root `.env` if you want the Dockerized frontend on another host port, for example `http://localhost:3001`.

6.  **Stop the stack**:
    ```bash
    docker compose down
    ```

## Media Upload Processing

For standard audio and photo uploads, select one or more files and wait for their chunks to finish uploading. The upload drawer then allows you to save the batch.

- Chunk upload creates staging records only; it does not create a Queue item for each file.
- Saving creates one `upload` Queue item for the accepted batch. Its `total` is the number of submitted files, and `completed` counts only media created successfully.
- File merging, content validation, duplicate detection, media creation, and preview generation run sequentially in that background batch.
- A batch with duplicates finishes with a warning. A batch with any failed file finishes with an error. Review the Queue page for the outcome of every submitted batch.

## Offline Field Work

ecoSignal supports offline field work through a signed collection bundle containing audio, photos, annotations, reviews, and labels.

### Export a collection bundle

Open `Data > Collections` in the web interface, select one collection, and click `Export Bundle`. ecoSignal generates a complete bundle containing all media in the background. The export drawer provides the download when ready, and the file remains available for 24 hours.

### Import a collection bundle

Select the target project, open `Data > Collections`, click `Import Bundle`, and choose one zip file. The web interface uploads it in chunks and displays the background status, created/skipped counts, conflicts, and warnings. Closing the drawer does not cancel the task; progress remains available on the Queue page.

Rules:

- The target `project_id` must already exist.
- The caller must have `project:write` on that project.
- Offline import batches accept `.zip` files only.
- The server verifies the bundle signature and SHA-256 checksums before importing.
- Media UUID is the identity key. A matching UUID and binary is reused and linked to the target collection; a matching UUID with different content aborts the import.
- Equal file hashes with different UUIDs remain separate media records.
- Existing files are never overwritten. Filename collisions receive a deterministic UUID suffix.
- Audio and photo previews are regenerated after import; preview failures are reported as warnings without discarding imported media.
- The underlying export endpoint is `POST /api/v1/collection-bundle-exports`; import sessions use `POST /api/v1/data-imports`.

## Data Migration and Rollback Scripts

For one-time migration from legacy `ecoSound-web` to `ecoSignal`, use the root-level scripts below.

### Prerequisites

- `ecoSignal` `backend` and `db` containers are running (`docker compose watch` or `docker compose up -d`).
- Legacy `ecoSound-web` directory exists (default: `./ecoSound-web`, configurable via `LEGACY_PROJECT_DIR` in `.env`).
- If database migration is enabled, legacy MySQL must be reachable.
- On Linux, the backend container reaches the host MySQL through `host.docker.internal`, provided by the Compose `host-gateway` mapping in this repo.

### Migrate legacy data into ecoSignal

```bash
chmod +x ./migrate-data.sh
sudo ./migrate-data.sh <old-project-dir> [options]
```

Examples:

```bash
# Recommended after a fresh deploy: back up, clear demo/seed data, then migrate
./migrate-data.sh --reset-target

# Explicit legacy project path (still use --reset-target after a fresh deploy)
./migrate-data.sh /path/to/ecoSound-web --reset-target

# Preview only (no writes)
./migrate-data.sh --dry-run

# Empty target only (no Demo Project / collection / site rows)
./migrate-data.sh

# Provide the public URL of the legacy instance explicitly
./migrate-data.sh --reset-target --legacy-app-url https://ecosound-web.example.com/ecosound_web
```

Common options:

- `--dry-run`: Preview migration without writing data
- `--skip-db`: Skip database migration
- `--skip-files`: Skip static file migration
- `--copy-files`: Copy legacy static files into `app-media-data` volume (emergency mode)
- `--reset-target`: Required after a fresh deploy. Backup current ecoSignal DB/media, clear business data (including Demo Project / collection / site), then migrate
- `--legacy-app-url <url>`: Public URL of the legacy instance, used to identify its own node in the federation network

### Legacy app URL resolution

The migration must know the public URL of the instance it is migrating, because that URL identifies the local node in the federation network. Legacy installs ship an empty `APP_URL` and resolve the hostname per request, so it often cannot be detected automatically.

Resolution order, first non-empty value wins:

1. `--legacy-app-url <url>` on the command line
2. `LEGACY_APP_URL` from the shell environment or `.env`
3. `APP_URL` in the legacy `src/config/config.ini`
4. Inference from the legacy database: the stored `app_url` setting, then a unique match on server name and coordinates among the known federation nodes

`LEGACY_HOST_URL` follows the same environment-over-config precedence and defaults to the legacy `HOST_URL`. Values that are not `http://` or `https://` URLs are rejected before the migration starts.

If none of these resolve, the migration aborts during preflight, before any data is written, and reports the server name, coordinates, and candidate URLs it found. Set `LEGACY_APP_URL` in `.env` and rerun with the same options; an aborted preflight leaves no partially migrated data behind.

Migration notes:

- First startup seeds Demo Project, Demo collection, and Demo site. A first migration after a fresh deploy will fail unless you pass `--reset-target`.
- The shell script checks legacy MySQL connectivity from the host before starting the in-container migration.
- The default media strategy is `direct-mount`: the script recreates `backend` and `worker` with the current `LEGACY_PROJECT_DIR`, then verifies `/app/sounds/sounds`, `/app/sounds/images`, and `/app/sounds/projects` before any database migration runs.
- A plain `docker compose restart` is not enough to refresh legacy bind mounts after changing `LEGACY_PROJECT_DIR`; the migration script uses container recreate semantics instead.
- `--copy-files` switches to copy mode: legacy media files are copied into `app-media-data`, so post-migration access no longer depends on the legacy project staying mounted.
- The actual database migration runs inside the `backend` container and connects to the legacy MySQL using `host.docker.internal` by default.
- If your legacy MySQL is not running on the same host as Docker, override `MYSQL_HOST` with the real reachable address before running the script.

### Roll back from backups

```bash
./rollback.sh <backup_name> [options]
```

Examples:

```bash
# Restore from most recent backup folder in .upgrade-backup/
./rollback.sh latest

# Restore a specific backup
./rollback.sh backup_20260411_133000

# Restore a target backup and skip prompt
./rollback.sh target_backup_20260420_210000 --force
```

Common options:

- `--force`: Skip confirmation prompt
- `--keep-new`: Preserve current ecoSignal volumes when restoring a legacy backup

Notes:

- Backups are stored under `./.upgrade-backup/`.
- `target_backup_*` is an ecoSignal target backup (DB + media) generated before reset migration.
- `backup_*` is a legacy backup set used for rolling back to ecoSound-web.

## Running Tests

Run tests against an already-running local Docker stack:

```bash
# Full backend suite
docker compose exec -T backend pytest

# One backend test module or test case
docker compose exec -T backend pytest tests/api/routes/test_media.py
docker compose exec -T backend pytest tests/api/routes/test_media.py::test_create_media

# Frontend tests and production build
docker compose exec -T frontend npm run test -- --run
docker compose exec -T frontend npm run build
```

Backend pytest uses a separate `ecosignal_test` database in the same PostgreSQL instance. It creates or reuses that database, runs migrations there, and initializes test data; it does not write to the application database (`ecosignal`). The `ecosignal_test` database remains after tests and may be removed separately when no longer needed.

> Warning: `./scripts/test-local.sh` runs `docker-compose down -v --remove-orphans` before rebuilding the stack. It deletes the current Compose project's database, media, Redis, and RabbitMQ volumes. Use it only in an isolated environment whose data can be discarded; never run it against a local or deployed stack with data you need to retain.

## Monitoring

- **Sentry**: captures unhandled API exceptions and worker-side failures (when enabled).
- **Prometheus**: exports service metrics at `GET /metrics`.
- Recommended production setup: keep `/metrics` behind internal network or gateway protection.
- Full guide: [docs/observability.md](docs/observability.md)

## Deployment

This project uses Docker Compose for deployment. HTTP is the default; setting `ENABLE_HTTPS=true` enables the Traefik-managed HTTPS deployment.

### Prerequisites

1. A remote server with Docker installed
2. A DNS record or hosts entry pointing your app domain to the server

### Deployment Steps

1. **Create your environment file from the template**:

   ```bash
   cp .env.example .env
   ```

   Then edit `.env` and provide the real values for your deployment.
   Be sure to review `SECRET_KEY`, `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, and any domain, email, Sentry, or legacy path settings required by your environment.
   HTTP mode uses `DOMAIN` and `FRONTEND_PORT` for the frontend, API, and media on one origin. Set `ENABLE_HTTPS=true` only for a public deployment: it uses `dashboard.DOMAIN` for the frontend and `api.DOMAIN` for the API, requires `EMAIL`, and requires public inbound ports 80 and 443.

   `./deploy.sh` reads `ENVIRONMENT` from the root `.env` file. Allowed values are `local`, `staging`, and `production`; both `.env.example` and the backend default to `local`. Set it explicitly to `staging` on a staging server and `production` on a production server. The `local` environment always disables login inactivity expiry. In `staging` and `production`, `AUTH_SESSION_IDLE_EXPIRE_MINUTES` controls the timeout and defaults to 30 minutes.

   `ENVIRONMENT=production` configures the backend only; it does not switch a Vite development server into production mode and cannot fix frontend Vite error overlays. The command below only checks the resolved environment value; it does not start or change any service.

   Before deploying, verify the value resolved by Compose:

   ```bash
   docker compose -f docker-compose.yml config --environment | grep '^ENVIRONMENT='
   ```

   `.env.example` is safe to commit as a template. `.env` is environment-specific and must stay uncommitted.

2. **Deploy the frontend in production mode**. This is the fix for Vite's development error overlay appearing in already-open browser tabs. The script excludes `docker-compose.override.yml`, builds the frontend production bundle, and serves it through nginx. It serializes releases, waits for dependencies, applies setup once, and waits for service health:
   ```bash
   chmod +x ./deploy.sh ./rollback.sh
   ./deploy.sh --dry-run
   sudo ./deploy.sh
   ```

   Do not use `docker compose up`, `docker compose up -d`, or `docker compose watch` as a public/production deployment: those commands automatically load `docker-compose.override.yml`, which starts the frontend through Vite's development server on port 5173. On Windows, run `.\deploy.ps1` instead (or `deploy.bat` in Command Prompt).

   After deployment, verify the environment and effective inactivity timeout inside the backend container:

   ```bash
   STACK_NAME="$(docker compose -f docker-compose.yml config --environment | awk -F= '$1 == "STACK_NAME" { print tolower($2); exit }')"
   docker compose --project-name "${STACK_NAME:-ecosignal}" --profile production -f docker-compose.yml exec backend python -c \
   'from app.core.config import settings; print(settings.ENVIRONMENT, settings.auth_session_idle_timeout_seconds)'
   ```

   With `ENVIRONMENT=production` and the default timeout, the expected output is `production 1800`.
   

   On macOS and Linux, use `./deploy.sh`; neither platform requires `flock`.

   Use `--dry-run` to validate the resolved production configuration, and `--force-unlock` only after verifying `.deploy/deploy.lock` is stale. Set `TAG` only when you need a custom image tag; otherwise Compose uses `latest`. The scripts intentionally use only production Compose files; `docker-compose.override.yml` remains the local development overlay used by `docker compose up` and `docker compose watch`.

   Production defaults use three web workers and separate interactive and analysis consumers. The interactive consumer also runs startup synchronization and scheduled maintenance. Tune `WEB_CONCURRENCY` and the `DB_*` pool values only after observing CPU, memory, queue depth, and PostgreSQL connection usage.

### CI/CD with GitHub Actions

The project uses **GitHub Actions** for automated deployment.

| Environment    | Trigger                 | Workflow File                             |
| -------------- | ----------------------- | ----------------------------------------- |
| **Staging**    | Push to `main` branch   | `.github/workflows/deploy-staging.yml`    |
| **Production** | Publish a new Release   | `.github/workflows/deploy-production.yml` |

The workflows set `ENVIRONMENT` directly: the staging workflow uses `staging`, and the production workflow uses `production`. Do not add `ENVIRONMENT` as a GitHub variable.

#### Required GitHub Secrets

| Secret                                         | Description            |
| ---------------------------------------------- | ---------------------- |
| `SECRET_KEY`                                   | Application secret key |
| `FIRST_SUPERUSER`                              | Admin email            |
| `FIRST_SUPERUSER_PASSWORD`                     | Admin password         |
| `POSTGRES_PASSWORD`                            | Database password      |
| `REDIS_PASSWORD`                               | Redis password (default `ecosignal` for local; must override via secret in staging/production) |
| `RABBITMQ_ERLANG_COOKIE`                       | RabbitMQ node cookie (replace the local default with a unique, stable secret in each deployment) |
| `SENTRY_DSN`                                   | Sentry DSN (optional)  |

#### Optional GitHub Variables

| Variable                                      | Default         | Description                    |
| --------------------------------------------- | --------------- | ------------------------------ |
| `DOMAIN`                                      | none            | Deployment domain name         |
| `FRONTEND_PORT`                               | `80`            | Frontend host port             |
| `STACK_NAME`                                  | none            | Docker Compose project name    |
| `BACKEND_CORS_ORIGINS`                        | none            | Backend CORS origins           |
| `AUTH_SESSION_IDLE_EXPIRE_MINUTES`            | `30`            | Login inactivity timeout for staging/production; `0` disables it |
| `PROJECT_NAME`                                | `ecoSignal`     | Application name               |
| `POSTGRES_USER`                               | `postgres`      | PostgreSQL username            |
| `POSTGRES_DB`                                 | `ecosignal`     | PostgreSQL database name       |
| `DOCKER_IMAGE_BACKEND`                        | `backend`       | Backend image name             |
| `DOCKER_IMAGE_FRONTEND`                       | `frontend`      | Frontend image name            |
| `LEGACY_PROJECT_DIR`                          | `./ecoSound-web`| Legacy media mount source path |
| `LEGACY_APP_URL`                              | none            | Public URL of the legacy instance, used for federation node identity during migration |
| `LEGACY_HOST_URL`                             | legacy `HOST_URL` | Federation hub the legacy instance registers with |
| `GEO_DB_READY_URL`                            | bundled default | Geo DB ready archive URL       |
| `GEO_DB_XR_SEED_URL`                          | bundled default | Geo DB XR seed archive URL     |
Define `DOMAIN`, `STACK_NAME`, and `BACKEND_CORS_ORIGINS` separately inside the GitHub `staging` and `production` environments so the variable names stay aligned with `.env` while the values differ by environment.

#### Install GitHub Actions Runner

Follow the [GitHub Actions self-hosted runner guide](https://docs.github.com/en/actions/hosting-your-own-runners) to set up a runner on your server with the appropriate environment label (`staging` or `production`).

The deployment workflows copy `.env.example` to `.env` on the runner, then append environment-specific overrides from GitHub Actions secrets and variables.

## Credits and License

This project is a refactor of **ecoSound-web**.

- **Original Design**: [Kevin Darras](http://kevindarras.weebly.com/index.html)
- **Original Development**: [Noemi Perez](https://github.com/nperezg) and Dilong Liu.
- **License**: Licensed under the [GNU General Public License, v3](https://www.gnu.org/licenses/gpl-3.0.en.html).

The corresponding updatable scientific publication is in [F1000Research](https://f1000research.com/articles/9-1224/v3).
