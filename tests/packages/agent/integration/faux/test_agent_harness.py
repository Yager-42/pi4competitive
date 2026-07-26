from __future__ import annotations

from pathlib import Path

import pytest
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import faux_assistant_message, faux_provider

from earendil_works.pi_agent import AgentHarness, JsonlSessionRepo
from earendil_works.pi_agent.extensions import create_extension_runtime, load_extension_from_factory
from earendil_works.pi_agent.extensions import ExtensionRunner
from earendil_works.pi_agent.harness.compaction import snapshot_fingerprint
from earendil_works.pi_agent.harness.env.python_env import LocalFileSystem


@pytest.mark.asyncio
async def test_harness_prompt_persists_jsonl(tmp_path: Path) -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"]([faux_assistant_message("harness-ok")])
    model = faux["getModel"]()

    fs = LocalFileSystem(cwd=str(tmp_path))
    repo = JsonlSessionRepo({"fs": fs, "sessionsRoot": str(tmp_path / "data" / "sessions")})
    session = await repo.create({"cwd": str(tmp_path)})
    harness = AgentHarness(
        session=session,
        stream_fn=models.streamSimple,
        model=model,  # type: ignore[arg-type]
        system_prompt="test",
    )
    await harness.prompt("hello")
    meta = await session.get_metadata()
    reopened = await repo.open(meta)
    ctx = await reopened.build_context()
    roles = [m.get("role") for m in ctx["messages"] if isinstance(m, dict)]
    assert roles[0] == "user"
    assert roles[-1] == "assistant"
    harness.close()


@pytest.mark.asyncio
async def test_harness_applies_compaction_plan_atomically(tmp_path: Path) -> None:
    faux = faux_provider()
    models = create_models()
    models.setProvider(faux["provider"])
    faux["setResponses"]([faux_assistant_message("summary")])
    repo = JsonlSessionRepo({"fs": LocalFileSystem(cwd=str(tmp_path)),
                             "sessionsRoot": str(tmp_path / "sessions")})
    session = await repo.create({"cwd": str(tmp_path)})
    old = {"role": "user", "content": "old", "timestamp": 1}
    active = {"role": "user", "content": "active", "timestamp": 2}
    await session.append_message(old)
    await session.append_message(active)
    harness = AgentHarness(session=session, stream_fn=models.streamSimple,
                           model=faux["getModel"]())
    harness.agent.state.messages = [old, active]

    runtime = create_extension_runtime()

    def factory(api) -> None:
        def plan(event, _ctx):
            entries = event["preparation"]["entries"]
            return {"compactionPlan": {
                "version": 1, "snapshotFingerprint": snapshot_fingerprint(entries),
                "foldEntryIds": [entries[0]["id"]], "retainEntryIds": [entries[1]["id"]],
                "summaryInstructions": "summarize", "details": {},
            }}
        api.on("session_before_compact", plan)

    extension = await load_extension_from_factory(factory, tmp_path, runtime)
    harness.agent.set_extension_runner(ExtensionRunner([extension], runtime, tmp_path))
    harness._bind_extension_context()
    ctx = harness.agent.extension_runner.create_context()
    assert ctx.getContextUsage()["contextWindow"] == faux["getModel"]()["contextWindow"]
    assert ctx.compact() == "accepted"
    assert ctx.compact() == "already_pending"
    result = await harness.compact()
    assert result and result["summary"] == "summary"
    assert [message["content"] for message in harness.agent.state.messages if message["role"] == "user"] == ["active"]
    assert any(entry["type"] == "compaction" for entry in await session.get_branch())
    harness.close()
