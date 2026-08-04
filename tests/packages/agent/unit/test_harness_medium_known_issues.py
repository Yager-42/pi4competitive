from __future__ import annotations

import pytest


from earendil_works.pi_agent.harness.session.jsonl_storage import (
    parse_entry_line,
    parse_header_line,
)
from earendil_works.pi_agent.harness.types import SessionError


def test_jsonl_rejects_non_finite_values() -> None:
    for constant in ("NaN", "Infinity", "-Infinity"):
        line = (
            '{"type":"custom_message","id":"x","parentId":null,"timestamp":"t",'
            f'"customType":"x","content":{constant},"display":true}}'
        )
        with pytest.raises(SessionError, match="valid JSON"):
            parse_entry_line(line, "session.jsonl", 2)

    header = (
        '{"type":"session","version":3,"id":"s","timestamp":"t",'
        '"cwd":"/repo","metadata":{"value":NaN}}'
    )
    with pytest.raises(SessionError, match="valid session header"):
        parse_header_line(header, "session.jsonl")


def test_jsonl_rejects_malformed_message_content_blocks() -> None:
    base = '{"type":"message","id":"x","parentId":null,"timestamp":"t","message":'
    for block in ('{}', '{"type":"toolCall"}', '{"type":"image","data":"x"}'):
        with pytest.raises(SessionError, match="content block"):
            parse_entry_line(base + '{"role":"assistant","content":[' + block + ']}}', "s", 2)
    valid = parse_entry_line(
        base
        + '{"role":"assistant","content":[{"type":"text","text":"ok"},'
        '{"type":"thinking","thinking":"h"},{"type":"toolCall","id":"c",'
        '"name":"echo","arguments":{}}]}}',
        "s",
        2,
    )
    assert valid["message"]["content"][0]["text"] == "ok"  # type: ignore[index]
