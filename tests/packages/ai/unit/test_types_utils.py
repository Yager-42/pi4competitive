from __future__ import annotations

import pytest

from earendil_works.pi_ai.api.transform_messages import (
    build_anthropic_messages_payload,
    build_openai_completions_payload,
)
from earendil_works.pi_ai.utils.json_parse import parse_partial_json
from earendil_works.pi_ai.utils.validation import ValidationError, validate_tool_arguments
from earendil_works.pi_ai.utils.uuid import uuidv7


def test_context_messages_roundtrip_json() -> None:
    import json

    ctx = {
        "systemPrompt": "sys",
        "messages": [
            {"role": "user", "content": "hi", "timestamp": 1},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "yo"}],
                "api": "faux",
                "provider": "faux",
                "model": "faux-1",
                "usage": {
                    "input": 1,
                    "output": 1,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "totalTokens": 2,
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0},
                },
                "stopReason": "stop",
                "timestamp": 2,
            },
        ],
    }
    restored = json.loads(json.dumps(ctx))
    assert restored == ctx


def test_validation_reject_bad_tool_args() -> None:
    schema = {
        "type": "object",
        "properties": {"q": {"type": "string"}},
        "required": ["q"],
        "additionalProperties": False,
    }
    with pytest.raises(ValidationError):
        validate_tool_arguments(schema, {})
    assert validate_tool_arguments(schema, {"q": "x"})["q"] == "x"


def test_parse_partial_json() -> None:
    assert parse_partial_json('{"a": 1')["a"] == 1
    assert parse_partial_json("") == {}


def test_uuidv7_shape() -> None:
    u = uuidv7()
    assert isinstance(u, str)
    assert len(u) >= 8


def test_openai_completions_payload_tools_shape() -> None:
    model = {
        "id": "gpt-test",
        "name": "t",
        "api": "openai-completions",
        "provider": "openai",
        "baseUrl": "https://api.openai.com/v1",
        "reasoning": False,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 8,
        "maxTokens": 8,
    }
    ctx = {
        "messages": [{"role": "user", "content": "hi", "timestamp": 0}],
        "tools": [
            {
                "name": "lookup",
                "description": "d",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
            }
        ],
    }
    payload = build_openai_completions_payload(model, ctx)
    assert payload["model"] == "gpt-test"
    assert payload["stream"] is True
    assert payload["tools"][0]["type"] == "function"
    assert payload["tools"][0]["function"]["name"] == "lookup"


def test_anthropic_messages_tool_name_normalization() -> None:
    model = {
        "id": "claude",
        "name": "c",
        "api": "anthropic-messages",
        "provider": "anthropic",
        "baseUrl": "https://api.anthropic.com",
        "reasoning": False,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 8,
        "maxTokens": 256,
    }
    ctx = {
        "systemPrompt": "s",
        "messages": [{"role": "user", "content": "hi", "timestamp": 0}],
        "tools": [
            {
                "name": "lookup",
                "description": "d",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
    }
    payload = build_anthropic_messages_payload(model, ctx)
    assert payload["tools"][0]["name"] == "lookup"
    assert "input_schema" in payload["tools"][0]
    assert payload["system"] == "s"
