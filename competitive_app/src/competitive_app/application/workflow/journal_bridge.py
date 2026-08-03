"""JournalBridge — harness extension 事件 → RunJournal.

机制重写（poirot ``RunJournalMiddleware`` 是 LangGraph ``AgentMiddleware``，契约
§2.2 禁搬）；行为语义 COPY poirot（transplant source 见下）：
事件命名（``agent.*``/``llm.*``/``tool.*``/``compaction.*``）、tool 输出截
2000 字符、无 journal 时静默不报错。

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/middlewares/run_journal_middleware.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see native/vendor/licenses/POIROT-MIT.txt)
Host delta: LangGraph middleware → pi extension factory（机制面重写；挂载走
``load_extension_from_factory``，先例：EvidenceIntake extraction factory）。
"""

from __future__ import annotations

from typing import Any

from competitive_app.adapter.out.observability import guarded_append
from competitive_app.adapter.out.observability.run_journal import RunJournal

_TOOL_OUTPUT_LIMIT = 2000  # COPY poirot: tool 输出截 2000


import contextvars

# 当前 run 的 journal（TaskService._run_research 入口设置，run 结束 reset）。
# wiring 的 FallbackStream emit sink 与 harness journal extension 都经它解析
# "本次调用属于哪个 run"（先例：extraction.current_subtask ContextVar）。
current_run_journal: contextvars.ContextVar[RunJournal | None] = contextvars.ContextVar(
    "current_run_journal", default=None
)


def _tool_text(content: Any) -> str:
    """tool_result content（pi content block 列表）→ 文本。"""
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        from earendil_works.pi_ai.utils.text import extract_text

        return extract_text(content)
    return str(content)


def make_journal_extension_factory(journal: RunJournal | None):
    """Build an extension factory hooking harness lifecycle events → journal.

    Returned callable is the ``register(api)`` function for
    ``load_extension_from_factory`` (先例：``make_extraction_extension_factory``)。
    journal 为 None → 不注册任何 handler，静默 no-op（poirot 无 journal 语义）。
    """

    if journal is None:
        def register_noop(api: Any = None) -> None:
            return None

        return register_noop

    state: dict[str, Any] = {"last_model": None}

    def register(api: Any) -> None:
        async def on_agent_start(event: dict[str, Any], _ctx: Any = None) -> None:
            guarded_append(journal, "agent.started", {"run_id": journal.run_id})

        async def on_agent_settled(event: dict[str, Any], _ctx: Any = None) -> None:
            guarded_append(journal, "agent.finished", {"run_id": journal.run_id})

        async def on_llm_request(event: dict[str, Any], _ctx: Any = None) -> None:
            payload = event.get("payload") or {}
            model_id = payload.get("model") if isinstance(payload, dict) else None
            state["last_model"] = model_id
            guarded_append(
                journal,
                "llm.request",
                {"run_id": journal.run_id, "model": model_id},
            )

        async def on_llm_response(event: dict[str, Any], _ctx: Any = None) -> None:
            guarded_append(
                journal,
                "llm.response",
                {
                    "run_id": journal.run_id,
                    "model": state["last_model"],
                    "status": event.get("status"),
                },
            )

        async def on_tool_call(event: dict[str, Any], _ctx: Any = None) -> None:
            guarded_append(
                journal,
                "tool.called",
                {
                    "run_id": journal.run_id,
                    "tool_name": event.get("toolName"),
                    "tool_input": event.get("input") or {},
                },
            )

        async def on_tool_result(event: dict[str, Any], _ctx: Any = None) -> None:
            status = "error" if event.get("isError") else "ok"
            guarded_append(
                journal,
                "tool.finished",
                {
                    "run_id": journal.run_id,
                    "tool_name": event.get("toolName"),
                    "output": _tool_text(event.get("content"))[:_TOOL_OUTPUT_LIMIT],
                    "status": status,
                },
            )

        async def on_compact_requested(event: dict[str, Any], _ctx: Any = None) -> None:
            guarded_append(
                journal,
                "compaction.requested",
                {
                    "run_id": journal.run_id,
                    "reason": event.get("reason"),
                    "willRetry": event.get("willRetry"),
                },
            )

        async def on_compact_completed(event: dict[str, Any], _ctx: Any = None) -> None:
            guarded_append(
                journal,
                "compaction.completed",
                {
                    "run_id": journal.run_id,
                    "reason": event.get("reason"),
                    "fromExtension": event.get("fromExtension"),
                },
            )

        api.on("agent_start", on_agent_start)
        api.on("agent_settled", on_agent_settled)
        api.on("before_provider_request", on_llm_request)
        api.on("after_provider_response", on_llm_response)
        api.on("tool_call", on_tool_call)
        api.on("tool_result", on_tool_result)
        api.on("session_before_compact", on_compact_requested)
        api.on("session_compact", on_compact_completed)

    return register


__all__ = ["make_journal_extension_factory"]
