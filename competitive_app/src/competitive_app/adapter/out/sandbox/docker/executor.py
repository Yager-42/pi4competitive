"""Docker CLI execution seam for the production AgentTool sandbox.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/docker/executor.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)
Host delta: Docker CLI only; remote/Apple Container execution is omitted.
"""
from __future__ import annotations

import subprocess
from typing import Protocol, runtime_checkable


@runtime_checkable
class DockerExecutor(Protocol):
    """Run Docker CLI arguments in the host process namespace."""

    def run(self, cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Execute a Docker command; kwargs mirror :func:`subprocess.run`."""
        ...

    def translate_path(self, host_path: str) -> str:
        """Return the path visible to the Docker daemon."""
        ...


class LocalDockerExecutor:
    """Default executor: invoke the local Docker CLI without shell parsing."""

    def run(self, cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if not cmd or cmd[0] != "docker":
            raise ValueError("Docker executor accepts only docker CLI commands")
        return subprocess.run(cmd, **kwargs)  # type: ignore[arg-type,return-value]

    def translate_path(self, host_path: str) -> str:
        return host_path


__all__ = ["DockerExecutor", "LocalDockerExecutor"]
