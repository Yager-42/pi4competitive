"""Unit — host-side sandbox egress gate (ADR 0016).

Guards ``_build_native_review_domain``, the callback ``runner.answer_network_
request`` consults for every outbound connection the sandboxed worker makes.
Nothing covered this before: the callback did not exist, and with
``review_domain=None`` the runner's ``action = "deny"`` initial value stands,
so every search/fetch tool was denied and coverage stayed 0.
"""
from __future__ import annotations

import socket
from typing import Any

import pytest

from competitive_app.adapter.out.sandbox.native import network_policy
from competitive_app.wiring import _build_native_review_domain, _domain_in_allowlist


def _endpoint(hostname: str, port: int = 443) -> dict[str, Any]:
    return {"hostname": hostname, "port": port, "protocol": "tcp"}


def _resolver(*addresses: tuple[str, int]):
    async def resolve(_hostname: str) -> list[tuple[str, int]]:
        return list(addresses)

    return resolve


# ------------------------------------------------------------- allowlist mode


@pytest.mark.parametrize(
    ("hostname", "expected"),
    [
        ("example.com", True),
        ("api.example.com", True),
        ("a.b.example.com", True),
        ("notexample.com", False),  # suffix match must not span a label
        ("example.com.evil.test", False),
        ("other.test", False),
    ],
)
def test_domain_in_allowlist_matches_on_label_boundary(hostname: str, expected: bool) -> None:
    assert _domain_in_allowlist(hostname, frozenset({"example.com"})) is expected


@pytest.mark.asyncio
async def test_allowlist_allows_listed_and_denies_everything_else() -> None:
    review = _build_native_review_domain(" Example.COM , api.other.test. ")
    assert await review(_endpoint("example.com")) == "allow"
    assert await review(_endpoint("cdn.example.com")) == "allow"
    assert await review(_endpoint("api.other.test")) == "allow"
    assert await review(_endpoint("other.test")) == "deny"  # parent is not listed
    assert await review(_endpoint("tavily.com")) == "deny"


@pytest.mark.asyncio
async def test_allowlist_mode_never_consults_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """The allowlist branch decides on its own; a DNS lookup here would be a
    silent way for a listed-but-private host to be resolved at approval time."""

    async def explode(_hostname: str) -> list[tuple[str, int]]:
        raise AssertionError("allowlist mode must not resolve")

    monkeypatch.setattr(network_policy, "_default_resolver", explode)
    review = _build_native_review_domain("example.com")
    assert await review(_endpoint("example.com")) == "allow"
    assert await review(_endpoint("elsewhere.test")) == "deny"


# --------------------------------------------------------------- default mode


@pytest.mark.asyncio
async def test_default_allows_public_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        network_policy, "_default_resolver", _resolver(("93.184.216.34", 4))
    )
    review = _build_native_review_domain("")
    assert await review(_endpoint("example.com")) == "allow"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.1.2.3",  # RFC1918
        "192.168.1.10",
        "169.254.169.254",  # cloud metadata
        "198.18.0.7",  # proxy fake-ip range
        "100.64.0.1",  # CGNAT
    ],
)
async def test_default_denies_non_public_addresses(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    monkeypatch.setattr(network_policy, "_default_resolver", _resolver((address, 4)))
    review = _build_native_review_domain("")
    assert await review(_endpoint("internal.test")) == "deny"


@pytest.mark.asyncio
async def test_default_denies_mixed_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """One private answer poisons the name: a split-horizon record must not be
    approved on the strength of its public sibling."""
    monkeypatch.setattr(
        network_policy,
        "_default_resolver",
        _resolver(("93.184.216.34", 4), ("10.0.0.5", 4)),
    )
    review = _build_native_review_domain("")
    assert await review(_endpoint("split.test")) == "deny"


@pytest.mark.asyncio
async def test_default_denies_on_dns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(_hostname: str) -> list[tuple[str, int]]:
        raise socket.gaierror("nxdomain")

    monkeypatch.setattr(network_policy, "_default_resolver", fail)
    review = _build_native_review_domain("")
    assert await review(_endpoint("missing.test")) == "deny"


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", ["", "example.com"])
async def test_missing_hostname_is_denied(allowed: str) -> None:
    review = _build_native_review_domain(allowed)
    assert await review(_endpoint("")) == "deny"
    assert await review({"port": 443}) == "deny"
