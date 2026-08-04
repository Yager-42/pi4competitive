"""SRT network proxies — HTTP CONNECT/absolute-URI proxy, SOCKS5 server,
single-port mux front-end, parent-proxy resolution/NO_PROXY, bounded
dialing, and listen-in-range port selection.

Source: sandbox-runtime@0.0.67 ``src/sandbox/{http-proxy,socks-proxy,mux-proxy,parent-proxy,listen-in-range}.ts``
Repository: anthropics/sandbox-runtime @ 21d8f75e1bc00eede09b3103e68b2eae097110d1
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta (ADAPT, per G0 map §4.1): asyncio streams replace Node net/http;
``filter`` callbacks take ``(port, host)`` (the upstream socket argument is
dropped); the SOCKS server implements the SOCKS5 state machine directly
(the upstream wraps ``@pondwader/socks5-server``); the mux pipes client
sockets to the HTTP backend over a unix socket exactly like upstream.
Omitted branches: TLS termination, MITM routing, body/header mutation,
SigV4, and the CRL path (no ``mitmCA``). The HTTP relay forces
``Connection: close`` upstream so response framing never has to be
re-assembled. Parent-proxy resolution reads the host environment (SRT's
own process env), never the worker's.
"""
from __future__ import annotations

import asyncio
import base64
import errno
import inspect
import ipaddress
import os
import re
import socket
import ssl
import struct
from typing import Any, Awaitable, Callable
from urllib.parse import unquote, urlsplit

from .process import log_for_debugging

CONNECT_TIMEOUT_SECONDS = 30.0
MAX_REQUEST_BODY_SIZE = 10 * 1024 * 1024


class RequestBodyTooLarge(ValueError):
    """Raised before buffering a request body beyond the proxy limit."""


# Hop-by-hop headers per RFC 7230 §6.1 + proxy-specific headers.
HOP_BY_HOP = frozenset(
    [
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    ]
)

_LOOPBACK_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::ffff:127.0.0.0/104"),
]

_HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9._-]+$")

FilterCallback = Callable[[int, str], Awaitable[bool] | bool]


# ---------------------------------------------------------------------------
# host helpers (parent-proxy.ts)
# ---------------------------------------------------------------------------

def strip_brackets(host: str) -> str:
    if host.startswith("[") and host.endswith("]"):
        return host[1:-1]
    return host


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def is_valid_host(host: str) -> bool:
    """Reject control chars, zone ids, oversized names (CRLF/null-byte
    injection + zone-identifier allowlist bypass)."""
    if not host or len(host) > 255:
        return False
    bare = strip_brackets(host)
    if "%" in bare:
        return False
    if is_ip_literal(bare):
        return True
    return bool(_HOST_LABEL_RE.match(bare))


def canonicalize_host(host: str) -> str | None:
    """Normalize inet_aton shorthand, hex/octal octets, IPv6 compression,
    trailing dots, case, brackets — so allowlist comparisons agree with what
    getaddrinfo will dial."""
    bare = strip_brackets(host).lower()
    if not bare:
        return None
    # IPv4 forms (dotted, inet_aton shorthand, hex/octal) via socket.inet_aton.
    if ":" not in bare:
        candidate = bare.rstrip(".")
        try:
            packed = socket.inet_aton(candidate)
            return socket.inet_ntoa(packed)
        except OSError:
            pass
        # Plain DNS name: strip trailing dot, lowercase.
        if _HOST_LABEL_RE.match(bare):
            return bare.rstrip(".")
        return None
    # IPv6 (possibly bracketed, possibly with trailing dot).
    candidate = bare.rstrip(".")
    try:
        return str(ipaddress.IPv6Address(candidate))
    except (ipaddress.AddressValueError, ValueError):
        return None


def strip_hop_by_hop(headers: dict[str, str]) -> dict[str, str]:
    """Drop hop-by-hop headers + anything named in Connection."""
    extra: set[str] = set()
    conn = next((v for k, v in headers.items() if k.lower() == "connection"), None)
    if conn:
        for token in conn.split(","):
            extra.add(token.strip().lower())
    out: dict[str, str] = {}
    for key, value in headers.items():
        lk = key.lower()
        if lk not in HOP_BY_HOP and lk not in extra:
            out[key] = value
    return out


def proxy_auth_header(proxy_url: str) -> str | None:
    parts = urlsplit(proxy_url)
    if not parts.username and not parts.password:
        return None
    try:
        creds = f"{unquote(parts.username or '')}:{unquote(parts.password or '')}"
    except Exception:
        creds = f"{parts.username or ''}:{parts.password or ''}"
    encoded = base64.b64encode(creds.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def redact_url(url: str | None) -> str:
    if not url:
        return "-"
    parts = urlsplit(url)
    if not parts.username and not parts.password:
        return url
    netloc = parts.netloc
    at = netloc.rfind("@")
    if at != -1:
        netloc = "***:***@" + netloc[at + 1 :]
    return urlsplit(url)._replace(netloc=netloc).geturl()


# ---------------------------------------------------------------------------
# parent proxy resolution / NO_PROXY (parent-proxy.ts)
# ---------------------------------------------------------------------------

class ResolvedParentProxy:
    def __init__(
        self,
        http_url: str | None,
        https_url: str | None,
        no_proxy_all: bool,
        no_proxy_suffixes: list[str],
        no_proxy_cidrs: list[ipaddress._BaseNetwork],
    ) -> None:
        self.http_url = http_url
        self.https_url = https_url
        self.no_proxy_all = no_proxy_all
        self.no_proxy_suffixes = no_proxy_suffixes
        self.no_proxy_cidrs = no_proxy_cidrs


def _parse_proxy_url(raw: str | None) -> str | None:
    if not raw:
        return None
    has_scheme = re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.IGNORECASE)
    with_scheme = raw if has_scheme else f"http://{raw}"
    try:
        parts = urlsplit(with_scheme)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("unsupported scheme or empty host")
        return with_scheme
    except ValueError:
        log_for_debugging(
            f"Invalid parent proxy URL, ignoring: {redact_url(raw)}",
            level="error",
        )
        return None


def _parse_no_proxy(
    raw: str,
) -> tuple[bool, list[str], list[ipaddress._BaseNetwork]]:
    all_flag = False
    suffixes: list[str] = []
    cidrs: list[ipaddress._BaseNetwork] = []

    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if entry == "*":
            all_flag = True
            continue

        if "/" in entry:
            ip_part, prefix_part = entry.split("/", 1)
            try:
                net = ipaddress.ip_network(f"{ip_part}/{prefix_part}", strict=False)
                cidrs.append(net)
            except ValueError:
                pass
            continue

        value = entry.lower()
        bracketed = re.match(r"^\[([^\]]+)\](?::\d+)?$", value)
        if bracketed:
            value = bracketed.group(1)
        if value.startswith("*."):
            value = value[1:]
        if ":" not in value:
            # Bare IPv4 literal → exact CIDR.
            try:
                cidrs.append(ipaddress.ip_network(value))
                continue
            except ValueError:
                pass
            colon = value.rfind(":")
            if colon != -1 and value[colon + 1 :].isdigit():
                value = value[:colon]
        suffixes.append(value)
    return all_flag, suffixes, cidrs


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in net for net in _LOOPBACK_NETS)


def should_bypass_parent_proxy(resolved: ResolvedParentProxy, host: str) -> bool:
    """NO_PROXY matching with golang suffix semantics; loopback always
    bypasses. The port is never consulted (upstream behavior)."""
    h = strip_brackets(host.lower().rstrip("."))
    if _is_loopback(h):
        return True
    if resolved.no_proxy_all:
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        ip = None
    if ip is not None:
        if any(ip in net for net in resolved.no_proxy_cidrs):
            return True
    for suffix in resolved.no_proxy_suffixes:
        if suffix.startswith("."):
            if h == suffix[1:] or h.endswith(suffix):
                return True
        else:
            if h == suffix or h.endswith("." + suffix):
                return True
    return False


def select_parent_proxy_url(
    resolved: ResolvedParentProxy, *, is_https: bool
) -> str | None:
    if is_https:
        return resolved.https_url or resolved.http_url
    return resolved.http_url


def resolve_parent_proxy(
    cfg: dict[str, Any] | None = None,
) -> ResolvedParentProxy | None:
    """Resolve the parent proxy from config, falling back to the SRT
    process's own env (never the sandboxed child's)."""
    http = (
        (cfg or {}).get("http")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )
    https = (
        (cfg or {}).get("https")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or http
    )
    no_proxy_raw = (
        (cfg or {}).get("noProxy")
        or os.environ.get("NO_PROXY")
        or os.environ.get("no_proxy")
        or ""
    )
    http_url = _parse_proxy_url(http)
    https_url = _parse_proxy_url(https)
    if http_url is None and https_url is None:
        return None
    all_flag, suffixes, cidrs = _parse_no_proxy(no_proxy_raw)
    return ResolvedParentProxy(
        http_url=http_url,
        https_url=https_url,
        no_proxy_all=all_flag,
        no_proxy_suffixes=suffixes,
        no_proxy_cidrs=cidrs,
    )


# ---------------------------------------------------------------------------
# dialing (parent-proxy.ts dialDirect / openConnectTunnel)
# ---------------------------------------------------------------------------

async def dial_direct(
    host: str, port: int, timeout: float = CONNECT_TIMEOUT_SECONDS
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Bounded direct dial; raises TimeoutError / OSError."""
    return await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout=timeout
    )


async def open_connect_tunnel(
    *,
    dest_host: str,
    dest_port: int,
    dial: Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
    auth_header: str | None = None,
    timeout: float = CONNECT_TIMEOUT_SECONDS,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Dial a proxy transport, send ``CONNECT host:port``, require 2xx,
    resolve with the tunnelled stream pair."""
    bare = strip_brackets(dest_host)
    if not is_valid_host(bare):
        raise ValueError(
            f"Invalid destination host for CONNECT: {dest_host!r}"
        )
    if not isinstance(dest_port, int) or not 1 <= dest_port <= 65535:
        raise ValueError(f"Invalid destination port: {dest_port}")
    authority = f"[{bare}]:{dest_port}" if ":" in bare else f"{bare}:{dest_port}"

    reader, writer = await asyncio.wait_for(dial(), timeout=timeout)
    try:
        request = (
            f"CONNECT {authority} HTTP/1.1\r\n"
            f"Host: {authority}\r\n"
            + (f"Proxy-Authorization: {auth_header}\r\n" if auth_header else "")
            + "\r\n"
        )
        writer.write(request.encode("latin1"))
        await writer.drain()

        buf = b""
        while b"\r\n\r\n" not in buf:
            if len(buf) > 16 * 1024:
                raise RuntimeError("CONNECT response header too large")
            chunk = await asyncio.wait_for(reader.read(4096), timeout=timeout)
            if not chunk:
                raise ConnectionError("Proxy closed during CONNECT handshake")
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        status_line = head.split(b"\r\n", 1)[0].decode("latin1", "replace")
        if not re.match(r"^HTTP/1\.[01] 2\d\d(?:\s|$)", status_line):
            raise ConnectionError(f"Proxy refused CONNECT: {status_line.strip()}")
        # Re-emit any bytes that arrived after the header terminator via a
        # prefix wrapper (never poke asyncio internals).
        if rest:
            return _UnshiftedReader(reader, rest), writer
        return reader, writer
    except Exception:
        writer.close()
        raise


async def connect_via_parent_proxy(
    proxy_url: str,
    dest_host: str,
    dest_port: int,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """CONNECT tunnel through an http(s) parent proxy (TLS dial for https
    parents, SNI omitted for IP literals)."""
    parts = urlsplit(proxy_url)
    proxy_host = strip_brackets(parts.hostname or "")
    proxy_port = parts.port or (443 if parts.scheme == "https" else 80)
    use_tls = parts.scheme == "https"

    async def _dial() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if use_tls:
            context = ssl.create_default_context()
            return await asyncio.open_connection(
                proxy_host,
                proxy_port,
                ssl=context,
                server_hostname=None if is_ip_literal(proxy_host) else proxy_host,
            )
        return await asyncio.open_connection(proxy_host, proxy_port)

    return await open_connect_tunnel(
        dest_host=dest_host,
        dest_port=dest_port,
        dial=_dial,
        auth_header=proxy_auth_header(proxy_url),
    )


# ---------------------------------------------------------------------------
# listen-in-range.ts
# ---------------------------------------------------------------------------

async def listen_in_range(
    do_listen: Callable[[int], Awaitable[None]],
    port_range: tuple[int, int] | None,
    exclude: set[int] | None = None,
) -> None:
    """Bind to the first free port in ``range``, retrying on EADDRINUSE;
    ephemeral port 0 when no range is given. Raises when the range is
    exhausted."""
    exclude = exclude or set()
    if port_range is None:
        await do_listen(0)
        return
    lo, hi = port_range
    port = lo
    while port <= hi:
        if port in exclude:
            port += 1
            continue
        try:
            await do_listen(port)
            return
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE and port < hi:
                port += 1
                continue
            raise
    raise RuntimeError(
        f"No free port in range {lo}-{hi} (excluding {','.join(map(str, exclude))})"
    )


# ---------------------------------------------------------------------------
# HTTP proxy (http-proxy.ts, non-TLS subset)
# ---------------------------------------------------------------------------

async def _read_headers(reader: asyncio.StreamReader) -> tuple[str, dict[str, str]]:
    """Read one request/response head block: ``<start line>`` + header lines
    (Latin-1 per HTTP spec). Returns (start_line, headers)."""
    request_line = await reader.readline()
    if not request_line:
        raise ConnectionError("EOF before request line")
    start_line = request_line.decode("latin1").rstrip("\r\n")
    headers: dict[str, str] = {}
    while True:
        line = await reader.readline()
        if not line or line in (b"\r\n", b"\n"):
            break
        name, _, value = line.decode("latin1").partition(":")
        headers[name.strip().lower()] = value.strip()
    return start_line, headers


def _header_get(headers: dict[str, str], name: str) -> str | None:
    """Case-insensitive header lookup (Node lowercases header names)."""
    return next((v for k, v in headers.items() if k.lower() == name), None)


def _check_proxy_auth(
    got: str | None, proxy_auth_token: str | None
) -> bool:
    if not proxy_auth_token:
        return True
    match = re.match(r"^basic\s+([a-z0-9+/=]+)\s*$", got or "", re.IGNORECASE)
    if not match:
        return False
    try:
        decoded = base64.b64decode(match.group(1)).decode("utf-8")
    except Exception:
        return False
    sep = decoded.find(":")
    return sep > 0 and decoded[sep + 1 :] == proxy_auth_token


class HttpProxyServer:
    """HTTP proxy with CONNECT tunnelling and absolute-URI forwarding.

    ADAPT of ``createHttpProxyServer`` minus TLS termination / body
    mutation / SigV4 / CRL. Forwards with ``Connection: close`` so the
    response relay terminates on upstream EOF — no chunk reassembly needed.
    """

    def __init__(
        self,
        filter_cb: FilterCallback,
        *,
        proxy_auth_token: str | None = None,
        parent_proxy: ResolvedParentProxy | None = None,
    ) -> None:
        self._filter = filter_cb
        self._proxy_auth_token = proxy_auth_token
        self._parent_proxy = parent_proxy
        self._server: asyncio.base_events.Server | None = None
        self._sock_path: str | None = None

    async def listen(self, path: str) -> None:
        self._sock_path = path
        self._server = await asyncio.start_unix_server(
            self._handle_connection, path=path
        )

    async def listen_tcp(self, host: str, port: int) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, host=host, port=port
        )

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._sock_path:
            try:
                os.unlink(self._sock_path)
            except OSError:
                pass
            self._sock_path = None

    # -- connection handling -------------------------------------------------

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            start_line, headers = await _read_headers(reader)
            parts = start_line.split(" ", 2)
            if len(parts) < 3:
                await _send_simple(writer, 400, "Bad Request")
                return
            method, target, _version = parts
            if method.upper() == "CONNECT":
                await self._handle_connect(target, headers, reader, writer)
            else:
                await self._handle_request(
                    method, target, headers, reader, writer
                )
        except ConnectionError:
            pass
        except Exception as error:  # noqa: BLE001 — upstream 500 path
            log_for_debugging(f"Error handling HTTP request: {error}")
            try:
                await _send_simple(writer, 500, "Internal Server Error")
            except (ConnectionError, OSError):
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _handle_connect(
        self,
        target: str,
        headers: dict[str, str],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        if not _check_proxy_auth(
            _header_get(headers, "proxy-authorization"), self._proxy_auth_token
        ):
            writer.write(
                b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                b'Proxy-Authenticate: Basic realm="srt"\r\n\r\n'
            )
            await writer.drain()
            return
        parsed = _parse_connect_target(target)
        if parsed is None:
            log_for_debugging(f"Invalid CONNECT request: {target}", level="error")
            await _send_simple(writer, 400, "Bad Request")
            return
        hostname, port = parsed
        if not is_valid_host(hostname):
            log_for_debugging(f"Invalid CONNECT host: {hostname!r}", level="error")
            await _send_simple(writer, 400, "Bad Request")
            return
        canonical_hostname = canonicalize_host(hostname)
        if canonical_hostname is None:
            log_for_debugging(f"Invalid CONNECT host: {hostname!r}", level="error")
            await _send_simple(writer, 400, "Bad Request")
            return
        hostname = canonical_hostname

        allowed = await _call_filter(self._filter, port, hostname)
        if not allowed:
            log_for_debugging(f"Connection blocked to {hostname}:{port}", level="error")
            writer.write(
                b"HTTP/1.1 403 Forbidden\r\n"
                b"Content-Type: text/plain\r\n"
                b"X-Proxy-Error: blocked-by-allowlist\r\n"
                b"\r\n"
                b"Connection blocked by network allowlist"
            )
            await writer.drain()
            return

        parent_url = None
        if self._parent_proxy and not should_bypass_parent_proxy(
            self._parent_proxy, hostname
        ):
            parent_url = select_parent_proxy_url(self._parent_proxy, is_https=True)

        try:
            if parent_url:
                upstream_reader, upstream_writer = await connect_via_parent_proxy(
                    parent_url, hostname, port
                )
            else:
                upstream_reader, upstream_writer = await dial_direct(hostname, port)
        except Exception as error:  # noqa: BLE001
            log_for_debugging(
                f"CONNECT tunnel failed: {error}", level="error"
            )
            await _send_simple(writer, 502, "Bad Gateway")
            return

        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await _pipe_bidirectional(reader, writer, upstream_reader, upstream_writer)

    async def _handle_request(
        self,
        method: str,
        target: str,
        headers: dict[str, str],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        if not _check_proxy_auth(
            _header_get(headers, "proxy-authorization"), self._proxy_auth_token
        ):
            writer.write(
                b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                b'Proxy-Authenticate: Basic realm="srt"\r\n\r\n'
            )
            await writer.drain()
            return
        # Plain-HTTP proxy requests must be absolute-form (origin-form cannot
        # be routed).
        parts = urlsplit(target)
        if not parts.scheme or not parts.hostname:
            await _send_simple(writer, 400, "Bad Request")
            return
        hostname = strip_brackets(parts.hostname)
        port = parts.port or (443 if parts.scheme == "https" else 80)

        allowed = await _call_filter(self._filter, port, hostname)
        if not allowed:
            log_for_debugging(f"HTTP request blocked to {hostname}:{port}", level="error")
            writer.write(
                b"HTTP/1.1 403 Forbidden\r\n"
                b"Content-Type: text/plain\r\n"
                b"X-Proxy-Error: blocked-by-allowlist\r\n"
                b"\r\n"
                b"Connection blocked by network allowlist"
            )
            await writer.drain()
            return

        # Read the request body (Content-Length or chunked), with a hard
        # bound so untrusted clients cannot force unbounded buffering.
        try:
            body = await _read_body(reader, headers)
        except RequestBodyTooLarge:
            await _send_simple(writer, 413, "Payload Too Large")
            return
        except ValueError:
            await _send_simple(writer, 400, "Bad Request")
            return

        forwarded = strip_hop_by_hop(headers)
        forwarded["host"] = (
            f"{parts.hostname}:{parts.port}" if parts.port else parts.hostname
        )
        forwarded["connection"] = "close"
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        abs_url = f"{parts.scheme}://{forwarded['host']}{path}"

        parent_url = None
        if self._parent_proxy and not should_bypass_parent_proxy(
            self._parent_proxy, hostname
        ):
            parent_url = select_parent_proxy_url(
                self._parent_proxy, is_https=parts.scheme == "https"
            )

        try:
            if parent_url:
                p_parts = urlsplit(parent_url)
                proxy_host = strip_brackets(p_parts.hostname or "")
                proxy_port = p_parts.port or (
                    443 if p_parts.scheme == "https" else 80
                )
                auth = proxy_auth_header(parent_url)
                if p_parts.scheme == "https":
                    context = ssl.create_default_context()
                    upstream_reader, upstream_writer = (
                        await asyncio.open_connection(
                            proxy_host,
                            proxy_port,
                            ssl=context,
                            server_hostname=(
                                None
                                if is_ip_literal(proxy_host)
                                else proxy_host
                            ),
                        )
                    )
                else:
                    upstream_reader, upstream_writer = (
                        await asyncio.open_connection(proxy_host, proxy_port)
                    )
                if auth:
                    forwarded["proxy-authorization"] = auth
                await _write_upstream_request(
                    upstream_writer, method, abs_url, forwarded, body
                )
            else:
                use_tls = parts.scheme == "https"
                if use_tls:
                    context = ssl.create_default_context()
                    upstream_reader, upstream_writer = await asyncio.open_connection(
                        hostname, port, ssl=context, server_hostname=hostname
                    )
                else:
                    upstream_reader, upstream_writer = await dial_direct(
                        hostname, port
                    )
                await _write_upstream_request(
                    upstream_writer, method, path, forwarded, body
                )
        except Exception as error:  # noqa: BLE001
            log_for_debugging(f"Proxy request failed: {error}", level="error")
            await _send_simple(writer, 502, "Bad Gateway")
            return

        await _relay_response(upstream_reader, writer, method)


async def _write_upstream_request(
    writer: asyncio.StreamWriter,
    method: str,
    target: str,
    headers: dict[str, str],
    body: bytes,
) -> None:
    lines = [f"{method} {target} HTTP/1.1"]
    for name, value in headers.items():
        lines.append(f"{name}: {value}")
    if body and _header_get(headers, "content-length") is None:
        lines.append(f"Content-Length: {len(body)}")
    payload = ("\r\n".join(lines) + "\r\n\r\n").encode("latin1") + body
    writer.write(payload)
    await writer.drain()


async def _read_body(
    reader: asyncio.StreamReader, headers: dict[str, str]
) -> bytes:
    te = headers.get("transfer-encoding", "").lower()
    if "chunked" in te:
        chunks = bytearray()
        while True:
            size_line = await reader.readline()
            if not size_line:
                break
            size_str = size_line.split(b";", 1)[0].strip()
            try:
                size = int(size_str, 16)
            except ValueError:
                break
            if size == 0:
                while True:
                    trailer = await reader.readline()
                    if trailer in (b"\r\n", b"\n", b""):
                        break
                break
            if size < 0 or size > MAX_REQUEST_BODY_SIZE - len(chunks):
                raise RequestBodyTooLarge(
                    f"request body exceeds {MAX_REQUEST_BODY_SIZE} bytes"
                )
            chunks.extend(await reader.readexactly(size))
            await reader.readline()  # trailing CRLF
        return bytes(chunks)
    content_length = headers.get("content-length")
    if content_length:
        try:
            length = int(content_length)
        except ValueError as error:
            raise ValueError("invalid Content-Length") from error
        if length < 0:
            raise ValueError("invalid negative Content-Length")
        if length > MAX_REQUEST_BODY_SIZE:
            raise RequestBodyTooLarge(
                f"request body exceeds {MAX_REQUEST_BODY_SIZE} bytes"
            )
        if length > 0:
            return await reader.readexactly(length)
    return b""


async def _relay_response(
    upstream_reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    method: str,
) -> None:
    while True:
        try:
            start_line, headers = await _read_headers(upstream_reader)
        except ConnectionError:
            return
        status_parts = start_line.split(" ", 2)
        status_code = (
            int(status_parts[1])
            if len(status_parts) >= 2 and status_parts[1].isdigit()
            else 0
        )

        outgoing = strip_hop_by_hop(headers)
        outgoing["Connection"] = "close"
        payload = start_line + "\r\n"
        for name, value in outgoing.items():
            payload += f"{name}: {value}\r\n"
        payload += "\r\n"
        writer.write(payload.encode("latin1"))
        await writer.drain()

        # Informational responses (for example 100 Continue) are interim;
        # forward them, then consume and relay the final response as well.
        # 101 Switching Protocols is a terminal protocol upgrade.
        if 100 <= status_code < 200 and status_code != 101:
            continue

        no_body = (
            method.upper() == "HEAD"
            or status_code in (204, 304)
            or status_code == 101
        )
        if no_body:
            return
        content_length = headers.get("content-length")
        if content_length:
            try:
                remaining = int(content_length)
            except ValueError:
                remaining = 0
            while remaining > 0:
                chunk = await upstream_reader.read(min(65536, remaining))
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
                remaining -= len(chunk)
            return
        if "chunked" in headers.get("transfer-encoding", "").lower():
            # Relay the chunked stream verbatim until the terminal 0-chunk.
            while True:
                line = await upstream_reader.readline()
                if not line:
                    break
                writer.write(line)
                await writer.drain()
                size_str = line.split(b";", 1)[0].strip()
                try:
                    size = int(size_str, 16)
                except ValueError:
                    break
                if size == 0:
                    while True:
                        trailer = await upstream_reader.readline()
                        if trailer in (b"\r\n", b"\n", b""):
                            break
                        writer.write(trailer)
                        await writer.drain()
                    break
                chunk = await upstream_reader.readexactly(size + 2)  # data + CRLF
                writer.write(chunk)
                await writer.drain()
            return
        # Close-delimited body: relay until upstream EOF.
        while True:
            chunk = await upstream_reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()




def _parse_connect_target(target: str) -> tuple[str, int] | None:
    match = re.match(r"^\[([^\]]+)\]:(\d+)$", target) or re.match(
        r"^([^:]+):(\d+)$", target
    )
    if not match:
        return None
    port = int(match.group(2))
    if port < 1 or port > 65535:
        return None
    return match.group(1), port


async def _send_simple(
    writer: asyncio.StreamWriter, status: int, text: str
) -> None:
    reason = {400: "Bad Request", 403: "Forbidden", 413: "Payload Too Large", 500: "Internal Server Error", 502: "Bad Gateway"}.get(status, "")
    writer.write(f"HTTP/1.1 {status} {reason}\r\nContent-Length: {len(text)}\r\nConnection: close\r\n\r\n{text}".encode("latin1"))
    await writer.drain()


async def _call_filter(
    filter_cb: FilterCallback, port: int, host: str
) -> bool:
    result = filter_cb(port, host)
    if inspect.isawaitable(result):
        return bool(await result)
    return bool(result)


async def _pipe_bidirectional(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream_reader: asyncio.StreamReader,
    upstream_writer: asyncio.StreamWriter,
) -> None:
    async def _pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        try:
            while True:
                chunk = await src.read(65536)
                if not chunk:
                    break
                dst.write(chunk)
                await dst.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                dst.close()
            except Exception:
                pass

    c2u = asyncio.ensure_future(_pump(client_reader, upstream_writer))
    u2c = asyncio.ensure_future(_pump(upstream_reader, client_writer))
    await asyncio.gather(c2u, u2c, return_exceptions=True)


# ---------------------------------------------------------------------------
# SOCKS5 proxy (socks-proxy.ts — direct implementation)
# ---------------------------------------------------------------------------

class SocksProxyServer:
    """SOCKS5 CONNECT proxy with hostname validation, optional
    username/password auth (user ``srt``), the allow callback, and direct/
    parent routing. ADAPT: replaces ``@pondwader/socks5-server`` with a
    small asyncio state machine (same behaviors: malformed hosts rejected
    before the allowlist matcher, auth 0x01 reply, REQUEST_GRANTED /
    HOST_UNREACHABLE statuses)."""

    def __init__(
        self,
        filter_cb: FilterCallback,
        *,
        proxy_auth_token: str | None = None,
        parent_proxy: ResolvedParentProxy | None = None,
    ) -> None:
        self._filter = filter_cb
        self._proxy_auth_token = proxy_auth_token
        self._parent_proxy = parent_proxy
        self._server: asyncio.base_events.Server | None = None

    async def listen(self, host: str, port: int) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, host=host, port=port
        )

    async def handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await self._handle_connection(reader, writer)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            greeting = await reader.readexactly(2)
            if greeting[0] != 0x05:
                log_for_debugging("SOCKS greeting rejected: not SOCKS5")
                writer.close()
                return
            n_methods = greeting[1]
            methods = await reader.readexactly(n_methods)
            if self._proxy_auth_token:
                if 0x02 not in methods:
                    writer.write(b"\x05\xff")  # no acceptable methods
                    await writer.drain()
                    writer.close()
                    return
                writer.write(b"\x05\x02")
                await writer.drain()
                if not await self._authenticate(reader, writer):
                    return
            else:
                if 0x00 not in methods:
                    writer.write(b"\x05\xff")
                    await writer.drain()
                    writer.close()
                    return
                writer.write(b"\x05\x00")
                await writer.drain()

            request = await reader.readexactly(4)
            _ver, cmd, _rsv, atyp = request
            if cmd != 0x01:
                log_for_debugging(
                    f"SOCKS unsupported command {cmd}; only CONNECT supported"
                )
                await self._reply(writer, 0x07)
                writer.close()
                return
            host, port = await self._read_addr(reader, atyp)
            if host is None:
                log_for_debugging("SOCKS malformed address", level="error")
                await self._reply(writer, 0x01)
                writer.close()
                return
            if not is_valid_host(host):
                log_for_debugging(
                    f"Rejecting malformed SOCKS host: {host!r}", level="error"
                )
                await self._reply(writer, 0x02)
                writer.close()
                return
            log_for_debugging(f"Connection request to {host}:{port}")
            allowed = await _call_filter(self._filter, port, host)
            if not allowed:
                log_for_debugging(f"Connection blocked to {host}:{port}", level="error")
                await self._reply(writer, 0x02)
                writer.close()
                return
            log_for_debugging(f"Connection allowed to {host}:{port}")

            parent_url = None
            if self._parent_proxy and not should_bypass_parent_proxy(
                self._parent_proxy, host
            ):
                parent_url = select_parent_proxy_url(self._parent_proxy, is_https=True)

            try:
                if parent_url:
                    upstream_reader, upstream_writer = await connect_via_parent_proxy(
                        parent_url, host, port
                    )
                else:
                    upstream_reader, upstream_writer = await dial_direct(host, port)
            except Exception as error:  # noqa: BLE001
                log_for_debugging(
                    f"SOCKS connect to {host}:{port} failed: {error}",
                    level="error",
                )
                await self._reply(writer, 0x04)
                writer.close()
                return

            await self._reply(writer, 0x00)
            await _pipe_bidirectional(reader, writer, upstream_reader, upstream_writer)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _authenticate(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> bool:
        try:
            version = await reader.readexactly(1)
            ulen = (await reader.readexactly(1))[0]
            uname = (await reader.readexactly(ulen)).decode("utf-8", "replace")
            plen = (await reader.readexactly(1))[0]
            passwd = (await reader.readexactly(plen)).decode("utf-8", "replace")
        except (asyncio.IncompleteReadError, ValueError):
            return False
        if version[0] != 0x01 or uname != "srt" or passwd != self._proxy_auth_token:
            log_for_debugging("SOCKS auth rejected", level="error")
            writer.write(b"\x01\x01")
            await writer.drain()
            writer.close()
            return False
        writer.write(b"\x01\x00")
        await writer.drain()
        return True

    async def _read_addr(
        self, reader: asyncio.StreamReader, atyp: int
    ) -> tuple[str | None, int]:
        try:
            if atyp == 0x01:  # IPv4
                raw = await reader.readexactly(4)
                host = socket.inet_ntop(socket.AF_INET, raw)
            elif atyp == 0x03:  # domain
                length = (await reader.readexactly(1))[0]
                host = (await reader.readexactly(length)).decode("utf-8", "replace")
            elif atyp == 0x04:  # IPv6
                raw = await reader.readexactly(16)
                host = socket.inet_ntop(socket.AF_INET6, raw)
            else:
                return None, 0
            port_raw = await reader.readexactly(2)
            port = struct.unpack(">H", port_raw)[0]
        except (asyncio.IncompleteReadError, OSError, UnicodeDecodeError):
            return None, 0
        return host, port

    async def _reply(self, writer: asyncio.StreamWriter, status: int) -> None:
        writer.write(bytes([0x05, status, 0x00, 0x01, 0, 0, 0, 0, 0, 0]))
        await writer.drain()


# ---------------------------------------------------------------------------
# mux proxy (mux-proxy.ts)
# ---------------------------------------------------------------------------

SOCKS_FIRST_BYTES = frozenset([0x04, 0x05])
DEFAULT_FIRST_BYTE_TIMEOUT_SECONDS = 10.0


class MuxProxyServer:
    """Single-port front-end dispatching each connection to the SOCKS
    handler (first byte 0x04/0x05) or to the HTTP backend over a unix
    socket. ADAPT: asyncio; ``unref`` is a no-op (asyncio listeners do not
    keep a loop alive by themselves)."""

    def __init__(
        self,
        http_backend: HttpProxyServer,
        handle_socks: Callable[
            [asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]
        ],
        first_byte_timeout: float = DEFAULT_FIRST_BYTE_TIMEOUT_SECONDS,
    ) -> None:
        self._http_backend = http_backend
        self._handle_socks = handle_socks
        self._first_byte_timeout = first_byte_timeout
        self._server: asyncio.base_events.Server | None = None
        self._backend_sock_path: str | None = None
        self._sock_path: str | None = None

    async def listen_http_backend(self, path: str | None = None) -> None:
        """Start the HTTP backend on a private unix socket. Must be awaited
        before the front-end listens."""
        if path is None:
            self._backend_sock_path = (
                f"/tmp/srt-mux-{os.getpid()}-{id(self):x}.sock"
            )
        else:
            self._backend_sock_path = path
        try:
            os.unlink(self._backend_sock_path)
        except OSError:
            pass
        await self._http_backend.listen(self._backend_sock_path)

    async def listen(self, host: str, port: int) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, host=host, port=port
        )

    def get_port(self) -> int | None:
        if self._server is None or self._server.sockets is None:
            return None
        sock = self._server.sockets[0]
        return int(sock.getsockname()[1])

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        await self._http_backend.close()
        if self._backend_sock_path:
            try:
                os.unlink(self._backend_sock_path)
            except OSError:
                pass
            self._backend_sock_path = None

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            first_byte = await asyncio.wait_for(
                reader.readexactly(1), timeout=self._first_byte_timeout
            )
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError):
            writer.close()
            return
        if first_byte[0] in SOCKS_FIRST_BYTES:
            await self._handle_socks(_UnshiftedReader(reader, first_byte), writer)
        else:
            await self._dispatch_http(reader, writer, first_byte)

    async def _dispatch_http(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        first_byte: bytes,
    ) -> None:
        if self._backend_sock_path is None:
            log_for_debugging(
                "mux: HTTP dispatch before backend bound; dropping",
                level="error",
            )
            writer.close()
            return
        try:
            upstream_reader, upstream_writer = await asyncio.open_unix_connection(
                self._backend_sock_path
            )
        except OSError as error:
            code = getattr(error, "errno", None)
            log_for_debugging(
                f"mux: HTTP backend dial failed: {error}", level="error"
            )
            if not writer.is_closing():
                writer.write(
                    f"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n"
                    f"mux backend dial failed ({code})\n".encode("latin1")
                )
                await writer.drain()
            writer.close()
            return
        upstream_writer.write(first_byte)
        await upstream_writer.drain()
        await _pipe_bidirectional(reader, writer, upstream_reader, upstream_writer)


class _UnshiftedReader:
    """Wraps a StreamReader with a peeked first byte already consumed."""

    def __init__(self, reader: asyncio.StreamReader, prefix: bytes) -> None:
        self._reader = reader
        self._prefix = prefix

    async def readexactly(self, n: int) -> bytes:
        if len(self._prefix) >= n:
            out, self._prefix = self._prefix[:n], self._prefix[n:]
            return out
        out = self._prefix
        self._prefix = b""
        return out + await self._reader.readexactly(n - len(out))

    async def read(self, n: int = -1) -> bytes:
        if self._prefix:
            if n < 0:
                out, self._prefix = self._prefix, b""
                return out + await self._reader.read()
            out, self._prefix = self._prefix[:n], self._prefix[n:]
            return out
        return await self._reader.read(n)

    async def readline(self) -> bytes:
        data = bytearray(self._prefix)
        self._prefix = b""
        while b"\n" not in data:
            chunk = await self._reader.read(4096)
            if not chunk:
                break
            data.extend(chunk)
        line, _, rest = bytes(data).partition(b"\n")
        if rest:
            self._prefix = rest
        return line + (b"\n" if b"\n" in data else b"")

    def at_eof(self) -> bool:
        return not self._prefix and self._reader.at_eof()
