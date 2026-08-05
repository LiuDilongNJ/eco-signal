"""HTTP request helpers."""
from __future__ import annotations

import ipaddress

from fastapi import Request


def _is_valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _is_trusted_proxy(host: str) -> bool:
    """Trust Docker/private peers that terminate Traefik or nginx."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local)


def get_client_ip(request: Request) -> str | None:
    """Return the real client IP behind reverse proxies when safe.

    Only honor ``X-Forwarded-For`` / ``X-Real-IP`` when the immediate peer is a
    private/loopback address (typical Docker Traefik/nginx hop). Direct public
    connections keep ``request.client.host`` so clients cannot spoof headers.
    """
    peer = request.client.host if request.client else None
    if not peer or not _is_trusted_proxy(peer):
        return peer

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        candidate = forwarded_for.split(",", 1)[0].strip()
        if candidate and _is_valid_ip(candidate):
            return candidate

    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if real_ip and _is_valid_ip(real_ip):
        return real_ip

    return peer
