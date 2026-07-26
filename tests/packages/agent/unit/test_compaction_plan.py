from __future__ import annotations

import pytest

from earendil_works.pi_agent.harness.compaction import isolated_summary, snapshot_fingerprint, validate_compaction_plan


def test_compaction_plan_validation_boundaries() -> None:
    entries = [
        {"id": "a", "message": {"role": "assistant", "content": [{"type": "toolCall", "id": "c"}]}},
        {"id": "b", "message": {"role": "toolResult", "toolCallId": "c", "content": []}},
        {"id": "c", "message": {"role": "user", "content": "active"}},
    ]
    plan = {"version": 1, "snapshotFingerprint": snapshot_fingerprint(entries),
            "foldEntryIds": ["a", "b"], "retainEntryIds": ["c"],
            "summaryInstructions": "summary", "details": {}}
    validate_compaction_plan(plan, entries, {"c"})

    broken = {**plan, "foldEntryIds": ["a"], "retainEntryIds": ["b", "c"]}
    with pytest.raises(ValueError, match="atomic"):
        validate_compaction_plan(broken, entries, {"c"})
    with pytest.raises(ValueError, match="active turn"):
        validate_compaction_plan({**plan, "foldEntryIds": ["a", "b", "c"], "retainEntryIds": []}, entries, {"c"})


@pytest.mark.asyncio
async def test_isolated_summary_retries_without_session_callbacks() -> None:
    calls = []

    class Stream:
        async def result(self):
            if len(calls) == 1:
                raise RuntimeError("retry")
            return {"content": [{"type": "text", "text": "summary"}]}

    def stream_fn(_model, context, options):
        calls.append((context, options))
        return Stream()

    result = await isolated_summary(
        [{"role": "user", "content": "hello"}], "instructions", stream_fn, {"id": "m"},
        {"sessionId": "secret", "onPayload": object(), "cacheRetention": "short"},
    )
    assert result == "summary"
    assert len(calls) == 2
    assert calls[0] == ({"systemPrompt": "instructions", "messages": [{"role": "user", "content": "hello"}], "tools": []},
                        {"cacheRetention": "short"})
