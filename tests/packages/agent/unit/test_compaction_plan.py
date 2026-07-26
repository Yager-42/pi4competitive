from __future__ import annotations

import pytest

from earendil_works.pi_agent.harness.compaction import snapshot_fingerprint, validate_compaction_plan


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
