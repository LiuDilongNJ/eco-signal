"""网络网络 API 路由：公开节点、本实例配置、HOST 注册与同步、统计。 / Network federation: nodes, settings, HOST registration, sync, stats."""
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from app.api.deps import ActiveAdmin, SessionDep
from app.schemas.network import (
    NetworkNodePublic,
    NetworkSettings,
    NetworkSettingsUpdate,
    NodeRegistration,
    NodeStats,
    SyncResult,
)
from app.schemas.response import ApiResponse, api_success
from app.services import network_service

router = APIRouter(tags=["网络 / network"])



@router.get(
    "/network-nodes",
    response_model=ApiResponse[list[NetworkNodePublic]],
    summary="获取网络节点列表 / Get network node list",
)
def get_nodes(session: SessionDep) -> Any:
    """
    获取所有公开网络节点（含缓存统计数据）。本地节点统计为实时查询。
    Get all public network nodes with cached statistics.
    The local node's stats are computed in real time.

    无需身份验证。此接口也作为子节点同步来源。
    No authentication required. Also used by child nodes as sync source.
    """
    nodes = network_service.get_public_nodes(session)
    return api_success(data=nodes)


@router.get(
    "/network-statistics",
    response_model=ApiResponse[NodeStats],
    summary="获取本实例实时统计 / Get local instance real-time stats",
)
def get_local_stats(session: SessionDep) -> Any:
    """
    返回本实例当前各资源数量（用于调试或对外暴露统计数据）。
    Returns real-time resource counts for the local instance.

    无需身份验证。 / No authentication required.
    """
    stats = network_service.get_local_stats(session)
    return api_success(data=stats)


@router.post(
    "/network-nodes",
    response_model=ApiResponse[list[NetworkNodePublic]],
    summary="接受子节点注册或隐藏（HOST 专用）/ Accept child registration or hide request (HOST only)",
)
def register_node(
    session: SessionDep,
    payload: NodeRegistration,
    x_federation_timestamp: str | None = Header(
        default=None,
        alias="X-Federation-Timestamp",
        description="Unix timestamp (seconds) when the request was signed",
    ),
    x_federation_signature: str | None = Header(
        default=None,
        alias="X-Federation-Signature",
        description="HMAC-SHA256(secret, '{timestamp}:{app_url}')",
    ),
) -> Any:
    """
    子节点保存设置时调用此接口，向本实例（HOST）上报自身信息。
    HOST 会把子节点 upsert 到 network_node 表，并按 shared 字段控制是否对外公开。

    Called by a child node when it saves its settings.
    The HOST upserts the child row in network_node and uses the shared flag to
    control whether it appears in the public node list.

    安全机制 / Security:
    若 HOST 配置了 network_federation_secret，则必须提供有效的
    X-Federation-Timestamp 和 X-Federation-Signature 请求头，
    且时间戳须在 ±5 分钟以内（防重放攻击）。
    If network_federation_secret is configured on the HOST, valid
    X-Federation-Timestamp and X-Federation-Signature headers are required.
    The timestamp must be within ±5 minutes (anti-replay protection).
    """
    if not network_service.verify_federation_request(
        session,
        timestamp_str=x_federation_timestamp,
        signature=x_federation_signature,
        app_url=payload.app_url,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing federation signature",
        )

    nodes = network_service.handle_registration(session, payload)
    return api_success(data=nodes)


@router.get(
    "/network-settings",
    response_model=ApiResponse[NetworkSettings],
    summary="获取网络配置 / Get federation settings",
)
def get_settings(session: SessionDep, _admin: ActiveAdmin) -> Any:
    """
    读取本实例的网络配置（server_name, app_url, host_url, 经纬度, shared）。
    Read local instance federation settings.

    仅管理员可访问。 / Admin only.
    """
    cfg = network_service.get_network_settings(session)
    return api_success(data=cfg)


@router.put(
    "/network-settings",
    response_model=ApiResponse[NetworkSettings],
    summary="更新网络配置 / Update federation settings",
)
def update_settings(
    session: SessionDep, data: NetworkSettingsUpdate, _admin: ActiveAdmin
) -> Any:
    """
    更新网络配置。保存后会自动刷新本实例节点信息，并（若已配置 host_url）向 HOST 同步注册/隐藏状态。
    Update federation settings. Automatically refreshes the local node row
    and syncs registration/visibility with HOST if host_url is configured.

    仅管理员可访问。 / Admin only.
    """
    cfg = network_service.update_network_settings(session, data)
    return api_success(data=cfg)


@router.post(
    "/network-node-sync-jobs",
    response_model=ApiResponse[SyncResult],
    summary="手动同步节点列表 / Manually sync node list from HOST",
)
def sync_nodes(session: SessionDep, _admin: ActiveAdmin) -> Any:
    """
    手动触发从 HOST 同步节点列表（子节点使用）。
    若本实例是 HOST（未配置 host_url），直接返回成功（无操作）。
    Manually trigger a sync of the node list from HOST (child node use).
    If this instance is the HOST (no host_url), returns api_success immediately.

    仅管理员可访问。 / Admin only.
    """
    result = network_service.sync_from_host(session)
    return api_success(data=result)


@router.post(
    "/network-secret-rotations",
    response_model=ApiResponse[NetworkSettings],
    summary="生成新的网络密钥 / Generate a new federation secret",
)
def generate_secret(session: SessionDep, _admin: ActiveAdmin) -> Any:
    """
    生成一个新的 256-bit 网络密钥并保存。旧密钥立即失效，
    所有子节点需要更新为相同的密钥后才能重新注册。
    Generates a new 256-bit federation secret and saves it.
    The old secret is invalidated immediately; all child nodes must
    be updated with the same secret before they can register again.

    仅管理员可访问。 / Admin only.
    """
    new_secret = network_service.generate_federation_secret()
    cfg = network_service.update_network_settings(
        session, NetworkSettingsUpdate(federation_secret=new_secret)
    )
    return api_success(data=cfg, message="New federation secret generated")


@router.delete(
    "/network-nodes/{node_id}",
    response_model=ApiResponse[None],
    summary="删除节点 / Delete network node",
)
def delete_node(session: SessionDep, node_id: int, _admin: ActiveAdmin) -> Any:
    """
    从本地 network_node 表中删除指定节点。不影响其他实例。
    Delete a node record from the local network_node table.
    Does not affect other instances.

    仅管理员可访问，且不可删除本地节点。
    Admin only. The local node cannot be deleted.
    """
    network_service.delete_node(session, node_id)
    return api_success(data=None, message="Node deleted")
