# Observability Guide

This project includes:

- Sentry for error tracking
- Prometheus-compatible metrics exposed by the backend

EcoSignal does not require Prometheus or Grafana to run. The backend only exposes metrics at `GET /metrics`; Prometheus and Grafana can run on the same host, another machine, or an existing observability platform.

## Architecture

- EcoSignal API exports Prometheus text metrics at `GET /metrics`.
- Prometheus scrapes EcoSignal over HTTP.
- Grafana connects to Prometheus as a data source.
- EcoSignal does not call Prometheus or Grafana at runtime.

Recommended production shape:

```text
EcoSignal backend /metrics  <--scrape--  Prometheus  <--query--  Grafana
```

## Sentry

Sentry captures unhandled API exceptions and worker-side failures when enabled. The interactive worker also reports startup synchronization and scheduled maintenance failures.

Configure these values in `.env`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `SENTRY_DSN` | empty | Sentry project DSN. Required for event delivery |
| `SENTRY_ENABLED` | `true` | Global Sentry switch |
| `SENTRY_ENABLE_IN_LOCAL` | `false` | Whether local environment can send events |
| `SENTRY_ENABLE_LOGS` | `true` | Whether SDK logs are sent to Sentry |
| `SENTRY_TRACES_SAMPLE_RATE` | `1.0` | Performance tracing sample rate |
| `SENTRY_PROFILE_SESSION_SAMPLE_RATE` | `1.0` | Profiling sample rate |
| `SENTRY_PROFILE_LIFECYCLE` | `trace` | Profiling lifecycle mode |
| `SENTRY_SEND_DEFAULT_PII` | `true` | Whether to send default personally identifiable information |

Example:

```env
SENTRY_DSN=https://<public_key>@o<org_id>.ingest.sentry.io/<project_id>
SENTRY_ENABLED=true
SENTRY_ENABLE_IN_LOCAL=false
SENTRY_ENABLE_LOGS=true
SENTRY_TRACES_SAMPLE_RATE=1.0
SENTRY_PROFILE_SESSION_SAMPLE_RATE=1.0
SENTRY_PROFILE_LIFECYCLE=trace
SENTRY_SEND_DEFAULT_PII=true
```

Notes:

- If `SENTRY_DSN` is empty, Sentry initialization is skipped.
- If `ENVIRONMENT=local`, set `SENTRY_ENABLE_IN_LOCAL=true` to send local events.
- The API and worker both set a `service` tag during initialization.
- Request IDs are attached to Sentry events as `request_id` tags and extra data.

## Prometheus Metrics

Enable metrics with:

```env
METRICS_ENABLED=true
```

The backend exposes:

```text
GET /metrics
```

Current built-in HTTP metrics include:

- `ecosignal_http_requests_total`
- `ecosignal_http_request_duration_seconds`
- `ecosignal_db_pool_connections`
- `ecosignal_worker_tasks_total`
- `ecosignal_worker_task_duration_seconds`

Production Compose shares Prometheus multiprocess files between Gunicorn and worker containers so `/metrics` includes all web workers and background task outcomes. Keep the metrics volume managed by Compose; do not delete its files while the stack is running.

Metrics are collected by request method, route path, and status code. The `/metrics`, `/docs`, `/redoc`, and OpenAPI paths are excluded from HTTP request counting.

Verify the endpoint:

```bash
curl http://localhost:8000/metrics
```

If metrics are disabled, the endpoint returns `404 Metrics disabled`.

## External Prometheus And Grafana

Prometheus and Grafana do not need to run in this project. Deploy them wherever they can reach the backend.

Use `.env` to record the external service URLs for deployment notes or future UI links:

```env
PROMETHEUS_URL=http://prometheus.example.com
GRAFANA_URL=http://grafana.example.com
```

The current backend does not read `PROMETHEUS_URL` or `GRAFANA_URL`.

Example Prometheus scrape configuration for an external backend URL:

```yaml
scrape_configs:
  - job_name: "ecosignal-backend"
    metrics_path: /metrics
    static_configs:
      - targets: ["api.example.com"]
```

If Prometheus reaches the backend through an internal network, use that internal address instead:

```yaml
scrape_configs:
  - job_name: "ecosignal-backend"
    metrics_path: /metrics
    static_configs:
      - targets: ["ecosignal-backend.internal:8000"]
```

In Grafana, add Prometheus as a data source using the URL where Grafana can reach Prometheus, for example:

```text
http://prometheus.example.com
```

## Optional Local Stack

For local development only, this repository includes:

- [docker-compose.observability.yml](../docker-compose.observability.yml)
- [monitoring/prometheus/prometheus.yml](../monitoring/prometheus/prometheus.yml)

Start the local application and observability stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d
```

Local URLs:

- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

The local Prometheus configuration uses Docker networking:

```yaml
targets: ["backend:8000"]
```

If ports `9090` or `3000` conflict locally, edit `docker-compose.observability.yml` or deploy Prometheus/Grafana separately. These ports are not controlled by `.env`.

Local Grafana credentials are controlled by:

```env
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin123
```

## Security Recommendation

- Do not expose `/metrics` publicly unless intentionally protected.
- Prefer internal network access, reverse proxy restrictions, or gateway-level protection.
- Change the local Grafana password before exposing it outside your machine.

## Quick Checklist

1. Set `METRICS_ENABLED=true`.
2. Confirm `GET /metrics` returns Prometheus text metrics.
3. Configure Prometheus to scrape the backend address it can reach.
4. Configure Grafana to use the Prometheus URL it can reach.
5. Set `SENTRY_DSN` if Sentry error reporting is needed.
