from __future__ import annotations

from pathlib import Path

import pytest
from earendil_works.pi_ai import create_models
from earendil_works.pi_ai.providers.faux import faux_assistant_message, faux_provider

from earendil_works.pi_agent import AgentHarness, JsonlSessionRepo
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
