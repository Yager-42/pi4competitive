"""Production sandbox lifecycle bound to parent session scopes.

NEW-HOST: P3.3 E3/E4 composition — the outer session/task run owns exactly
one release; abort rejects new scope work and destroys the whole container
while preserving the workspace; task delete additionally removes only the
derived workspace.  Every scope id is derived from the parent session id,
never from raw HTTP/tool input.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts.sandbox_provider import SandboxProvider
from .native.workspace import remove_workspace
from .protocol import RpcFrame
from .sandbox import Sandbox
from .utils.sandbox_id import derive_sandbox_id
from .approved_registry import ApprovedToolRegistry
from .sandbox_tool_executor import SandboxToolExecutor

CANARY_SESSION_ID = "agent-tool-sandbox-startup-canary"


class SandboxLifecycle:
    """Own the outer run lifecycle and startup verification for one provider."""

    def __init__(
        self,
        *,
        provider: SandboxProvider,
        registry: ApprovedToolRegistry,
        executor: SandboxToolExecutor,
        sandbox_root: Path,
        backend: Any | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._executor = executor
        self._sandbox_root = Path(sandbox_root)
        self._backend = backend

    def scope_for(self, session_id: str) -> str:
        return derive_sandbox_id(session_id)

    async def release(self, *, session_id: str) -> None:
        """Outer run end: once-only release (no-op when nothing was acquired)."""
        await self._provider.release(self.scope_for(session_id))

    async def destroy(self, *, session_id: str) -> None:
        """Session/task abort: reject new scope work, destroy + verify, keep workspace."""
        await self._provider.destroy_scope(self.scope_for(session_id))

    async def delete_workspace(self, *, session_id: str) -> None:
        """Task delete: abort/destroy first, then delete only the derived workspace."""
        scope = self.scope_for(session_id)
        await self._provider.destroy_scope(scope)
        remove_workspace(self._sandbox_root, scope)

    async def shutdown(self) -> None:
        await self._provider.shutdown()

    async def verify_startup(self, *, build_identity: str) -> None:
        """E1.3: manifest handshake + isolated echo canary.

        The provider's readiness check enforces the RPC protocol; the host
        registry must be an exact subset of the image's baked manifest; the
        canary proves the baked manifest accepts the host's echo binding and
        the worker round-trips frames.
        """
        if "echo" not in self._registry.bindings:
            raise RuntimeError("sandbox startup canary requires the echo_example capability")
        if self._backend is not None:
            import json

            from .approved_registry import parse_approved_manifest

            raw = self._backend.read_baked_manifest()
            try:
                manifest = parse_approved_manifest(json.loads(raw))
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"sandbox baked manifest is invalid: {exc}") from exc
            self._registry.validate_baked_manifest(manifest, build_identity=build_identity)
        scope = derive_sandbox_id(CANARY_SESSION_ID)

        async def noop(_frame: RpcFrame) -> None:
            return None

        try:
            sandbox: Sandbox = await self._provider.acquire(scope)
            request = self._canary_request(scope)
            terminal = await sandbox.execute_worker(request, noop)
            if terminal.type != "result":
                raise RuntimeError("sandbox startup canary did not reach a result frame")
            content = (terminal.result or {}).get("content") or []
            text = "".join(
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
            if text != "canary":
                raise RuntimeError("sandbox startup canary echoed unexpected content")
        finally:
            try:
                await self._provider.destroy_scope(scope)
            except Exception:  # noqa: BLE001
                pass

    def _canary_request(self, scope_id: str) -> Any:
        from .protocol import PROTOCOL_VERSION, RpcRequest

        binding = self._registry.bindings["echo"]
        target = binding.to_mapping()
        return RpcRequest(
            protocol_version=PROTOCOL_VERSION,
            scope_id=scope_id,
            tool_call_id="startup-canary",
            tool_name="echo",
            target=target,
            arguments={"text": "canary"},
        )


__all__ = ["CANARY_SESSION_ID", "SandboxLifecycle"]
