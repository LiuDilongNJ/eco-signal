from __future__ import annotations

import re
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app.core.config import settings
from app.models.network import NetworkNode
from app.models.system import Setting
from app.services import network_service


def _upsert_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        row = Setting(name=key, value=value)
    else:
        row.value = value
    db.add(row)
    db.commit()


def test_get_nodes_returns_shared_local_row_after_settings_save(
    client: TestClient, db: Session
) -> None:
    """GET /network-nodes should return the persisted shared local node row."""
    network_service.update_network_settings(
        db,
        network_service.NetworkSettingsUpdate(
            server_name="Local Test Node",
            app_url="https://local.example",
            host_url="https://local.example",
            latitude=10.123,
            longitude=20.456,
            shared=True,
        ),
    )

    r = client.get(f"{settings.API_V1_STR}/network-nodes")
    assert r.status_code == 200
    payload = r.json()
    assert payload["code"] == 0
    data = payload["data"]
    local_nodes = [n for n in data if n["is_local"] is True]
    assert len(local_nodes) == 1

    local = local_nodes[0]
    assert local["name"] == "Local Test Node"
    assert local["app_url"] == "https://local.example"
    assert local["latitude"] == 10.123
    assert local["longitude"] == 20.456
    assert local["shared"] is True


def test_network_urls_are_validated_and_private_http_is_supported(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    invalid_settings = client.put(
        f"{settings.API_V1_STR}/network-settings",
        headers=superuser_token_headers,
        json={"app_url": "file:///tmp/app", "host_url": "https://host.example"},
    )
    assert invalid_settings.status_code == 422

    invalid_registration = client.post(
        f"{settings.API_V1_STR}/network-nodes",
        json={"app_url": "//child.example", "name": "Invalid Child"},
    )
    assert invalid_registration.status_code == 422

    normalized = client.put(
        f"{settings.API_V1_STR}/network-settings",
        headers=superuser_token_headers,
        json={
            "server_name": "Private Node",
            "app_url": "  http://192.168.1.20:8080  ",
            "host_url": "",
        },
    )
    assert normalized.status_code == 200
    assert normalized.json()["data"]["app_url"] == "http://192.168.1.20:8080"
    assert normalized.json()["data"]["host_url"] == ""

def test_register_requires_signature_when_secret_configured(
    client: TestClient, db: Session
) -> None:
    """POST /network-nodes should reject unsigned requests when secret exists."""
    secret = "test-secret-123"
    _upsert_setting(db, "network_federation_secret", secret)

    body = {
        "app_url": "https://child.example",
        "name": "Child Node",
        "latitude": 1.0,
        "longitude": 2.0,
        "stats": {"users": 1},
    }

    r = client.post(f"{settings.API_V1_STR}/network-nodes", json=body)
    assert r.status_code == 401


def test_register_accepts_valid_hmac_signature(client: TestClient, db: Session) -> None:
    """POST /network-nodes should accept valid signed request."""
    secret = "test-secret-456"
    app_url = "https://child-valid.example"
    _upsert_setting(db, "network_federation_secret", secret)

    timestamp = str(int(time.time()))
    signature = network_service._compute_signature(secret, timestamp, app_url)

    body = {
        "app_url": app_url,
        "name": "Signed Child",
        "latitude": 30.1,
        "longitude": 120.2,
        "stats": {"users": 3, "projects": 2},
    }
    headers = {
        "X-Federation-Timestamp": timestamp,
        "X-Federation-Signature": signature,
    }

    r = client.post(f"{settings.API_V1_STR}/network-nodes", json=body, headers=headers)
    assert r.status_code == 200
    payload = r.json()
    assert payload["code"] == 0
    assert isinstance(payload["data"], list)
    assert any(item["app_url"] == app_url for item in payload["data"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude", -90.1),
        ("latitude", 90.1),
        ("longitude", -180.1),
        ("longitude", 180.1),
    ],
)
def test_register_node_rejects_out_of_range_coordinates(
    client: TestClient, field: str, value: float
) -> None:
    """Node registration rejects coordinates outside WGS84 bounds."""
    body = {
        "app_url": "https://out-of-range.example",
        "name": "Out of Range Node",
        "latitude": 30.0,
        "longitude": 120.0,
    }
    body[field] = value

    response = client.post(f"{settings.API_V1_STR}/network-nodes", json=body)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [(-180.0, -90.0), (180.0, 90.0)],
)
def test_register_node_accepts_coordinate_boundaries(
    client: TestClient, longitude: float, latitude: float
) -> None:
    """Node registration accepts inclusive WGS84 coordinate boundaries."""
    response = client.post(
        f"{settings.API_V1_STR}/network-nodes",
        json={
            "app_url": f"https://boundary-{latitude}.example",
            "name": "Boundary Node",
            "latitude": latitude,
            "longitude": longitude,
        },
    )

    assert response.status_code == 200


def test_generate_secret_admin_only(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    """Only admin can generate federation secret."""
    forbidden = client.post(
        f"{settings.API_V1_STR}/network-secret-rotations",
        headers=normal_user_token_headers,
    )
    assert forbidden.status_code == 403

    ok = client.post(
        f"{settings.API_V1_STR}/network-secret-rotations",
        headers=superuser_token_headers,
    )
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["code"] == 0
    assert payload["data"]["federation_secret"]
    assert db.exec(select(NetworkNode).where(NetworkNode.is_local == True)).first() is None  # noqa: E712
    # token_hex(32) -> 64 hex chars
    assert len(payload["data"]["federation_secret"]) == 64


def test_get_local_stats_endpoint(client: TestClient) -> None:
    """GET /network-statistics should return real-time stats payload."""
    r = client.get(f"{settings.API_V1_STR}/network-statistics")
    assert r.status_code == 200
    payload = r.json()
    assert payload["code"] == 0
    assert "users" in payload["data"]
    assert "projects" in payload["data"]


def test_admin_settings_and_sync_endpoints(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """Admin can read/update settings and call manual sync."""
    get_r = client.get(
        f"{settings.API_V1_STR}/network-settings",
        headers=superuser_token_headers,
    )
    assert get_r.status_code == 200
    assert get_r.json()["code"] == 0

    update_r = client.put(
        f"{settings.API_V1_STR}/network-settings",
        headers=superuser_token_headers,
        json={
            "server_name": "Admin Updated Node",
            "app_url": "https://local-admin.example",
            "host_url": "https://local-admin.example",
            "latitude": 30.0,
            "longitude": 120.0,
            "shared": True,
        },
    )
    assert update_r.status_code == 200
    assert update_r.json()["code"] == 0

    sync_r = client.post(
        f"{settings.API_V1_STR}/network-node-sync-jobs",
        headers=superuser_token_headers,
    )
    assert sync_r.status_code == 200
    assert sync_r.json()["code"] == 0

    nodes_r = client.get(f"{settings.API_V1_STR}/network-nodes")
    assert nodes_r.status_code == 200
    nodes = nodes_r.json()["data"]
    local = next((n for n in nodes if n["is_local"]), None)
    assert local is not None
    # Time format must be: YYYY-MM-DD HH:mm:ss
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", local["last_synced_at"])


@pytest.mark.parametrize(
    "payload",
    [
        {"server_name": "Only Name"},
        {"app_url": "https://only-url.example"},
        {"server_name": "", "app_url": ""},
    ],
)
def test_initial_network_settings_require_server_name_and_app_url(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    payload: dict[str, str],
) -> None:
    """Initial local node creation requires both identity fields."""
    response = client.put(
        f"{settings.API_V1_STR}/network-settings",
        headers=superuser_token_headers,
        json=payload,
    )

    assert response.status_code == 422
    assert "required" in response.json()["message"].lower()


def test_initial_network_settings_create_local_node_with_identity_fields(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """A valid initial configuration persists the local node."""
    response = client.put(
        f"{settings.API_V1_STR}/network-settings",
        headers=superuser_token_headers,
        json={"server_name": "Initial Node", "app_url": "https://initial.example"},
    )

    assert response.status_code == 200
    node = db.exec(select(NetworkNode).where(NetworkNode.is_local == True)).first()  # noqa: E712
    assert node is not None
    assert node.name == "Initial Node"
    assert node.app_url == "https://initial.example"


def test_existing_local_node_allows_partial_server_name_update(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """Existing local nodes retain partial update behavior."""
    network_service.update_network_settings(
        db,
        network_service.NetworkSettingsUpdate(
            server_name="Before Update", app_url="https://partial.example"
        ),
    )

    response = client.put(
        f"{settings.API_V1_STR}/network-settings",
        headers=superuser_token_headers,
        json={"server_name": "After Update"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["server_name"] == "After Update"
    assert data["app_url"] == "https://partial.example"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude", -90.1),
        ("latitude", 90.1),
        ("longitude", -180.1),
        ("longitude", 180.1),
    ],
)
def test_update_network_settings_rejects_out_of_range_coordinates(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    field: str,
    value: float,
) -> None:
    """Network settings reject coordinates outside WGS84 bounds."""
    response = client.put(
        f"{settings.API_V1_STR}/network-settings",
        headers=superuser_token_headers,
        json={field: value},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [(-180.0, -90.0), (180.0, 90.0)],
)
def test_update_network_settings_accepts_coordinate_boundaries(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    longitude: float,
    latitude: float,
) -> None:
    """Network settings accept inclusive WGS84 coordinate boundaries."""
    response = client.put(
        f"{settings.API_V1_STR}/network-settings",
        headers=superuser_token_headers,
        json={
            "server_name": "Boundary Node",
            "app_url": f"https://local-boundary-{latitude}.example",
            "host_url": f"https://local-boundary-{latitude}.example",
            "longitude": longitude,
            "latitude": latitude,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["longitude"] == longitude
    assert response.json()["data"]["latitude"] == latitude


@pytest.mark.parametrize(
    "payload",
    [
        {"shared": True},
        {"shared": True, "latitude": 30.0},
        {"shared": True, "longitude": 120.0},
    ],
)
def test_public_network_settings_require_both_coordinates(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    payload: dict[str, bool | float],
) -> None:
    """Public nodes must provide both coordinates."""
    response = client.put(
        f"{settings.API_V1_STR}/network-settings",
        headers=superuser_token_headers,
        json={
            "server_name": "Public Node",
            "app_url": "https://public-node.example",
            **payload,
        },
    )

    assert response.status_code == 422
    assert "latitude and longitude" in response.json()["message"]


def test_public_network_settings_reject_coordinate_removal(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """Public nodes cannot clear either coordinate through a partial update."""
    network_service.update_network_settings(
        db,
        network_service.NetworkSettingsUpdate(
            server_name="Public Node",
            app_url="https://public-node.example",
            latitude=30.0,
            longitude=120.0,
            shared=True,
        ),
    )

    response = client.put(
        f"{settings.API_V1_STR}/network-settings",
        headers=superuser_token_headers,
        json={"latitude": None},
    )

    assert response.status_code == 422


def test_delete_node_endpoint_variants(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """Delete endpoint should handle not found/local/remote cases correctly."""
    not_found = client.delete(
        f"{settings.API_V1_STR}/network-nodes/999999",
        headers=superuser_token_headers,
    )
    assert not_found.status_code == 404

    local_node = NetworkNode(
        app_url="https://local-delete.example",
        name="Local Delete",
        is_local=True,
        shared=True,
    )
    db.add(local_node)
    db.commit()
    db.refresh(local_node)

    cannot_delete_local = client.delete(
        f"{settings.API_V1_STR}/network-nodes/{local_node.node_id}",
        headers=superuser_token_headers,
    )
    assert cannot_delete_local.status_code == 400

    remote_node = NetworkNode(
        app_url="https://remote-delete.example",
        name="Remote Delete",
        is_local=False,
        shared=True,
    )
    db.add(remote_node)
    db.commit()
    db.refresh(remote_node)

    delete_remote = client.delete(
        f"{settings.API_V1_STR}/network-nodes/{remote_node.node_id}",
        headers=superuser_token_headers,
    )
    assert delete_remote.status_code == 200
    assert delete_remote.json()["code"] == 0


def test_get_nodes_hides_local_node_when_shared_disabled(client: TestClient, db: Session) -> None:
    network_service.update_network_settings(
        db,
        network_service.NetworkSettingsUpdate(
            server_name="Private Local Node",
            app_url="https://private-local.example",
            host_url="https://private-local.example",
            shared=False,
        ),
    )

    db.add(
        NetworkNode(
            app_url="https://remote-public.example",
            name="Remote Public",
            is_local=False,
            shared=True,
        )
    )
    db.commit()

    r = client.get(f"{settings.API_V1_STR}/network-nodes")

    assert r.status_code == 200
    data = r.json()["data"]
    assert all(node["is_local"] is False for node in data)
    assert any(node["app_url"] == "https://remote-public.example" for node in data)


def test_register_with_shared_false_keeps_remote_node_hidden(client: TestClient, db: Session) -> None:
    secret = "test-secret-hide"
    app_url = "https://child-remove.example"
    _upsert_setting(db, "network_federation_secret", secret)
    db.add(NetworkNode(app_url=app_url, name="Child Remove", is_local=False, shared=True))
    db.commit()

    timestamp = str(int(time.time()))
    signature = network_service._compute_signature(secret, timestamp, app_url)
    headers = {
        "X-Federation-Timestamp": timestamp,
        "X-Federation-Signature": signature,
    }

    r = client.post(
        f"{settings.API_V1_STR}/network-nodes",
        json={"app_url": app_url, "name": "Child Remove", "shared": False},
        headers=headers,
    )

    assert r.status_code == 200
    stored = db.exec(select(NetworkNode).where(NetworkNode.app_url == app_url)).first()
    assert stored is not None
    assert stored.shared is False
    assert all(node["app_url"] != app_url for node in r.json()["data"])


def test_register_with_shared_false_requires_signature_when_secret_configured(
    client: TestClient, db: Session
) -> None:
    _upsert_setting(db, "network_federation_secret", "test-secret-hide-required")

    r = client.post(
        f"{settings.API_V1_STR}/network-nodes",
        json={
            "app_url": "https://child-remove-noauth.example",
            "name": "Child Remove",
            "shared": False,
        },
    )

    assert r.status_code == 401
