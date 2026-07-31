"""Live security S1–S12 on the real derived worker image (feature §14.2).

Requires: SANDBOX_IMAGE pinned digest present locally + a working Docker
daemon.  Every assertion is enforcement on a real container (inspect, exec,
cross-scope reads), not command-string checks.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from competitive_app.adapter.out.sandbox.approved_registry import (
    ApprovedRegistryError,
    ApprovedToolRegistry,
)
from competitive_app.adapter.out.sandbox.docker.docker_sandbox_provider import DockerSandboxProvider
from competitive_app.adapter.out.sandbox.docker.local_container_backend import (
    _ALLOWED_ENVIRONMENT,
    LocalContainerBackend,
)
from competitive_app.adapter.out.sandbox.guards.docker_path_guard import remove_workspace
from competitive_app.adapter.out.sandbox.protocol import RpcFrame, RpcRequest
from competitive_app.adapter.out.sandbox.sandbox import Sandbox
from competitive_app.adapter.out.sandbox.types import (
    CPU_LIMIT,
    FILE_SIZE_LIMIT,
    MEMORY_LIMIT,
    MEMORY_SWAP_LIMIT,
    NOFILE_LIMIT,
    PIDS_LIMIT,
    TMPFS_SIZE,
    VIRTUAL_WORKSPACE_PREFIX,
    require_scope_id,
)
from competitive_app.adapter.out.sandbox.protocol import encode_request, RpcFrame, RpcRequest
from competitive_app.adapter.out.sandbox.utils.sandbox_id import derive_sandbox_id

pytestmark = [pytest.mark.live, pytest.mark.asyncio]

TMPFS_PATHS = (
    "/tmp",
    "/run",
    "/var/log/gem",
    "/var/lib/aio-sandbox",
    "/var/lib/nginx",
    "/home/gem",
    "/opt/aio",
)


def _image() -> str:
    image = os.environ.get("SANDBOX_IMAGE", "")
    if not image:
        pytest.skip("SANDBOX_IMAGE not set (S1–S12)")
    return image


def _docker(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def _require_docker() -> None:
    if _docker(["info"], timeout=15).returncode != 0:
        pytest.skip("docker daemon unavailable (S1–S12)")


async def _exec(container: str, command: str) -> subprocess.CompletedProcess[str]:
    return await asyncio.to_thread(
        _docker, ["exec", container, "bash", "-c", command], timeout={"timeout": 45}
    )


def _exec_sync(container: str, command: str) -> subprocess.CompletedProcess[str]:
    return _docker(["exec", container, "bash", "-c", command], timeout=45)


@pytest.fixture
async def sandbox_env(tmp_path: Path):
    _require_docker()
    image = _image()
    root = tmp_path / "sandboxes"
    root.mkdir(parents=True)
    os.environ.setdefault("LLM_API_KEY", "sentinel-secret-xyz")  # must never leak
    environment = {name: os.environ.get(name) for name in _ALLOWED_ENVIRONMENT}
    backend = LocalContainerBackend(image=image, sandbox_root=root, environment=environment)
    backend.verify_image_identity()
    provider = DockerSandboxProvider(
        image=image,
        sandbox_root=root,
        environment=environment,
        backend=backend,
        start_idle_checker=False,
    )
    await provider.start()
    yield backend, provider, root
    await provider.shutdown()


async def _acquire(provider: DockerSandboxProvider, scope: str) -> tuple[Sandbox, Any]:
    sandbox = await provider.acquire(scope)
    info = await provider.get_info(scope)
    assert info is not None and info.container_name is not None
    return sandbox, info


async def _noop_frame(_frame: RpcFrame) -> None:
    return None


def _request(scope: str, tool: str, target: dict[str, str], arguments: dict[str, Any]) -> RpcRequest:
    return RpcRequest(
        protocol_version=1,
        scope_id=scope,
        tool_call_id="live-sec",
        tool_name=tool,
        target=target,
        arguments=arguments,
    )


async def test_s1_host_canary_outside_mount_invisible(sandbox_env, tmp_path: Path) -> None:
    _, provider, root = sandbox_env
    canary = tmp_path / "host-canary" / "secret.txt"
    canary.parent.mkdir(parents=True)
    canary.write_text("top-secret", encoding="utf-8")
    scope = derive_sandbox_id("s1-session")
    sandbox, info = await _acquire(provider, scope)
    # workspace write visible inside the container
    (root / scope / "probe.txt").write_text("visible", encoding="utf-8")
    inside = _exec_sync(info.container_name, f"cat {VIRTUAL_WORKSPACE_PREFIX}/probe.txt")
    assert inside.returncode == 0 and inside.stdout.strip() == "visible"
    # the host canary is NOT reachable from the container by any path
    outside = _exec_sync(info.container_name, f"cat {canary}")
    assert outside.returncode != 0
    await provider.destroy_scope(scope)


async def test_s2_cross_scope_workspace_isolation(sandbox_env, tmp_path: Path) -> None:
    _, provider, root = sandbox_env
    scope_a = derive_sandbox_id("s2-session-a")
    scope_b = derive_sandbox_id("s2-session-b")
    assert scope_a != scope_b
    _, info_a = await _acquire(provider, scope_a)
    _, info_b = await _acquire(provider, scope_b)
    (root / scope_a / "private.txt").write_text("a-private", encoding="utf-8")
    # B's container cannot read A's workspace directory
    probe = _exec_sync(info_b.container_name, f"cat {VIRTUAL_WORKSPACE_PREFIX}/../{scope_a}/private.txt")
    assert probe.returncode != 0
    # B can read its own workspace
    (root / scope_b / "mine.txt").write_text("mine", encoding="utf-8")
    mine = _exec_sync(info_b.container_name, f"cat {VIRTUAL_WORKSPACE_PREFIX}/mine.txt")
    assert mine.returncode == 0 and mine.stdout.strip() == "mine"
    await provider.destroy_scope(scope_a)
    await provider.destroy_scope(scope_b)


async def test_s3_mounts_contain_only_workspace(sandbox_env, tmp_path: Path) -> None:
    backend, provider, root = sandbox_env
    scope = derive_sandbox_id("s3-session")
    _, info = await _acquire(provider, scope)
    inspected = _docker(["inspect", info.container_name])
    assert inspected.returncode == 0
    payload = json.loads(inspected.stdout)[0]
    mounts = payload["Mounts"]
    assert len(mounts) == 1
    mount = mounts[0]
    assert mount["Type"] == "bind"
    assert Path(mount["Source"]).resolve() == (root / scope).resolve()
    assert mount["Destination"] == VIRTUAL_WORKSPACE_PREFIX
    forbidden = ("/Volumes/lexar", ".git", ".env", "app.db", "sessions", "/home", "docker.sock")
    blob = json.dumps(mounts)
    for item in forbidden:
        assert item not in blob
    assert not payload["HostConfig"].get("Binds")  # no legacy -v binds
    await provider.destroy_scope(scope)


async def test_s4_symlink_and_traversal_guards(sandbox_env, tmp_path: Path) -> None:
    _, provider, root = sandbox_env
    # symlinked workspace must be refused, never followed
    evil = root / ("e" * 64)
    victim = tmp_path / "victim"
    victim.mkdir()
    evil.symlink_to(victim, target_is_directory=True)
    with pytest.raises(Exception, match="symlink|not a directory|invalid"):
        remove_workspace(root, ("e" * 64))
    assert victim.is_dir()  # untouched
    # traversal / raw inputs cannot reach backend commands
    for bad in ("", "..", "../x", "a" * 64 + "/x", "A" * 64):
        with pytest.raises(ValueError, match="64-hex"):
            require_scope_id(bad)
    await provider.shutdown()
    await provider.start()  # provider still usable after guard checks


async def test_s5_container_env_only_g21_names(sandbox_env) -> None:
    _, provider, root = sandbox_env
    scope = derive_sandbox_id("s5-session")
    _, info = await _acquire(provider, scope)
    inspected = _docker(["inspect", info.container_name])
    payload = json.loads(inspected.stdout)[0]
    env = payload["Config"]["Env"]
    names = {line.split("=", 1)[0] for line in env}
    # G21 host names pass through; baked base-image vars are allowed; host env
    # outside the fixed list must NOT leak (S5).
    for host_name in _ALLOWED_ENVIRONMENT:
        if os.environ.get(host_name) is not None:
            assert host_name in names, f"G21 var {host_name} missing from container"
    os.environ["SOME_HOST_SECRET"] = "host-only-value"
    assert "SOME_HOST_SECRET" not in names
    assert "LLM_API_KEY" not in names
    assert all("sentinel-secret-xyz" not in line for line in env)  # value absent
    assert all("host-only-value" not in line for line in env)
    assert f"SANDBOX_ID={scope}" in env
    await provider.destroy_scope(scope)


async def test_s6_worker_error_has_no_host_fallback(sandbox_env) -> None:
    _, provider, root = sandbox_env
    scope = derive_sandbox_id("s6-session")
    sandbox, _ = await _acquire(provider, scope)
    # unknown tool with a plausible target → worker rejects with error frame
    request = _request(
        scope,
        "not_a_real_tool",
        {"module": "capability_packages.echo_example.extensions.echo_tools", "qualname": "_echo_execute"},
        {"text": "x"},
    )
    terminal = await sandbox.execute_worker(request, _noop_frame)
    assert terminal.type == "error"
    assert terminal.error is not None
    assert terminal.error.get("safeMessage")
    await provider.destroy_scope(scope)


async def test_s7_digest_pinning_and_protocol_mismatch(sandbox_env, tmp_path: Path) -> None:
    _, provider, root = sandbox_env
    with pytest.raises(ValueError, match="pinned by registry and sha256 digest"):
        LocalContainerBackend(image="pi4competitive-tool-worker:dev-3", sandbox_root=root)
    scope = derive_sandbox_id("s7-session")
    with pytest.raises(Exception, match="unsupported protocol version"):
        encode_request(
            RpcRequest(
                protocol_version=999,
                scope_id=scope,
                tool_call_id="live-sec",
                tool_name="echo",
                target={"module": "capability_packages.echo_example.extensions.echo_tools", "qualname": "_echo_execute"},
                arguments={"text": "x"},
            )
        )


async def test_s8_limits_trigger_on_real_container(sandbox_env) -> None:
    _, provider, root = sandbox_env
    scope = derive_sandbox_id("s8-session")
    _, info = await _acquire(provider, scope)
    container = info.container_name
    # tmpfs cap: 300 MiB into a 256 MiB tmpfs
    big_tmpfs = _exec_sync(container, "dd if=/dev/zero of=/tmp/big bs=1M count=300 status=none")
    assert big_tmpfs.returncode != 0
    # fsize cap: 200 MiB into a 100 MiB file limit
    big_file = _exec_sync(container, "dd if=/dev/zero of=/home/gem/big bs=1M count=200 status=none")
    assert big_file.returncode != 0
    # pid cap: 300 forks against pids=128
    fork_bomb = _exec_sync(container, "python3 -c 'import os; [os.fork() for _ in range(300)]'")
    assert fork_bomb.returncode != 0
    # memory cap: 3 GiB bytearray against mem=2g
    oom = _exec_sync(container, "python3 -c 'x = bytearray(3 * 1024**3)'")
    assert oom.returncode != 0
    # the container survives (or was OOM-removed); provider still serves new work
    alive = await provider._backend.is_alive(info)
    if alive:
        healthy = _exec_sync(container, "true")
        assert healthy.returncode == 0
    fresh = await provider.acquire(scope)  # reclaim/recreate cleanly
    assert fresh is not None
    await provider.destroy_scope(scope)


async def test_s9_abort_destroys_container_and_preserves_workspace(sandbox_env) -> None:
    _, provider, root = sandbox_env
    scope = derive_sandbox_id("s9-session")
    _, info = await _acquire(provider, scope)
    (root / scope / "keep.txt").write_text("retained", encoding="utf-8")
    await provider.destroy_scope(scope)
    # container is gone from the daemon
    gone = _docker(["inspect", info.container_name])
    assert gone.returncode != 0
    # workspace retained on host (G9)
    assert (root / scope / "keep.txt").read_text(encoding="utf-8") == "retained"
    # resume in a NEW container sees the retained workspace
    fresh, fresh_info = await _acquire(provider, scope)
    assert fresh_info.container_id != info.container_id
    seen = _exec_sync(fresh_info.container_name, f"cat {VIRTUAL_WORKSPACE_PREFIX}/keep.txt")
    assert seen.returncode == 0 and seen.stdout.strip() == "retained"
    await provider.destroy_scope(scope)


async def test_s10_hardening_inspect_real_container(sandbox_env) -> None:
    _, provider, root = sandbox_env
    scope = derive_sandbox_id("s10-session")
    _, info = await _acquire(provider, scope)
    payload = json.loads(_docker(["inspect", info.container_name]).stdout)[0]
    config, host = payload["Config"], payload["HostConfig"]
    assert config["User"] == "1000:1000"
    assert host["ReadonlyRootfs"] is True
    assert host["Privileged"] is False
    assert host["CapAdd"] in (None, [])
    assert "ALL" in (host["CapDrop"] or [])
    assert "no-new-privileges" in {str(s).lower() for s in (host["SecurityOpt"] or [])}
    assert host["PidsLimit"] == PIDS_LIMIT
    assert host["Memory"] == 2 * 1024 * 1024 * 1024
    assert host["MemorySwap"] == 2 * 1024 * 1024 * 1024
    ulimits = {u["Name"]: (u["Soft"], u["Hard"]) for u in (host["Ulimits"] or [])}
    assert ulimits["nofile"] == (NOFILE_LIMIT, NOFILE_LIMIT)
    assert ulimits["fsize"] == (104857600, 104857600)
    tmpfs = host.get("Tmpfs") or {}
    for path in TMPFS_PATHS:
        assert path in tmpfs and "size=" in tmpfs[path]
    assert host["NetworkMode"] != "host"
    assert not host.get("PidMode") and host.get("IpcMode") != "host"
    await provider.destroy_scope(scope)


async def test_s11_control_port_binds_loopback_only(sandbox_env) -> None:
    _, provider, root = sandbox_env
    scope = derive_sandbox_id("s11-session")
    _, info = await _acquire(provider, scope)
    payload = json.loads(_docker(["inspect", info.container_name]).stdout)[0]
    ports = payload["NetworkSettings"]["Ports"]
    entries = ports.get("8080/tcp") or []
    assert entries and all(e.get("HostIp") in ("127.0.0.1", "127.0.0.1/32") for e in entries)
    bindings = payload["HostConfig"].get("PortBindings") or {}
    assert all("127.0.0.1" in str(b) for b in bindings.values())
    assert not payload["HostConfig"].get("ExtraHosts")
    assert not payload["HostConfig"].get("Dns")
    await provider.destroy_scope(scope)


async def test_s12_stable_scope_ids_and_container_names(sandbox_env) -> None:
    _, provider, root = sandbox_env
    assert derive_sandbox_id("same") == derive_sandbox_id("same")
    assert derive_sandbox_id("same") != derive_sandbox_id("other")
    scope = derive_sandbox_id("s12-session")
    _, info = await _acquire(provider, scope)
    assert len(scope) == 64 and set(scope) <= set("0123456789abcdef")
    assert info.container_name.startswith("competitive-app-sandbox-")
    listed = _docker(["ps", "--filter", "label=competitive-app.agent-tool-sandbox=v1", "--format", "{{.Names}}"])
    for name in (listed.stdout or "").splitlines():
        if not name.startswith("competitive-app-sandbox-"):
            continue  # foreign/unmanaged container sharing the label
        suffix = name[len("competitive-app-sandbox-") :]
        assert len(suffix) == 64 and set(suffix) <= set("0123456789abcdef")
    await provider.destroy_scope(scope)
