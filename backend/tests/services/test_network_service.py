from __future__ import annotations

import time

import pytest
from sqlmodel import Session, select

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


def test_verify_federation_request_returns_true_without_secret(db: Session) -> None:
    """Without configured secret, verification should gracefully allow request."""
    ok = network_service.verify_federation_request(
        db,
        timestamp_str=None,
        signature=None,
        app_url="https://child.example",
    )
    assert ok is True


def test_verify_federation_request_rejects_missing_headers_when_secret_set(
    db: Session,
) -> None:
    """With configured secret, missing signature headers should fail."""
    _upsert_setting(db, "network_federation_secret", "unit-secret")

    ok = network_service.verify_federation_request(
        db,
        timestamp_str=None,
        signature=None,
        app_url="https://child.example",
    )
    assert ok is False


def test_verify_federation_request_accepts_valid_signature(db: Session) -> None:
    """Valid timestamp + HMAC should pass verification."""
    secret = "unit-secret-valid"
    app_url = "https://child-valid.example"
    _upsert_setting(db, "network_federation_secret", secret)

    timestamp = str(int(time.time()))
    signature = network_service._compute_signature(secret, timestamp, app_url)

    ok = network_service.verify_federation_request(
        db,
        timestamp_str=timestamp,
        signature=signature,
        app_url=app_url,
    )
    assert ok is True


def test_verify_federation_request_rejects_expired_timestamp(db: Session) -> None:
    """Timestamp outside tolerance window should fail verification."""
    secret = "unit-secret-expired"
    app_url = "https://child-expired.example"
    _upsert_setting(db, "network_federation_secret", secret)

    old_timestamp = str(int(time.time()) - 3600)
    signature = network_service._compute_signature(secret, old_timestamp, app_url)

    ok = network_service.verify_federation_request(
        db,
        timestamp_str=old_timestamp,
        signature=signature,
        app_url=app_url,
    )
    assert ok is False


def test_verify_federation_request_rejects_invalid_timestamp(db: Session) -> None:
    _upsert_setting(db, "network_federation_secret", "unit-secret-invalid-ts")
    ok = network_service.verify_federation_request(
        db,
        timestamp_str="not-an-int",
        signature="abc",
        app_url="https://child-invalid-ts.example",
    )
    assert ok is False


def test_get_network_settings_warns_and_returns_defaults_without_local_node(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        network_service.logger,
        "warning",
        lambda message, *_args: warnings.append(message),
    )

    result = network_service.get_network_settings(db)

    assert result.app_url == ""
    assert result.server_name == ""
    assert any("no local network_node row" in message for message in warnings)


def test_update_network_settings_explicit_null_clears_coordinate_and_omission_preserves_other_values(
    db: Session,
) -> None:
    network_service.update_network_settings(
        db,
        network_service.NetworkSettingsUpdate(
            server_name="Settings node",
            app_url="https://settings-node.example",
            host_url="https://settings-node.example",
            latitude=10.5,
            longitude=20.5,
            federation_secret="secret-to-clear",
        ),
    )

    result = network_service.update_network_settings(
        db,
        network_service.NetworkSettingsUpdate(latitude=None, federation_secret=""),
    )

    assert result.latitude is None
    assert result.longitude == 20.5
    assert result.server_name == "Settings node"
    assert result.federation_secret == ""

def test_get_public_nodes_uses_local_stats_when_local_row_exists(db: Session) -> None:
    _upsert_setting(db, "network_host_url", "https://local-existing.example")
    network_service.update_network_settings(
        db,
        network_service.NetworkSettingsUpdate(
            server_name="Local Existing",
            app_url="https://local-existing.example",
            host_url="https://local-existing.example",
            latitude=30.0,
            longitude=120.0,
            shared=True,
        ),
    )
    result = network_service.get_public_nodes(db)
    assert any(n.is_local and n.app_url == "https://local-existing.example" for n in result)


def test_sync_from_host_returns_early_for_host_mode(db: Session) -> None:
    network_service.update_network_settings(
        db,
        network_service.NetworkSettingsUpdate(
            server_name="Host Self",
            app_url="https://host-self.example",
            host_url="https://host-self.example",
        ),
    )
    result = network_service.sync_from_host(db)
    assert result.message == "host node – sync not needed"


def test_sync_from_host_handles_unreachable_host(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    network_service.update_network_settings(
        db,
        network_service.NetworkSettingsUpdate(
            server_name="Unreachable Child",
            app_url="https://child-unreachable.example",
            host_url="https://host-unreachable.example",
        ),
    )

    def _boom(*_args, **_kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(network_service.httpx, "get", _boom)
    result = network_service.sync_from_host(db)
    assert result.synced == 0
    assert "unreachable" in result.message


def test_sync_from_host_success(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    network_service.update_network_settings(
        db,
        network_service.NetworkSettingsUpdate(
            server_name="Sync Child",
            app_url="https://child-sync.example",
            host_url="https://host-sync.example",
        ),
    )
    db.add(
        NetworkNode(
            app_url="https://old-remote.example",
            name="Old Remote",
            is_local=False,
            shared=True,
        )
    )
    db.commit()

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "data": [
                    {"app_url": "https://child-sync.example", "name": "Self"},
                    {
                        "app_url": "https://new-remote.example",
                        "name": "New Remote",
                        "stats": {"users": 2, "projects": 1},
                    },
                ]
            }

    monkeypatch.setattr(network_service.httpx, "get", lambda *args, **kwargs: _Resp())
    result = network_service.sync_from_host(db)
    assert result.synced == 1
    assert db.exec(
        select(NetworkNode).where(
            NetworkNode.app_url == "https://new-remote.example"
        )
    ).first() is not None


def test_register_to_host_not_child_returns_early(db: Session) -> None:
    cfg = network_service.NetworkSettings(
        app_url="https://self.example",
        host_url="https://self.example",
    )
    result = network_service.register_to_host(db, cfg)
    assert result.message == "not a child node"


def test_register_to_host_unreachable(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    cfg = network_service.NetworkSettings(
        app_url="https://child-reg.example",
        host_url="https://host-reg.example",
        shared=True,
    )

    def _boom(*_args, **_kwargs):
        raise RuntimeError("post down")

    monkeypatch.setattr(network_service.httpx, "post", _boom)
    result = network_service.register_to_host(db, cfg)
    assert result.synced == 0
    assert "unreachable" in result.message


def test_register_to_host_posts_hidden_state_when_local_node_not_shared(
    monkeypatch: pytest.MonkeyPatch, db: Session
) -> None:
    cfg = network_service.NetworkSettings(
        app_url="https://child-private.example",
        host_url="https://host-private.example",
        shared=False,
    )
    posted_payloads: list[dict] = []

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"data": []}

    def _post(*_args, **kwargs):
        posted_payloads.append(kwargs["json"])
        return _Resp()

    monkeypatch.setattr(network_service.httpx, "post", _post)

    result = network_service.register_to_host(db, cfg)

    assert result.synced == 0
    assert result.message == "ok"
    assert len(posted_payloads) == 1
    assert posted_payloads[0]["app_url"] == "https://child-private.example"
    assert posted_payloads[0]["name"] == "https://child-private.example"
    assert posted_payloads[0]["shared"] is False
    assert set(posted_payloads[0]["stats"]) == {
        "users",
        "projects",
        "collections",
        "audios",
        "photos",
        "videos",
        "annotations",
        "sites",
    }


def test_register_to_host_success(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    cfg = network_service.NetworkSettings(
        server_name="Child Reg",
        app_url="https://child-reg-ok.example",
        host_url="https://host-reg-ok.example",
        shared=True,
        federation_secret="secret-ok",
    )

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "data": [
                    {"app_url": "https://child-reg-ok.example", "name": "Self"},
                    {
                        "app_url": "https://remote-after-reg.example",
                        "name": "Remote After Reg",
                        "stats": {"users": 5},
                    },
                ]
            }

    monkeypatch.setattr(network_service.httpx, "post", lambda *args, **kwargs: _Resp())
    result = network_service.register_to_host(db, cfg)
    assert result.synced == 1
    assert db.exec(
        select(NetworkNode).where(
            NetworkNode.app_url == "https://remote-after-reg.example"
        )
    ).first() is not None


def test_get_public_nodes_hides_local_node_when_not_shared(db: Session) -> None:
    network_service.update_network_settings(
        db,
        network_service.NetworkSettingsUpdate(
            server_name="Private Local",
            app_url="https://private-local.example",
            host_url="https://private-local.example",
            shared=False,
        ),
    )
    db.add(
        NetworkNode(
            app_url="https://remote-visible.example",
            name="Remote Visible",
            is_local=False,
            shared=True,
        )
    )
    db.commit()

    result = network_service.get_public_nodes(db)

    assert all(not node.is_local for node in result)
    assert any(node.app_url == "https://remote-visible.example" for node in result)


def test_handle_registration_keeps_hidden_remote_node_out_of_public_list(db: Session) -> None:
    result = network_service.handle_registration(
        db,
        network_service.NodeRegistration(
            app_url="https://child-hidden.example",
            name="Hidden Child",
            shared=False,
        ),
    )

    stored = db.exec(
        select(NetworkNode).where(NetworkNode.app_url == "https://child-hidden.example")
    ).first()

    assert stored is not None
    assert stored.shared is False
    assert all(node.app_url != "https://child-hidden.example" for node in result)


def test_update_network_settings_syncs_hidden_registration_when_shared_switched_off(
    monkeypatch: pytest.MonkeyPatch, db: Session
) -> None:
    network_service.update_network_settings(
        db,
        network_service.NetworkSettingsUpdate(
            server_name="Child Shared",
            app_url="https://child-shared.example",
            host_url="https://host-shared.example",
            latitude=30.0,
            longitude=120.0,
            shared=True,
        ),
    )

    calls: list[bool] = []

    def _fake_register(_session: Session, cfg=None):
        calls.append(cfg.shared)
        return network_service.SyncResult(synced=0, message="ok")

    monkeypatch.setattr(network_service, "register_to_host", _fake_register)

    result = network_service.update_network_settings(
        db,
        network_service.NetworkSettingsUpdate(shared=False),
    )

    assert result.shared is False
    assert calls == [False]
