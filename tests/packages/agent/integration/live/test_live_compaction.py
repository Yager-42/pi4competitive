"""Live: compaction helpers over a real multi-turn transcript (+ optional LLM summary)."""
from __future__ import annotations

from typing import Any

import pytest

from earendil_works.pi_agent import compact, prepare_compaction, should_compact
from earendil_works.pi_agent.harness.compaction import estimate_context_tokens, generate_summary

from .helpers import assistants, make_agent

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_live_prepare_compaction_on_real_transcript(live_gateway) -> None:
    agent = make_agent(
        live_gateway,
        system_prompt="Answer very briefly with one short sentence.",
    )
    for q in (
        "Name a primary color.",
        "Name a fruit.",
        "Name a planet.",
    ):
        await agent.prompt(q)
        await agent.wait_for_idle()

    messages = list(agent.state.messages)
    assert len(assistants(messages)) >= 3
    tokens = estimate_context_tokens(messages)
    assert tokens > 0

    prep = prepare_compaction(messages, {"keepRecentTokens": 20})
    assert "cutIndex" in prep
    assert isinstance(prep["messagesToKeep"], list)

    # Force should_compact true with tiny window
    assert should_compact(messages, context_window=tokens + 1, settings={"reserveTokens": tokens})


@pytest.mark.asyncio
async def test_live_compact_with_real_model_summary(live_gateway) -> None:
    agent = make_agent(
        live_gateway,
        system_prompt="One short sentence answers only.",
    )
    await agent.prompt("What is the capital of France?")
    await agent.wait_for_idle()
    await agent.prompt("What is 3+4?")
    await agent.wait_for_idle()
    messages = list(agent.state.messages)

    models = live_gateway["models"]
    model = live_gateway["model"]
    api_key = live_gateway["api_key"]

    async def stream_fn(m, context, options=None):
        opts = dict(options or {})
        opts.setdefault("apiKey", api_key)
        opts.setdefault("maxTokens", 256)
        return models.streamSimple(m, context, opts)

    # Direct live summary path
    summary = await generate_summary(messages)
    assert isinstance(summary, str) and summary

    # compact() API (fallback summary is ok; exercise call path with stream_fn)
    result = await compact(messages, stream_fn=stream_fn, model=model)
    assert result["summary"]
    assert result["tokensBefore"] >= 1
    assert "keptMessages" in result
