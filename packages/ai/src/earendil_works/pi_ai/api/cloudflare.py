"""Cloudflare AI gateway helpers."""
from __future__ import annotations
from typing import Any

def cloudflare_headers(account_id: str | None = None, gateway_id: str | None = None) -> dict[str, str]:
    h: dict[str, str] = {}
    if account_id:
        h["cf-aig-account-id"] = account_id
    if gateway_id:
        h["cf-aig-gateway-id"] = gateway_id
    return h
