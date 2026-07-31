"""Hardened Docker CLI backend for one AgentTool sandbox scope.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/docker/local_container_backend.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)
Host delta: digest-only images, one workspace bind, loopback-only control
port, fixed environment allowlist, and locked Docker hardening policy.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..contracts.sandbox_backend import SandboxBackend
from ..guards.docker_path_guard import ensure_workspace
from ..types import (
    CPU_LIMIT,
    FILE_SIZE_LIMIT,
    MEMORY_LIMIT,
    MEMORY_SWAP_LIMIT,
    NOFILE_LIMIT,
    PIDS_LIMIT,
    TMPFS_SIZE,
    VIRTUAL_WORKSPACE_PREFIX,
    SandboxInfo,
    require_digest_image,
    require_scope_id,
)
from .executor import DockerExecutor, LocalDockerExecutor

_CONTAINER_PORT = 8080
_CONTAINER_USER = "1000:1000"
_CONTAINER_LABEL = "competitive-app.agent-tool-sandbox=v1"
_ALLOWED_ENVIRONMENT = frozenset(
    {
        "TAVILY_API_KEY",
        "TAVILY_API_URL",
        "ANYSEARCH_API_KEY",
        "ANYSEARCH_API_URL",
        "GROK_API_KEY",
        "GROK_API_URL",
        "GROK_MODEL",
    }
)


def _get_free_port(start: int = 18080) -> int:
    """Return a currently free loopback port (Docker allocation is authoritative)."""
    del start
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _normalise_tmpfs(value: object) -> str:
    return str(value or "").replace(" ", "").lower()


def _has_limit(ulimits: object, name: str, value: int) -> bool:
    if not isinstance(ulimits, list):
        return False
    for item in ulimits:
        if not isinstance(item, dict) or item.get("Name") != name:
            continue
        return item.get("Soft") == value and item.get("Hard") == value
    return False


class LocalContainerBackend(SandboxBackend):
    """Provision and inspect hardened Docker containers.

    The public methods are async so FastAPI lifecycle code never blocks the
    event loop; all Docker CLI calls run in a worker thread.  The backend has
    no arbitrary mount or provider selection surface.
    """

    def __init__(
        self,
        *,
        image: str,
        sandbox_root: str | Path,
        environment: Mapping[str, str | None] | None = None,
        container_prefix: str = "competitive-app-sandbox",
        executor: DockerExecutor | None = None,
    ) -> None:
        self._image = require_digest_image(image)
        self._sandbox_root = Path(sandbox_root)
        self._environment = {
            key: value
            for key, value in (environment or {}).items()
            if key in _ALLOWED_ENVIRONMENT and value is not None
        }
        self._prefix = container_prefix
        self._executor = executor or LocalDockerExecutor()
        self._image_id: str | None = None

    @property
    def image(self) -> str:
        return self._image

    @property
    def sandbox_root(self) -> Path:
        return self._sandbox_root

    @property
    def environment_names(self) -> frozenset[str]:
        return frozenset(self._environment)

    def _container_name(self, scope_id: str) -> str:
        return f"{self._prefix}-{require_scope_id(scope_id)}"

    def _run(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return self._executor.run(command, **kwargs)

    def verify_image_identity(self) -> str:
        """E1 startup gate: daemon reachable AND pinned digest resolved locally."""
        image_id = self._resolve_image_id()
        if image_id is None:
            raise RuntimeError(
                f"sandbox image not found locally or daemon unavailable: {self._image}"
            )
        return image_id

    def read_baked_manifest(self) -> bytes:
        """Read the baked ``approved_tools.json`` out of the pinned image.

        E1 startup handshake: the host registry must be a subset of the
        image's baked manifest with identical targets.
        """
        result = self._run(
            [
                "docker", "run", "--rm", "--read-only", "--network", "none",
                "--entrypoint", "cat", self._image,
                "/opt/pi4competitive/approved_tools.json",
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            detail = (result.stderr or b"").decode(errors="replace")[:200]
            raise RuntimeError(f"failed to read baked worker manifest: {detail}")
        return result.stdout
    def _resolve_image_id(self) -> str | None:
        """Resolve the pinned manifest digest to its immutable image config ID.

        Docker normalizes ``Config.Image`` to the tag form, so container image
        identity is proven by comparing the container's ``Image`` (config ID)
        against the pinned digest's resolved ID.
        """
        if self._image_id is not None:
            return self._image_id
        try:
            result = self._run(
                ["docker", "image", "inspect", "--format", "{{.Id}}", self._image],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        self._image_id = result.stdout.strip() or None
        return self._image_id

    async def create(self, scope_id: str) -> SandboxInfo:
        return await asyncio.to_thread(self._create_sync, require_scope_id(scope_id))

    def _create_sync(self, scope_id: str) -> SandboxInfo:
        existing = self._discover_sync(scope_id)
        if existing is not None:
            return existing
        workspace = ensure_workspace(self._sandbox_root, scope_id)
        port = _get_free_port()
        name = self._container_name(scope_id)
        command = self._run_command(
            name=name,
            scope_id=scope_id,
            workspace=workspace,
            port=port,
        )
        child_env = os.environ.copy()
        child_env.update(self._environment)
        try:
            result = self._run(
                command,
                capture_output=True,
                text=True,
                check=True,
                env=child_env,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "docker run failed").strip()
            raise RuntimeError(f"failed to start sandbox container: {detail[:500]}") from exc
        container_id = (result.stdout or "").strip() or None
        info = SandboxInfo(
            sandbox_id=scope_id,
            sandbox_url=f"http://127.0.0.1:{port}",
            container_name=name,
            container_id=container_id,
        )
        inspected = self._inspect_sync(name)
        if inspected is None or not self._validate_inspect(inspected, scope_id):
            self._stop_sync(info)
            raise RuntimeError("Docker sandbox failed hardening inspection")
        return info

    def _run_command(self, *, name: str, scope_id: str, workspace: Path, port: int) -> list[str]:
        mount = f"type=bind,src={workspace},dst={VIRTUAL_WORKSPACE_PREFIX},readonly=false"
        command = [
            "docker",
            "run",
            "--rm",
            "--detach",
            "--name",
            name,
            "--label",
            _CONTAINER_LABEL,
            "--publish",
            f"127.0.0.1:{port}:{_CONTAINER_PORT}/tcp",
            "--user",
            _CONTAINER_USER,
            "--read-only",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,size={TMPFS_SIZE}",
            "--tmpfs",
            f"/run:rw,noexec,nosuid,size={TMPFS_SIZE},uid=1000,gid=1000",
            "--tmpfs",
            f"/var/log/gem:rw,nosuid,size={TMPFS_SIZE},uid=1000,gid=1000,mode=1777",
            "--tmpfs",
            f"/var/lib/aio-sandbox:rw,nosuid,size={TMPFS_SIZE},uid=1000,gid=1000",
            "--tmpfs",
            f"/var/lib/nginx:rw,nosuid,size={TMPFS_SIZE},uid=1000,gid=1000,mode=1777",
            "--tmpfs",
            f"/home/gem:rw,nosuid,size={TMPFS_SIZE},uid=1000,gid=1000",
            "--tmpfs",
            f"/opt/aio:rw,nosuid,size={TMPFS_SIZE},uid=1000,gid=1000",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--cpus",
            CPU_LIMIT,
            "--memory",
            MEMORY_LIMIT,
            "--memory-swap",
            MEMORY_SWAP_LIMIT,
            "--pids-limit",
            str(PIDS_LIMIT),
            "--ulimit",
            f"nofile={NOFILE_LIMIT}:{NOFILE_LIMIT}",
            "--ulimit",
            f"fsize={_bytes_from_size(FILE_SIZE_LIMIT)}:{_bytes_from_size(FILE_SIZE_LIMIT)}",
            "--mount",
            mount,
            "--env",
            f"SANDBOX_ID={scope_id}",
            "--env",
            f"THREAD_ID={scope_id}",
        ]
        for key in sorted(self._environment):
            # Docker inherits the value from the subprocess environment.  The
            # secret itself therefore never appears in argv or worker frames.
            command.extend(("--env", key))
        command.append(self._image)
        return command

    async def destroy(self, info: SandboxInfo) -> None:
        await asyncio.to_thread(self._stop_sync, info)

    def _stop_sync(self, info: SandboxInfo) -> None:
        target = info.container_id or info.container_name
        if not target:
            return
        try:
            result = self._run(
                ["docker", "stop", "--time", str(3), target],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode not in (0, 1):
                raise RuntimeError((result.stderr or "docker stop failed").strip())
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"failed to stop sandbox container: {target}") from exc
        # A stopped container may remain briefly in Docker's inspect table;
        # --rm removes it asynchronously.  Never report a running container as
        # destroyed, but tolerate a disappeared container.
        deadline = asyncio_timeout_monotonic() + 5.0
        while asyncio_timeout_monotonic() < deadline:
            inspected = self._inspect_sync(target)
            if inspected is None or not bool((inspected.get("State") or {}).get("Running")):
                return
        raise RuntimeError(f"sandbox container did not stop: {target}")

    async def is_alive(self, info: SandboxInfo) -> bool | None:
        return await asyncio.to_thread(self._is_alive_sync, info)

    def _is_alive_sync(self, info: SandboxInfo) -> bool | None:
        target = info.container_name or self._container_name(info.sandbox_id)
        inspected = self._inspect_sync(target)
        if inspected is None:
            return False
        state = inspected.get("State")
        if not isinstance(state, dict) or "Running" not in state:
            return None
        return bool(state["Running"])

    async def discover(self, scope_id: str) -> SandboxInfo | None:
        return await asyncio.to_thread(self._discover_sync, require_scope_id(scope_id))

    def _discover_sync(self, scope_id: str) -> SandboxInfo | None:
        name = self._container_name(scope_id)
        inspected = self._inspect_sync(name)
        if inspected is None:
            return None
        state = inspected.get("State")
        if not isinstance(state, dict) or not state.get("Running"):
            return None
        if not self._validate_inspect(inspected, scope_id):
            raise RuntimeError(f"existing sandbox failed hardening inspection: {name}")
        port = self._host_port(inspected)
        if port is None:
            raise RuntimeError(f"existing sandbox has no loopback control port: {name}")
        return SandboxInfo(
            sandbox_id=scope_id,
            sandbox_url=f"http://127.0.0.1:{port}",
            container_name=name,
            container_id=str(inspected.get("Id") or "") or None,
            created_at=str(inspected.get("Created") or ""),
        )

    async def list_running(self) -> list[SandboxInfo]:
        return await asyncio.to_thread(self._list_running_sync)

    def _list_running_sync(self) -> list[SandboxInfo]:
        try:
            result = self._run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    f"label={_CONTAINER_LABEL}",
                    "--format",
                    "{{.Names}}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []
        names = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        infos: list[SandboxInfo] = []
        for name in names:
            if not name.startswith(f"{self._prefix}-"):
                continue
            scope_id = name[len(self._prefix) + 1 :]
            if len(scope_id) != 64:
                continue
            inspected = self._inspect_sync(name)
            if inspected is None or not self._validate_inspect(inspected, scope_id):
                continue
            port = self._host_port(inspected)
            if port is None:
                continue
            infos.append(
                SandboxInfo(
                    sandbox_id=scope_id,
                    sandbox_url=f"http://127.0.0.1:{port}",
                    container_name=name,
                    container_id=str(inspected.get("Id") or "") or None,
                    created_at=str(inspected.get("Created") or ""),
                )
            )
        return infos

    def _inspect_sync(self, target: str) -> dict[str, Any] | None:
        try:
            result = self._run(
                ["docker", "inspect", target],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            return None
        return payload[0]

    def _host_port(self, inspected: Mapping[str, Any]) -> int | None:
        ports = ((inspected.get("NetworkSettings") or {}).get("Ports") or {})
        entries = ports.get(f"{_CONTAINER_PORT}/tcp")
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("HostIp") not in ("127.0.0.1", "127.0.0.1/32"):
                continue
            try:
                return int(entry["HostPort"])
            except (KeyError, TypeError, ValueError):
                return None
        return None

    def _validate_inspect(self, inspected: Mapping[str, Any], scope_id: str) -> bool:
        config = inspected.get("Config")
        host = inspected.get("HostConfig")
        mounts = inspected.get("Mounts")
        if not isinstance(config, dict) or not isinstance(host, dict) or not isinstance(mounts, list):
            return False
        labels = config.get("Labels") or {}
        image_id = self._resolve_image_id()
        if image_id is None or inspected.get("Image") != image_id:
            return False
        if config.get("User") != _CONTAINER_USER:
            return False
        if host.get("ReadonlyRootfs") is not True or host.get("Privileged") is True:
            return False
        if host.get("NetworkMode") == "host" or host.get("PidMode") or host.get("IpcMode") in ("host", "shareable"):
            return False
        if host.get("CapAdd") not in (None, []):
            return False
        cap_drop = host.get("CapDrop") or []
        if "ALL" not in cap_drop and "all" not in cap_drop:
            return False
        security = {str(item).lower() for item in (host.get("SecurityOpt") or [])}
        if "no-new-privileges" not in security and "no-new-privileges:true" not in security:
            return False
        if host.get("PidsLimit") != PIDS_LIMIT:
            return False
        if host.get("Memory") != _bytes_from_size(MEMORY_LIMIT) or host.get("MemorySwap") != _bytes_from_size(MEMORY_SWAP_LIMIT):
            return False
        if host.get("NanoCpus") != 1_000_000_000:
            return False
        if not _has_limit(host.get("Ulimits"), "nofile", NOFILE_LIMIT):
            return False
        if not _has_limit(host.get("Ulimits"), "fsize", _bytes_from_size(FILE_SIZE_LIMIT)):
            return False
        tmpfs = host.get("Tmpfs") or {}
        if not isinstance(tmpfs, dict) or not all(
            path in tmpfs and _tmpfs_is_capped(tmpfs[path])
            for path in (
                "/tmp",
                "/run",
                "/var/log/gem",
                "/var/lib/aio-sandbox",
                "/var/lib/nginx",
                "/home/gem",
                "/opt/aio",
            )
        ):
            return False
        if len(mounts) != 1:
            return False
        mount = mounts[0]
        workspace = self._sandbox_root.resolve() / scope_id
        if not isinstance(mount, dict):
            return False
        if (
            mount.get("Type") != "bind"
            or Path(str(mount.get("Source", ""))).resolve() != workspace
            or mount.get("Destination") != VIRTUAL_WORKSPACE_PREFIX
            or mount.get("RW") is not True
        ):
            return False
        if inspected.get("HostConfig", {}).get("Binds") not in (None, []):
            return False
        return self._host_port(inspected) is not None


def _bytes_from_size(value: str) -> int:
    raw = value.strip().lower()
    units = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
    for suffix, multiplier in units.items():
        if raw.endswith(suffix):
            return int(float(raw[: -len(suffix)]) * multiplier)
    return int(raw)


def _tmpfs_is_capped(value: object) -> bool:
    normalised = _normalise_tmpfs(value)
    return "size=268435456" in normalised or "size=256m" in normalised or "size=262144k" in normalised


def asyncio_timeout_monotonic() -> float:
    # Local import keeps module import cheap and makes the helper easy to patch
    # in deterministic backend tests.
    import time

    return time.monotonic()


__all__ = ["LocalContainerBackend"]
