"""Live P1 smoke as pytest (same gateway contract as scripts/smoke_live_model.py)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_live_complete_simple_pong(live_gateway) -> None:
    models = live_gateway["models"]
    model = live_gateway["model"]
    msg = await models.completeSimple(
        model,
        {
            "systemPrompt": "Reply with exactly: pong",
            "messages": [
                {"role": "user", "content": "Reply with exactly: pong", "timestamp": 0},
            ],
        },
        {"apiKey": live_gateway["api_key"]},
    )
    stop = msg.get("stopReason")
    assert stop in ("stop", "length", "toolUse"), (
        f"stopReason={stop} error={msg.get('errorMessage')}"
    )
    text = ""
    for block in msg.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text") or ""
    assert text  # non-empty completion
