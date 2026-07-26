from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PATH = Path(__file__).parents[3] / "capability_packages/reasonix_prefix_cache/extensions/reasonix_prefix_cache.py"
_SPEC = importlib.util.spec_from_file_location("reasonix_prefix_cache", _PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
_canonicalize = _MODULE._canonicalize


def test_reasonix_canonicalizes_known_tool_shapes_and_marker() -> None:
    marker = {"type": "ephemeral"}
    openai = {"tools": [
        {"function": {"name": "z", "parameters": {"required": ["b", "a"]}}, "cache_control": marker},
        {"function": {"name": "a", "parameters": {"type": "object"}}},
    ]}
    canonical, diagnostic = _canonicalize(openai)
    assert diagnostic is None
    assert [tool["function"]["name"] for tool in canonical["tools"]] == ["a", "z"]
    assert canonical["tools"][-1]["cache_control"] == marker
    assert canonical["tools"][-1]["function"]["parameters"]["required"] == ["b", "a"]

    anthropic = {"tools": [
        {"name": "z", "defer_loading": True}, {"name": "b", "cache_control": marker}, {"name": "a"},
    ]}
    canonical, diagnostic = _canonicalize(anthropic)
    assert diagnostic is None
    assert [tool["name"] for tool in canonical["tools"]] == ["a", "b", "z"]
    assert canonical["tools"][1]["cache_control"] == marker
