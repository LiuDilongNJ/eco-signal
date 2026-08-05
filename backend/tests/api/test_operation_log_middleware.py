"""Unit tests for operation log middleware client IP wiring."""
import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.api import middleware as operation_log_middleware_module


def _request(*, method: str = "POST", path: str = "/api/v1/projects") -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("172.18.0.5", 12345),
        "server": ("testserver", 80),
    }
    return Request(scope)


@pytest.mark.anyio
async def test_operation_log_middleware_uses_get_client_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def call_next(_request: Request) -> Response:
        return Response(status_code=201)

    async def fake_extract_payload(_request: Request) -> dict:
        return {"name": "demo"}

    def fake_save_operation_log(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(
        operation_log_middleware_module,
        "_extract_payload",
        fake_extract_payload,
    )
    monkeypatch.setattr(
        operation_log_middleware_module,
        "_save_operation_log",
        fake_save_operation_log,
    )
    monkeypatch.setattr(
        operation_log_middleware_module,
        "get_client_ip",
        lambda _request: "203.0.113.77",
    )
    monkeypatch.setattr(
        operation_log_middleware_module,
        "_extract_user_id",
        lambda _request: 1,
    )

    response = await operation_log_middleware_module.operation_log_middleware(
        _request(),
        call_next,
    )

    assert response.status_code == 201
    assert response.background is not None
    await response.background()
    assert captured["req_ip"] == "203.0.113.77"
    assert captured["action"] == "create"
    assert captured["resource_type"] == "projects"
    assert captured["payload"] == {"name": "demo"}
