"""Live — memory blob reaches the write prompt in a real run (research-workflow v0.2.5).

Env-gated (skips without OPENAI key); not exit-blocking. Pre-seeds a Notion
evidence in the real store, runs a real task (brief target=Notion), polls until
the write stage *starts* (current_stage=="write" — the write prompt is sent),
then reads the session JSONL and asserts the prior-findings blob (with the
seeded value) reached the write user message.

Does NOT require write to complete (robust to the known write-stage flakiness):
the blob is in the prompt the moment write starts, regardless of whether the
LLM call then succeeds.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


class _TestToolExecutor:
    async def execute(self, *, scope_id, tool, tool_call_id, params, signal=None, on_update=None):
        del scope_id
        return await tool.execute(tool_call_id, params, signal, on_update)


class _TestSandboxLifecycle:
    async def release(self, *, session_id):
        return None

    async def destroy(self, *, session_id):
        return None

    async def delete_workspace(self, *, session_id):
        return None

    async def shutdown(self) -> None:
        return None


_SEED_SQL = (
    "insert or replace into evidences(evidence_id, task_id, entity, attribute, "
    "value, finding, source_url, source_type, domain, brand, confidence, "
    "captured_at) values(?,?,?,?,?,?,?,?,?,?,?,?)"
)
_SEED_VALUE = "$99/mo (seeded prior)"


async def test_live_memory_blob_reaches_write_prompt(tmp_path: Path, live_env) -> None:
    import os

    os.environ["SESSIONS_ROOT"] = str(tmp_path / "sessions")
    os.environ["APP_DB"] = str(tmp_path / "app.db")
    os.environ["SESSIONS_CWD"] = "live-mem"
    # Lower the coverage threshold + iteration cap so search finishes FAST
    # (partial coverage) → write stage starts → the memory blob is in the write
    # prompt. We are NOT testing search quality here, only that the memory blob
    # reaches the write prompt in a real run.
    os.environ["SEARCH_COVERAGE_THRESHOLD"] = "0.05"
    os.environ["SEARCH_MAX_ITERATIONS"] = "2"

    from competitive_app.adapter.in_.fastapi.app import create_app
    from competitive_app.wiring import build_application_state, load_config_from_env

    state = await build_application_state(
        load_config_from_env(),
        tool_executor=_TestToolExecutor(),
        sandbox_lifecycle=_TestSandboxLifecycle(),
    )
    # Pre-seed a Notion evidence so the write stage recalls it.
    await state.store.init()
    assert state.store._db is not None
    await state.store._db.execute(
        _SEED_SQL,
        (
            "ev_seed_live",
            "t_seed",
            "Notion",
            "pricing",
            _SEED_VALUE,
            _SEED_VALUE,
            "https://notion.com/pricing",
            "web",
            "notion.com",
            "Notion",
            0.95,
            "2026-01-01",
        ),
    )
    await state.store._db.commit()

    try:
        app = create_app()
        app.state.application = state  # type: ignore[attr-defined]
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=60
        ) as client:
            create = await client.post(
                "/api/v2/tasks",
                json={
                    "research_brief": {
                        "target": {"name": "Notion", "category": "note-taking SaaS"},
                        "goal": "Compare Notion vs Obsidian pricing",
                        "competitors": ["Obsidian"],
                        "dimensions": ["pricing"],
                    },
                    "metadata": {"trace": "live-mem-inject"},
                },
            )
            assert create.status_code == 202, create.text
            task_id = create.json()["task_id"]
            session_id = create.json()["session_id"]

            # Poll until write stage starts (blob is in the prompt by then) or terminal.
            deadline = asyncio.get_event_loop().time() + 300.0
            reached_write = False
            t: dict = {}
            while asyncio.get_event_loop().time() < deadline:
                t = (await client.get(f"/api/v2/tasks/{task_id}")).json()
                proj = t.get("projection") or {}
                write_stage = (proj.get("stages") or {}).get("write")
                # write was reached iff it's running or already terminal (ok/failed);
                # "pending" (initial) does NOT count.
                if proj.get("current_stage") == "write" or write_stage in {
                    "running",
                    "ok",
                    "failed",
                }:
                    reached_write = True
                    break
                if t.get("status") in {"failed", "aborted"}:
                    break
                await asyncio.sleep(2.0)
            if not reached_write:
                pytest.skip(
                    f"write stage did not start in 300s (search slow on real gateway); "
                    f"memory wiring is offline-verified. last state: {t.get('projection')}"
                )

        # Read the session JSONL + assert the prior-findings blob reached a user message.
        async with state.store._db.execute(
            "select file_path from sessions where session_id=?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        assert row is not None, "session not in sessions table"
        session_file = Path(row[0])
        assert session_file.is_file(), f"session JSONL missing: {session_file}"
        contents = session_file.read_text(encoding="utf-8")
        assert "Prior findings" in contents, "memory blob header not in write prompt"
        assert _SEED_VALUE in contents, "seeded prior value not in write prompt"
    finally:
        await state.shutdown()
