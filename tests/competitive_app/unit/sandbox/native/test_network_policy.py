"""O4 — public-address network policy vectors (PORT of network-policy.test.ts).

Source: pi-sandbox@0.4.2 ``network-policy.test.ts``
License: Apache-2.0 (retained under the native sandbox license directory)
"""
from __future__ import annotations

import asyncio

import pytest

from competitive_app.adapter.out.sandbox.native.network_policy import (
    is_public_address,
    normalize_public_hostname,
    validate_public_hostname,
)


def test_network_review_accepts_only_normalized_domain_names() -> None:
    assert normalize_public_hostname("API.Example.COM.") == "api.example.com"
    assert normalize_public_hostname("127.0.0.1") is None
    assert normalize_public_hostname("localhost") is None
    assert normalize_public_hostname("bad host.example") is None
    assert normalize_public_hostname("") is None
    assert normalize_public_hostname("no-dot") is None


def test_private_loopback_link_local_and_multicast_are_prohibited() -> None:
    for address in [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "192.168.1.1",
        "::1",
        "fd00::1",
        "fe80::1",
    ]:
        assert is_public_address(address) is False, address
    assert is_public_address("93.184.216.34") is True
    assert is_public_address("2606:2800:220:1:248:1893:25c8:1946") is True


def test_invalid_and_non_ip_inputs_are_not_public() -> None:
    assert is_public_address("not-an-ip") is False
    assert is_public_address("") is False
    assert is_public_address("127.0.0.1", 6) is False  # family mismatch


def test_domain_resolving_to_any_prohibited_address_fails_closed() -> None:
    async def mixed_resolver(_hostname: str):
        return [("93.184.216.34", 4), ("127.0.0.1", 4)]

    assert (
        asyncio.run(validate_public_hostname("example.com", mixed_resolver)) is None
    )


def test_all_public_resolution_accepts() -> None:
    async def public_resolver(_hostname: str):
        return [("93.184.216.34", 4)]

    assert (
        asyncio.run(validate_public_hostname("example.com", public_resolver))
        == "example.com"
    )


def test_resolution_failure_fails_closed() -> None:
    async def failing_resolver(_hostname: str):
        raise OSError("nxdomain")

    assert (
        asyncio.run(validate_public_hostname("example.com", failing_resolver)) is None
    )


def test_empty_resolution_fails_closed() -> None:
    async def empty_resolver(_hostname: str):
        return []

    assert (
        asyncio.run(validate_public_hostname("example.com", empty_resolver)) is None
    )


@pytest.mark.parametrize(
    "hostname",
    [
        "127.0.0.1",
        "localhost",
        "bad host.example",
        "1.2.3.4",
        "x" * 254,
    ],
)
def test_non_public_inputs_never_reach_the_resolver(hostname: str) -> None:
    called = False

    async def spy_resolver(_hostname: str):
        nonlocal called
        called = True
        return [("93.184.216.34", 4)]

    assert asyncio.run(validate_public_hostname(hostname, spy_resolver)) is None
    assert called is False


def test_real_default_resolver_maps_af_constants_to_ipaddress_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for the P3.3 V3-gate fix: getaddrinfo yields AF_INET/
    AF_INET6 (2/30) while is_public_address expects ipaddress versions
    (4/6); without the map every real DNS result was non-public and the
    broker could never emit a grant request."""
    import socket

    async def fake_getaddrinfo(
        hostname: str,
        _port: None,
        *,
        family: int,
        type: int,
    ):
        assert hostname == "example.com"
        assert family == 0
        assert type == socket.SOCK_STREAM
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                6,
                "",
                ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0),
            ),
        ]

    async def _scenario() -> str | None:
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
        return await validate_public_hostname("example.com")

    assert asyncio.run(_scenario()) == "example.com"
