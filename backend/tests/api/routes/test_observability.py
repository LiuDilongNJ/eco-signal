from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.schemas.storage import FilesystemStatus, StorageStatus
from app.services.storage_service import StorageStatusUnavailableError


def test_health_response_contains_meta_and_request_id_header(
    client: TestClient,
) -> None:
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
            response = local_client.get(
                f"{settings.API_V1_STR}/media/1", params={"project_id": 1}
            )

    assert response.status_code == 500
    body = response.json()
    assert body["message"] == "Internal Server Error"
    assert "meta" in body
    mock_capture.assert_called_once()


def test_metrics_reports_storage_and_cache_snapshot(client, monkeypatch):
    monkeypatch.setattr(
        "app.main.get_storage_status",
        lambda: StorageStatus(
            checked_at="2026-11-05 00:00:00",
            status="warning",
            filesystems=[
                FilesystemStatus(
                    scope="media",
                    path="/media",
                    available=True,
                    total_bytes=1000,
                    free_bytes=200,
                    used_bytes=800,
                    used_percent=80,
                    status="warning",
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "app.main.detail_cache_service.read_snapshot",
        lambda: {"bytes_used": 4096, "bundles": 1, "last_success": 123},
    )
    response = client.get("/metrics")
    assert response.status_code == 200
    assert 'ecosignal_storage_used_percent{scope="media"} 80.0' in response.text
    assert 'ecosignal_detail_cache_state{kind="bytes_used"} 4096.0' in response.text


def test_metrics_remains_available_when_storage_cannot_be_sampled(client, monkeypatch):
    def unavailable():
        raise StorageStatusUnavailableError()

    monkeypatch.setattr("app.main.get_storage_status", unavailable)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert 'ecosignal_storage_available{scope="media"} 0.0' in response.text
