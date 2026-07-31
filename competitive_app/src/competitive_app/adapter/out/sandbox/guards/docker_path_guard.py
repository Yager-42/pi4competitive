"""Docker path and workspace guard.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/guards/docker_path_guard.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)
Host delta: fixed prefix, traversal/symlink/workspace validation (ADAPT).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..exceptions import SandboxPermissionError

_VIRTUAL_PREFIX = "/mnt/poirot/user-data"
_REDIRECT_PATTERN = re.compile(r">{1,2}\s*(/[^\s;|&]*)")
_SCOPE_ID_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def _validate_virtual_path(path: str) -> None:
    if not isinstance(path, str) or "\x00" in path:
        raise SandboxPermissionError(
            f"invalid sandbox path: {path!r}", path=str(path), operation="validate_path"
        )
    if path != _VIRTUAL_PREFIX and not path.startswith(_VIRTUAL_PREFIX + "/"):
        raise SandboxPermissionError(
            f"path must be under {_VIRTUAL_PREFIX}: {path}",
            path=path,
            operation="validate_path",
        )
    relative = path[len(_VIRTUAL_PREFIX):]
    if relative == "":
        return
    if not relative.startswith("/") or relative.startswith("//") or "\\" in relative:
        raise SandboxPermissionError(
            f"path traversal is forbidden: {path}", path=path, operation="validate_path"
        )
    if any(part in ("", ".", "..") for part in relative[1:].split("/")): 
        raise SandboxPermissionError(
            f"path traversal is forbidden: {path}", path=path, operation="validate_path"
        )


class DockerPathGuard:
    """Require all virtual paths and redirects to stay in the fixed mount."""

    def validate_path(self, path: str, *, write: bool = False) -> None:
        del write
        _validate_virtual_path(path)

    def validate_command(self, command: str) -> None:
        if not isinstance(command, str) or "\x00" in command or ".." in command:
            raise SandboxPermissionError(
                "worker command contains a forbidden path", path=str(command), operation="validate_command"
            )
        for match in _REDIRECT_PATTERN.finditer(command):
            target = match.group(1)
            _validate_virtual_path(target)


def canonical_workspace_root(root: str | Path) -> Path:
    path = Path(root).expanduser()
    if path.exists() and path.is_symlink():
        raise SandboxPermissionError(
            "sandbox root must not be a symlink", path=str(path), operation="workspace_root"
        )
    path.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve(strict=True)
    if resolved.is_symlink() or not resolved.is_dir():
        raise SandboxPermissionError(
            "sandbox root must be a directory", path=str(resolved), operation="workspace_root"
        )
    return resolved


def ensure_workspace(root: str | Path, scope_id: str) -> Path:
    if not isinstance(scope_id, str) or _SCOPE_ID_PATTERN.fullmatch(scope_id) is None:
        raise SandboxPermissionError(
            "invalid sandbox scope id", path=str(scope_id), operation="workspace"
        )
    canonical_root = canonical_workspace_root(root)
    workspace = canonical_root / scope_id
    if workspace.parent != canonical_root:
        raise SandboxPermissionError(
            "workspace must be a direct sandbox-root child", path=str(workspace), operation="workspace"
        )
    if workspace.is_symlink():
        raise SandboxPermissionError(
            "sandbox workspace must not be a symlink", path=str(workspace), operation="workspace"
        )
    if workspace.exists() and not workspace.is_dir():
        raise SandboxPermissionError(
            "sandbox workspace must be a directory", path=str(workspace), operation="workspace"
        )
    workspace.mkdir(parents=False, exist_ok=True)
    resolved = workspace.resolve(strict=True)
    if resolved.parent != canonical_root or resolved.is_symlink():
        raise SandboxPermissionError(
            "sandbox workspace escaped its root", path=str(resolved), operation="workspace"
        )
    return resolved

def remove_workspace(root: str | Path, scope_id: str) -> None:
    """Delete the exact derived workspace directory (task-delete cascade only).

    Reuses ``ensure_workspace``'s guards: the target must be a direct
    non-symlink ``<64hex>`` child of the canonical root.
    """
    workspace = ensure_workspace(root, scope_id)
    shutil.rmtree(workspace)
    lock_file = workspace.parent / f"{scope_id}.lock"
    try:
        lock_file.unlink(missing_ok=True)
    except OSError:
        pass


__all__ = ["DockerPathGuard", "canonical_workspace_root", "ensure_workspace", "remove_workspace"]
