"""High-level agent harness: session + agent + resources.

upstream: packages/agent/src/harness/agent-harness.ts
Minimal C-tier façade for P2: prompt persists to Session automatically.
"""
from __future__ import annotations

from typing import Any

from earendil_works.pi_agent.agent import Agent, AgentOptions
from earendil_works.pi_agent.types import AgentEvent, AgentMessage, AgentTool, StreamFn

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
        tool_execution: str = "parallel",
    ) -> None:
        prompt = build_system_prompt(base=system_prompt, skills=skills)
        self.session = session
        self.agent = Agent(
            AgentOptions(
                stream_fn=stream_fn,
                initial_state={
                    "model": model,
                    "tools": tools or [],
                    "systemPrompt": prompt,
                },
                tool_execution=tool_execution,  # type: ignore[arg-type]
            )
        )
        self._unsub = self.agent.subscribe(self._on_event)

    async def _on_event(self, event: AgentEvent, signal: Any) -> None:
        if event.get("type") == "message_end":
            message = event.get("message")
            if message is not None:
                await self.session.append_message(message)  # type: ignore[arg-type]

    async def prompt(self, input: str | AgentMessage | list[AgentMessage]) -> None:
        await self.agent.prompt(input)
        await self.agent.wait_for_idle()

    async def build_context(self) -> dict[str, Any]:
        return await self.session.build_context()  # type: ignore[return-value]

    def close(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None  # type: ignore[assignment]


__all__ = ["AgentHarness"]
