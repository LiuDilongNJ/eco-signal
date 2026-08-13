import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

import sentry_sdk
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response as RawResponse
from fastapi.routing import APIRoute
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest, multiprocess
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.api.middleware import operation_log_middleware
from app.core.config import settings
from app.core.db import engine
from app.core.exceptions import AppValidationError
from app.core.observability import (
    REQUEST_ID_HEADER,
    bind_request_id,
    build_meta_dict,
    current_request_id,
    generate_request_id,
    init_sentry,
    reset_request_id,
    sentry_request_scope,
)
from app.media_paths import (
    is_safe_public_media_request_path,
    media_root,
    resolve_existing_media_path,
)
from app.schemas.response import ApiErrorResponse

logger = logging.getLogger(__name__)
PROM_REGISTRY = CollectorRegistry(auto_describe=True)
_PROM_MULTIPROC_ENABLED = bool(os.getenv("PROMETHEUS_MULTIPROC_DIR"))
if _PROM_MULTIPROC_ENABLED:
    multiprocess.MultiProcessCollector(PROM_REGISTRY)
_METRIC_REGISTRY = None if _PROM_MULTIPROC_ENABLED else PROM_REGISTRY
PROM_HTTP_REQUESTS_TOTAL = Counter(
    "ecosignal_http_requests_total",
    "Total number of HTTP requests",
    labelnames=("method", "path", "status_code"),
    registry=_METRIC_REGISTRY,
)
PROM_HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "ecosignal_http_request_duration_seconds",
    "Request duration in seconds",
    labelnames=("method", "path"),
    registry=_METRIC_REGISTRY,
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
PROM_DB_POOL_CONNECTIONS = Gauge(
    "ecosignal_db_pool_connections",
    "SQLAlchemy database pool connection counts",
    labelnames=("state",),
    registry=_METRIC_REGISTRY,
)


def custom_generate_unique_id(route: APIRoute) -> str:
    tag = route.tags[0] if route.tags else "static"
    return f"{tag}-{route.name}"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期管理"""
    yield


init_sentry("api")

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

# Set all CORS enabled origins
if settings.all_cors_origins:
    cors_kw: dict = {
        "allow_origins": settings.all_cors_origins,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
        "expose_headers": ["Content-Disposition", "X-Auth-Reason"],
    }
    # 局域网用 IP 打开 Vite（如 http://192.168.x.x:5173）直连后端 :8000 时，origins 列表里往往只有 localhost。
    # 仅在 local 环境放宽为常见私网地址，避免每次换 IP 都改 BACKEND_CORS_ORIGINS。
    if settings.ENVIRONMENT == "local":
        cors_kw["allow_origin_regex"] = (
            r"https?://(localhost|127\.0\.0\.1)(:\d+)?$"
            r"|https?://(192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
            r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})(:\d{1,5})?$"
        )
    app.add_middleware(CORSMiddleware, **cors_kw)

@app.middleware("http")
async def strip_empty_query_params(request: Request, call_next):
    """Strip empty string query parameters for GET requests before route handling.
    仅对 GET 请求过滤空字符串 Query 参数，避免整数类型筛选参数收到空字符串时的 422 校验错误。
    POST/PUT/PATCH 请求不做处理，避免影响通过 query 参数传递置空意图的场景。
    """
    if request.method == "GET":
        params = [
            (k, v)
            for k, v in parse_qsl(
                request.scope["query_string"].decode("utf-8"), keep_blank_values=True
            )
            if v != ""
        ]
        request.scope["query_string"] = urlencode(params).encode("utf-8")
    return await call_next(request)


@app.middleware("http")
async def bind_request_context(request: Request, call_next):
    request_id = request.headers.get(REQUEST_ID_HEADER) or generate_request_id()
    request.state.request_id = request_id
    token = bind_request_id(request_id)
    try:
        with sentry_request_scope(request_id):
            response = await call_next(request)
    finally:
        reset_request_id(token)
    response.headers.setdefault(REQUEST_ID_HEADER, request_id)
    return response


@app.middleware("http")
async def prometheus_metrics_middleware(request: Request, call_next):
    if not settings.METRICS_ENABLED:
        return await call_next(request)

    excluded_paths = {
        "/metrics",
        "/docs",
        "/redoc",
        app.openapi_url,
    }
    started_at = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - started_at

    if request.url.path not in excluded_paths:
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        method = request.method.upper()
        status_code = str(response.status_code)
        PROM_HTTP_REQUESTS_TOTAL.labels(method=method, path=route_path, status_code=status_code).inc()
        PROM_HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=route_path).observe(elapsed)
    return response


app.middleware("http")(operation_log_middleware)
app.include_router(api_router, prefix=settings.API_V1_STR)

try:
    media_root().mkdir(parents=True, exist_ok=True)
except OSError:
    logger.warning("Media root %s could not be created during startup", media_root())


@app.get("/sounds/{media_path:path}", include_in_schema=False)
async def serve_media(media_path: str) -> FileResponse:
    if not is_safe_public_media_request_path(media_path):
        raise HTTPException(status_code=400, detail="Invalid media path")

    resolved = resolve_existing_media_path(Path(media_path))
    if resolved is None or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")
    return FileResponse(resolved)


@app.get("/metrics", include_in_schema=False)
def metrics() -> RawResponse:
    if not settings.METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="Metrics disabled")
    pool = engine.pool
    PROM_DB_POOL_CONNECTIONS.labels(state="checked_out").set(pool.checkedout())
    PROM_DB_POOL_CONNECTIONS.labels(state="checked_in").set(pool.checkedin())
    PROM_DB_POOL_CONNECTIONS.labels(state="overflow").set(max(pool.overflow(), 0))
    metrics_body = generate_latest(PROM_REGISTRY)
    return RawResponse(content=metrics_body, media_type=CONTENT_TYPE_LATEST)


# Global exception handlers for unified error response format
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle HTTP exceptions with unified ApiErrorResponse format."""
    error_response = ApiErrorResponse(
        code=exc.status_code,
        message=str(exc.detail) if exc.detail else "Error",
        detail=None,
        meta=build_meta_dict(),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump(),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle validation errors with unified ApiErrorResponse format."""
    # Format validation errors
    errors = exc.errors()
    detail = "; ".join([f"{err['loc'][-1]}: {err['msg']}" for err in errors])

    error_response = ApiErrorResponse(
        code=422,
        message="Validation Error",
        detail=detail,
        meta=build_meta_dict(),
    )
    return JSONResponse(
        status_code=422,
        content=error_response.model_dump()
    )


@app.exception_handler(AppValidationError)
async def app_validation_exception_handler(_request: Request, exc: AppValidationError) -> JSONResponse:
    """Handle domain-level validation errors (raised from repositories/services)."""
    error_response = ApiErrorResponse(
        code=400,
        message=exc.detail,
        detail=None,
        meta=build_meta_dict(),
    )
    return JSONResponse(status_code=400, content=error_response.model_dump())


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions with unified ApiErrorResponse format."""
    logger.exception("Unhandled exception occurred")
    sentry_sdk.capture_exception(exc)

    error_response = ApiErrorResponse(
        code=500,
        message="Internal Server Error",
        detail=str(exc) if settings.ENVIRONMENT == "local" else None,
        meta={
            **build_meta_dict(),
            "request_id": getattr(request.state, "request_id", current_request_id()),
        },
    )
    return JSONResponse(
        status_code=500,
        content=error_response.model_dump()
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
    )
