# 可观测性操作文档

本项目包含以下可观测性能力：

- Sentry：错误跟踪
- Prometheus 兼容指标：由后端暴露

EcoSignal 默认不依赖 Prometheus 或 Grafana 启动。后端只负责通过 `GET /metrics` 暴露指标；Prometheus 和 Grafana 可以部署在本机、其他服务器，或已有的监控平台中。

## 架构说明

- EcoSignal API 通过 `GET /metrics` 输出 Prometheus 文本格式指标。
- Prometheus 通过 HTTP 主动抓取 EcoSignal。
- Grafana 连接 Prometheus 数据源。
- EcoSignal 运行时不会主动调用 Prometheus 或 Grafana。

推荐生产形态：

```text
EcoSignal backend /metrics  <--scrape--  Prometheus  <--query--  Grafana
```

## Sentry

Sentry 用于采集 API 未处理异常和 worker 任务异常；交互任务消费者中的启动同步和定时维护异常也会被采集。

在 `.env` 中配置：

| 变量名 | 默认值 | 含义 |
| --- | --- | --- |
| `SENTRY_DSN` | 空 | Sentry 项目 DSN。真正上报事件时必填 |
| `SENTRY_ENABLED` | `true` | Sentry 总开关 |
| `SENTRY_ENABLE_IN_LOCAL` | `false` | 是否允许本地环境上报 |
| `SENTRY_ENABLE_LOGS` | `true` | 是否把 SDK 日志发送到 Sentry |
| `SENTRY_TRACES_SAMPLE_RATE` | `1.0` | 性能追踪采样率 |
| `SENTRY_PROFILE_SESSION_SAMPLE_RATE` | `1.0` | Profiling 采样率 |
| `SENTRY_PROFILE_LIFECYCLE` | `trace` | Profiling 生命周期模式 |
| `SENTRY_SEND_DEFAULT_PII` | `true` | 是否发送默认 PII 信息 |

示例：

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

说明：

- 如果 `SENTRY_DSN` 为空，Sentry 初始化会跳过。
- 如果 `ENVIRONMENT=local`，需要设置 `SENTRY_ENABLE_IN_LOCAL=true` 才会上报本地事件。
- API 和 worker 初始化时都会设置 `service` 标签。
- 请求的 `request_id` 会写入 Sentry 事件的 tag 和 extra。

## Prometheus 指标

通过以下配置开启指标：

```env
METRICS_ENABLED=true
```

后端暴露：

```text
GET /metrics
```

当前内置 HTTP 指标包括：

- `ecosignal_http_requests_total`
- `ecosignal_http_request_duration_seconds`
- `ecosignal_db_pool_connections`
- `ecosignal_worker_tasks_total`
- `ecosignal_worker_task_duration_seconds`

生产 Compose 会在 Gunicorn 与 worker 容器之间共享 Prometheus 多进程指标文件，因此 `/metrics` 会汇总所有 Web worker 和后台任务结果。运行中的服务不得手动删除该指标 volume 中的文件。

这些指标按请求方法、路由路径和状态码统计。`/metrics`、`/docs`、`/redoc` 和 OpenAPI 路径不会计入 HTTP 请求统计。

验证接口：

```bash
curl http://localhost:8000/metrics
```

如果指标关闭，接口会返回 `404 Metrics disabled`。

## 外部 Prometheus 和 Grafana

Prometheus 和 Grafana 不需要运行在本项目里。只要它们能访问后端即可。

可以在 `.env` 中记录外部服务地址，用于部署说明或未来 UI 入口：

```env
PROMETHEUS_URL=http://prometheus.example.com
GRAFANA_URL=http://grafana.example.com
```

当前后端不会读取 `PROMETHEUS_URL` 或 `GRAFANA_URL`。

外部 Prometheus 抓取公网或网关地址示例：

```yaml
scrape_configs:
  - job_name: "ecosignal-backend"
    metrics_path: /metrics
    static_configs:
      - targets: ["api.example.com"]
```

如果 Prometheus 通过内网访问后端，则使用内网地址：

```yaml
scrape_configs:
  - job_name: "ecosignal-backend"
    metrics_path: /metrics
    static_configs:
      - targets: ["ecosignal-backend.internal:8000"]
```

在 Grafana 中添加 Prometheus 数据源时，填写 Grafana 能访问到的 Prometheus 地址，例如：

```text
http://prometheus.example.com
```

## 可选本地监控栈

仅用于本地开发，仓库提供：

- [docker-compose.observability.yml](../docker-compose.observability.yml)
- [monitoring/prometheus/prometheus.yml](../monitoring/prometheus/prometheus.yml)

启动本地应用和监控栈：

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d
```

本地访问地址：

- Prometheus：`http://localhost:9090`
- Grafana：`http://localhost:3000`

本地 Prometheus 使用 Docker 网络地址：

```yaml
targets: ["backend:8000"]
```

如果本地 `9090` 或 `3000` 端口冲突，请直接调整 `docker-compose.observability.yml`，或使用独立部署方式。端口不再通过 `.env` 控制。

本地 Grafana 账号密码由以下配置控制：

```env
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin123
```

## 安全建议

- 不建议直接把 `/metrics` 暴露到公网，除非已经有明确访问保护。
- 推荐通过内网、反向代理限制或网关权限保护指标接口。
- 如果 Grafana 不只在本机临时使用，请修改默认密码。

## 快速检查清单

1. 设置 `METRICS_ENABLED=true`。
2. 确认 `GET /metrics` 返回 Prometheus 文本指标。
3. 配置 Prometheus 抓取它能访问到的后端地址。
4. 配置 Grafana 使用它能访问到的 Prometheus URL。
5. 如需错误跟踪，配置 `SENTRY_DSN`。
