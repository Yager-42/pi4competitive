from __future__ import annotations

from pathlib import Path

import pytest

from earendil_works.pi_agent import AgentHarness
from earendil_works.pi_agent.harness.compaction import (
    generate_summary,
    prepare_branch_entries,
    should_compact,
    snapshot_fingerprint,
    validate_compaction_plan,
)
from earendil_works.pi_agent.harness.env.python_env import LocalFileSystem
from earendil_works.pi_agent.harness.messages import convert_to_llm
from earendil_works.pi_agent.harness.prompt_templates import (
    PromptTemplate,
    format_prompt_template_invocation,
)
from earendil_works.pi_agent.harness.session import InMemorySessionRepo
from earendil_works.pi_agent.harness.session.jsonl_storage import parse_entry_line
from earendil_works.pi_agent.harness.session.session import default_context_entry_transform
from earendil_works.pi_agent.harness.skills import (
    format_skills_for_system_prompt,
    load_skill_from_file,
)
from earendil_works.pi_agent.harness.types import SessionError, TError


@pytest.mark.asyncio
async def test_native_compaction_persists_and_rebuilds_context() -> None:
    repo = InMemorySessionRepo()
    session = await repo.create()
    old = {"role": "user", "content": "old", "timestamp": 1}
    active = {"role": "user", "content": "active", "timestamp": 2}
    await session.append_message(old)
    await session.append_message(active)
    harness = AgentHarness(session=session, stream_fn=None, model={})  # type: ignore[arg-type]
    harness.agent.state.messages = [old, active]

    result = await harness.compact()
    assert result is not None
    assert any(e["type"] == "compaction" for e in await session.get_entries())
    assert harness.agent.state.messages
    harness.close()


@pytest.mark.asyncio
async def test_generate_summary_uses_stream_fn_and_model() -> None:
    calls: list[tuple[object, object]] = []

    class Stream:
        async def result(self):
            return {"content": [{"type": "text", "text": "model summary"}]}

    def stream_fn(model, context, options):
        calls.append((model, context))
        return Stream()

    summary = await generate_summary(
        [{"role": "user", "content": "hello"}], stream_fn, {"id": "model"}
    )
    assert summary == "model summary"
    assert calls and calls[0][0] == {"id": "model"}


def test_should_compact_does_not_trigger_empty_zero_window() -> None:
    assert not should_compact([], context_window=0)
    assert not should_compact([], context_window=100, settings={"reserveTokens": 100})
    assert should_compact([{"role": "user", "content": "x"}], 100, {"reserveTokens": 100})


def test_branch_summary_uses_history_after_anchor() -> None:
    entries = [{"id": x, "type": "message"} for x in ("root", "anchor", "branch")]
    assert [e["id"] for e in prepare_branch_entries(entries, "anchor")] == ["branch"]
    assert prepare_branch_entries(entries, "missing") == entries


def test_compaction_plan_checks_results_independent_of_order() -> None:
    entries = [
        {"id": "result", "message": {"role": "toolResult", "toolCallId": "call", "content": []}},
        {"id": "call", "message": {"role": "assistant", "content": [{"type": "toolCall", "id": "call"}]}},
    ]
    plan = {
        "version": 1,
        "snapshotFingerprint": snapshot_fingerprint(entries),
        "foldEntryIds": ["result"],
        "retainEntryIds": ["call"],
    }
    with pytest.raises(ValueError, match="atomic"):
        validate_compaction_plan(plan, entries)


def test_context_transform_preserves_history_for_stale_anchor() -> None:
    entries = [
        {"type": "message", "id": "old", "parentId": None, "timestamp": "t", "message": {"role": "user", "content": "old"}},
        {"type": "compaction", "id": "compact", "parentId": "old", "timestamp": "t", "summary": "s", "tokensBefore": 1, "firstKeptEntryId": "missing"},
    ]
    result = default_context_entry_transform(entries)  # type: ignore[arg-type]
    assert [entry["id"] for entry in result] == ["old", "compact"]


@pytest.mark.asyncio
async def test_create_dir_reports_regular_file(tmp_path: Path) -> None:
    target = tmp_path / "file"
    target.write_text("x")
    result = await LocalFileSystem(cwd=str(tmp_path)).createDir("file")
    assert not result["ok"]
    assert result["error"].code == "already_exists"  # type: ignore[index]


def test_hidden_custom_messages_are_not_sent_to_model() -> None:
    messages = [
        {"role": "custom", "content": "hidden", "display": False, "timestamp": 1},
        {"role": "custom", "content": "visible", "display": True, "timestamp": 2},
    ]
    converted = convert_to_llm(messages)  # type: ignore[arg-type]
    assert len(converted) == 1
    assert converted[0]["content"][0]["text"] == "visible"  # type: ignore[index]


def test_prompt_template_args_treat_backslashes_literally() -> None:
    template = PromptTemplate(name="x", content="{{ arguments }}")
    assert format_prompt_template_invocation(template, r"C:\\tmp\1") == r"C:\\tmp\1"

def test_jsonl_parser_rejects_unknown_and_malformed_entries() -> None:
    with pytest.raises(SessionError) as unknown:
        parse_entry_line('{"type":"future","id":"x","timestamp":"t"}', "s", 2)
    assert unknown.value.code == "invalid_entry"
    with pytest.raises(SessionError):
        parse_entry_line(
            '{"type":"session_info","id":"x","parentId":null,"timestamp":"t","name":7}',
            "s",
            2,
        )
    valid = parse_entry_line(
        '{"type":"custom_message","id":"x","parentId":null,"timestamp":"t",'
        '"customType":"stage_output","content":{"stage":"research","items":[1,true]},"display":true}',
        "s",
        2,
    )
    assert valid["content"]["stage"] == "research"  # type: ignore[index]
    with pytest.raises(SessionError):
        parse_entry_line(
            '{"type":"custom_message","id":"y","parentId":null,"timestamp":"t",'
            '"customType":"stage_output","content":42,"display":true}',
            "s",
            2,
        )


@pytest.mark.asyncio
async def test_memory_repo_rejects_create_and_fork_id_collisions() -> None:
    repo = InMemorySessionRepo()
    source = await repo.create({"id": "same"})
    with pytest.raises(SessionError, match="already exists"):
        await repo.create({"id": "same"})
    with pytest.raises(SessionError, match="already exists"):
        await repo.fork(await source.get_metadata(), {"id": "same"})


def test_skill_markup_is_escaped_and_frontmatter_is_strict(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\nname: a & b\ndescription: x < y\ndisableModelInvocation: true\n---\nbody --- keep\n",
        encoding="utf-8",
    )
    skill = load_skill_from_file(path)
    assert skill.disableModelInvocation
    skill.disableModelInvocation = False
    rendered = format_skills_for_system_prompt([skill])
    assert "a &amp; b" in rendered
    assert "x &lt; y" in rendered

    path.write_text("---\nname: x\n---\nbody\n---\n", encoding="utf-8")
    parsed = load_skill_from_file(path)
    assert parsed.content == "body\n---\n"


def test_skill_frontmatter_opening_delimiter_allows_trailing_whitespace(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text("---   \nname: example\ndescription: Example\n---\n\nBODY\n", encoding="utf-8")

    skill = load_skill_from_file(path)

    assert skill.name == "example"
    assert skill.description == "Example"
    assert skill.content == "BODY\n"


def test_result_error_type_is_exception_bound() -> None:
    assert TError.__bound__ is BaseException


@pytest.mark.asyncio
async def test_shutdown_closes_subscription_when_extension_shutdown_fails() -> None:
    harness = object.__new__(AgentHarness)
    closed: list[bool] = []
    harness._unsub = lambda: closed.append(True)

    class BrokenAgent:
        async def shutdown_extensions(self):
            raise RuntimeError("boom")

    harness.agent = BrokenAgent()
    with pytest.raises(RuntimeError, match="boom"):
        await harness.shutdown()
    assert closed == [True]
