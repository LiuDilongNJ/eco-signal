from __future__ import annotations

from sqlmodel import Session

from app.models.network import NetworkNode
from app.repositories.network_repository import network_repository
from app.schemas.network import NodeStats


def test_upsert_create_and_update(db: Session) -> None:
    created = network_repository.upsert(
        db,
        app_url="https://repo-node.example",
        name="Repo Node",
        latitude=1.1,
        longitude=2.2,
        is_local=False,
        shared=True,
        stats=NodeStats(users=1, projects=2),
    )
    assert created.node_id is not None
    assert created.name == "Repo Node"
    assert created.stat_users == 1

    updated = network_repository.upsert(
        db,
        app_url="https://repo-node.example",
        name="Repo Node Updated",
        latitude=3.3,
        longitude=4.4,
        is_local=False,
        shared=False,
        stats=NodeStats(users=9, projects=8),
    )
    assert updated.node_id == created.node_id
    assert updated.name == "Repo Node Updated"
    assert updated.stat_users == 9
    assert updated.stat_projects == 8


def test_upsert_updates_is_local_flag(db: Session) -> None:
    network_repository.upsert(
        db,
        app_url="https://repo-role-change.example",
        name="Remote First",
        latitude=None,
        longitude=None,
        is_local=False,
        shared=False,
        stats=NodeStats(),
    )

    updated = network_repository.upsert(
        db,
        app_url="https://repo-role-change.example",
        name="Local Later",
        latitude=None,
        longitude=None,
        is_local=True,
        shared=True,
        stats=NodeStats(),
    )

    assert updated.is_local is True
    assert updated.shared is True


def test_getters_and_ordering(db: Session) -> None:
    local = network_repository.upsert(
        db,
        app_url="https://repo-local.example",
        name="A Local",
        latitude=None,
        longitude=None,
        is_local=True,
        shared=True,
        stats=NodeStats(),
    )
    remote = network_repository.upsert(
        db,
        app_url="https://repo-remote.example",
        name="B Remote",
        latitude=None,
        longitude=None,
        is_local=False,
        shared=False,
        stats=NodeStats(),
    )

    rows = network_repository.get_all(db)
    assert rows[0].is_local is True
    assert rows[0].node_id == local.node_id
    assert network_repository.get_by_url(db, "https://repo-remote.example").node_id == remote.node_id  # type: ignore[union-attr]
    assert network_repository.get_by_id(db, local.node_id).app_url == "https://repo-local.example"  # type: ignore[union-attr]


def test_get_public_nodes_filters_hidden_rows(db: Session) -> None:
    network_repository.upsert(
        db,
        app_url="https://repo-public-local.example",
        name="Public Local",
        latitude=None,
        longitude=None,
        is_local=True,
        shared=True,
        stats=NodeStats(),
    )
    network_repository.upsert(
        db,
        app_url="https://repo-public-remote.example",
        name="Public Remote",
        latitude=None,
        longitude=None,
        is_local=False,
        shared=True,
        stats=NodeStats(),
    )
    network_repository.upsert(
        db,
        app_url="https://repo-hidden-remote.example",
        name="Hidden Remote",
        latitude=None,
        longitude=None,
        is_local=False,
        shared=False,
        stats=NodeStats(),
    )

    rows = network_repository.get_public_nodes(db)

    assert [row.app_url for row in rows] == [
        "https://repo-public-local.example",
        "https://repo-public-remote.example",
    ]


def test_delete_remote_nodes_and_delete_by_id(db: Session) -> None:
    local = NetworkNode(app_url="https://repo-del-local.example", name="DL", is_local=True, shared=True)
    remote_a = NetworkNode(app_url="https://repo-del-a.example", name="DA", is_local=False, shared=True)
    remote_b = NetworkNode(app_url="https://repo-del-b.example", name="DB", is_local=False, shared=False)
    db.add(local)
    db.add(remote_a)
    db.add(remote_b)
    db.commit()
    db.refresh(local)
    db.refresh(remote_a)
    db.refresh(remote_b)

    deleted_count = network_repository.delete_remote_nodes(db)
    assert deleted_count >= 2
    assert network_repository.get_by_url(db, "https://repo-del-local.example") is not None
    assert network_repository.get_by_url(db, "https://repo-del-a.example") is None

    temp = NetworkNode(app_url="https://repo-delete-id.example", name="Temp", is_local=False, shared=True)
    db.add(temp)
    db.commit()
    db.refresh(temp)
    deleted = network_repository.delete_by_id(db, temp.node_id)
    assert deleted is not None
    assert network_repository.get_by_id(db, temp.node_id) is None
