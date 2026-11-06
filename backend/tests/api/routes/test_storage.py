from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


@pytest.mark.parametrize(
    ("used_percent", "expected_status"),
    [
        (79.9, "healthy"),
        (80.0, "warning"),
        (89.9, "warning"),
        (90.0, "critical"),
    ],
)
def test_get_storage_status_for_admin(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    used_percent: float,
    expected_status: str,
) -> None:
    total = 10_000
    free = round(total * (1 - used_percent / 100))
    expected_used = total - free

    with patch(
        "app.services.storage_service.shutil.disk_usage",
        return_value=SimpleNamespace(total=total, used=expected_used, free=free),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/system/storage",
            headers=superuser_token_headers,
        )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["status"] == expected_status
    assert len(payload["data"]["filesystems"]) == 2
    for item in payload["data"]["filesystems"]:
        assert item["used_bytes"] == expected_used
        assert item["used_percent"] == round((expected_used / total) * 100, 1)
        assert item["status"] == expected_status
        assert item["available"] is True


def test_get_storage_status_forbidden_for_normal_user(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/system/storage",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 403


def test_get_storage_status_requires_authentication(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/system/storage")

    assert response.status_code == 401


def test_get_storage_status_returns_503_when_disk_read_fails(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    with patch(
        "app.services.storage_service.shutil.disk_usage",
        side_effect=OSError("unavailable"),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/system/storage",
            headers=superuser_token_headers,
        )

    assert response.status_code == 503
    assert response.json()["message"] == "Storage status is unavailable"


def test_get_storage_status_keeps_partial_results(client, superuser_token_headers):
    with patch(
        "app.services.storage_service.shutil.disk_usage",
        side_effect=[OSError(), SimpleNamespace(total=10000, free=2000)],
    ):
        response = client.get(
            f"{settings.API_V1_STR}/system/storage", headers=superuser_token_headers
        )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "warning"
    assert data["filesystems"][0]["available"] is False
    assert data["filesystems"][0]["free_bytes"] is None


def test_get_storage_status_uses_unrounded_threshold(client, superuser_token_headers):
    with patch(
        "app.services.storage_service.shutil.disk_usage",
        return_value=SimpleNamespace(total=100000, free=20001),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/system/storage", headers=superuser_token_headers
        )
    data = response.json()["data"]
    assert data["filesystems"][0]["used_percent"] == 80.0
    assert data["status"] == "healthy"
