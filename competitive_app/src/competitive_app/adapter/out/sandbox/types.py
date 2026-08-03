"""P3.3 sandbox types and fixed runtime constants.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/types.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see native/vendor/licenses/POIROT-MIT.txt)
Host delta: stdlib UTC timestamps, full 64-hex scope ids, and locked config
constants (ADAPT).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

IMAGE_DIGEST_PATTERN = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
SCOPE_ID_PATTERN = re.compile(r"^[a-f0-9]{64}$")

IDLE_TIMEOUT_SECONDS = 600
IDLE_SCAN_INTERVAL_SECONDS = 60
NO_CHANGE_TIMEOUT_SECONDS = 1800
REPLICAS = 3
READINESS_TIMEOUT_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 5
STOP_TIMEOUT_SECONDS = 15
STOP_INSPECT_TIMEOUT_SECONDS = 5

CPU_LIMIT = "1"
MEMORY_LIMIT = "2g"
MEMORY_SWAP_LIMIT = "2g"
PIDS_LIMIT = 128
TMPFS_SIZE = "256m"
NOFILE_LIMIT = 1024
FILE_SIZE_LIMIT = "100m"
VIRTUAL_WORKSPACE_PREFIX = "/mnt/poirot/user-data"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def require_digest_image(image: str) -> str:
    if not isinstance(image, str) or IMAGE_DIGEST_PATTERN.fullmatch(image) is None:
        raise ValueError("sandbox image must be pinned by registry and sha256 digest")
    return image


def require_scope_id(scope_id: str) -> str:
    if not isinstance(scope_id, str) or SCOPE_ID_PATTERN.fullmatch(scope_id) is None:
        raise ValueError("sandbox scope id must be a lowercase 64-hex value")
    return scope_id


@dataclass(frozen=True, slots=True)
class SandboxInfo:
    sandbox_id: str
    sandbox_url: str
    container_name: str | None = None
    container_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        require_scope_id(self.sandbox_id)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "sandbox_id": self.sandbox_id,
            "sandbox_url": self.sandbox_url,
            "container_name": self.container_name,
            "container_id": self.container_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SandboxInfo":
        return cls(
            sandbox_id=str(data["sandbox_id"]),
            sandbox_url=str(data.get("sandbox_url") or ""),
            container_name=str(data["container_name"]) if data.get("container_name") else None,
            container_id=str(data["container_id"]) if data.get("container_id") else None,
            created_at=str(data.get("created_at") or utc_now_iso()),
        )


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    image: str
    workspace_root: Path
    build_identity: str

    def __post_init__(self) -> None:
        require_digest_image(self.image)
        if not self.build_identity:
            raise ValueError("sandbox build identity must be non-empty")


__all__ = [
    "CPU_LIMIT",
    "FILE_SIZE_LIMIT",
    "IDLE_SCAN_INTERVAL_SECONDS",
    "IDLE_TIMEOUT_SECONDS",
    "MEMORY_LIMIT",
    "MEMORY_SWAP_LIMIT",
    "NO_CHANGE_TIMEOUT_SECONDS",
    "NOFILE_LIMIT",
    "PIDS_LIMIT",
    "READINESS_TIMEOUT_SECONDS",
    "REPLICAS",
    "REQUEST_TIMEOUT_SECONDS",
    "STOP_INSPECT_TIMEOUT_SECONDS",
    "STOP_TIMEOUT_SECONDS",
    "TMPFS_SIZE",
    "VIRTUAL_WORKSPACE_PREFIX",
    "SandboxConfig",
    "SandboxInfo",
    "require_digest_image",
    "require_scope_id",
    "utc_now_iso",
]
