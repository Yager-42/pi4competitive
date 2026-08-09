"""ADR 0016 — ``AgentHarness.attach_extension_runtime_and_rebind``.

FIX: ephemeral sub-agents attach an extension AFTER ``__init__`` (no
``capability_report`` applied), so ``_bind_extension_context`` runs while
``extension_runner`` is still None → returns early → ``getContextUsage`` /
``compact`` never bound → reasonix ``turn_end`` raises
``Extension context action not bound: getContextUsage`` (swallowed by emit) →
compaction never fires. Proven by experiment C.

The new method wraps ``attach_extension_runtime`` (attach runner) +
``_bind_extension_context`` (rebind context_actions to that runner).
"""
from __future__ import annotations

import pytest
from earendil_works.pi_agent import AgentHarness, InMemorySessionRepo
from earendil_works.pi_agent.extensions import (
    attach_extension_runtime,
    create_extension_runtime,
    load_extension_from_factory,
)
from earendil_works.pi_agent.extensions.types import LoadExtensionsResult
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import faux_assistant_message, faux_provider


async def _build_harness() -> tuple[AgentHarness, dict]:
    """Build an ephemeral-style harness with capability_report=None (no runner at __init__)."""
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"]([faux_assistant_message("ok")])
    model = faux["getModel"]()
    repo = InMemorySessionRepo()
    session = await repo.create({"cwd": "ephemeral"})
    harness = AgentHarness(
        session=session,
        stream_fn=models.streamSimple,
        model=model,  # type: ignore[arg-type]
        # capability_report=None — mirrors build_ephemeral; extension_runner
        # is NOT attached in __init__.
    )
    return harness, model


async def _loaded_noop() -> LoadExtensionsResult:
    """A LoadExtensionsResult carrying one no-op extension."""
    runtime = create_extension_runtime()

    def factory(api) -> None:  # type: ignore[no-untyped-def]
        async def on_turn_end(_event, _ctx) -> None:
            return None

        api.on("turn_end", on_turn_end)

    extension = await load_extension_from_factory(factory, "ephemeral", runtime, "<noop>")
    return LoadExtensionsResult(extensions=[extension], errors=[], runtime=runtime)


@pytest.mark.asyncio
async def test_subagent_harness_has_no_runner_at_init() -> None:
    """Bug precondition: capability_report=None → extension_runner is None in __init__.

    _bind_extension_context then returns early (no runner) → context_actions
    never bound until an extension is attached + rebound.
    """
    harness, _ = await _build_harness()
    assert harness.agent.extension_runner is None


@pytest.mark.asyncio
async def test_attach_extension_runtime_alone_leaves_context_unbound() -> None:
    """Regression justification: plain attach_extension_runtime does NOT rebind.

    ``Agent.set_extension_runner`` binds DEFAULT context_actions where
    ``getContextUsage`` returns None and ``compact`` raises "not available on
    Agent". Without the rebind, reasonix ``turn_end`` sees ``getContextUsage()``
    is None → appends ``context_usage_unavailable`` → returns (compaction never
    fires). This is the exact bug on ephemeral sub-agents.
    """
    harness, _ = await _build_harness()
    loaded = await _loaded_noop()
    attach_extension_runtime(harness.agent, loaded, "ephemeral")
    runner = harness.agent.extension_runner
    assert runner is not None
    ctx = runner.create_context()
    # Default: None (not the real usage dict) — reasonix sees this and bails.
    assert ctx.getContextUsage() is None
    # Default compact is "unavailable" — would raise if reasonix ever reached it.
    with pytest.raises(RuntimeError, match="not available on Agent"):
        ctx.compact()
    harness.close()


@pytest.mark.asyncio
async def test_attach_and_rebind_binds_context_actions() -> None:
    """The fix: attach_extension_runtime_and_rebind binds getContextUsage/compact."""
    harness, model = await _build_harness()
    loaded = await _loaded_noop()
    runner = harness.attach_extension_runtime_and_rebind(loaded, "ephemeral")
    assert runner is harness.agent.extension_runner
    ctx = runner.create_context()

    usage = ctx.getContextUsage()
    assert usage is not None
    assert usage["contextWindow"] == int(model.get("contextWindow") or 0)
    assert "tokens" in usage

    # compact context_action toggles the pending flag (accepted → already_pending).
    assert ctx.compact() == "accepted"
    assert ctx.compact() == "already_pending"
    # The harness-level pending flag was set, clear it so close() is clean.
    harness._compaction_pending = False
    harness.close()


@pytest.mark.asyncio
async def test_attach_and_rebind_rebinds_on_second_attach() -> None:
    """A second attach+rebind rebinds context_actions to the new runner."""
    harness, _ = await _build_harness()
    loaded1 = await _loaded_noop()
    runner1 = harness.attach_extension_runtime_and_rebind(loaded1, "ephemeral")
    assert runner1.create_context().getContextUsage() is not None

    loaded2 = await _loaded_noop()
    runner2 = harness.attach_extension_runtime_and_rebind(loaded2, "ephemeral", replace=True)
    assert runner2 is harness.agent.extension_runner
    # New runner has context_actions bound too (not the old unbound state).
    assert runner2.create_context().getContextUsage() is not None
    harness.close()
