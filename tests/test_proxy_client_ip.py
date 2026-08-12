from __future__ import annotations

from fastapi import Request

from server.main import resolve_client_host


def request_from(host: str, cloudflare_host: str | None = None) -> Request:
    headers = []
    if cloudflare_host is not None:
        headers.append((b"cf-connecting-ip", cloudflare_host.encode("ascii")))
    return Request({"type": "http", "client": (host, 443), "headers": headers})


def test_trusted_tunnel_gateway_uses_cloudflare_client_ip() -> None:
    request = request_from("172.18.0.1", "203.0.113.24")

    assert resolve_client_host(request, ("172.18.0.1",)) == "203.0.113.24"


def test_untrusted_client_cannot_spoof_cloudflare_header() -> None:
    request = request_from("192.168.22.11", "203.0.113.24")

    assert resolve_client_host(request, ("172.18.0.1",)) == "192.168.22.11"


def test_invalid_cloudflare_client_ip_falls_back_to_gateway() -> None:
    request = request_from("172.18.0.1", "203.0.113.24, 198.51.100.8")

    assert resolve_client_host(request, ("172.18.0.1",)) == "172.18.0.1"
