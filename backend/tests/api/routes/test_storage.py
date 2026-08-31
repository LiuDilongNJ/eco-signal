from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


@pytest.mark.parametrize(
    ("used_percent", "expected_status"),
    [
        (69.9, "healthy"),
        (70.0, "warning"),
        (84.9, "warning"),
        (85.0, "critical"),
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
    assert payload["data"] == {
        "path": "/",
        "total_bytes": total,
        "used_bytes": expected_used,
        "free_bytes": free,
        "used_percent": round((expected_used / total) * 100, 1),
        "status": expected_status,
    }


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
    assert response.json()["message"] == "Container storage status is unavailable"
