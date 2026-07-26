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

class _Api:
    def __init__(self):
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler


def _registered():
    api = _Api()
    _MODULE.register(api)
    state = next(cell.cell_contents for cell in api.handlers["message_end"].__closure__
                 if isinstance(cell.cell_contents, _MODULE._State))
    return api.handlers, state


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


def test_reasonix_observes_real_usage_and_response_status() -> None:
    handlers, state = _registered()
    assert handlers["message_end"](
        {"message": {"usage": {"cacheRead": 9, "cacheWrite": 3}}}, None
    ) is None
    handlers["after_provider_response"]({"status": 200}, None)
    assert state.buckets[0] == {"cacheRead": 9, "cacheWrite": 3}
    assert state.diagnostics == ["provider_status:200"]
