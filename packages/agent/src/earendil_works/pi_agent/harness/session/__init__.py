"""Session tree, JSONL storage, memory backends.

upstream: packages/agent/src/harness/session/*
"""
from __future__ import annotations

from .jsonl_repo import JsonlSessionRepo
from .jsonl_storage import JsonlSessionStorage, load_jsonl_session_metadata
from .memory_repo import InMemorySessionRepo
from .memory_storage import InMemorySessionStorage
from .repo_utils import create_session_id, create_timestamp, get_entries_to_fork, to_session
from .session import (
    DEFAULT_SESSIONS_DIR_NAME,
    Session,
    build_context_entries,
    build_session_context,
    default_context_entry_transform,
)

__all__ = [
    "DEFAULT_SESSIONS_DIR_NAME",
    "InMemorySessionRepo",
    "InMemorySessionStorage",
    "JsonlSessionRepo",
    "JsonlSessionStorage",
    "Session",
    "build_context_entries",
    "build_session_context",
    "create_session_id",
    "create_timestamp",
    "default_context_entry_transform",
    "get_entries_to_fork",
    "load_jsonl_session_metadata",
    "to_session",
]
