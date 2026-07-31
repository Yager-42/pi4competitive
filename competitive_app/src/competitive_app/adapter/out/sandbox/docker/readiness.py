"""Readiness polling for the pinned AIO sandbox server."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

import httpx

from ..types import READINESS_TIMEOUT_SECONDS, REQUEST_TIMEOUT_SECONDS


def _identity_matches(
    payload: Any,
    *,
    expected_build_identity: str | None,
    expected_protocol: str | None,
    expected_protocol_version: int | None,
) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if expected_build_identity is not None and payload.get("buildIdentity") != expected_build_identity:
        return False
    if expected_protocol is not None and payload.get("protocol") != expected_protocol:
        return False
    if expected_protocol_version is not None and payload.get("protocolVersion") != expected_protocol_version:
        return False
    return True


def _ready_response(
    response: httpx.Response,
    *,
    expected_build_identity: str | None,
    expected_protocol: str | None,
    expected_protocol_version: int | None,
) -> bool:
    if response.status_code != 200:
        return False
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not _identity_matches(
        payload,
        expected_build_identity=expected_build_identity,
        expected_protocol=expected_protocol,
        expected_protocol_version=expected_protocol_version,
    ):
        return False
    if isinstance(payload, Mapping):
        status = payload.get("status") or payload.get("state")
        if status is not None and str(status).lower() not in {"ready", "healthy", "running", "ok"}:
            return False
    return True


async def wait_for_sandbox_ready_async(
    sandbox_url: str,
    timeout: float = READINESS_TIMEOUT_SECONDS,
    poll_interval: float = 1.0,
    *,
    expected_build_identity: str | None = None,
    expected_protocol: str | None = None,
    expected_protocol_version: int | None = None,
) -> bool:
    """Poll ``/v1/sandbox`` without blocking the event loop."""
    if not sandbox_url:
        return False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, timeout)
    async with httpx.AsyncClient(timeout=float(REQUEST_TIMEOUT_SECONDS)) as client:
        while loop.time() < deadline:
            remaining = max(0.01, deadline - loop.time())
            try:
                response = await client.get(
                    f"{sandbox_url.rstrip('/')}/v1/sandbox",
                    timeout=min(float(REQUEST_TIMEOUT_SECONDS), remaining),
                )
                if _ready_response(
                    response,
                    expected_build_identity=expected_build_identity,
                    expected_protocol=expected_protocol,
                    expected_protocol_version=expected_protocol_version,
                ):
                    return True
            except (httpx.HTTPError, OSError):
                pass
            await asyncio.sleep(min(max(0.0, poll_interval), max(0.0, deadline - loop.time())))
    return False


def wait_for_sandbox_ready(
    sandbox_url: str,
    timeout: float = READINESS_TIMEOUT_SECONDS,
    poll_interval: float = 1.0,
    *,
    expected_build_identity: str | None = None,
    expected_protocol: str | None = None,
    expected_protocol_version: int | None = None,
) -> bool:
    """Synchronous compatibility helper for non-FastAPI diagnostics."""
    deadline = time.monotonic() + max(0.0, timeout)
    with httpx.Client(timeout=float(REQUEST_TIMEOUT_SECONDS)) as client:
        while time.monotonic() < deadline:
            remaining = max(0.01, deadline - time.monotonic())
            try:
                response = client.get(
                    f"{sandbox_url.rstrip('/')}/v1/sandbox",
                    timeout=min(float(REQUEST_TIMEOUT_SECONDS), remaining),
                )
                if _ready_response(
                    response,
                    expected_build_identity=expected_build_identity,
                    expected_protocol=expected_protocol,
                    expected_protocol_version=expected_protocol_version,
                ):
                    return True
            except (httpx.HTTPError, OSError):
                pass
            time.sleep(min(max(0.0, poll_interval), max(0.0, deadline - time.monotonic())))
    return False


__all__ = ["wait_for_sandbox_ready", "wait_for_sandbox_ready_async"]
