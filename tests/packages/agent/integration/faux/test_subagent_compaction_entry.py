"""ADR 0016 + research-workflow v0.2.9 — multi-turn sub-agent compaction entry.

End-to-end offline proof that the A1 mechanism produces a compaction entry on a
sub-agent (experiment C proved compaction TRIGGERS but produced NO entry because
``activeTurnEntryIds=ALL`` on a single-turn session).

Setup mirrors ``wiring.build_ephemeral``: a harness with ``capability_report=None``
gets reasonix attached via ``attach_extension_runtime_and_rebind`` (rebinds
``getContextUsage``/``compact``). Two ``harness.prompt`` calls create a multi-turn
session. Round 1 is small (below threshold → no compaction); round 2 is large
(triggers compaction). With a second user message, ``activeTurnEntryIds`` is now
just round 2, so reasonix ``before_compact`` folds round 1 → ``append_compaction``
→ a compaction entry appears in the session branch.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from earendil_works.pi_agent import AgentHarness, InMemorySessionRepo
from earendil_works.pi_agent.extensions import (
    create_extension_runtime,
)
from earendil_works.pi_agent.extensions.types import LoadExtensionsResult
from earendil_works.pi_agent.package_manager import load_capability_packages
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import faux_assistant_message, faux_provider

ROOT = Path(__file__).resolve().parents[5]


async def _reasonix_extensions() -> list:
    """Load the real reasonix extension(s) fresh (mirrors build_ephemeral)."""
    report = await load_capability_packages(
        cwd=ROOT, enabled=["reasonix_prefix_cache"]
    )
    if report and report.extension_result:
        return list(report.extension_result.extensions)
    return []


@pytest.mark.asyncio
async def test_multiturn_compaction_produces_entry() -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    # round 1 small (below 6400 threshold for window=8000); round 2 large (above);
    # one more response for the isolated_summary call inside compact().
    big = "round2 " + "x" * 40_000  # ~10k tokens > 6400
    faux["setResponses"]([
        faux_assistant_message("round1 small"),
        faux_assistant_message(big),
        faux_assistant_message("compaction summary"),
    ])
    base_model = faux["getModel"]()
    model = {**base_model, "contextWindow": 8000}

    repo = InMemorySessionRepo()
    session = await repo.create({"cwd": "ephemeral"})
    harness = AgentHarness(
        session=session,
        stream_fn=models.streamSimple,
        model=model,  # type: ignore[arg-type]
        # capability_report=None — no runner at __init__ (the sub-agent case).
    )

    # Attach reasonix via the ADR 0016 method (attach + rebind context_actions).
    runtime = create_extension_runtime()
    extensions = await _reasonix_extensions()
    assert extensions, "reasonix extension failed to load"
    loaded = LoadExtensionsResult(extensions=extensions, errors=[], runtime=runtime)
    harness.attach_extension_runtime_and_rebind(loaded, "ephemeral")

    # Multi-turn: two user messages (what coverage_engine v0.2.9 round 1 + 2 do).
    await harness.prompt("round 1 user")
    await harness.prompt("round 2 user")

    branch = await session.get_branch()
    compactions = [e for e in branch if e.get("type") == "compaction"]
    assert compactions, (
        f"expected a compaction entry after multi-turn; branch types="
        f"{[e.get('type') for e in branch]}"
    )
    harness._compaction_pending = False
    harness.close()
