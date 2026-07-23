from __future__ import annotations

from pathlib import Path

import pytest

from earendil_works.pi_agent import (
    compact,
    create_read_tool,
    create_write_tool,
    estimate_context_tokens,
    find_cut_point,
    prepare_compaction,
    should_compact,
)
from earendil_works.pi_agent.harness.prompt_templates import (
    PromptTemplate,
    format_prompt_template_invocation,
)
from earendil_works.pi_agent.harness.skills import load_skill_from_file, skill_to_context_injection
from earendil_works.pi_agent.harness.system_prompt import build_system_prompt


def test_should_compact_threshold() -> None:
    messages = [{"role": "user", "content": "x" * 400, "timestamp": 0}] * 50
    assert estimate_context_tokens(messages) > 100  # type: ignore[arg-type]
    assert should_compact(messages, context_window=1000, settings={"reserveTokens": 900})  # type: ignore[arg-type]
    assert not should_compact(messages, context_window=1_000_000)  # type: ignore[arg-type]


def test_prepare_and_cut_point() -> None:
    messages = [{"role": "user", "content": f"m{i}", "timestamp": i} for i in range(20)]
    cut = find_cut_point(messages, keep_recent_tokens=5)  # type: ignore[arg-type]
    assert 0 <= cut < len(messages)
    prep = prepare_compaction(messages, {"keepRecentTokens": 5})  # type: ignore[arg-type]
    assert "messagesToSummarize" in prep
    assert "messagesToKeep" in prep


@pytest.mark.asyncio
async def test_compact_fallback_summary() -> None:
    messages = [{"role": "user", "content": "hello world", "timestamp": 0}]
    result = await compact(messages)  # type: ignore[arg-type]
    assert "summary" in result
    assert result["tokensBefore"] >= 1


def test_skill_and_system_prompt(tmp_path: Path) -> None:
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text(
        "---\nname: demo\ndescription: A demo skill\n---\n\nDo the thing.\n",
        encoding="utf-8",
    )
    skill = load_skill_from_file(skill_path)
    assert skill.name == "demo"
    assert "demo" in skill_to_context_injection(skill)
    prompt = build_system_prompt(base="You are helpful.", skills=[skill])
    assert "You are helpful." in prompt
    assert "demo" in prompt


def test_prompt_template_args() -> None:
    t = PromptTemplate(name="x", content="Run: $ARGUMENTS")
    assert format_prompt_template_invocation(t, "abc") == "Run: abc"


@pytest.mark.asyncio
async def test_read_write_tools(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    write = create_write_tool()
    read = create_read_tool()
    await write.execute("1", {"path": str(target), "content": "hello"}, None, None)
    result = await read.execute("2", {"path": str(target)}, None, None)
    assert result["content"][0]["text"] == "hello"  # type: ignore[index]
