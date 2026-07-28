"""Live L1 — three-stage research workflow against a real provider.

research-workflow-v1 v0.2.0 §6.2 L1: real provider key → POST /tasks runs the
three stages (plan/search/write) over the network with judge extraction →
/report returns non-empty markdown.

Marked @pytest.mark.live; skipped without key (conftest L2).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


_TASK_BODY = {
    "research_brief": {
        "target": {"name": "Notion", "category": "note-taking SaaS"},
        "goal": "Compare Notion vs Obsidian for personal note-taking",
        "competitors": ["Obsidian"],
        "dimensions": ["pricing", "features"],
    },
    "metadata": {"trace": "live-l1"},
}


async def _client(state):
    from competitive_app.adapter.in_.fastapi.app import create_app

    app = create_app()
    app.state.application = state  # type: ignore[attr-defined]
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wait_terminal(client: AsyncClient, task_id: str, timeout: float = 180.0) -> str:
    deadline = asyncio.get_event_loop().time() + timeout
    status = "pending"
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/v2/tasks/{task_id}")
        status = resp.json().get("status")
        if status in {"completed", "failed", "aborted"}:
            return status
        await asyncio.sleep(1.0)
    return status


async def test_live_three_stages_real_provider(tmp_path: Path, live_env) -> None:
    import os

    os.environ["SESSIONS_ROOT"] = str(tmp_path / "sessions")
    os.environ["APP_DB"] = str(tmp_path / "app.db")
    os.environ["SESSIONS_CWD"] = "live-test"
    # Use the default whitelist (echo + search_* + Reasonix prefix cache);
    # search packages load when their env keys are present, fail-closed otherwise.

    from competitive_app.wiring import build_application_state, load_config_from_env

    state = await build_application_state(load_config_from_env())
    try:
        async with await _client(state) as client:
            # 1) POST /tasks — kick off the six-stage runner.
            create = await client.post("/api/v2/tasks", json=_TASK_BODY)
            assert create.status_code == 202, create.text
            task_id = create.json()["task_id"]
            session_id = create.json()["session_id"]
            assert session_id, "POST /tasks must return a session_id"

            # 2) Poll GET /tasks/{id} until terminal.
            status = await _wait_terminal(client, task_id, timeout=360.0)
            assert status == "completed", f"live run did not complete: {status}"

            # 3) GET /tasks/{id} — projection shows all three stages ok (v0.2.0).
            task = await client.get(f"/api/v2/tasks/{task_id}")
            assert task.status_code == 200
            proj = task.json()["projection"]
            assert proj["current_stage"] is None
            for stage in ("plan", "search", "write"):
                assert proj["stages"][stage] == "ok", f"{stage} not ok: {proj['stages']}"
            # Coverage map was driven by the search stage.
            assert proj["coverage"]["total"] > 0, "live run must build a coverage map"

            # 4) GET /tasks — list contains the task.
            listed = await client.get("/api/v2/tasks")
            assert listed.status_code == 200
            assert any(t["task_id"] == task_id for t in listed.json()["tasks"])

            # 5) GET /tasks/{id}/report — write stage markdown.
            report = await client.get(f"/api/v2/tasks/{task_id}/report")
            assert report.status_code == 200
            r = report.json()
            assert r["stage"] == "write"
            assert r["report"], "live report markdown must be non-empty (L1)"

            # 6) GET /tasks/{id}/sessions — 1:1 single element.
            sessions = await client.get(f"/api/v2/tasks/{task_id}/sessions")
            assert sessions.status_code == 200
            sl = sessions.json()["sessions"]
            assert len(sl) == 1
            assert sl[0]["session_id"] == session_id

            # 7) GET /sessions/{id} — session indexed.
            sess = await client.get(f"/api/v2/sessions/{session_id}")
            assert sess.status_code == 200
            assert sess.json()["session_id"] == session_id

            # 8) GET /sessions/{id}/messages — contains three stage outputs +
            #    the write report text (verify via interface, not service).
            msgs = await client.get(f"/api/v2/sessions/{session_id}/messages")
            assert msgs.status_code == 200
            messages = msgs.json()["messages"]
            blob = _stringify_messages(messages)
            # Three stage_output custom_message entries (one per stage, v0.2.0).
            customs = [m for m in messages if isinstance(m, dict) and m.get("role") == "custom"]
            assert len(customs) == 3, f"expected 3 stage_output entries, got {len(customs)}"
            # The write report text appears in the serialized messages (use a
            # short newline-free prefix — JSON escaping turns \n into \\n).
            prefix = r["report"].split("\n")[0][:40]
            assert prefix and prefix in blob, f"write report prefix not in /messages: {prefix!r}"
            # Each stage prompt produced an assistant message; expect >= 3
            # (plan + write; search drives sub-agents that don't persist to JSONL).
            assistant_count = sum(
                1 for m in messages if isinstance(m, dict) and m.get("role") == "assistant"
            )
            assert assistant_count >= 2, f"expected >=2 assistant messages, got {assistant_count}"
    finally:
        await state.shutdown()


async def test_live_multiturn_collect_retry_cache(tmp_path: Path, live_env) -> None:
    """Real app session: collect tool loop, then retry under one stable prefix."""
    import json
    import os

    os.environ["SESSIONS_ROOT"] = str(tmp_path / "sessions")
    os.environ["APP_DB"] = str(tmp_path / "app.db")
    os.environ["SESSIONS_CWD"] = "live-cache-test"

    from competitive_app.wiring import build_application_state, load_config_from_env

    state = await build_application_state(load_config_from_env())
    stable_protocol = (
        "You are an evidence collector. Keep the research protocol and tool schemas stable. "
        "Use search tools before answering, preserve source URLs, and return concise findings. "
        * 140
    )
    try:
        async with await _client(state) as client:
            created = await client.post(
                "/api/v2/sessions",
                json={"system_prompt": stable_protocol},
            )
            assert created.status_code == 200, created.text
            session_id = created.json()["session_id"]

            first = await client.post(
                f"/api/v2/sessions/{session_id}/prompt",
                json={
                    "content": (
                        "Collect current Notion and Obsidian pricing evidence. "
                        "Make at least one search-tool call, then summarize with source URLs."
                    )
                },
            )
            assert first.status_code == 200, first.text

            retry = await client.post(
                f"/api/v2/sessions/{session_id}/prompt",
                json={
                    "content": (
                        "Retry the collection for missing official pricing evidence. "
                        "Make another search-tool call with a different query, then revise the summary."
                    )
                },
            )
            assert retry.status_code == 200, retry.text

            response = await client.get(f"/api/v2/sessions/{session_id}/messages")
            assert response.status_code == 200, response.text
            messages = response.json()["messages"]
            assistants = [m for m in messages if isinstance(m, dict) and m.get("role") == "assistant"]
            tool_results = [m for m in messages if isinstance(m, dict) and m.get("role") == "toolResult"]
            assert len(assistants) >= 4, "two collect turns must each enter a tool loop"
            assert len(tool_results) >= 2, "collect + retry must execute real search tools"

            usage = [m.get("usage") or {} for m in assistants]
            cache_read = sum(int(item.get("cacheRead") or 0) for item in usage)
            cache_write = sum(int(item.get("cacheWrite") or 0) for item in usage)
            input_tokens = sum(int(item.get("input") or 0) for item in usage)
            denominator = input_tokens + cache_read
            assert cache_read > 0, "multi-turn collect + retry must produce a real warm-cache hit"
            print(json.dumps({
                "enabled": os.environ.get("CAPABILITY_PACKAGES_ENABLED", "<default>"),
                "assistant_requests": len(assistants),
                "tool_results": len(tool_results),
                "input_tokens": input_tokens,
                "cache_read": cache_read,
                "cache_write": cache_write,
                "cache_rate": cache_read / denominator if denominator else 0,
            }, sort_keys=True))
    finally:
        await state.shutdown()

async def test_live_tool_order_perturbation_cache(tmp_path: Path, live_env) -> None:
    """Reverse model-visible tools between warm and measured requests."""
    import json
    import os
    from dataclasses import replace

    os.environ["SESSIONS_ROOT"] = str(tmp_path / "sessions")
    os.environ["APP_DB"] = str(tmp_path / "app.db")
    os.environ["SESSIONS_CWD"] = "live-tool-order-test"
    from competitive_app.wiring import build_application_state, load_config_from_env

    state = await build_application_state(load_config_from_env())
    try:
        async with await _client(state) as client:
            created = await client.post(
                "/api/v2/sessions", json={"system_prompt": "Stable tool-order experiment."}
            )
            assert created.status_code == 200, created.text
            session_id = created.json()["session_id"]
            seed = await client.post(
                f"/api/v2/sessions/{session_id}/prompt",
                json={"content": "Reply exactly: seeded. Do not call tools."},
            )
            assert seed.status_code == 200, seed.text
            agent = state.registry.get_agent(session_id)
            assert agent is not None and len(agent.state.tools) >= 2
            expanded = [
                replace(tool, description=tool.description + (f" stable-{tool.name}" * 900))
                for tool in agent.state.tools
            ]
            agent.state.tools = sorted(expanded, key=lambda tool: tool.name)
            warm = await client.post(
                f"/api/v2/sessions/{session_id}/prompt",
                json={"content": "Reply exactly: warm. Do not call tools."},
            )
            assert warm.status_code == 200, warm.text
            agent.state.tools = list(reversed(agent.state.tools))
            measured = await client.post(
                f"/api/v2/sessions/{session_id}/prompt",
                json={"content": "Reply exactly: measured. Do not call tools."},
            )
            assert measured.status_code == 200, measured.text
            warm_usage = warm.json()["message"].get("usage") or {}
            measured_usage = measured.json()["message"].get("usage") or {}
            print(json.dumps({
                "scenario": "tool_order_perturbation",
                "enabled": os.environ.get("CAPABILITY_PACKAGES_ENABLED", "<default>"),
                "warm_cache_read": int(warm_usage.get("cacheRead") or 0),
                "measured_cache_read": int(measured_usage.get("cacheRead") or 0),
                "measured_input": int(measured_usage.get("input") or 0),
            }, sort_keys=True))
    finally:
        await state.shutdown()


async def test_live_stable_six_stage_prefix_cache(tmp_path: Path, live_env) -> None:
    """Prototype six stages as user instructions under one fixed system/tools prefix."""
    import json
    import os

    os.environ["SESSIONS_ROOT"] = str(tmp_path / "sessions")
    os.environ["APP_DB"] = str(tmp_path / "app.db")
    os.environ["SESSIONS_CWD"] = "live-stable-stages-test"
    from competitive_app.wiring import build_application_state, load_config_from_env

    state = await build_application_state(load_config_from_env())
    stable_protocol = (
        "You are one competitive-research engine. Keep this protocol fixed across all stages. "
        "Follow the stage named by the user, preserve evidence, and emit concise JSON. " * 140
    )
    try:
        async with await _client(state) as client:
            created = await client.post(
                "/api/v2/sessions", json={"system_prompt": stable_protocol}
            )
            assert created.status_code == 200, created.text
            session_id = created.json()["session_id"]
            usages = []
            for stage in ("plan", "search", "write"):
                response = await client.post(
                    f"/api/v2/sessions/{session_id}/prompt",
                    json={"content": f"Stage={stage}. Do not call tools. Return one small JSON object."},
                )
                assert response.status_code == 200, response.text
                usages.append(response.json()["message"].get("usage") or {})
            cache_read = sum(int(item.get("cacheRead") or 0) for item in usages)
            input_tokens = sum(int(item.get("input") or 0) for item in usages)
            denominator = input_tokens + cache_read
            assert cache_read > 0
            print(json.dumps({
                "scenario": "stable_six_stage_prefix",
                "enabled": os.environ.get("CAPABILITY_PACKAGES_ENABLED", "<default>"),
                "requests": len(usages),
                "input_tokens": input_tokens,
                "cache_read": cache_read,
                "cache_rate": cache_read / denominator if denominator else 0,
            }, sort_keys=True))
    finally:
        await state.shutdown()


async def test_live_reasonix_long_context_compaction(tmp_path: Path, live_env) -> None:
    """Force a small host window and verify Reasonix performs a real rewrite epoch."""
    import json
    import os

    os.environ["SESSIONS_ROOT"] = str(tmp_path / "sessions")
    os.environ["APP_DB"] = str(tmp_path / "app.db")
    os.environ["SESSIONS_CWD"] = "live-reasonix-compaction-test"
    os.environ["MODEL_CONTEXT_WINDOW_TOKENS"] = "8000"
    from competitive_app.wiring import build_application_state, load_config_from_env

    state = await build_application_state(load_config_from_env())
    stable_protocol = "Stable compaction research protocol. " * 700
    try:
        async with await _client(state) as client:
            created = await client.post(
                "/api/v2/sessions", json={"system_prompt": stable_protocol}
            )
            assert created.status_code == 200, created.text
            session_id = created.json()["session_id"]
            first = await client.post(
                f"/api/v2/sessions/{session_id}/prompt",
                json={"content": "Record baseline fact: Notion and Obsidian are note-taking tools."},
            )
            assert first.status_code == 200, first.text
            agent = state.registry.get_agent(session_id)
            assert agent is not None and agent.extension_runner is not None
            extension_errors = []
            agent.extension_runner.on_error(extension_errors.append)
            pressure = await client.post(
                f"/api/v2/sessions/{session_id}/prompt",
                json={"content": ("Evidence detail about pricing and features. " * 900)},
            )
            assert pressure.status_code == 200, pressure.text
            harness = state.registry.get_harness(session_id)
            assert harness is not None
            pending_after_prompt = harness._compaction_pending
            assert pending_after_prompt is False, "App must consume the Harness checkpoint"

            extension = next(
                ext for ext in agent.extension_runner.extensions
                if "reasonix_prefix_cache" in ext.resolvedPath
            )
            handler = extension.handlers["message_end"][0]
            reasonix_state = next(
                cell.cell_contents for cell in handler.__closure__
                if hasattr(cell.cell_contents, "buckets")
            )
            metadata = next(
                item for item in await state.repo.list({"cwd": "live-reasonix-compaction-test"})
                if item["id"] == session_id
            )
            session = await state.repo.open(metadata)
            entries = await session.get_entries()
            compactions = [entry for entry in entries if entry.get("type") == "compaction"]
            from earendil_works.pi_agent.harness.compaction import estimate_context_tokens
            assert compactions, (
                "Reasonix must append a real compaction entry; "
                f"state={reasonix_state}; errors={extension_errors}; "
                f"tokens={estimate_context_tokens(agent.state.messages)}; "
                f"window={agent.state.model.get('contextWindow')}"
            )
            assert reasonix_state.epoch >= 1
            print(json.dumps({
                "scenario": "long_context_compaction",
                "pending_after_prompt": pending_after_prompt,
                "compactions": len(compactions),
                "epoch": reasonix_state.epoch,
                "buckets": reasonix_state.buckets,
                "diagnostics": reasonix_state.diagnostics,
                "extension_errors": [error.error for error in extension_errors],
            }, sort_keys=True))
    finally:
        await state.shutdown()



def _stringify_messages(messages: list) -> str:
    """Flatten all message content into one string for substring checks."""
    import json

    parts: list[str] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    parts.append(str(block.get("text") or block.get("content") or ""))
        elif isinstance(content, dict):
            # custom_message stage output: {"plan": "..."} / {"report": "..."} / ...
            parts.append(json.dumps(content, ensure_ascii=False))
        # custom_message entries may carry stage output in details too.
        for key in ("details", "data", "output"):
            if key in m and isinstance(m[key], (dict, list)):
                parts.append(json.dumps(m[key], ensure_ascii=False))
    return "\n".join(parts)
