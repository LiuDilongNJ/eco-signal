# ecoSignal

[中文文档](README_ZH.md)

ecoSignal is a web application for collaboratively managing, navigating, visualising, annotating, and analysing audio and photos from biodiversity monitoring surveys. It supports field work that continues across online and offline environments.

## Technology stack

- Backend: [FastAPI](https://fastapi.tiangolo.com/) with PostgreSQL and PostGIS
- Frontend: React and TypeScript
- Infrastructure: Docker Compose
- Observability: Sentry and Prometheus

## Quick start

### Requirements

- Docker Engine 23.0 or later
- Docker Compose v2.22 or later
- Docker Buildx with BuildKit enabled
- At least 50 GB of free disk space for a first installation

Check your Docker installation:

```bash
docker version
docker compose version
docker buildx version
docker buildx inspect --bootstrap
```

The Dockerfiles use BuildKit cache mounts. If an older installation requires it, enable BuildKit in the current shell:

```bash
export DOCKER_BUILDKIT=1
```

If `docker buildx version` is unavailable, or a build reports `the --mount option requires BuildKit`, install Docker with the official `docker-buildx-plugin` and `docker-compose-plugin` packages. On Ubuntu:

```bash
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### Configure and run

From the repository root, create your local environment file:

```bash
cp .env.example .env
```

Review at least `SECRET_KEY`, `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD`, and `POSTGRES_PASSWORD`. `.env.example` is the committed template; `.env` is environment-specific and must not be committed.

Start the development stack:

```bash
docker compose watch
```

Use `docker compose up --build -d` for a background startup and `docker compose down` to stop the stack. Docker Compose uses `STACK_NAME` as the project name, defaulting to `ecosignal`; keep it consistent for commands that operate on the same stack.

On first startup, the worker downloads BirdNET assets into the shared model volume. The geographical database imports reference data in the background; monitor its progress with:

```bash
docker compose logs -f geo_db
```

The backend can start before the geographical import completes. If Docker Hub is unavailable, configure mirror-backed image variables in `.env`.

### Service addresses

With the default `FRONTEND_PORT=80` configuration:

| Service | Address |
| --- | --- |
| Web application | http://localhost |
| API | http://localhost:28000 |
| API documentation | http://localhost:28000/docs |
| Traefik dashboard | http://localhost:8090 |

Set `FRONTEND_PORT` in `.env` to use another frontend host port.

### Local development notes

- The first worker startup downloads model assets once; later restarts reuse the shared model volume.
- The geographical database imports reference data in the background. It is normal for this import to outlive the first backend startup.
- If BuildKit cache-mount instructions fail, install a current Docker Engine package with the Buildx and Compose plugins instead of using a standalone Buildx binary.
- If Docker Hub is unreachable, set mirror-backed image values in `.env`, for example:

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
- Run `docker compose config --environment` to inspect resolved environment values without starting or changing services.
- Keep `RABBITMQ_ERLANG_COOKIE` stable while its data volume is in use; changing it prevents the RabbitMQ node from starting.

## Tests

Run tests in Docker:

```bash
docker compose exec -T backend pytest
docker compose exec -T backend pytest tests/api/routes/test_media.py
docker compose exec -T backend pytest tests/api/routes/test_media.py::test_create_media
docker compose exec -T frontend npm run test -- --run
docker compose exec -T frontend npm run build
```

Backend tests use a separate `ecosignal_test` database in the same PostgreSQL instance. The test setup creates or reuses that database, runs migrations, and initializes test data; it does not write to the application database (`ecosignal`). The test database remains after tests and may be removed separately. `./scripts/test-local.sh` removes the current stack's database, media, Redis, and RabbitMQ volumes before rebuilding; use it only where all stack data may be discarded.

> Warning: `./scripts/test-local.sh` runs `docker-compose down -v --remove-orphans` before rebuilding the stack. It deletes the current Compose project's database, media, Redis, and RabbitMQ volumes. Never run it against a local or deployed stack with data you need to retain.

## Production note

`docker compose watch` and the local `docker compose up` commands are for development only. For public deployment, migration, backup, recovery, HTTPS, and GitHub Actions configuration, use the [Operations Guide](docs/operations-guide.md).

## Documentation

| Guide | For | Covers |
| --- | --- | --- |
| [User Guide](docs/user-guide.md) | Researchers, uploaders, annotators, reviewers | Working with projects, media, annotations, reviews, imports, offline bundles, and Queue |
| [Administrator Guide](docs/admin-guide.md) | System, project, and collection managers | Access control, public access, settings, data administration, and application operations |
| [Operations Guide](docs/operations-guide.md) | Deployment and migration operators | Production configuration, releases, migration, backup, and recovery |
| [Observability Guide](docs/observability.md) | Operations teams | Sentry, Prometheus, and Grafana |
| [Geographical Data Guides](geo_db/GEO_IMPORT_en.md) | Geodata maintainers | Importing and exporting geographical reference data |

## Credits and License

This project is a refactor of **ecoSound-web**.

- **Original Design**: [Kevin Darras](http://kevindarras.weebly.com/index.html)
- **Original Development**: [Noemi Perez](https://github.com/nperezg) and Dilong Liu.
- **License**: Licensed under the [GNU General Public License, v3](https://www.gnu.org/licenses/gpl-3.0.en.html).

The corresponding updatable scientific publication is in [F1000Research](https://f1000research.com/articles/9-1224/v3).
