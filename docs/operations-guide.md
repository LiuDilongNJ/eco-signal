# ecoSignal Operations Guide

[中文](operations-guide.zh.md) · [Documentation home](../README.md)

**For:** operators who deploy, maintain, migrate, or recover a shared ecoSignal environment.  
**Before you begin:** prepare a Docker host, secure environment values, and verified backups before changing a deployed system.

## Contents

- [Configure production](#configure-production)
- [Configure custom domains and HTTPS](#configure-custom-domains-and-https)
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

## Configure custom domains and HTTPS

All modes use one `DOMAIN` for the homepage `/`, API `/api/`, and media `/sounds/`. Point DNS A/AAAA records to the server address; a CNAME points to another hostname. No `api.` or `dashboard.` subdomains are needed. The Traefik dashboard is not publicly exposed.

### 1. Own certificates: HTTPS directly through Nginx

```ini
DOMAIN=ecosignal.example.org
ENABLE_HTTPS=true
HTTPS_MODE=static
TLS_CERT_FILE=/etc/ssl/certs/ecosignal-fullchain.pem
TLS_KEY_FILE=/etc/ssl/private/ecosignal.key
BACKEND_CORS_ORIGINS="https://ecosignal.example.org"
```

- Supply a PEM certificate chain in leaf-first order followed by intermediate certificates, and a matching private key without an interactive password. The certificate must cover `DOMAIN` and be currently valid. Restrict private-key source access to the deployment account and administrators.
- Frontend Nginx publishes host ports 80/443, redirects HTTP to the configured `https://DOMAIN`, proxies `/api/` to the backend, and serves `/sounds/` directly from mounted files. The backend does not publish a host port.
- A Docker tool container checks certificate format, validity, hostname and key matching. Expiry within 30 days produces a warning; invalid material blocks deployment. Host OpenSSL is not required.
- Private CA certificates are supported. Install the organization's trust chain on browsers and API clients. Deployment verification pins the validated leaf instead of requiring the tool container to trust the private CA.
- Validated certificates are copied into `.deploy/tls`, mounted read-only as a whole directory. It contains private keys and the previous pair: restrict access, exclude it from Git and images, and retain it in a stable deployment directory. Do not edit the installed pair manually.

To update certificates only, replace the configured source files, then run:

```bash
./deploy.sh --reload-certs
# Windows PowerShell:
./deploy.ps1 -ReloadCerts
```

Updates share the deployment lock, back up and install the pair, run `nginx -t`, then `nginx -s reload`. New TLS connections must return the expected fingerprint and hostname within 30 seconds. Failure restores the previous pair, verifies recovery, and returns a nonzero status. This operation does not enable maintenance, restart containers, or rebuild the application; old workers finish existing requests. Full application releases may still require a maintenance window.

### 2. Automated certificates: Traefik + Let's Encrypt

```ini
DOMAIN=ecosignal.example.org
ENABLE_HTTPS=true
HTTPS_MODE=letsencrypt
EMAIL=admin@example.org
BACKEND_CORS_ORIGINS="https://ecosignal.example.org"
```

Traefik publishes ports 80/443 and terminates HTTPS before forwarding to frontend Nginx. Both frontend and API use `https://ecosignal.example.org`. TLS-ALPN-01 requires public port 443 to reach Traefik directly; port 80 serves HTTP redirects. Allow outbound ACME access and avoid upstream proxies intercepting the TLS challenge. Traefik persists ACME accounts/certificates and renews automatically; do not use `--reload-certs` for this mode.

Initial issuance waits up to 180 seconds. Failure reports diagnostics instead of deployment success. Test with `ACME_CA_SERVER=https://acme-staging-v02.api.letsencrypt.org/directory` using a separate Compose project and certificate volume, never production ACME data. Test roots are not trusted by ordinary clients. Restore the default production directory for deployment; do not bypass production trust verification.

### 3. HTTP: internal access or an external HTTPS gateway

```ini
DOMAIN=ecosignal.example.org
ENABLE_HTTPS=false
FRONTEND_PORT=80
BACKEND_CORS_ORIGINS="http://ecosignal.example.org"
```

Nginx serves `http://DOMAIN:FRONTEND_PORT`. When an external gateway terminates TLS, configure CORS for the browser's actual origin and have the trusted gateway set `X-Forwarded-Proto`.

### Mode changes and verification

- Switch modes in a maintenance window. Before handing over ports, the script checks Traefik's deployment directory and stack ownership. It stops only the matching entrypoint and retains ACME volumes; ambiguous ownership blocks the operation. Do not share this entrypoint instance between projects.
- `--dry-run` / `-DryRun` resolves application, entrypoint and maintenance configuration and validates static source certificates. It may build a tool image and run temporary validation containers, but does not start the application or replace installed certificates.
- Deployment verifies ingress TLS before ending maintenance, then checks the homepage and API health endpoint. Failure retains or restores maintenance. Checks originate in the ingress container network with correct SNI; also verify public DNS, firewall rules and client CA trust from an external client.

### Deployment regression tests

Run `./scripts/test-tls.sh` for validation, script failure handling and Nginx reload tests; `./scripts/test-tls.sh --integration` also builds the production frontend and tests isolated HTTP/static/ACME stacks, including issuance and renewal against Pebble, a local ACME test CA. Test stacks use unique names, no published host ports, and separate disposable certificate volumes. `./scripts/test-tls.sh --powershell` runs the same command tests through Bash and PowerShell 7 in a Linux container; native Windows Docker Desktop path/ACL behavior still requires host validation.

The self-hosted Actions checkout preserves `.deploy` so active directory mounts, certificate backups and deployment locks survive code updates. Keep the checkout path stable. Source keys remain outside the checkout.

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

Set optional values such as `DOMAIN`, `ENABLE_HTTPS`, `HTTPS_MODE`, `TLS_CERT_FILE`, `TLS_KEY_FILE`, `FRONTEND_PORT`, `STACK_NAME`, `BACKEND_CORS_ORIGINS`, and `AUTH_SESSION_IDLE_EXPIRE_MINUTES` separately in the staging and production environments. Do not define `ENVIRONMENT` as a GitHub variable. Install a self-hosted runner with the appropriate environment label.

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

Options are:

- `--dry-run`: preview migration without writing data
- `--reset-target`: back up target database and media, clear business data, then migrate. Do not substitute manual destructive database commands for the reset workflow.
- `--repair-permissions`: repair and re-map legacy permissions into the `user_scope_role` access role architecture on an already migrated target
- `--legacy-app-url <url>`: provide the source public URL used for federation node identity - sets the source public address explicitly
The following limit or select the transfer strategy:
- `--skip-db`: skip database migration (transfers only files if used alone)
- `--skip-files`: skip static file migration (transfers only database if used alone)
- `--copy-files`: copy source static files into the target-managed `app-media-data` volume, convert WAV files to FLAC lossless compression, and extract embedded audio metadata into the database

The script checks source MySQL connectivity from the host before starting the in-container transfer. When the target is a fresh deployment, its seeded Demo Project, collection, and site require `--reset-target` before the first migration. The default direct-mount strategy verifies `/app/sounds/sounds`, `/app/sounds/images`, and `/app/sounds/projects` before database work, and backfills audio metadata. Copy mode converts WAVs to FLAC, extracts metadata, verifies the copied trees, sets `MEDIA_STORAGE_MODE=managed`, and recreates running media services. Later access and new uploads then use `app-media-data`; the source directories are not deleted automatically.

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

Optional GitHub variables include:

| Variable | Default or meaning |
| --- | --- |
| `DOMAIN` | No default; deployment domain |
| `FRONTEND_PORT` | `80` for HTTP; HTTPS overrides the public origin port to `443` |
| `STACK_NAME` | Compose project name |
| `BACKEND_CORS_ORIGINS` | No default; allowed backend origins |
| `AUTH_SESSION_IDLE_EXPIRE_MINUTES` | `30` in staging/production; `0` disables expiry |
| `PROJECT_NAME` | `ecoSignal` |
| `POSTGRES_USER` / `POSTGRES_DB` | `postgres` / `ecosignal` |
| `DOCKER_IMAGE_BACKEND` / `DOCKER_IMAGE_FRONTEND` | `backend` / `frontend` |
| `MEDIA_STORAGE_MODE` | `managed`; use `direct-mount` only when source media remains mounted |
| `ENABLE_HTTPS` | `false` in the example; Actions defaults to `true` |
| `ACME_CA_SERVER` | Production Let's Encrypt directory by default; isolate test CA data |
| `HTTPS_MODE` | `letsencrypt`; set `static` for Bring-Your-Own-Certificate HTTPS |
| `TLS_CERT_FILE` / `TLS_KEY_FILE` | Host paths to static TLS certificate and private key |
| `LEGACY_PROJECT_DIR` | `./ecoSound-web`; source media path |
| `LEGACY_APP_URL` / `LEGACY_HOST_URL` | Source public URL / federation hub |
| `GEO_DB_READY_URL` / `GEO_DB_XR_SEED_URL` | Bundled geographical-data defaults |

Define domain, stack, and CORS values separately in staging and production. The workflows set `ENVIRONMENT` directly and copy `.env.example` before appending environment-specific values. The main defaults are `FRONTEND_PORT=80`, `PROJECT_NAME=ecoSignal`, `POSTGRES_USER=postgres`, `POSTGRES_DB=ecosignal`, `AUTH_SESSION_IDLE_EXPIRE_MINUTES=30` in staging and production, and the bundled defaults for geographical-data URLs. `REDIS_PASSWORD` must be replaced for staging and production even though local development has a default.

Production defaults use three web workers and separate interactive and analysis consumers. The interactive consumer also performs startup synchronisation and scheduled maintenance. Adjust `WEB_CONCURRENCY` and `DB_*` pool values only after observing resource use, queue depth, and PostgreSQL connections.

Use the [Observability Guide](observability.md) for metrics, errors, and dashboards. Keep metrics behind internal network or gateway protection.

## Related documentation

- [Administrator Guide](admin-guide.md) for application-level operations
- [User Guide](user-guide.md) for daily workflows
- [Documentation home](../README.md)
