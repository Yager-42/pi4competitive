"""Unit — _public_host_review_domain (native_runtime network approval gate).

FIX: search provider calls (tavily/anysearch/grok) were 403'd because the
runner's ``review_domain`` was unset → default deny. This gate allows public
hosts, denies private/mixed/unresolvable (fail closed).
"""
from __future__ import annotations

import pytest

from competitive_app.adapter.out.sandbox.native.native_runtime import (
    _public_host_review_domain,
)


async def _resolve_factory(addresses: list[tuple[str, int]]):
    async def _resolve(_hostname: str) -> list[tuple[str, int]]:
        return list(addresses)

    return _resolve


@pytest.mark.asyncio
async def test_public_host_allowed() -> None:
    # 8.8.8.8 is a public DNS resolver (not in prohibited private ranges)
    resolve = await _resolve_factory([("8.8.8.8", 4)])
    result = await _public_host_review_domain(
        {"hostname": "api.tavily.com", "port": 443, "protocol": "tcp"},
        resolve=resolve,
    )
    assert result == "allow"


@pytest.mark.asyncio
async def test_private_host_denied() -> None:
    # 10.0.0.1 is RFC1918 private → must deny (fail closed)
    resolve = await _resolve_factory([("10.0.0.1", 4)])
    result = await _public_host_review_domain(
        {"hostname": "internal.local", "port": 80, "protocol": "tcp"},
        resolve=resolve,
    )
    assert result == "deny"


@pytest.mark.asyncio
async def test_mixed_resolution_denied() -> None:
    # One public + one private address → fail closed (mixed resolution)
    resolve = await _resolve_factory([("8.8.8.8", 4), ("192.168.1.1", 4)])
    result = await _public_host_review_domain(
        {"hostname": "ambiguous.example", "port": 443, "protocol": "tcp"},
        resolve=resolve,
    )
    assert result == "deny"


@pytest.mark.asyncio
async def test_unresolvable_denied() -> None:
    # Empty resolution (DNS failure) → fail closed
    resolve = await _resolve_factory([])
    result = await _public_host_review_domain(
        {"hostname": "nonexistent.invalid", "port": 443, "protocol": "tcp"},
        resolve=resolve,
    )
    assert result == "deny"


@pytest.mark.asyncio
async def test_empty_hostname_denied() -> None:
    resolve = await _resolve_factory([("8.8.8.8", 4)])
    result = await _public_host_review_domain(
        {"hostname": "", "port": 443, "protocol": "tcp"}, resolve=resolve
    )
    assert result == "deny"


@pytest.mark.asyncio
async def test_resolver_exception_denied() -> None:
    async def _raising_resolve(_hostname: str):
        raise RuntimeError("DNS explosion")

    result = await _public_host_review_domain(
        {"hostname": "api.tavily.com", "port": 443, "protocol": "tcp"},
        resolve=_raising_resolve,
    )
    assert result == "deny"


@pytest.mark.asyncio
async def test_endpoint_object_attribute_access() -> None:
    # review_domain may receive an object (not dict) with .hostname attribute
    resolve = await _resolve_factory([("8.8.8.8", 4)])

    class _Endpoint:
        hostname = "api.tavily.com"

    result = await _public_host_review_domain(_Endpoint(), resolve=resolve)
    assert result == "allow"
