"""Public-address network policy (COPY-semantics).

Source: pi-sandbox@0.4.2 ``src/network-policy.mjs``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta: Node ``dns.lookup({all: true, verbatim: true})`` is replaced by
``asyncio.getaddrinfo`` over the running event loop (same all-address
resolution semantics); the resolver is injectable for offline tests exactly
like upstream's ``resolve`` parameter. FIX (P3.3 V3 gate): the Node
resolver yields ``4``/``6`` ipaddress versions while ``getaddrinfo`` yields
AF_INET/AF_INET6 constants, so ``_default_resolver`` now maps them to
ipaddress versions — without the map every DNS result was classified
non-public and the broker could never emit a grant request (fail-closed
but silently broken approval). Upstream never resolves via ``isIP``
family checks, so this is a port-only defect.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable

_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")

_PROHIBITED_V4 = [
    ("0.0.0.0", 8),
    ("10.0.0.0", 8),
    ("100.64.0.0", 10),
    ("127.0.0.0", 8),
    ("169.254.0.0", 16),
    ("172.16.0.0", 12),
    ("192.0.0.0", 24),
    ("192.168.0.0", 16),
    ("198.18.0.0", 15),
    ("224.0.0.0", 4),
    ("240.0.0.0", 4),
]
_PROHIBITED_V6 = [
    ("::", 128),
    ("::1", 128),
    ("fc00::", 7),
    ("fe80::", 10),
    ("ff00::", 8),
]

_prohibited_v4 = [ipaddress.ip_network(f"{net}/{pfx}") for net, pfx in _PROHIBITED_V4]
_prohibited_v6 = [ipaddress.ip_network(f"{net}/{pfx}") for net, pfx in _PROHIBITED_V6]

Resolver = Callable[[str], Awaitable[list[tuple[str, int]]]]


def is_public_address(address: str, family: int | None = None) -> bool:
    """True when *address* is a public (non-prohibited) address.

    Family is inferred when omitted (Node ``isIP`` semantics); anything
    that is not a valid IPv4/IPv6 literal returns False.
    """
    if family is None:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return False
        family = 4 if parsed.version == 4 else 6
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if family == 4 and parsed.version == 4:
        return not any(parsed in net for net in _prohibited_v4)
    if family == 6 and parsed.version == 6:
        return not any(parsed in net for net in _prohibited_v6)
    return False


def normalize_public_hostname(value: str) -> str | None:
    """Normalize a public hostname, or None when it is not a plausible
    public DNS name (IP literals, localhost, spaces, bad labels)."""
    hostname = value.strip().rstrip(".").lower()
    if (
        not hostname
        or len(hostname) > 253
        or _is_ip_literal(hostname)
        or "." not in hostname
        or any(
            not label or len(label) > 63 or not _LABEL_RE.match(label)
            for label in hostname.split(".")
        )
    ):
        return None
    return hostname


def _is_ip_literal(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return False


async def _default_resolver(hostname: str) -> list[tuple[str, int]]:
    """All-address DNS resolution (Node lookup all+verbatim parity)."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(
        hostname, None, family=0, type=socket.SOCK_STREAM
    )
    addresses: list[tuple[str, int]] = []
    for family, _socktype, _proto, _canonname, sockaddr in infos:
        ip = sockaddr[0]
        # FIX: map AF_* constants to ipaddress versions (4/6); skip any
        # other family. See the module header host-delta note.
        if family == socket.AF_INET:
            version = 4
        elif family == socket.AF_INET6:
            version = 6
        else:
            continue
        addresses.append((ip, version))
    return addresses


async def validate_public_hostname(
    value: str,
    resolve: Resolver | None = None,
) -> str | None:
    """Return the normalized hostname only when every resolved address is
    public; None for non-public names, mixed/private resolution, or DNS
    failure (fail closed)."""
    hostname = normalize_public_hostname(value)
    if not hostname:
        return None
    resolver = resolve or _default_resolver
    try:
        addresses = await resolver(hostname)
    except Exception:
        return None
    return (
        hostname
        if len(addresses) > 0
        and all(is_public_address(ip, family) for ip, family in addresses)
        else None
    )


__all__ = [
    "Resolver",
    "is_public_address",
    "normalize_public_hostname",
    "validate_public_hostname",
]
