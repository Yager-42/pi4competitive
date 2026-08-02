"""Native sandbox workspace helpers (ADAPT of the Docker path guard).

Source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/guards/docker_path_guard.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)

Host delta (P3.3 Phase D, G0 map §6.1): the canonical-root/ensure/remove
workspace guards are Docker-path-agnostic and are ported verbatim; the
``/mnt/poirot/user-data`` virtual-path validation and redirect scanning
belong to the deleted Docker guard and are NOT carried over (the native
worker runs on the host; the SRT policy is the path boundary).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..exceptions import SandboxPermissionError

_SCOPE_ID_PATTERN = re.compile(r"^[a-f0-9]{64}$")


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
    non-symlink ``<64hex>`` child of the canonical root. The historical
    ``<scope>.lock`` sidecar is removed for layout parity.
    """
    workspace = ensure_workspace(root, scope_id)
    shutil.rmtree(workspace)
    lock_file = workspace.parent / f"{scope_id}.lock"
    try:
        lock_file.unlink(missing_ok=True)
    except OSError:
        pass


__all__ = ["canonical_workspace_root", "ensure_workspace", "remove_workspace"]
