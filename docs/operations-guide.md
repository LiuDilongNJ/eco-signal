# ecoSignal Operations Guide

[中文](operations-guide.zh.md) · [Documentation home](../README.md)

**For:** operators who deploy, maintain, migrate, or recover a shared ecoSignal environment.  
**Before you begin:** prepare a Docker host, secure environment values, and verified backups before changing a deployed system.

## Contents

- [Configure production](#configure-production)
- [Deploy and verify](#deploy-and-verify)
- [Use GitHub Actions](#use-github-actions)
- [Migrate data](#migrate-data)
- [Recover data](#recover-data)

## Configure production

Create `.env` from `.env.example` and set real values for `SECRET_KEY`, `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `RABBITMQ_ERLANG_COOKIE`, and required domain, email, Sentry, and integration settings.

Set `ENVIRONMENT=staging` or `ENVIRONMENT=production` explicitly. `AUTH_SESSION_IDLE_EXPIRE_MINUTES` controls inactivity expiry and defaults to 30 minutes. Use a stable `STACK_NAME` for one deployed stack. Inspect resolved configuration before deployment:

```bash
docker compose -f docker-compose.yml config --environment | grep '^ENVIRONMENT='
```

HTTP is the default. A public HTTPS deployment needs `ENABLE_HTTPS=true`, `dashboard.DOMAIN`, `api.DOMAIN`, `EMAIL`, and public inbound ports 80 and 443. HTTP mode uses `DOMAIN` and `FRONTEND_PORT` on one origin.

## Deploy and verify

Use the production script, which excludes the local development override, builds the production frontend, serializes releases, waits for dependencies, and checks health:

```bash
chmod +x ./deploy.sh ./rollback.sh
./deploy.sh --dry-run
sudo ./deploy.sh
```

Do not use `docker compose up`, `docker compose up -d`, or `docker compose watch` for a public deployment: they load the local development override. On Windows, use `deploy.ps1` or `deploy.bat`.

After deployment, verify the active environment and idle timeout:

```bash
STACK_NAME="$(docker compose -f docker-compose.yml config --environment | awk -F= '$1 == "STACK_NAME" { print tolower($2); exit }')"
docker compose --project-name "${STACK_NAME:-ecosignal}" --profile production -f docker-compose.yml exec backend python -c \
  'from app.core.config import settings; print(settings.ENVIRONMENT, settings.auth_session_idle_timeout_seconds)'
```

The default production result is `production 1800`. Use `--force-unlock` only after confirming `.deploy/deploy.lock` is stale. Tune worker and database settings only after observing CPU, memory, queue depth, and connection use.

## Use GitHub Actions

Staging runs on pushes to `main`; production runs when a release is published. Configure `SECRET_KEY`, `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, and `RABBITMQ_ERLANG_COOKIE` as environment secrets, plus `SENTRY_DSN` when enabled.

Set optional values such as `DOMAIN`, `FRONTEND_PORT`, `STACK_NAME`, `BACKEND_CORS_ORIGINS`, and `AUTH_SESSION_IDLE_EXPIRE_MINUTES` separately in the staging and production environments. Do not define `ENVIRONMENT` as a GitHub variable. Install a self-hosted runner with the appropriate environment label.

## Migrate data

Before transfer, run the target `backend` and `db` containers, make the source project directory available, and confirm source MySQL connectivity when database transfer is enabled. On Linux, the backend can reach same-host MySQL through `host.docker.internal`; set `MYSQL_HOST` for another host.

Always preview before writing:

```bash
chmod +x ./migrate-data.sh
./migrate-data.sh --dry-run
./migrate-data.sh --reset-target
```

The complete command form is:

```bash
sudo ./migrate-data.sh <source-project-dir> [options]
```

Examples:

```bash
# Reset a newly deployed target after creating its backup
./migrate-data.sh --reset-target

# Specify the source project directory
./migrate-data.sh /path/to/ecoSound-web --reset-target

# Transfer only files or only database data
./migrate-data.sh --skip-db
./migrate-data.sh --skip-files

# Copy files into the managed media volume
./migrate-data.sh --copy-files

# Set the source public address explicitly
./migrate-data.sh --reset-target --legacy-app-url https://ecosound-web.example.com/ecosound_web
```

`--reset-target` backs up target database and media, clears business data, then begins migration. `--skip-db`, `--skip-files`, and `--copy-files` limit or select the transfer strategy. The default mounts source media during transfer; copy mode stores media in the target-managed volume. Do not substitute manual destructive database commands for the reset workflow.

Common options are:

- `--dry-run`: preview migration without writing data
- `--skip-db`: skip database migration
- `--skip-files`: skip static file migration
- `--copy-files`: copy source static files into the `app-media-data` volume
- `--reset-target`: back up target database and media, clear business data, then migrate
- `--legacy-app-url <url>`: provide the source public URL used for federation node identity

The script checks source MySQL connectivity from the host before starting the in-container transfer. When the target is a fresh deployment, its seeded Demo Project, collection, and site require `--reset-target` before the first migration. Changing `LEGACY_PROJECT_DIR` requires container recreation; a plain `docker compose restart` does not refresh the bind mount. The default direct-mount strategy verifies `/app/sounds/sounds`, `/app/sounds/images`, and `/app/sounds/projects` before database work. Copy mode places files in `app-media-data`, so later access does not depend on the source directory remaining mounted.

If the source public address cannot be detected, pass `--legacy-app-url <url>` or set `LEGACY_APP_URL`. Address resolution stops before writes if no valid `http://` or `https://` candidate exists.

The first non-empty source address wins in this order: `--legacy-app-url <url>`, `LEGACY_APP_URL` from the shell or `.env`, `APP_URL` in the source `src/config/config.ini`, then the source database's stored `app_url` or a unique match on server name and coordinates among known federation nodes. `LEGACY_HOST_URL` follows the same environment-over-configuration precedence and defaults to the source `HOST_URL`. When resolution fails, preflight reports the server name, coordinates, and candidates and leaves no partially migrated data.

## Recover data

Restore migration backups with:

```bash
./rollback.sh latest
./rollback.sh backup_20260411_133000
./rollback.sh target_backup_20260420_210000 --force
```

Backups live in `.upgrade-backup/`. Confirm the backup name and its impact before restoring. `--force` skips confirmation; `--keep-new` preserves current target volumes when restoring a source backup.

The `backup_*` set is used when restoring source data to the source installation; `target_backup_*` is the target database and media backup made before a reset migration. Keep the backup directory outside disposable test environments and verify the restored service before allowing users to resume work.

## Production deployment details

The production script uses only production Compose files, builds the frontend production bundle, serves it through nginx, applies setup once, waits for dependencies and health checks, and serializes concurrent releases. Set `TAG` only when a custom image tag is required; otherwise Compose uses `latest`. macOS and Linux use `./deploy.sh` and do not require `flock`.

The staging workflow is `.github/workflows/deploy-staging.yml` and runs on pushes to `main`. The production workflow is `.github/workflows/deploy-production.yml` and runs when a Release is published. Required secrets are `SECRET_KEY`, `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `RABBITMQ_ERLANG_COOKIE`, and optional `SENTRY_DSN`.

Optional GitHub variables include `DOMAIN`, `FRONTEND_PORT`, `STACK_NAME`, `BACKEND_CORS_ORIGINS`, `AUTH_SESSION_IDLE_EXPIRE_MINUTES`, `PROJECT_NAME`, `POSTGRES_USER`, `POSTGRES_DB`, `DOCKER_IMAGE_BACKEND`, `DOCKER_IMAGE_FRONTEND`, `LEGACY_PROJECT_DIR`, `LEGACY_APP_URL`, `LEGACY_HOST_URL`, `GEO_DB_READY_URL`, and `GEO_DB_XR_SEED_URL`. Define domain, stack, and CORS values separately in staging and production. The workflows set `ENVIRONMENT` directly and copy `.env.example` before appending environment-specific values.

| Variable | Default or meaning |
| --- | --- |
| `DOMAIN` | No default; deployment domain |
| `FRONTEND_PORT` | `80`; frontend host port |
| `STACK_NAME` | Compose project name |
| `BACKEND_CORS_ORIGINS` | No default; allowed backend origins |
| `AUTH_SESSION_IDLE_EXPIRE_MINUTES` | `30` in staging/production; `0` disables expiry |
| `PROJECT_NAME` | `ecoSignal` |
| `POSTGRES_USER` / `POSTGRES_DB` | `postgres` / `ecosignal` |
| `DOCKER_IMAGE_BACKEND` / `DOCKER_IMAGE_FRONTEND` | `backend` / `frontend` |
| `LEGACY_PROJECT_DIR` | `./ecoSound-web`; source media path |
| `LEGACY_APP_URL` / `LEGACY_HOST_URL` | Source public URL / federation hub |
| `GEO_DB_READY_URL` / `GEO_DB_XR_SEED_URL` | Bundled geographical-data defaults |

The main defaults are `FRONTEND_PORT=80`, `PROJECT_NAME=ecoSignal`, `POSTGRES_USER=postgres`, `POSTGRES_DB=ecosignal`, `AUTH_SESSION_IDLE_EXPIRE_MINUTES=30` in staging and production, and the bundled defaults for geographical-data URLs. `REDIS_PASSWORD` must be replaced for staging and production even though local development has a default.

Production defaults use three web workers and separate interactive and analysis consumers. The interactive consumer also performs startup synchronisation and scheduled maintenance. Adjust `WEB_CONCURRENCY` and `DB_*` pool values only after observing resource use, queue depth, and PostgreSQL connections.

Use the [Observability Guide](observability.md) for metrics, errors, and dashboards. Keep metrics behind internal network or gateway protection.

## Related documentation

- [Administrator Guide](admin-guide.md) for application-level operations
- [User Guide](user-guide.md) for daily workflows
- [Documentation home](../README.md)
