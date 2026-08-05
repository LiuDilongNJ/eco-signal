from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_health_response_contains_meta_and_request_id_header(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/health")

    assert response.status_code == 200
    body = response.json()
    assert "meta" in body
    assert body["meta"]["version"] == settings.APP_VERSION
    assert body["meta"]["timestamp"]
    assert body["meta"]["request_id"]
    assert response.headers["X-Request-ID"] == body["meta"]["request_id"]


def test_request_id_passthrough_uses_client_header(client: TestClient) -> None:
    custom_request_id = "req_custom_001"
    response = client.get(
        f"{settings.API_V1_STR}/health",
        headers={"X-Request-ID": custom_request_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert response.headers["X-Request-ID"] == custom_request_id
    assert body["meta"]["request_id"] == custom_request_id


def test_metrics_endpoint_exposes_http_metrics(client: TestClient) -> None:
    client.get(f"{settings.API_V1_STR}/health")
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "ecosignal_http_requests_total" in response.text
    assert "ecosignal_http_request_duration_seconds" in response.text
    assert "ecosignal_db_pool_connections" in response.text


def test_unhandled_exception_is_captured_by_sentry(client: TestClient) -> None:
    del client
    with (
        patch("app.main.sentry_sdk.capture_exception") as mock_capture,
        patch(
            "app.api.routes.media.media_service.get_media",
            side_effect=RuntimeError("boom"),
        ),
    ):
        with TestClient(app, raise_server_exceptions=False) as local_client:
            response = local_client.get(f"{settings.API_V1_STR}/media/1", params={"project_id": 1})

    assert response.status_code == 500
    body = response.json()
    assert body["message"] == "Internal Server Error"
    assert "meta" in body
    mock_capture.assert_called_once()
