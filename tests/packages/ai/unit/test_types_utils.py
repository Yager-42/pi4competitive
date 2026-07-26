from __future__ import annotations

import pytest

from earendil_works.pi_ai.api.transform_messages import (
    _cache_retention,
    build_anthropic_messages_payload,
    build_openai_completions_payload,
)
from earendil_works.pi_ai.utils.json_parse import parse_partial_json
from earendil_works.pi_ai.api._http_stream import _openai_usage
from earendil_works.pi_ai.api.anthropic_messages import _apply_anthropic_usage
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

def test_cache_retention_resolution(monkeypatch) -> None:
    monkeypatch.setenv("PI_CACHE_RETENTION", "long")
    assert _cache_retention({}) == "long"
    assert _cache_retention({"cacheRetention": "none"}) == "none"
    assert _cache_retention({"cacheRetention": "short"}) == "short"
    assert _cache_retention({"env": {"PI_CACHE_RETENTION": "short"}}) == "short"



def test_openai_completions_cache_request_and_usage() -> None:
    model = {
        "id": "gpt-test",
        "api": "openai-completions",
        "provider": "openai",
        "baseUrl": "https://api.openai.com/v1",
        "compat": {"supportsLongCacheRetention": True},
    }
    payload = build_openai_completions_payload(
        model, {"messages": []}, {"sessionId": "x" * 65, "cacheRetention": "long"}
    )
    assert payload["prompt_cache_key"] == "x" * 64
    assert payload["prompt_cache_retention"] == "24h"
    assert "prompt_cache_key" not in build_openai_completions_payload(
        model, {"messages": []}, {"sessionId": "session", "cacheRetention": "none"}
    )
    assert _openai_usage(
        {
            "prompt_tokens": 20,
            "completion_tokens": 3,
            "prompt_tokens_details": {"cached_tokens": 7, "cache_write_tokens": 5},
        }
    ) == {"input": 8, "output": 3, "cacheRead": 7, "cacheWrite": 5, "totalTokens": 23}
    assert _openai_usage(
        {"prompt_tokens": 20, "completion_tokens": 3, "prompt_cache_hit_tokens": 7}
    )["cacheRead"] == 7


def test_anthropic_cache_control_and_usage() -> None:
    model = {
        "id": "claude", "api": "anthropic-messages", "provider": "anthropic", "maxTokens": 8,
        "compat": {"supportsLongCacheRetention": True},
    }
    context = {
        "systemPrompt": "system",
        "messages": [{"role": "user", "content": "hello", "timestamp": 0}],
        "tools": [{"name": "lookup", "description": "d", "parameters": {"type": "object"}}],
    }
    payload = build_anthropic_messages_payload(model, context, {"cacheRetention": "long"})
    marker = {"type": "ephemeral", "ttl": "1h"}
    assert payload["system"][-1]["cache_control"] == marker
    assert payload["messages"][-1]["content"][-1]["cache_control"] == marker
    assert payload["tools"][-1]["cache_control"] == marker
    usage = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0}
    _apply_anthropic_usage(
        usage,
        {"input_tokens": 5, "output_tokens": 2, "cache_read_input_tokens": 7,
         "cache_creation_input_tokens": 3, "cache_creation": {"ephemeral_1h_input_tokens": 3}},
    )
    assert usage == {"input": 5, "output": 2, "cacheRead": 7, "cacheWrite": 3,
                     "cacheWrite1h": 3, "totalTokens": 17}


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
    assert payload["system"] == [{"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}]
