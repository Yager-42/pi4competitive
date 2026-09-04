"""Clarify scope (P1): an explicit competitor answer is the complete set.

The competitors question exists to narrow scope. Treating the answer as a
floor let the deselected candidates return via `discovered`, so choosing 2
competitors researched 6 — three times the coverage cells and runtime.
"""
from __future__ import annotations

from competitive_app.application.workflow.task_service import _coerce_competitors

DISCOVERED = [
    "Notion",
    "Evernote",
    "Microsoft OneNote",
    "Obsidian",
    "Google Keep",
    "Bear",
    "Logseq",
]


def test_exclusive_answer_is_not_widened_by_discovered() -> None:
    result = _coerce_competitors(
        ["Notion", "Obsidian", "Evernote"],  # LLM tried to expand
        DISCOVERED,
        ["Notion", "Obsidian"],
        exclusive=True,
    )
    assert result == ["Notion", "Obsidian"]


def test_exclusive_answer_dedups_and_caps() -> None:
    result = _coerce_competitors(
        None,
        DISCOVERED,
        ["Notion", "Notion", "Obsidian"],
        exclusive=True,
    )
    assert result == ["Notion", "Obsidian"]


def test_non_exclusive_still_unions_as_before() -> None:
    """No explicit answer: keep the v0.2.8 floor behaviour so the LLM cannot
    drop a query-listed brand."""
    result = _coerce_competitors(["Logseq"], DISCOVERED, ["Notion"], exclusive=False)
    assert result[0] == "Notion"
    assert "Logseq" in result
    assert len(result) <= 6


def test_exclusive_with_empty_must_include_falls_back_to_union() -> None:
    """`exclusive` only binds when there is an actual selection to honour."""
    result = _coerce_competitors(["Notion"], DISCOVERED, [], exclusive=True)
    assert "Notion" in result
    assert len(result) > 1


def test_union_path_is_capped_at_six() -> None:
    result = _coerce_competitors(None, DISCOVERED, [], exclusive=False)
    assert len(result) == 6
