"""Context compaction and branch summarization.

upstream: packages/agent/src/harness/compaction/*
"""
from __future__ import annotations

from .branch_summarization import (
    collect_entries_for_branch_summary,
    generate_branch_summary,
    prepare_branch_entries,
)
from .compaction import (
    DEFAULT_COMPACTION_SETTINGS,
    calculate_context_tokens,
    compact,
    estimate_context_tokens,
    estimate_tokens,
    find_cut_point,
    find_turn_start_index,
    generate_summary,
    generate_summary_with_usage,
    get_last_assistant_usage,
    prepare_compaction,
    serialize_conversation,
    should_compact,
)

__all__ = [
    "DEFAULT_COMPACTION_SETTINGS",
    "calculate_context_tokens",
    "collect_entries_for_branch_summary",
    "compact",
    "estimate_context_tokens",
    "estimate_tokens",
    "find_cut_point",
    "find_turn_start_index",
    "generate_branch_summary",
    "generate_summary",
    "generate_summary_with_usage",
    "get_last_assistant_usage",
    "prepare_branch_entries",
    "prepare_compaction",
    "serialize_conversation",
    "should_compact",
]
