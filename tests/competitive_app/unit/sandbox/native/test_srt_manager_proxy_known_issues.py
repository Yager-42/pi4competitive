from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from competitive_app.adapter.out.sandbox.native.srt import manager
from competitive_app.adapter.out.sandbox.native.srt import proxy


@pytest_asyncio.fixture(autouse=True)
async def _reset_manager_state():
    await manager.reset()
    yield
    await manager.reset()


class _CaptureWriter:
    def __init__(self) -> None:
        self.parts: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.parts.append(data)

    async def drain(self) -> None:
        return None


def _reader(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


@pytest.mark.asyncio
async def test_initialize_dependency_failure_is_published_to_waiters(monkeypatch: pytest.MonkeyPatch) -> None:
    await manager.reset()

    async def failed_dependencies() -> dict[str, list[str]]:
        return {"errors": ["missing dependency"], "warnings": []}

    monkeypatch.setattr(manager, "check_dependencies_async", failed_dependencies)

    results = await asyncio.gather(
        manager.initialize({"network": {}}),
        manager.initialize({"network": {}}),
        return_exceptions=True,
    )
    assert all(isinstance(result, RuntimeError) for result in results)
    assert manager._initialization_error is not None
    assert manager._initialization_done is not None
    assert manager._initialization_done.is_set()
    await manager.reset()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "network", [{"deniedDomains": ["*"]}, {"strictAllowlist": True}]
)
async def test_denied_only_and_strict_network_configs_enable_proxy(
    monkeypatch: pytest.MonkeyPatch, network: dict[str, object]
) -> None:
    captured: dict[str, object] = {}

    async def fake_wrap(**kwargs: object) -> list[str]:
        captured.update(kwargs)
        return ["wrapped"]

    monkeypatch.setattr(manager, "get_platform", lambda: "macos")
    monkeypatch.setattr(manager, "_wrap_macos", fake_wrap)
    manager._config = {"network": network}  # type: ignore[assignment]
    manager._manager_context = None
    manager._initialization_done = None
    result = await manager.wrap_with_sandbox("true")
    assert result == ["wrapped"]
    assert captured["needs_network_restriction"] is True
    assert captured["needs_network_proxy"] is True
    await manager.reset()


@pytest.mark.asyncio
async def test_reset_recreates_initialization_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    manager._initialization_lock = asyncio.Lock()
    manager._initialization_done = asyncio.Event()
    await manager.reset()
    assert manager._initialization_lock is None

    async def failed_dependencies() -> dict[str, list[str]]:
        return {"errors": ["missing dependency"], "warnings": []}

    monkeypatch.setattr(manager, "check_dependencies_async", failed_dependencies)
    with pytest.raises(RuntimeError, match="missing dependency"):
        await manager.initialize({"network": {}})
    await manager.reset()


@pytest.mark.asyncio
async def test_sandbox_ask_awaits_future(monkeypatch: pytest.MonkeyPatch) -> None:
    manager._config = {"network": {}}  # type: ignore[assignment]
    future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
    future.set_result(True)
    assert await manager.filter_network_request(443, "example.com", lambda _request: future) is True
    await manager.reset()


def test_seccomp_argv0_requires_verified_apply_path(monkeypatch: pytest.MonkeyPatch) -> None:
    manager._config = {"seccomp": {"argv0": "srt-seccomp", "applyPath": "/missing"}}  # type: ignore[assignment]
    monkeypatch.setattr(manager, "get_apply_seccomp_binary_path", lambda path: None)
    assert manager.get_seccomp_availability() is False
    manager._config = {"seccomp": {"argv0": "srt-seccomp"}}  # type: ignore[assignment]
    assert manager.get_seccomp_availability() is False
    manager._config = {"seccomp": {"argv0": "srt-seccomp", "applyPath": "/verified"}}  # type: ignore[assignment]
    monkeypatch.setattr(manager, "get_apply_seccomp_binary_path", lambda path: path)
    assert manager.get_seccomp_availability() is True
    manager._config = None


@pytest.mark.asyncio
async def test_http_connect_filters_and_dials_canonical_hostname() -> None:
    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await reader.read(32)
            writer.write(data)
            await writer.drain()
        finally:
            writer.close()

    origin = await asyncio.start_server(echo, "127.0.0.1", 0)
    origin_port = origin.sockets[0].getsockname()[1]
    seen: list[str] = []
    http_proxy = proxy.HttpProxyServer(lambda _port, host: seen.append(host) or True)
    await http_proxy.listen_tcp("127.0.0.1", 0)
    proxy_port = http_proxy._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(f"CONNECT 127.1:{origin_port} HTTP/1.1\r\n\r\n".encode())
        await writer.drain()
        assert await reader.readline() == b"HTTP/1.1 200 Connection Established\r\n"
        assert await reader.readexactly(2) == b"\r\n"
        payload = b"origin echo payload"
        writer.write(payload)
        await writer.drain()
        assert await reader.readexactly(len(payload)) == payload
        writer.close()
        await writer.wait_closed()
        assert seen == ["127.0.0.1"]
    finally:
        await http_proxy.close()
        origin.close()
        await origin.wait_closed()


@pytest.mark.asyncio
async def test_header_names_are_case_insensitive_for_body_and_response() -> None:
    request = _reader(
        b"POST / HTTP/1.1\r\nTransfer-Encoding: Chunked\r\n\r\n"
        b"4\r\nbody\r\n0\r\n\r\n"
    )
    _start, headers = await proxy._read_headers(request)
    assert headers["transfer-encoding"] == "Chunked"
    assert await proxy._read_body(request, headers) == b"body"

    response = _reader(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello")
    writer = _CaptureWriter()
    await proxy._relay_response(response, writer, "GET")
    output = b"".join(writer.parts)
    assert b"HTTP/1.1 200 OK" in output
    assert output.endswith(b"hello")


@pytest.mark.asyncio
async def test_request_body_limit_covers_content_length_and_chunked(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(proxy.RequestBodyTooLarge):
        await proxy._read_body(
            _reader(b""), {"content-length": str(proxy.MAX_REQUEST_BODY_SIZE + 1)}
        )
    with pytest.raises(proxy.RequestBodyTooLarge):
        await proxy._read_body(
            _reader(f"{proxy.MAX_REQUEST_BODY_SIZE + 1:x}\r\n".encode()),
            {"transfer-encoding": "chunked"},
        )

    monkeypatch.setattr(proxy, "MAX_REQUEST_BODY_SIZE", 5)
    with pytest.raises(proxy.RequestBodyTooLarge):
        await proxy._read_body(
            _reader(b"3\r\nabc\r\n3\r\ndef\r\n0\r\n\r\n"),
            {"transfer-encoding": "chunked"},
        )
    with pytest.raises(asyncio.IncompleteReadError):
        await proxy._read_body(_reader(b"4\r\nab"), {"transfer-encoding": "chunked"})


@pytest.mark.asyncio
async def test_relay_forwards_100_continue_then_final_response() -> None:
    upstream = _reader(
        b"HTTP/1.1 100 Continue\r\n\r\n"
        b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello"
    )
    writer = _CaptureWriter()
    await proxy._relay_response(upstream, writer, "POST")
    output = b"".join(writer.parts)
    assert output.count(b"HTTP/1.1") == 2
    assert output.endswith(b"hello")
