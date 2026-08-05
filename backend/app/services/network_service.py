import hashlib
import hmac
import logging
import secrets
import time
from datetime import UTC, datetime

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlmodel import Session

from app.models import (
    Annotation,
    Collection,
    Media,
    Project,
    Site,
    User,
)
from app.models.network import NetworkNode
from app.models.system import Setting
from app.repositories.network_repository import network_repository
from app.schemas.network import (
    NetworkNodePublic,
    NetworkSettings,
    NetworkSettingsUpdate,
    NodeRegistration,
    NodeStats,
    SyncResult,
)

logger = logging.getLogger(__name__)

# Setting table keys

_KEY_HOST_URL = "network_host_url"
_KEY_FEDERATION_SECRET = "network_federation_secret"

# HTTP timeout (seconds) for cross-instance calls
_HTTP_TIMEOUT = 15.0

# Acceptable clock skew for HMAC timestamp validation (seconds)
_TIMESTAMP_TOLERANCE = 300  # ±5 minutes


# Setting table helpers

def _read_setting(session: Session, key: str, default: str = "") -> str:
    row = session.get(Setting, key)
    return row.value if row else default


def _write_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        row = Setting(name=key, value=value)
    else:
        row.value = value
    session.add(row)


# HMAC signing and verification

def _compute_signature(secret: str, timestamp: str, app_url: str) -> str:
    """
    Compute HMAC-SHA256 signature for a federation request.

    Message format: "{timestamp}:{app_url}"
    The secret is never transmitted; only the signature is sent.
    """
    message = f"{timestamp}:{app_url}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_federation_request(
    session: Session,
    timestamp_str: str | None,
    signature: str | None,
    app_url: str,
) -> bool:
    """
    Verify an incoming federation request (POST /network-nodes).

    Rules:
    - If no federation_secret is configured on this HOST, log a warning
      and allow the request (graceful degradation for fresh installs).
    - If a secret IS configured, both timestamp and signature headers are
      required and must be valid.
    - Timestamp must be within ±5 minutes of server time (anti-replay).
    - Signature must match HMAC-SHA256(secret, "{timestamp}:{app_url}").
    """
    secret = _read_setting(session, _KEY_FEDERATION_SECRET)

    if not secret:
        logger.warning(
            "network_federation_secret is not configured – "
            "registration from %s accepted without signature verification. "
            "Set a federation secret to enforce request signing.",
            app_url,
        )
        return True

    if not timestamp_str or not signature:
        logger.warning(
            "Federation request from %s rejected: missing signature headers.",
            app_url,
        )
        return False

    # Validate timestamp (anti-replay)
    try:
        timestamp = int(timestamp_str)
    except ValueError:
        return False

    if abs(int(time.time()) - timestamp) > _TIMESTAMP_TOLERANCE:
        logger.warning(
            "Federation request from %s rejected: timestamp %s is outside "
            "the ±%d second tolerance window.",
            app_url,
            timestamp_str,
            _TIMESTAMP_TOLERANCE,
        )
        return False

    # Constant-time comparison to prevent timing attacks
    expected = _compute_signature(secret, timestamp_str, app_url)
    return hmac.compare_digest(expected, signature)


def generate_federation_secret() -> str:
    """Generate a cryptographically secure random federation secret."""
    return secrets.token_hex(32)  # 256-bit secret, hex-encoded


# Federation settings

def get_network_settings(session: Session) -> NetworkSettings:
    """Read federation settings from the local node row plus setting table."""
    local_node = network_repository.get_local_node(session)
    if local_node is None:
        logger.warning(
            "Federation settings have no local network_node row; returning initialization defaults"
        )
    return NetworkSettings(
        server_name=local_node.name if local_node else "",
        app_url=local_node.app_url if local_node else "",
        host_url=_read_setting(session, _KEY_HOST_URL),
        latitude=local_node.latitude if local_node else None,
        longitude=local_node.longitude if local_node else None,
        shared=local_node.shared if local_node else False,
        federation_secret=_read_setting(session, _KEY_FEDERATION_SECRET),
    )


def update_network_settings(
    session: Session, data: NetworkSettingsUpdate
) -> NetworkSettings:
    """
    Persist updated federation settings, then:
    1. Refresh the local node row with latest config + real-time stats.
    2. If host_url is set (child node), sync the visible/hidden state to HOST.
    """
    current = get_network_settings(session)
    fields = data.model_fields_set
    next_cfg = NetworkSettings(
        server_name=(data.server_name or "") if "server_name" in fields else current.server_name,
        app_url=(data.app_url or "") if "app_url" in fields else current.app_url,
        host_url=(data.host_url or "") if "host_url" in fields else current.host_url,
        latitude=data.latitude if "latitude" in fields else current.latitude,
        longitude=data.longitude if "longitude" in fields else current.longitude,
        shared=data.shared if "shared" in fields and data.shared is not None else current.shared,
        federation_secret=(
            (data.federation_secret or "")
            if "federation_secret" in fields
            else current.federation_secret
        ),
    )

    if "host_url" in fields:
        _write_setting(session, _KEY_HOST_URL, data.host_url or "")
    if "federation_secret" in fields:
        _write_setting(session, _KEY_FEDERATION_SECRET, data.federation_secret or "")

    session.commit()

    # Always refresh the local node row
    _ensure_local_node(session, next_cfg)
    current = get_network_settings(session)

    # Keep the HOST registry in sync whenever this child node saves federation settings.
    if current.host_url and current.host_url != current.app_url:
        try:
            register_to_host(session, current)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not sync HOST registration on settings save: %s", exc)

    return current


# Local statistics

def get_local_stats(session: Session) -> NodeStats:
    """
    Compute real-time aggregate counts for the local instance.
    These numbers are instance-wide (not filtered by permission).
    """
    users = session.scalar(select(func.count(User.user_id))) or 0
    projects = session.scalar(select(func.count(Project.project_id))) or 0
    collections = session.scalar(select(func.count(Collection.collection_id))) or 0
    audios = session.scalar(
        select(func.count(Media.media_id)).where(Media.media_type == "audio")
    ) or 0
    photos = session.scalar(
        select(func.count(Media.media_id)).where(Media.media_type == "photo")
    ) or 0
    videos = session.scalar(
        select(func.count(Media.media_id)).where(Media.media_type == "video")
    ) or 0
    annotations = session.scalar(select(func.count(Annotation.annotation_id))) or 0
    sites = session.scalar(select(func.count(Site.site_id))) or 0

    return NodeStats(
        users=users,
        projects=projects,
        collections=collections,
        audios=audios,
        photos=photos,
        videos=videos,
        annotations=annotations,
        sites=sites,
    )


# Public node list

def _node_to_public(
    node: NetworkNode, local_stats: NodeStats | None
) -> NetworkNodePublic:
    """Convert a NetworkNode ORM object to a public response schema."""
    stats = (
        local_stats
        if node.is_local and local_stats is not None
        else NodeStats(
            users=node.stat_users,
            projects=node.stat_projects,
            collections=node.stat_collections,
            audios=node.stat_audios,
            photos=node.stat_photos,
            videos=node.stat_videos,
            annotations=node.stat_annotations,
            sites=node.stat_sites,
        )
    )
    return NetworkNodePublic(
        id=node.node_id,
        name=node.name,
        app_url=node.app_url,
        latitude=node.latitude,
        longitude=node.longitude,
        is_local=node.is_local,
        shared=node.shared,
        stats=stats,
        last_synced_at=node.last_synced_at,
    )


def get_public_nodes(session: Session) -> list[NetworkNodePublic]:
    """
    Return discoverable nodes as response objects.
    The shared flag is the single source of truth for public visibility.
    """
    local_stats = get_local_stats(session)
    nodes = network_repository.get_public_nodes(session)
    return [_node_to_public(n, local_stats if n.is_local else None) for n in nodes]


# HOST role: receive child node registration

def handle_registration(
    session: Session, registration: NodeRegistration
) -> list[NetworkNodePublic]:
    """
    Called when this instance acts as HOST.
    Upserts the registering node and returns the current public node list.
    Hidden child nodes are retained locally with shared=false.
    """

    stats = registration.stats or NodeStats()
    network_repository.upsert(
        session,
        app_url=registration.app_url,
        name=registration.name,
        latitude=registration.latitude,
        longitude=registration.longitude,
        is_local=False,
        shared=registration.shared,
        stats=stats,
    )
    return get_public_nodes(session)


# Child role: sync from HOST

def sync_from_host(session: Session) -> SyncResult:
    """
    Fetch the full node list from the configured HOST and update local cache.
    If no host_url is configured (this instance IS the HOST), skip silently.
    """
    cfg = get_network_settings(session)
    if not cfg.host_url or cfg.host_url == cfg.app_url:
        return SyncResult(synced=0, message="host node – sync not needed")

    url = cfg.host_url.rstrip("/") + "/api/v1/network-nodes"
    try:
        response = httpx.get(url, timeout=_HTTP_TIMEOUT)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to reach HOST at %s: %s", url, exc)
        return SyncResult(synced=0, message=f"unreachable: {exc}")

    payload = response.json()
    # Expect {"code": 0, "data": [...]} or a plain list
    node_list = payload.get("data", payload) if isinstance(payload, dict) else payload

    # Remove all remote nodes, then re-insert from HOST response
    network_repository.delete_remote_nodes(session)

    count = 0
    for item in node_list:
        app_url = item.get("app_url", "")
        if not app_url:
            continue
        # Skip the row for this instance itself (it already exists as is_local)
        if app_url == cfg.app_url:
            continue
        raw_stats = item.get("stats") or {}
        stats = NodeStats(**raw_stats) if raw_stats else NodeStats()
        network_repository.upsert(
            session,
            app_url=app_url,
            name=item.get("name", app_url),
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
            is_local=False,
            shared=bool(item.get("shared", True)),
            stats=stats,
        )
        count += 1

    return SyncResult(synced=count, message="ok")


# Child role: register with HOST

def register_to_host(session: Session, cfg: NetworkSettings | None = None) -> SyncResult:
    """
    POST this instance's info and shared state to the HOST registration endpoint.
    Includes HMAC-SHA256 signature headers if federation_secret is configured.
    On success, applies the returned node list as a local sync.
    """
    if cfg is None:
        cfg = get_network_settings(session)

    if not cfg.host_url or not cfg.app_url or cfg.host_url == cfg.app_url:
        return SyncResult(synced=0, message="not a child node")

    stats = get_local_stats(session)
    payload = NodeRegistration(
        app_url=cfg.app_url,
        name=cfg.server_name or cfg.app_url,
        latitude=cfg.latitude,
        longitude=cfg.longitude,
        stats=stats,
        shared=cfg.shared,
    ).model_dump()

    # Build HMAC signature headers
    headers: dict[str, str] = {}
    if cfg.federation_secret:
        timestamp_str = str(int(time.time()))
        signature = _compute_signature(cfg.federation_secret, timestamp_str, cfg.app_url)
        headers["X-Federation-Timestamp"] = timestamp_str
        headers["X-Federation-Signature"] = signature

    url = cfg.host_url.rstrip("/") + "/api/v1/network-nodes"
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=_HTTP_TIMEOUT)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to register with HOST at %s: %s", url, exc)
        return SyncResult(synced=0, message=f"unreachable: {exc}")

    body = response.json()
    node_list = body.get("data", body) if isinstance(body, dict) else body

    # Apply the returned list as a sync
    network_repository.delete_remote_nodes(session)
    count = 0
    for item in node_list:
        app_url = item.get("app_url", "")
        if not app_url or app_url == cfg.app_url:
            continue
        raw_stats = item.get("stats") or {}
        stats_obj = NodeStats(**raw_stats) if raw_stats else NodeStats()
        network_repository.upsert(
            session,
            app_url=app_url,
            name=item.get("name", app_url),
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
            is_local=False,
            shared=bool(item.get("shared", True)),
            stats=stats_obj,
        )
        count += 1

    return SyncResult(synced=count, message="ok")


# Internal helpers

def _ensure_local_node(
    session: Session,
    cfg: NetworkSettings,
    stats: NodeStats | None = None,
) -> NetworkNode | None:
    """
    Create or update the local node row.
    If app_url is empty, does nothing and returns None.
    """
    local_node = network_repository.get_local_node(session)
    if not cfg.app_url:
        if local_node is not None:
            session.delete(local_node)
            session.commit()
        return None

    if stats is None:
        stats = get_local_stats(session)

    if local_node is not None and local_node.app_url != cfg.app_url:
        collision = network_repository.get_by_url(session, cfg.app_url)
        if collision is not None and collision.node_id != local_node.node_id:
            session.delete(collision)
            session.commit()

        local_node.app_url = cfg.app_url
        local_node.name = cfg.server_name or cfg.app_url
        local_node.latitude = cfg.latitude
        local_node.longitude = cfg.longitude
        local_node.is_local = True
        local_node.shared = cfg.shared
        local_node.stat_users = stats.users
        local_node.stat_projects = stats.projects
        local_node.stat_collections = stats.collections
        local_node.stat_audios = stats.audios
        local_node.stat_photos = stats.photos
        local_node.stat_videos = stats.videos
        local_node.stat_annotations = stats.annotations
        local_node.stat_sites = stats.sites
        local_node.last_synced_at = datetime.now(UTC)
        session.add(local_node)
        session.commit()
        session.refresh(local_node)
        return local_node

    return network_repository.upsert(
        session,
        app_url=cfg.app_url,
        name=cfg.server_name or cfg.app_url,
        latitude=cfg.latitude,
        longitude=cfg.longitude,
        is_local=True,
        shared=cfg.shared,
        stats=stats,
    )


def delete_node(session: Session, node_id: int) -> None:
    """Delete a network node by ID. Raises HTTPException for not-found or local node."""
    node = network_repository.get_by_id(session, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.is_local:
        raise HTTPException(status_code=400, detail="Cannot delete the local node")
    network_repository.delete_by_id(session, node_id)
