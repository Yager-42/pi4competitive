"""O14 — SRT proxy golden vectors: HTTP CONNECT/request filtering, SOCKS5
validation/auth, mux first-byte dispatch, NO_PROXY/parent behavior.

Source parity: sandbox-runtime@0.0.67 proxy tests (PORT, offline subset).
License: Apache-2.0 (retained under the native sandbox license directory)
"""
from __future__ import annotations

import asyncio
import socket

import pytest

from competitive_app.adapter.out.sandbox.native.srt.proxy import (
    HttpProxyServer,
    MuxProxyServer,
    SocksProxyServer,
    canonicalize_host,
    is_valid_host,
    proxy_auth_header,
    resolve_parent_proxy,
    select_parent_proxy_url,
    should_bypass_parent_proxy,
    strip_hop_by_hop,
)


def _server_port(server: asyncio.base_events.Server) -> int:
    return server.sockets[0].getsockname()[1]


# ---------------------------------------------------------------------------
# host helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("127.1", "127.0.0.1"),
        ("2130706433", "127.0.0.1"),
        ("0x7f.0.0.1", "127.0.0.1"),
        ("EXAMPLE.com.", "example.com"),
        ("0:0:0:0:0:0:0:1", "::1"),
        ("[::1]", "::1"),
        ("1.2.3.4", "1.2.3.4"),
        ("", None),
    ],
)
def test_canonicalize_host(raw: str, expected: str | None) -> None:
    assert canonicalize_host(raw) == expected


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("example.com", True),
        ("sub.example.com", True),
        ("127.0.0.1", True),
        ("::1", True),
        ("evil.com\x00.allowed.com", False),
        ("evil.com\r\n", False),
        ("::ffff:1.2.3.4%x.allowed.com", False),
        ("fe80::1%eth0", False),
        ("", False),
        ("x" * 300, False),
    ],
)
def test_is_valid_host(host: str, expected: bool) -> None:
    assert is_valid_host(host) is expected


def test_strip_hop_by_hop() -> None:
    headers = {
        "Host": "example.com",
        "Connection": "keep-alive, X-Custom",
        "keep-alive": "timeout=5",
        "proxy-authorization": "Basic abc",
        "X-Custom": "drop-me",
        "User-Agent": "curl",
    }
    out = strip_hop_by_hop(headers)
    assert out == {"Host": "example.com", "User-Agent": "curl"}


def test_proxy_auth_header() -> None:
    assert proxy_auth_header("http://user:pass@proxy:8080") == "Basic dXNlcjpwYXNz"
    assert proxy_auth_header("http://proxy:8080") is None


# ---------------------------------------------------------------------------
# parent proxy / NO_PROXY
# ---------------------------------------------------------------------------

def test_resolve_parent_proxy_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://host:3128")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("NO_PROXY", ".internal,10.0.0.0/8")
    resolved = resolve_parent_proxy(None)
    assert resolved is not None
    assert resolved.http_url == "http://host:3128"
    assert resolved.https_url == "http://host:3128"  # falls back to http
    assert should_bypass_parent_proxy(resolved, "svc.internal")
    assert should_bypass_parent_proxy(resolved, "10.1.2.3")
    assert not should_bypass_parent_proxy(resolved, "example.com")
    assert should_bypass_parent_proxy(resolved, "localhost")


def test_no_proxy_wildcard() -> None:
    resolved = resolve_parent_proxy({"http": "http://host:3128", "noProxy": "*"})
    assert resolved is not None
    assert should_bypass_parent_proxy(resolved, "anything.example.com")


def test_select_parent_proxy_url() -> None:
    resolved = resolve_parent_proxy(
        {"http": "http://h:1", "https": "https://h:2"}
    )
    assert resolved is not None
    assert select_parent_proxy_url(resolved, is_https=True) == "https://h:2"
    assert select_parent_proxy_url(resolved, is_https=False) == "http://h:1"


# ---------------------------------------------------------------------------
# HTTP proxy (live asyncio)
# ---------------------------------------------------------------------------

async def _echo_server() -> tuple[asyncio.base_events.Server, int]:
    """TCP echo server returning the request bytes as the response."""

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await reader.read(65536)
            if data:
                writer.write(data)
                await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_server(_handle, "127.0.0.1", 0)
    return server, _server_port(server)


async def _http_origin_server() -> tuple[asyncio.base_events.Server, int]:
    """Minimal HTTP/1.1 origin returning a fixed body."""

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readline()
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
            body = b"hello from origin"
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain\r\n"
                b"Content-Length: 17\r\n"
                b"Connection: close\r\n"
                b"\r\n"
                + body
            )
            await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_server(_handle, "127.0.0.1", 0)
    return server, _server_port(server)


async def test_http_connect_tunnel_allowed_and_relay() -> None:
    echo_server, echo_port = await _echo_server()
    proxy = HttpProxyServer(lambda _port, _host: True)
    await proxy.listen_tcp("127.0.0.1", 0)
    proxy_port = _server_port(proxy._server)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(
            f"CONNECT 127.0.0.1:{echo_port} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{echo_port}\r\n\r\n".encode()
        )
        await writer.drain()
        status = await reader.readline()
        assert status == b"HTTP/1.1 200 Connection Established\r\n"
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n"):
                break
        writer.write(b"ping")
        await writer.drain()
        assert await reader.readexactly(4) == b"ping"
        writer.close()
    finally:
        await proxy.close()
        echo_server.close()
        await echo_server.wait_closed()


async def test_http_connect_denied_returns_403() -> None:
    proxy = HttpProxyServer(lambda _port, _host: False)
    await proxy.listen_tcp("127.0.0.1", 0)
    proxy_port = _server_port(proxy._server)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
        await writer.drain()
        status = await reader.readline()
        assert status.startswith(b"HTTP/1.1 403")
        writer.close()
    finally:
        await proxy.close()


async def test_http_connect_requires_proxy_auth() -> None:
    proxy = HttpProxyServer(lambda _port, _host: True, proxy_auth_token="tok")
    await proxy.listen_tcp("127.0.0.1", 0)
    proxy_port = _server_port(proxy._server)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(b"CONNECT example.com:443 HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        status = await reader.readline()
        assert status.startswith(b"HTTP/1.1 407")
        writer.close()

        reader2, writer2 = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer2.write(
            b"CONNECT example.com:443 HTTP/1.1\r\nHost: x\r\n"
            b"Proxy-Authorization: Basic c3J0OnRvaw==\r\n\r\n"  # srt:tok
        )
        await writer2.drain()
        status2 = await reader2.readline()
        assert status2.startswith(b"HTTP/1.1 200")
        writer2.close()
    finally:
        await proxy.close()


async def test_http_plain_request_forwarded() -> None:
    origin, origin_port = await _http_origin_server()
    proxy = HttpProxyServer(lambda _port, _host: True)
    await proxy.listen_tcp("127.0.0.1", 0)
    proxy_port = _server_port(proxy._server)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(
            f"GET http://127.0.0.1:{origin_port}/path HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{origin_port}\r\n"
            f"Connection: keep-alive\r\n\r\n".encode()
        )
        await writer.drain()
        response = await reader.read(65536)
        assert response.startswith(b"HTTP/1.1 200 OK")
        assert b"hello from origin" in response
        writer.close()
    finally:
        await proxy.close()
        origin.close()
        await origin.wait_closed()


async def test_http_plain_request_403_on_deny() -> None:
    proxy = HttpProxyServer(lambda _port, _host: False)
    await proxy.listen_tcp("127.0.0.1", 0)
    proxy_port = _server_port(proxy._server)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n")
        await writer.drain()
        status = await reader.readline()
        assert status.startswith(b"HTTP/1.1 403")
        writer.close()
    finally:
        await proxy.close()


async def test_http_invalid_connect_target_400() -> None:
    proxy = HttpProxyServer(lambda _port, _host: True)
    await proxy.listen_tcp("127.0.0.1", 0)
    proxy_port = _server_port(proxy._server)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(b"CONNECT not-a-target HTTP/1.1\r\n\r\n")
        await writer.drain()
        status = await reader.readline()
        assert status.startswith(b"HTTP/1.1 400")
        writer.close()
    finally:
        await proxy.close()


# ---------------------------------------------------------------------------
# SOCKS5
# ---------------------------------------------------------------------------

async def test_socks5_connect_relay_and_filter() -> None:
    echo_server, echo_port = await _echo_server()
    proxy = SocksProxyServer(lambda _port, _host: True)
    await proxy.listen("127.0.0.1", 0)
    proxy_port = _server_port(proxy._server)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(b"\x05\x01\x00")  # greeting: no auth
        await writer.drain()
        assert await reader.readexactly(2) == b"\x05\x00"
        writer.write(
            b"\x05\x01\x00\x03"
            + bytes([len("127.0.0.1")])
            + b"127.0.0.1"
            + echo_port.to_bytes(2, "big")
        )
        await writer.drain()
        reply = await reader.readexactly(10)
        assert reply[1] == 0x00  # REQUEST_GRANTED
        writer.write(b"hello")
        await writer.drain()
        assert await reader.readexactly(5) == b"hello"
        writer.close()
    finally:
        await proxy.close()
        echo_server.close()
        await echo_server.wait_closed()


async def test_socks5_auth_required_and_username_check() -> None:
    proxy = SocksProxyServer(lambda _port, _host: True, proxy_auth_token="tok")
    await proxy.listen("127.0.0.1", 0)
    proxy_port = _server_port(proxy._server)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(b"\x05\x01\x02")
        await writer.drain()
        assert await reader.readexactly(2) == b"\x05\x02"
        # wrong password
        writer.write(b"\x01\x03srt\x03bad")
        await writer.drain()
        assert await reader.readexactly(2) == b"\x01\x01"
        writer.close()
    finally:
        await proxy.close()


async def test_socks5_malformed_host_rejected() -> None:
    proxy = SocksProxyServer(lambda _port, _host: True)
    await proxy.listen("127.0.0.1", 0)
    proxy_port = _server_port(proxy._server)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        await reader.readexactly(2)
        writer.write(b"\x05\x01\x00\x03" + b"\x0a" + b"evil.com\x00x" + b"\x00\x50")
        await writer.drain()
        reply = await reader.readexactly(10)
        assert reply[1] == 0x02  # not allowed
        writer.close()
    finally:
        await proxy.close()


async def test_socks5_blocked_by_filter() -> None:
    proxy = SocksProxyServer(lambda _port, _host: False)
    await proxy.listen("127.0.0.1", 0)
    proxy_port = _server_port(proxy._server)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        await reader.readexactly(2)
        writer.write(
            b"\x05\x01\x00\x03"
            + bytes([len("example.com")])
            + b"example.com"
            + b"\x01\xbb"
        )
        await writer.drain()
        reply = await reader.readexactly(10)
        assert reply[1] == 0x02
        writer.close()
    finally:
        await proxy.close()


# ---------------------------------------------------------------------------
# mux
# ---------------------------------------------------------------------------

async def test_mux_dispatches_http_and_socks_first_byte() -> None:
    echo_server, echo_port = await _echo_server()
    http_backend = HttpProxyServer(lambda _port, _host: True)
    socks = SocksProxyServer(lambda _port, _host: True)
    mux = MuxProxyServer(
        http_backend=http_backend,
        handle_socks=socks.handle_connection,
        first_byte_timeout=2.0,
    )
    await mux.listen_http_backend()
    await mux.listen("127.0.0.1", 0)
    mux_port = mux.get_port()
    assert mux_port is not None
    try:
        # HTTP first byte (G) -> CONNECT tunnel through the backend
        reader, writer = await asyncio.open_connection("127.0.0.1", mux_port)
        writer.write(
            f"CONNECT 127.0.0.1:{echo_port} HTTP/1.1\r\nHost: h\r\n\r\n".encode()
        )
        await writer.drain()
        status = await reader.readline()
        assert status == b"HTTP/1.1 200 Connection Established\r\n"
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n"):
                break
        writer.write(b"mux-http")
        await writer.drain()
        assert await reader.readexactly(8) == b"mux-http"
        writer.close()

        # SOCKS first byte (0x05) -> SOCKS handler directly
        reader2, writer2 = await asyncio.open_connection("127.0.0.1", mux_port)
        writer2.write(b"\x05\x01\x00")
        await writer2.drain()
        assert await reader2.readexactly(2) == b"\x05\x00"
        writer2.close()
    finally:
        await mux.close()
        echo_server.close()
        await echo_server.wait_closed()
