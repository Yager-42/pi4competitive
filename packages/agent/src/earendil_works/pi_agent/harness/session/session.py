"""Session tree and context build.

upstream: packages/agent/src/harness/session/session.ts
"""
from __future__ import annotations

from typing import Any, Callable

from earendil_works.pi_agent.types import AgentMessage

from ..messages import (
    create_branch_summary_message,
    create_compaction_summary_message,
    create_custom_message,
)
from ..types import (
    SessionContext,
    SessionEntryCursorOptions,
    SessionError,
    SessionMetadata,
    SessionStats,
    SessionStorage,
    SessionTreeEntry,
)

# Contract default (D24/D25): sessions SoT under data/sessions/, not OS temp alone.
DEFAULT_SESSIONS_DIR_NAME = "data/sessions"

ContextEntryTransform = Callable[[list[SessionTreeEntry]], list[SessionTreeEntry]]
CustomEntryContextMessageProjector = Callable[
    [SessionTreeEntry, int, list[SessionTreeEntry]], list[AgentMessage] | None
]


def default_context_entry_transform(path_entries: list[SessionTreeEntry]) -> list[SessionTreeEntry]:
    compaction = None
    for entry in path_entries:
        if entry.get("type") == "compaction":
            compaction = entry
    if not compaction:
        return list(path_entries)

    entries: list[SessionTreeEntry] = [compaction]
    compaction_idx = next(
        i
        for i, e in enumerate(path_entries)
        if e.get("type") == "compaction" and e["id"] == compaction["id"]
    )
    if compaction.get("retainedTail"):
        entries.extend(path_entries[compaction_idx + 1 :])
        return entries
    first_kept = compaction.get("firstKeptEntryId")
    if first_kept:
        found = False
        for i in range(compaction_idx):
            entry = path_entries[i]
            if entry["id"] == first_kept:
                found = True
            if found:
                entries.append(entry)
    entries.extend(path_entries[compaction_idx + 1 :])
    return entries


def build_context_entries(
    path_entries: list[SessionTreeEntry],
    options: dict[str, Any] | None = None,
) -> list[SessionTreeEntry]:
    options = options or {}
    entries = default_context_entry_transform(path_entries)
    for transform in options.get("entryTransforms") or []:
        entries = list(transform(entries))
    return entries


def session_entry_to_context_messages(
    entry: SessionTreeEntry,
    index: int,
    entries: list[SessionTreeEntry],
    options: dict[str, Any] | None = None,
) -> list[AgentMessage]:
    options = options or {}
    et = entry.get("type")
    if et == "message":
        return [entry["message"]]  # type: ignore[index,return-value]
    if et == "custom_message":
        return [
            create_custom_message(
                str(entry.get("customType")),
                entry.get("content"),  # type: ignore[arg-type]
                bool(entry.get("display")),
                entry.get("details"),
                str(entry.get("timestamp")),
            )
        ]
    if et == "compaction":
        msgs: list[AgentMessage] = [
            create_compaction_summary_message(
                str(entry.get("summary") or ""),
                int(entry.get("tokensBefore") or 0),
                str(entry.get("timestamp")),
            )
        ]
        tail = entry.get("retainedTail") or []
        msgs.extend(tail)  # type: ignore[arg-type]
        return msgs
    if et == "branch_summary" and entry.get("summary"):
        return [
            create_branch_summary_message(
                str(entry.get("summary")),
                str(entry.get("fromId")),
                str(entry.get("timestamp")),
            )
        ]
    if et == "custom":
        projectors = options.get("entryProjectors") or {}
        projector = projectors.get(entry.get("customType"))
        if projector:
            return list(projector(entry, index, entries) or [])
        return []
    return []


def _derive_session_context_state(path_entries: list[SessionTreeEntry]) -> dict[str, Any]:
    thinking_level = "off"
    model = None
    active_tool_names = None
    for entry in path_entries:
        et = entry.get("type")
        if et == "thinking_level_change":
            thinking_level = str(entry.get("thinkingLevel") or "off")
        elif et == "model_change":
            model = {"provider": str(entry.get("provider")), "modelId": str(entry.get("modelId"))}
        elif et == "message":
            msg = entry.get("message")
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                model = {
                    "provider": str(msg.get("provider")),
                    "modelId": str(msg.get("model")),
                }
        elif et == "active_tools_change":
            active_tool_names = list(entry.get("activeToolNames") or [])
    return {
        "thinkingLevel": thinking_level,
        "model": model,
        "activeToolNames": active_tool_names,
    }


def build_session_context(
    path_entries: list[SessionTreeEntry],
    options: dict[str, Any] | None = None,
) -> SessionContext:
    state = _derive_session_context_state(path_entries)
    context_entries = build_context_entries(path_entries, options)
    messages: list[AgentMessage] = []
    for i, entry in enumerate(context_entries):
        messages.extend(session_entry_to_context_messages(entry, i, context_entries, options))
    return {
        "messages": messages,
        "thinkingLevel": state["thinkingLevel"],
        "model": state["model"],
        "activeToolNames": state["activeToolNames"],
    }


class Session:
    def __init__(
        self,
        storage: SessionStorage[Any],
        context_build_options: dict[str, Any] | None = None,
    ) -> None:
        self._storage = storage
        self._context_build_options = context_build_options or {}

    async def get_metadata(self) -> SessionMetadata:
        return await self._storage.getMetadata()

    # camelCase aliases for isomorphism with TS public surface
    getMetadata = get_metadata

    def get_storage(self) -> SessionStorage[Any]:
        return self._storage

    getStorage = get_storage

    async def get_leaf_id(self) -> str | None:
        return await self._storage.getLeafId()

    getLeafId = get_leaf_id

    async def get_entry(self, id: str) -> SessionTreeEntry | None:
        return await self._storage.getEntry(id)

    getEntry = get_entry

    async def get_entries(
        self, options: SessionEntryCursorOptions | None = None
    ) -> list[SessionTreeEntry]:
        return await self._storage.getEntries(options)

    getEntries = get_entries

    async def get_branch(self, from_id: str | None = None) -> list[SessionTreeEntry]:
        leaf_id = from_id if from_id is not None else await self._storage.getLeafId()
        return await self._storage.getPathToRootOrCompaction(leaf_id)

    getBranch = get_branch

    def _merge_options(self, options: dict[str, Any] | None) -> dict[str, Any]:
        options = options or {}
        return {
            "entryTransforms": [
                *(self._context_build_options.get("entryTransforms") or []),
                *(options.get("entryTransforms") or []),
            ],
            "entryProjectors": {
                **(self._context_build_options.get("entryProjectors") or {}),
                **(options.get("entryProjectors") or {}),
            },
        }

    async def build_context_entries(
        self, options: dict[str, Any] | None = None
    ) -> list[SessionTreeEntry]:
        return build_context_entries(await self.get_branch(), self._merge_options(options))

    buildContextEntries = build_context_entries

    async def build_context(self, options: dict[str, Any] | None = None) -> SessionContext:
        return build_session_context(await self.get_branch(), self._merge_options(options))

    buildContext = build_context

    async def get_label(self, id: str) -> str | None:
        return await self._storage.getLabel(id)

    getLabel = get_label

    async def get_session_stats(self) -> SessionStats:
        return await self._storage.getSessionStats()

    getSessionStats = get_session_stats

    async def get_session_name(self) -> str | None:
        return await self._storage.getSessionName()

    getSessionName = get_session_name

    async def _append_typed(self, entry: SessionTreeEntry) -> str:
        await self._storage.appendEntry(entry)
        return entry["id"]

    async def append_message(self, message: AgentMessage) -> str:
        from .repo_utils import create_timestamp

        return await self._append_typed(
            {
                "type": "message",
                "id": await self._storage.createEntryId(),
                "parentId": await self._storage.getLeafId(),
                "timestamp": create_timestamp(),
                "message": message,
            }
        )

    appendMessage = append_message

    async def append_thinking_level_change(self, thinking_level: str) -> str:
        from .repo_utils import create_timestamp

        return await self._append_typed(
            {
                "type": "thinking_level_change",
                "id": await self._storage.createEntryId(),
                "parentId": await self._storage.getLeafId(),
                "timestamp": create_timestamp(),
                "thinkingLevel": thinking_level,
            }
        )

    appendThinkingLevelChange = append_thinking_level_change

    async def append_model_change(self, provider: str, model_id: str) -> str:
        from .repo_utils import create_timestamp

        return await self._append_typed(
            {
                "type": "model_change",
                "id": await self._storage.createEntryId(),
                "parentId": await self._storage.getLeafId(),
                "timestamp": create_timestamp(),
                "provider": provider,
                "modelId": model_id,
            }
        )

    appendModelChange = append_model_change

    async def append_active_tools_change(self, active_tool_names: list[str]) -> str:
        from .repo_utils import create_timestamp

        return await self._append_typed(
            {
                "type": "active_tools_change",
                "id": await self._storage.createEntryId(),
                "parentId": await self._storage.getLeafId(),
                "timestamp": create_timestamp(),
                "activeToolNames": list(active_tool_names),
            }
        )

    appendActiveToolsChange = append_active_tools_change

    async def append_compaction(
        self,
        summary: str,
        first_kept_entry_id: str | None,
        tokens_before: int,
        details: Any = None,
        from_hook: bool | None = None,
        usage: dict[str, Any] | None = None,
        retained_tail: list[AgentMessage] | None = None,
    ) -> str:
        from .repo_utils import create_timestamp

        entry: dict[str, Any] = {
            "type": "compaction",
            "id": await self._storage.createEntryId(),
            "parentId": await self._storage.getLeafId(),
            "timestamp": create_timestamp(),
            "summary": summary,
            "tokensBefore": tokens_before,
        }
        if first_kept_entry_id is not None:
            entry["firstKeptEntryId"] = first_kept_entry_id
        if details is not None:
            entry["details"] = details
        if from_hook is not None:
            entry["fromHook"] = from_hook
        if usage is not None:
            entry["usage"] = usage
        if retained_tail is not None:
            entry["retainedTail"] = retained_tail
        return await self._append_typed(entry)  # type: ignore[arg-type]

    appendCompaction = append_compaction

    async def append_custom_entry(self, custom_type: str, data: Any = None) -> str:
        from .repo_utils import create_timestamp

        entry: dict[str, Any] = {
            "type": "custom",
            "id": await self._storage.createEntryId(),
            "parentId": await self._storage.getLeafId(),
            "timestamp": create_timestamp(),
            "customType": custom_type,
        }
        if data is not None:
            entry["data"] = data
        return await self._append_typed(entry)  # type: ignore[arg-type]

    appendCustomEntry = append_custom_entry

    async def append_custom_message_entry(
        self,
        custom_type: str,
        content: Any,
        display: bool,
        details: Any = None,
    ) -> str:
        from .repo_utils import create_timestamp

        entry: dict[str, Any] = {
            "type": "custom_message",
            "id": await self._storage.createEntryId(),
            "parentId": await self._storage.getLeafId(),
            "timestamp": create_timestamp(),
            "customType": custom_type,
            "content": content,
            "display": display,
        }
        if details is not None:
            entry["details"] = details
        return await self._append_typed(entry)  # type: ignore[arg-type]

    appendCustomMessageEntry = append_custom_message_entry

    async def append_label(self, target_id: str, label: str | None) -> str:
        from .repo_utils import create_timestamp

        if not await self._storage.getEntry(target_id):
            raise SessionError("not_found", f"Entry {target_id} not found")
        return await self._append_typed(
            {
                "type": "label",
                "id": await self._storage.createEntryId(),
                "parentId": await self._storage.getLeafId(),
                "timestamp": create_timestamp(),
                "targetId": target_id,
                "label": label,
            }
        )

    appendLabel = append_label

    async def append_session_name(self, name: str) -> str:
        from .repo_utils import create_timestamp

        sanitized = " ".join(name.replace("\r", " ").replace("\n", " ").split()).strip()
        return await self._append_typed(
            {
                "type": "session_info",
                "id": await self._storage.createEntryId(),
                "parentId": await self._storage.getLeafId(),
                "timestamp": create_timestamp(),
                "name": sanitized,
            }
        )

    appendSessionName = append_session_name

    async def move_to(
        self,
        entry_id: str | None,
        summary: dict[str, Any] | None = None,
    ) -> str | None:
        from .repo_utils import create_timestamp

        if entry_id is not None and not await self._storage.getEntry(entry_id):
            raise SessionError("not_found", f"Entry {entry_id} not found")
        await self._storage.setLeafId(entry_id)
        if not summary:
            return None
        entry: dict[str, Any] = {
            "type": "branch_summary",
            "id": await self._storage.createEntryId(),
            "parentId": entry_id,
            "timestamp": create_timestamp(),
            "fromId": entry_id if entry_id is not None else "root",
            "summary": summary["summary"],
        }
        if "details" in summary:
            entry["details"] = summary["details"]
        if "usage" in summary:
            entry["usage"] = summary["usage"]
        if "fromHook" in summary:
            entry["fromHook"] = summary["fromHook"]
        return await self._append_typed(entry)  # type: ignore[arg-type]

    moveTo = move_to


__all__ = [
    "DEFAULT_SESSIONS_DIR_NAME",
    "Session",
    "build_context_entries",
    "build_session_context",
    "default_context_entry_transform",
    "session_entry_to_context_messages",
]
