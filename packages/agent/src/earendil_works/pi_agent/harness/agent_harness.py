"""High-level agent harness: session + agent + resources.

upstream: packages/agent/src/harness/agent-harness.ts
Minimal C-tier façade for P2: prompt persists to Session automatically.
"""
from __future__ import annotations

from typing import Any

from earendil_works.pi_agent.agent import Agent, AgentOptions
from earendil_works.pi_agent.types import AgentEvent, AgentMessage, AgentTool, StreamFn
from earendil_works.pi_agent.tool_execution import AgentToolExecutor
from earendil_works.pi_agent.harness.compaction import (
    compact, estimate_context_tokens, isolated_summary, snapshot_fingerprint,
    validate_compaction_plan,
)

from .session.session import Session
from .system_prompt import build_system_prompt
from .skills import Skill


class AgentHarness:
    """Thin harness: Agent + Session with auto-persist of message_end events."""

    def __init__(
        self,
        *,
        session: Session[Any],
        stream_fn: StreamFn,
        model: dict[str, Any],
        tools: list[AgentTool] | None = None,
        system_prompt: str = "",
        skills: list[Skill] | None = None,
        capability_report: Any | None = None,
        tool_execution: str = "parallel",
        tool_executor: AgentToolExecutor | None = None,
        tool_execution_scope_id: str = ""
    ) -> None:
        prompt = build_system_prompt(base=system_prompt, skills=skills)
        self.session = session
        self._compaction_pending = False
        self.agent = Agent(
            AgentOptions(
                stream_fn=stream_fn,
                initial_state={
                    "model": model,
                    "tools": tools or [],
                    "systemPrompt": prompt,
                },
                tool_execution=tool_execution,  # type: ignore[arg-type]
                tool_executor=tool_executor,
                tool_execution_scope_id=tool_execution_scope_id,
            )
        )
        if capability_report is not None:
            from earendil_works.pi_agent.package_manager.apply import apply_capability_report

            apply_capability_report(self.agent, capability_report)
        self._bind_extension_context()
        self.skills = self.agent.skills or list(skills or [])
        self.prompts = self.agent.prompts
        self._unsub = self.agent.subscribe(self._on_event)

    def _bind_extension_context(self) -> None:
        runner = self.agent.extension_runner
        if not runner:
            return

        def request_compaction(_options: dict[str, Any] | None = None) -> str:
            if self._compaction_pending:
                return "already_pending"
            self._compaction_pending = True
            return "accepted"

        def context_usage() -> dict[str, Any]:
            usage = next((message.get("usage") for message in reversed(self.agent.state.messages)
                          if message.get("role") == "assistant" and message.get("usage")), None)
            return {
                "tokens": estimate_context_tokens(self.agent.state.messages),
                "contextWindow": int((self.agent.state.model or {}).get("contextWindow") or 0),
                "usage": usage,
            }

        runner.bind_core(context_actions={
            "getSessionManager": lambda: self.session,
            "getContextUsage": context_usage,
            "compact": request_compaction,
        })

    async def _on_event(self, event: AgentEvent, signal: Any) -> None:
        if event.get("type") == "message_end":
            message = event.get("message")
            if message is not None:
                await self.session.append_message(message)  # type: ignore[arg-type]

    async def prompt(self, input: str | AgentMessage | list[AgentMessage]) -> None:
        context = await self.session.build_context()
        self.agent.state.messages = list(context.get("messages") or [])
        metadata = await self.session.get_metadata()
        self.agent.session_id = metadata["id"]
        await self.agent.prompt(input)
        await self.agent.wait_for_idle()
        if self._compaction_pending:
            try:
                await self.compact()
            finally:
                self._compaction_pending = False
        context = await self.session.build_context()
        self.agent.state.messages = list(context.get("messages") or [])

    async def build_context(self) -> dict[str, Any]:
        return await self.session.build_context()  # type: ignore[return-value]

    async def session_info_changed(self, name: str | None) -> None:
        if self.agent.extension_runner:
            await self.agent.extension_runner.emit({"type": "session_info_changed", "name": name})

    async def compact(self, settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
        runner = self.agent.extension_runner
        branch = await self.session.get_branch()
        entries = [{"id": entry["id"], "message": entry["message"]}
                   for entry in branch if entry.get("type") == "message"]
        active_start = max((i for i, entry in enumerate(entries)
                            if entry["message"].get("role") == "user"), default=len(entries))
        active_ids = {entry["id"] for entry in entries[active_start:]}
        preparation = {
            "snapshotFingerprint": snapshot_fingerprint(entries),
            "entries": entries,
            "activeTurnEntryIds": list(active_ids),
        }
        if runner:
            before = await runner.emit(
                {"type": "session_before_compact", "preparation": preparation,
                 "branchEntries": entries, "reason": "manual", "willRetry": False,
                 "signal": self.agent.signal}
            )
            if before and before.get("cancel"):
                return None
            if before and before.get("compactionCollision"):
                return None
            if before and before.get("compactionPlan") is not None:
                plan = before["compactionPlan"]
                try:
                    validate_compaction_plan(plan, entries, active_ids)
                except ValueError:
                    return None
                by_id = {entry["id"]: entry for entry in entries}
                folded = [by_id[entry_id]["message"] for entry_id in plan["foldEntryIds"]]
                retained = [by_id[entry_id]["message"] for entry_id in plan["retainEntryIds"]]
                summary = await isolated_summary(
                    folded, plan["summaryInstructions"], self.agent.stream_function,
                    self.agent.state.model,
                )
                await self.session.append_compaction(
                    summary, plan["retainEntryIds"][0] if plan["retainEntryIds"] else None,
                    estimate_context_tokens([entry["message"] for entry in entries]),
                    details=plan.get("details"), from_hook=True, retained_tail=retained,
                )
                result = {"summary": summary, "keptMessages": retained,
                          "tokensBefore": estimate_context_tokens([entry["message"] for entry in entries])}
                rebuilt = await self.session.build_context()
                self.agent.state.messages = list(rebuilt.get("messages") or [])
            elif before and before.get("compaction") is not None:
                result = before["compaction"]
            else:
                result = await compact(self.agent.state.messages, settings,
                                       self.agent.stream_function, self.agent.state.model)
        else:
            result = await compact(self.agent.state.messages, settings,
                                   self.agent.stream_function, self.agent.state.model)
        if runner:
            await runner.emit({"type": "session_compact", "compactionEntry": result,
                               "fromExtension": bool(before and (before.get("compaction") or before.get("compactionPlan"))),
                               "reason": "manual", "willRetry": False})
        return result

    async def shutdown(self) -> None:
        await self.agent.shutdown_extensions()
        self.close()

    def close(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None  # type: ignore[assignment]


__all__ = ["AgentHarness"]
