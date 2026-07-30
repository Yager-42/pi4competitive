"""Stage output storage/retrieval over JSONL session (F-R4/F-R9).

Stage outputs are stored as ``custom_message`` entries with customType
``"stage_output"`` and ``details={"stage": <name>}``. Retrieval walks the session
branch (leaf → root) and returns the latest output for a given stage.

Also hosts the v0.2.2 trace helpers (``_last_usage`` / ``_model_name``) so both
``research_runner`` and ``coverage_engine`` can import them without a circular
dependency (this module depends on neither).
"""
from __future__ import annotations

from typing import Any

STAGE_OUTPUT_CUSTOM_TYPE = "stage_output"


def last_usage(messages: list[Any]) -> dict[str, Any]:
    """v0.2.2: pull usage from the last assistant message (for span token counts)."""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            usage = message.get("usage")
            if isinstance(usage, dict):
                return usage
    return {}


def model_name(model: Any) -> str:
    """v0.2.2: extract a human-readable model id from an agent model dict."""
    if isinstance(model, dict):
        return str(model.get("model") or model.get("id") or model.get("name") or "")
    return str(model or "")



async def append_stage_output(session: Any, stage: str, output: dict[str, Any]) -> str:
    """Append a stage output to the session (F-R4)."""
    return await session.append_custom_message_entry(
        STAGE_OUTPUT_CUSTOM_TYPE,
        content=output,
        display=False,
        details={"stage": stage},
    )


async def get_stage_output(session: Any, stage: str) -> dict[str, Any] | None:
    """Return the latest output for ``stage`` on the session branch (F-R9).

    Walks leaf → root; returns the first matching custom_message entry's content.
    """
    branch = await session.get_branch()
    for entry in reversed(branch):
        if (
            entry.get("type") == "custom_message"
            and entry.get("customType") == STAGE_OUTPUT_CUSTOM_TYPE
            and isinstance(entry.get("details"), dict)
            and entry["details"].get("stage") == stage
        ):
            content = entry.get("content")
            if isinstance(content, dict):
                return content
    return None


async def collect_prior_outputs(session: Any, stages: tuple[str, ...]) -> dict[str, Any]:
    """Collect outputs for the given prior stages into a dict (F-R9)."""
    out: dict[str, Any] = {}
    for stage in stages:
        output = await get_stage_output(session, stage)
        if output is not None:
            out[stage] = output
    return out


__all__ = [
    "STAGE_OUTPUT_CUSTOM_TYPE",
    "append_stage_output",
    "collect_prior_outputs",
    "get_stage_output",
]
