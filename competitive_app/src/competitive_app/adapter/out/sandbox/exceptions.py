"""Poirot sandbox exceptions.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/exceptions.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)
Host delta: import/package path only (COPY).
"""
from __future__ import annotations


class SandboxError(Exception):
    """Sandbox error base with structured details."""

    def __init__(self, message: str = "", *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if not self.details:
            return self.message
        parts = [f"{key}={value!r}" for key, value in self.details.items()]
        return f"{self.message} ({', '.join(parts)})"


class SandboxNotFoundError(SandboxError):
    """Sandbox instance was not found."""

    def __init__(self, sandbox_id: str) -> None:
        super().__init__(
            f"sandbox not found: {sandbox_id}",
            details={"sandbox_id": sandbox_id},
        )


class SandboxRuntimeError(SandboxError):
    """Runtime unavailable or misconfigured."""


class SandboxCommandError(SandboxError):
    """Command execution failed; command details are bounded."""

    def __init__(
        self,
        message: str,
        *,
        command: str,
        exit_code: int | None = None,
    ) -> None:
        truncated = command[:100] + "..." if len(command) > 100 else command
        super().__init__(
            message,
            details={"command": truncated, "exit_code": exit_code},
        )


class SandboxFileError(SandboxError):
    """File operation failed."""

    def __init__(self, message: str, *, path: str, operation: str) -> None:
        super().__init__(
            message,
            details={"path": path, "operation": operation},
        )


class SandboxPermissionError(SandboxFileError):
    """Sandbox permission check failed."""


class SandboxFileNotFoundError(SandboxFileError):
    """Sandbox file was not found."""
