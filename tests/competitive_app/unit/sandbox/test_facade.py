from __future__ import annotations

from pathlib import Path

import pytest

from competitive_app.adapter.out.sandbox.contracts import PathTranslator, SecurityGuard
from competitive_app.adapter.out.sandbox.exceptions import SandboxPermissionError
from competitive_app.adapter.out.sandbox.native.paths import (
    NativePathTranslator,
    NativeSecurityGuard,
)
from competitive_app.adapter.out.sandbox.native.workspace import ensure_workspace
from competitive_app.adapter.out.sandbox.protocol import RpcFrame, RpcRequest
from competitive_app.adapter.out.sandbox.sandbox import FIXED_WORKER_COMMAND, Sandbox
from competitive_app.adapter.out.sandbox.utils import derive_sandbox_id


def test_scope_id_is_stable_full_width_and_workspace_is_direct_child(tmp_path: Path) -> None:
    scope = derive_sandbox_id("session-1")
    assert len(scope) == 64
    assert scope == derive_sandbox_id("session-1")
    assert scope != derive_sandbox_id("session-2")
    workspace = ensure_workspace(tmp_path / "sandboxes", scope)
    assert workspace.parent == (tmp_path / "sandboxes").resolve()
    assert workspace.name == scope


def test_workspace_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "sandboxes"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    scope = derive_sandbox_id("session")
    (root / scope).symlink_to(outside, target_is_directory=True)
    with pytest.raises(SandboxPermissionError, match="symlink"):
        ensure_workspace(root, scope)


def test_native_guard_only_accepts_fixed_worker_command() -> None:
    guard = NativeSecurityGuard()
    # Host paths are the SRT policy boundary, not the facade guard.
    guard.validate_path("/etc/passwd", write=True)
    guard.validate_command(FIXED_WORKER_COMMAND)
    for command in ("docker run evil", "rm -rf /", "python other.py"):
        with pytest.raises(SandboxPermissionError, match="fixed worker command"):
            guard.validate_command(command)


def test_native_translator_is_identity() -> None:
    translator = NativePathTranslator()
    assert translator.translate_path("/a/b") == "/a/b"
    assert translator.reverse_translate("/a/b") == "/a/b"
    assert translator.translate_command("x") == "x"
    assert translator.mask_output("secret") == "secret"
    assert isinstance(translator, PathTranslator)
    assert isinstance(NativeSecurityGuard(), SecurityGuard)


@pytest.mark.asyncio
async def test_sandbox_facade_preserves_validate_translate_execute_mask_order() -> None:
    calls: list[str] = []

    class Guard:
        def validate_command(self, command: str) -> None:
            calls.append(f"validate:{command}")

    class Translator:
        def translate_command(self, command: str) -> str:
            calls.append(f"translate:{command}")
            return "translated-worker"

        def mask_output(self, output: str) -> str:
            calls.append(f"mask:{output}")
            return output.replace("secret", "masked")

    class Runtime:
        async def execute_worker(self, request, on_frame, *, command, signal=None):  # type: ignore[no-untyped-def]
            calls.append(f"execute:{command}")
            frame = RpcFrame(1, request.scope_id, request.tool_call_id, 1, "result", result={"content": [{"type": "text", "text": "secret"}]})
            await on_frame(frame)
            return frame

        async def close(self) -> None:
            calls.append("close")

    request = RpcRequest(1, "scope", "call", "echo", {"module": "m", "qualname": "q"}, {})
    sandbox = Sandbox("scope", Runtime(), Translator(), Guard())
    frames: list[RpcFrame] = []
    await sandbox.execute_worker(request, frames.append)
    assert frames[0].result["content"][0]["text"] == "masked"  # type: ignore[index]
    assert calls[:3] == [
        "validate:python -m competitive_app.adapter.out.sandbox.worker",
        "translate:python -m competitive_app.adapter.out.sandbox.worker",
        "execute:translated-worker",
    ]
