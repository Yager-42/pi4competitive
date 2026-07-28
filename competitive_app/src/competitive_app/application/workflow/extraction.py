"""Extraction intake — judge-based evidence extraction (research-workflow-v1 v0.2.0).

ADR 0010 D-S6/D-S7 / F-R29/F-R30. Replaces PR3/4's direct sub-agent-evidence
fill with judge LLM extraction: when a sub-agent's ``*_fetch`` tool returns a
page, the Extraction extension submits it to EvidenceIntake, which batches
observations and calls the judge LLM to extract (entity, attribute, value,
source, confidence) into the SOCM evidence graph + coverage map.

Judge: independent model (``JUDGE_MODEL`` env, default fallback to main model,
F-R29 — local reversal of F-R7). Called via raw ``models.streamSimple`` (no
harness — single "give text, want JSON" call). Batched: one judge call per
entity's empty cells (D-S6).

Hook: extension ``tool_result`` event (filter ``toolName in {*_fetch}``); the
subtask's target cells are read from a ContextVar set by the coverage engine
before the sub-agent prompt (D-S7). Buffered flush + sub-agent-exit drain.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
from typing import Any
from uuid import uuid4

from ...domain.socm import EvidenceNode, SOCMState
from ...domain.socm.coverage import CellStatus

_log = logging.getLogger(__name__)

# ContextVar: the coverage engine sets this before a sub-agent prompt so the
# Extraction extension knows which entity + empty cells to extract for.
# Mirrors SearchOS set_current_table / _current_task_var (ADR 0010 D-S7).
current_subtask: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "extraction_current_subtask", default=None
)

# Cap judge input to avoid blowing the context window (ADR 0010 D-S7).
DEFAULT_JUDGE_MAX_INPUT_CHARS = 200_000


def _is_fetch_tool(tool_name: str) -> bool:
    return tool_name.endswith("_fetch")


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
        return "".join(parts)
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return ""


def _try_parse_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except Exception:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                return None
        return None


class EvidenceIntake:
    """Buffers page observations, batch-flushes via judge LLM into SOCM.

    PR5: simple synchronous flush (no background task pool yet — the sub-agent
    loop is single-threaded per harness, and ``flush`` is called at sub-agent
    exit). SearchOS uses a background flush semaphore; v0.2.0 keeps it inline
    for simplicity (F-R30 "buffer + batch flush" satisfied by per-entity batch).
    """

    def __init__(
        self,
        *,
        socm_store: Any,
        session_id: str,
        models: Any,
        judge_model: dict[str, Any] | None,
        max_input_chars: int = DEFAULT_JUDGE_MAX_INPUT_CHARS,
    ) -> None:
        self._socm_store = socm_store
        self._session_id = session_id
        self._models = models
        self._judge_model = judge_model
        self._max_input_chars = max_input_chars
        # entity_id -> list of (page_text, source_url) observations buffered.
        self._buffer: dict[str, list[tuple[str, str]]] = {}

    def submit(self, entity_id: str, page_text: str, source: str) -> None:
        if not page_text or not entity_id:
            return
        self._buffer.setdefault(entity_id, []).append((page_text[: self._max_input_chars], source))

    async def flush(self) -> int:
        """Flush all buffered observations through the judge; fill SOCM.

        Returns the number of evidence nodes added. Called at sub-agent exit
        (drain point — F-R30 sub-agent-exit flush).
        """
        if not self._buffer:
            return 0
        added = 0
        for entity_id, observations in list(self._buffer.items()):
            added += await self._extract_entity(entity_id, observations)
        self._buffer.clear()
        return added

    async def _extract_entity(self, entity_id: str, observations: list[tuple[str, str]]) -> int:
        """Run the judge for one entity's empty cells against buffered pages."""
        # Load current SOCM to find this entity's empty cells.
        state = await self._socm_store.load(self._session_id)
        empty_attrs = [
            attr.id
            for cell in state.coverage_map.cells.values()
            if cell.entity_id == entity_id and cell.status == CellStatus.EMPTY
            for attr in state.coverage_map.attributes
            if attr.id == cell.attribute_id
        ]
        if not empty_attrs or not observations:
            # No empty cells left (already filled by a sibling) or no pages.
            return 0

        pages_blob = "\n\n---\n\n".join(f"[{i}] {src}\n{txt}" for i, (txt, src) in enumerate(observations))
        findings = await self._call_judge(entity_id, empty_attrs, pages_blob)
        if not findings:
            return 0

        added = 0

        def _fill(s: SOCMState) -> SOCMState:
            nonlocal added
            for item in findings:
                attr = str(item.get("attribute") or "")
                value = str(item.get("value") or "").strip()
                if not value or attr not in empty_attrs:
                    continue
                source = str(item.get("source") or "")
                excerpt = str(item.get("source_excerpt") or "")[:200]
                try:
                    confidence = float(item.get("confidence") or 0.5)
                except (TypeError, ValueError):
                    confidence = 0.5
                node = EvidenceNode(
                    id=f"ev_{uuid4().hex[:8]}",
                    entity=entity_id,
                    attribute=attr,
                    value=value,
                    finding=f"{entity_id} {attr}: {value}",
                    source=source,
                    source_excerpt=excerpt,
                    confidence=confidence,
                )
                if s.evidence_graph.add_node(node):
                    s.coverage_map.fill(
                        entity_id, attr, value=value, source=source,
                        source_excerpt=excerpt, confidence=confidence,
                    )
                    added += 1
            return s

        await self._socm_store.atomic_update(self._session_id, _fill)
        return added

    async def _call_judge(
        self, entity_id: str, empty_attrs: list[str], pages_blob: str
    ) -> list[dict[str, Any]]:
        """One-shot judge call via completeSimple; returns parsed findings."""
        if self._models is None or self._judge_model is None:
            return []
        prompt = _build_judge_prompt(entity_id, empty_attrs, pages_blob)
        context = {"messages": [{"role": "user", "content": prompt}]}
        try:
            message = await self._models.completeSimple(self._judge_model, context)
        except Exception:  # noqa: BLE001
            _log.exception("judge completeSimple call failed for entity %s", entity_id)
            return []
        text = _extract_assistant_text(message)
        if not text:
            return []
        parsed = _try_parse_json(text)
        if isinstance(parsed, list):
            return [p for p in parsed if isinstance(p, dict)]
        return []


def _extract_assistant_text(response: Any) -> str:
    """Pull text from a streamSimple response (list of events or message dict)."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        return _message_text(response.get("content"))
    if isinstance(response, list):
        # Event stream: find the final message_end / message event.
        for event in reversed(response):
            if not isinstance(event, dict):
                continue
            if event.get("type") in {"message_end", "message"}:
                msg = event.get("message") or event
                return _message_text(msg.get("content") if isinstance(msg, dict) else None)
            if event.get("type") == "text":
                return str(event.get("text") or "")
        return ""
    return ""


def _build_judge_prompt(entity_id: str, empty_attrs: list[str], pages_blob: str) -> str:
    attrs = ", ".join(empty_attrs)
    return (
        f"You are an evidence extraction judge. Given pages of fetched web content and a target "
        f"entity, extract structured findings for the entity's empty attribute cells.\n\n"
        f"Entity: {entity_id}\n"
        f"Attributes to fill: {attrs}\n\n"
        f"Pages:\n{pages_blob}\n\n"
        f"For each attribute you can fill from the pages, return a JSON array of objects:\n"
        f'[{{"attribute": "<attr_id>", "value": "<value>", "source": "<url>", '
        f'"source_excerpt": "<verbatim quote>", "confidence": <0-1>}}]\n\n'
        f"Only fill attributes whose value is directly supported by the page text. "
        f"If no attribute can be filled, return []. Output ONLY the JSON array."
    )


# ----------------------------------------------------------- extension factory


def make_extraction_extension_factory(intake: EvidenceIntake):
    """Build an extension factory that hooks ``tool_result`` → EvidenceIntake.

    Returned callable is the ``register(api)`` function for load_extension_from_factory.
    Each ephemeral sub-agent harness gets its own intake (and thus its own buffer),
    so parallel sub-agents don't share extraction state.
    """

    def register(api) -> None:  # type: ignore[no-untyped-def]
        async def on_tool_result(event: dict[str, Any], _ctx: Any = None) -> None:
            tool_name = event.get("toolName") or event.get("tool_name") or ""
            if not _is_fetch_tool(str(tool_name)):
                return
            subtask = current_subtask.get()
            if not subtask:
                return
            entity_id = subtask.get("entity_id") or ""
            # The tool_result event carries content (list) + details (dict) at
            # top level (agent.py:494 emit). NOT nested under "result".
            page_text = _extract_page_text(event)
            source = _extract_source(event, tool_name)
            intake.submit(entity_id, page_text, source)

        api.on("tool_result", on_tool_result)

    return register


def _extract_page_text(event: Any) -> str:
    """Pull page text from a tool_result event (top-level content/details)."""
    if not isinstance(event, dict):
        return ""
    details = event.get("details")
    if isinstance(details, dict):
        for key in ("content", "text", "raw_content", "markdown"):
            val = details.get(key)
            if isinstance(val, str) and val:
                return val
        results = details.get("results")
        if isinstance(results, list):
            parts = []
            for item in results:
                if isinstance(item, dict):
                    parts.append(str(item.get("content") or item.get("raw_content") or ""))
            joined = "\n\n".join(p for p in parts if p)
            if joined:
                return joined
    content = event.get("content")
    if isinstance(content, list):
        return _message_text(content)
    if isinstance(content, str):
        return content
    return ""


def _extract_source(event: Any, tool_name: str) -> str:
    """Pull the source URL from a tool_result event."""
    if not isinstance(event, dict):
        return f"{tool_name}:fetch"
    details = event.get("details")
    if isinstance(details, dict):
        url = details.get("url") or details.get("source")
        if isinstance(url, str) and url:
            return url
        results = details.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            url = results[0].get("url") or results[0].get("link")
            if isinstance(url, str):
                return url
    # Fall back to the tool input URL if present.
    inp = event.get("input")
    if isinstance(inp, dict):
        url = inp.get("url")
        if isinstance(url, str) and url:
            return url
    return f"{tool_name}:fetch"


__all__ = [
    "DEFAULT_JUDGE_MAX_INPUT_CHARS",
    "EvidenceIntake",
    "current_subtask",
    "make_extraction_extension_factory",
]
