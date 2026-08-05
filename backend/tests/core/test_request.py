"""Tests for client IP extraction behind reverse proxies."""
from starlette.requests import Request

from app.core.request import get_client_ip


def _request(
    *,
    peer: str | None,
    headers: dict[str, str] | None = None,
) -> Request:
    header_items = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": header_items,
        "client": (peer, 12345) if peer else None,
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_get_client_ip_uses_x_forwarded_for_from_private_peer() -> None:
    request = _request(
        peer="172.18.0.5",
        headers={"X-Forwarded-For": "203.0.113.10, 10.0.0.2"},
    )
    assert get_client_ip(request) == "203.0.113.10"


def test_get_client_ip_falls_back_to_x_real_ip() -> None:
    request = _request(
        peer="10.0.0.8",
        headers={"X-Real-IP": "198.51.100.20"},
    )
    assert get_client_ip(request) == "198.51.100.20"


def test_get_client_ip_ignores_spoofed_headers_from_public_peer() -> None:
    request = _request(
        peer="8.8.8.8",
        headers={
            "X-Forwarded-For": "1.2.3.4",
            "X-Real-IP": "5.6.7.8",
        },
    )
    assert get_client_ip(request) == "8.8.8.8"


def test_get_client_ip_returns_peer_when_headers_missing() -> None:
    request = _request(peer="127.0.0.1")
    assert get_client_ip(request) == "127.0.0.1"


def test_get_client_ip_ignores_invalid_forwarded_values() -> None:
    request = _request(
        peer="172.18.0.5",
        headers={
            "X-Forwarded-For": "not-an-ip",
            "X-Real-IP": "also-bad",
        },
    )
    assert get_client_ip(request) == "172.18.0.5"


def test_get_client_ip_handles_missing_client() -> None:
    request = _request(peer=None, headers={"X-Forwarded-For": "203.0.113.10"})
    assert get_client_ip(request) is None
