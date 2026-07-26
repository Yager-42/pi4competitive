from __future__ import annotations

import json
from datetime import UTC, datetime
import os
from pathlib import Path

import pytest

from earendil_works.pi_ai.api.anthropic_messages import stream_simple as anthropic_stream
from earendil_works.pi_ai.api.openai_completions import stream_simple as openai_stream
from earendil_works.pi_agent import AgentHarness, JsonlSessionRepo, load_capability_packages
from earendil_works.pi_agent.harness.env.python_env import LocalFileSystem
from tests.live_env import load_dotenv


ROOT = Path(__file__).parents[4]


@pytest.mark.live
@pytest.mark.asyncio
async def test_reasonix_full_stack_live_warm_cache(tmp_path: Path) -> None:
    """C8: loader → Reasonix → Harness/Session → agent → ai adapter → provider → E1."""
    load_dotenv()
    key = os.environ.get("P3_2_LIVE_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("MODEL_API_KEY")
    model_id = os.environ.get("P3_2_LIVE_MODEL_ID") or os.environ.get("OPENAI_MODEL") or os.environ.get("MODEL_NAME")
    base_url = os.environ.get("P3_2_LIVE_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or os.environ.get("MODEL_BASE_URL")
    family = os.environ.get("P3_2_LIVE_API_FAMILY", "openai-completions")
    if not all((key, model_id, base_url)):
        pytest.skip("explicit P3.2 or existing OpenAI live credentials are required")
    if family not in {"openai-completions", "anthropic-messages"}:
        pytest.skip("P3_2_LIVE_API_FAMILY must be openai-completions or anthropic-messages")

    report = await load_capability_packages(
        ROOT / "capability_packages", enabled=["reasonix_prefix_cache"]
    )
    assert not report.tool_names()
    adapter = openai_stream if family == "openai-completions" else anthropic_stream

    def configured_stream(model, context, options=None):
        return adapter(model, context, {**(options or {}), "apiKey": key, "cacheRetention": "short"})

    model = {
        "id": model_id,
        "name": model_id,
        "api": family,
        "provider": os.environ.get("P3_2_LIVE_PROVIDER", "p3-2-live"),
        "baseUrl": base_url,
        "contextWindow": int(os.environ.get("P3_2_LIVE_CONTEXT_WINDOW", "128000")),
        "maxTokens": 64,
    }
    repo = JsonlSessionRepo({
        "fs": LocalFileSystem(cwd=str(tmp_path)), "sessionsRoot": str(tmp_path / "sessions")
    })
    session = await repo.create({"cwd": str(tmp_path)})
    stable_prefix = "Stable cache prefix. " * 1200
    harness = AgentHarness(
        session=session, stream_fn=configured_stream, model=model,
        system_prompt=stable_prefix, capability_report=report,
    )
    try:
        await harness.prompt("Reply with exactly: one")
        first = next(message for message in reversed(harness.agent.state.messages)
                     if message.get("role") == "assistant")
        await harness.prompt("Reply with exactly: two")
        second = next(message for message in reversed(harness.agent.state.messages)
                      if message.get("role") == "assistant")
        assert not first.get("errorMessage")
        assert not second.get("errorMessage")
        assert int((second.get("usage") or {}).get("cacheRead") or 0) > 0

        message_handler = report.extension_runner.extensions[0].handlers["message_end"][0]
        state = next(cell.cell_contents for cell in message_handler.__closure__
                     if hasattr(cell.cell_contents, "buckets"))
        assert any(bucket["cacheRead"] > 0 for bucket in state.buckets.values())
        assert state.epoch == 0
        print(json.dumps({
            "provider_family": family,
            "model_id": model_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "result": "pass",
            "first_cache_read": int((first.get("usage") or {}).get("cacheRead") or 0),
            "first_cache_write": int((first.get("usage") or {}).get("cacheWrite") or 0),
            "second_cache_read": int((second.get("usage") or {}).get("cacheRead") or 0),
            "second_cache_write": int((second.get("usage") or {}).get("cacheWrite") or 0),
            "prefix_digest": state.baseline,
            "prefix_length": len(stable_prefix),
            "epoch": state.epoch,
        }, sort_keys=True))
    finally:
        await harness.shutdown()
