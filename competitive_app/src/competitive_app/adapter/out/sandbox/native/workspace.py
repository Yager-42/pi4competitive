"""Native sandbox workspace helpers (ADAPT of the Docker path guard).

Source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/guards/docker_path_guard.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see native/vendor/licenses/POIROT-MIT.txt)

Host delta (P3.3 Phase D, G0 map §6.1): the canonical-root/ensure/remove
workspace guards are Docker-path-agnostic and are ported verbatim; the
``/mnt/poirot/user-data`` virtual-path validation and redirect scanning
belong to the deleted Docker guard and are NOT carried over (the native
worker runs on the host; the SRT policy is the path boundary).
"""
from __future__ import annotations

import re
import os
import shutil
from pathlib import Path

from ..exceptions import SandboxPermissionError

_SCOPE_ID_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def canonical_workspace_root(root: str | Path) -> Path:
    path = Path(root).expanduser()
    try:
        path.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
        fd = os.open(path, flags)
        try:
            mode = os.fstat(fd).st_mode
            if (mode & 0o170000) != 0o40000:
                raise SandboxPermissionError(
                    "sandbox root must be a directory", path=str(path), operation="workspace_root"
                )
        finally:
            os.close(fd)
    except SandboxPermissionError:
        raise
    except OSError as error:
        raise SandboxPermissionError(
            "sandbox root must be a directory", path=str(path), operation="workspace_root"
        ) from error
    if path.is_symlink():
        raise SandboxPermissionError(
            "sandbox root must not be a symlink", path=str(path), operation="workspace_root"
        )
    return path.resolve(strict=True)


def open_workspace_descriptor(root: str | Path, scope_id: str) -> tuple[Path, int]:
    """Create/validate a scope and retain its directory descriptor.

    The scope name is opened relative to a validated root descriptor with
    ``O_NOFOLLOW``. Callers that perform later workspace operations should
    retain the returned fd and use it as the ``dir_fd`` rather than reopening
    the path by name.
    """
    if not isinstance(scope_id, str) or _SCOPE_ID_PATTERN.fullmatch(scope_id) is None:
        raise SandboxPermissionError(
            "invalid sandbox scope id", path=str(scope_id), operation="workspace"
        )
    canonical_root = canonical_workspace_root(root)
    workspace = canonical_root / scope_id
    root_fd: int | None = None
    workspace_fd: int | None = None
    try:
        root_fd = os.open(
            canonical_root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW,
        )
        try:
            try:
                os.mkdir(scope_id, mode=0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
            workspace_fd = os.open(
                scope_id,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW,
                dir_fd=root_fd,
            )
            mode = os.fstat(workspace_fd).st_mode
            if (mode & 0o170000) != 0o40000:
                raise OSError("sandbox workspace is not a directory")
        finally:
            os.close(root_fd)
            root_fd = None
    except OSError as error:
        if workspace_fd is not None:
            os.close(workspace_fd)
        if root_fd is not None:
            os.close(root_fd)
        raise SandboxPermissionError(
            "sandbox workspace must be a non-symlink directory",
            path=str(workspace),
            operation="workspace",
        ) from error
    assert workspace_fd is not None
    return workspace, workspace_fd


def ensure_workspace(root: str | Path, scope_id: str) -> Path:
    workspace, workspace_fd = open_workspace_descriptor(root, scope_id)
    os.close(workspace_fd)
    return workspace

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


__all__ = [
    "canonical_workspace_root",
    "ensure_workspace",
    "open_workspace_descriptor",
    "remove_workspace",
]
