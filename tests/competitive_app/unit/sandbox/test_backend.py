"""LocalContainerBackend hardening and identity tests (S3/S5/S8/S10, plan D1).

Command-string level enforcement with a fake Docker executor; no daemon needed.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from competitive_app.adapter.out.sandbox.docker.local_container_backend import (
    LocalContainerBackend,
)
from competitive_app.adapter.out.sandbox.types import (
    CPU_LIMIT,
    FILE_SIZE_LIMIT,
    MEMORY_LIMIT,
    MEMORY_SWAP_LIMIT,
    NOFILE_LIMIT,
    PIDS_LIMIT,
    TMPFS_SIZE,
    VIRTUAL_WORKSPACE_PREFIX,
)

IMAGE = "registry.example/pi4competitive-tool-worker@sha256:" + "0" * 64
SCOPE = "a" * 64
TMPFS_PATHS = (
    "/tmp",
    "/run",
    "/var/log/gem",
    "/var/lib/aio-sandbox",
    "/var/lib/nginx",
    "/home/gem",
    "/opt/aio",
)


class _FakeExecutor:
    """Records docker argv; answers inspect with a hardened payload."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.inspect_payload: dict[str, Any] | None = None
        self.image_id = "sha256:" + "f" * 64

    def run(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(cmd)
        if cmd[0:2] == ["docker", "image"]:
            return subprocess.CompletedProcess(cmd, 0, self.image_id, "")
        if cmd[0:2] == ["docker", "inspect"]:
            if self.inspect_payload is None:
                return subprocess.CompletedProcess(cmd, 1, "", "not found")
            return subprocess.CompletedProcess(cmd, 0, json.dumps([self.inspect_payload]), "")
        if cmd[0:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(cmd, 0, "container-id-123\n", "")
        if cmd[0:2] == ["docker", "ps"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def translate_path(self, host_path: str) -> str:
        return host_path


def _backend(tmp_path: Path, executor: _FakeExecutor | None = None, **kwargs: Any) -> LocalContainerBackend:
    return LocalContainerBackend(
        image=IMAGE,
        sandbox_root=tmp_path,
        executor=executor or _FakeExecutor(),
        **kwargs,
    )


def _argv(backend: LocalContainerBackend, executor: _FakeExecutor) -> list[str]:
    command = backend._run_command(
        name=f"competitive-app-sandbox-{SCOPE}",
        scope_id=SCOPE,
        workspace=Path("/host/workspace") / SCOPE,
        port=18080,
    )
    executor.commands.append(command)  # record for assertions
    return command


def test_backend_rejects_non_digest_images(tmp_path: Path) -> None:
    for bad in ("ubuntu:latest", "pi4competitive-tool-worker:dev-3", "repo/img", ""):
        with pytest.raises(ValueError, match="pinned by registry and sha256 digest"):
            LocalContainerBackend(image=bad, sandbox_root=tmp_path, executor=_FakeExecutor())


def test_create_command_hardening(tmp_path: Path) -> None:
    executor = _FakeExecutor()
    backend = _backend(tmp_path, executor)
    command = _argv(backend, executor)
    assert command[0] == "docker" and command[1] == "run"
    assert "--user" in command and command[command.index("--user") + 1] == "1000:1000"
    assert "--read-only" in command
    assert "--cap-drop" in command and command[command.index("--cap-drop") + 1] == "ALL"
    assert "--security-opt" in command and command[command.index("--security-opt") + 1] == "no-new-privileges"
    assert "--cpus" in command and command[command.index("--cpus") + 1] == CPU_LIMIT
    assert "--memory" in command and command[command.index("--memory") + 1] == MEMORY_LIMIT
    assert "--memory-swap" in command and command[command.index("--memory-swap") + 1] == MEMORY_SWAP_LIMIT
    assert "--pids-limit" in command and command[command.index("--pids-limit") + 1] == str(PIDS_LIMIT)
    ulimits = [command[i + 1] for i in range(len(command) - 1) if command[i] == "--ulimit"]
    assert f"nofile={NOFILE_LIMIT}:{NOFILE_LIMIT}" in ulimits
    assert "fsize=104857600:104857600" in ulimits  # 100m as BYTES (Docker rejects m-suffix)
    assert "--privileged" not in command
    assert "--network" not in command or command[command.index("--network") + 1] != "host"
    assert "--ipc" not in command


def test_create_command_mounts_only_workspace_and_loopback_port(tmp_path: Path) -> None:
    executor = _FakeExecutor()
    backend = _backend(tmp_path, executor)
    command = _argv(backend, executor)
    publish = command[command.index("--publish") + 1]
    assert publish.startswith("127.0.0.1:") and publish.endswith(":8080/tcp")
    mount = command[command.index("--mount") + 1]
    assert mount.startswith("type=bind,")
    assert f"dst={VIRTUAL_WORKSPACE_PREFIX}" in mount
    assert "readonly=false" in mount
    src = mount.split(",", 1)[1].split("src=", 1)[1].split(",", 1)[0]
    # S3: bind sources stay inside the workspace root; no repo/.env/db/sessions/home/socket
    assert "--volume" not in command and "-v" not in command
    src = mount.split(",", 1)[1].split("src=", 1)[1].split(",", 1)[0]
    assert "/.git" not in src and "docker.sock" not in src and "app.db" not in src
    assert "/sessions" not in src and "/home" not in src and "/.env" not in src
    assert "/repo/" not in src and not src.endswith("/repo")

def test_create_command_tmpfs_caps_all_seven(tmp_path: Path) -> None:
    executor = _FakeExecutor()
    backend = _backend(tmp_path, executor)
    command = _argv(backend, executor)
    tmpfs = [command[i + 1] for i in range(len(command) - 1) if command[i] == "--tmpfs"]
    assert len(tmpfs) == 7
    for entry in tmpfs:
        path = entry.split(":", 1)[0]
        assert path in TMPFS_PATHS
        assert f"size={TMPFS_SIZE}" in entry


def test_environment_is_limited_to_g21_names(tmp_path: Path) -> None:
    executor = _FakeExecutor()
    backend = LocalContainerBackend(
        image=IMAGE,
        sandbox_root=tmp_path,
        executor=executor,
        environment={
            "TAVILY_API_KEY": "tv-secret",
            "LLM_API_KEY": "should-not-pass",
            "HOME": "/root",
            "PATH": "/usr/bin",
            "ANYSEARCH_API_URL": "http://127.0.0.1:9",
        },
    )
    assert backend.environment_names == frozenset({"TAVILY_API_KEY", "ANYSEARCH_API_URL"})
    command = _argv(backend, executor)
    env_args: list[str] = []
    for i, token in enumerate(command[:-1]):
        if token == "--env":
            env_args.append(command[i + 1].split("=", 1)[0])
    assert set(env_args) == {"SANDBOX_ID", "THREAD_ID", "TAVILY_API_KEY", "ANYSEARCH_API_URL"}
    # S5: no secret VALUE appears in argv (env passed by name only)
    assert "tv-secret" not in " ".join(command)


def test_verify_image_identity_resolves_daemon_image(tmp_path: Path) -> None:
    executor = _FakeExecutor()
    backend = _backend(tmp_path, executor)
    assert backend.verify_image_identity() == executor.image_id


def test_verify_image_identity_fails_closed_without_daemon(tmp_path: Path) -> None:
    class _DownExecutor:
        def run(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError("no docker")

        def translate_path(self, host_path: str) -> str:
            return host_path

    backend = _backend(tmp_path, _DownExecutor())
    with pytest.raises(RuntimeError, match="not found locally or daemon unavailable"):
        backend.verify_image_identity()


def test_read_baked_manifest_uses_isolated_read_only_container(tmp_path: Path) -> None:
    executor = _ManifestExecutor()
    backend = _backend(tmp_path, executor)
    payload = backend.read_baked_manifest()
    assert json.loads(payload)["protocol"] == "agent-tool-rpc.v1"
    run_cmd = executor.commands[-1]
    assert run_cmd[:5] == ["docker", "run", "--rm", "--read-only", "--network"]
    assert run_cmd[5] == "none"
    assert run_cmd[run_cmd.index("--entrypoint") + 1] == "cat"


class _ManifestExecutor(_FakeExecutor):
    def run(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(cmd)
        manifest = json.dumps({"protocol": "agent-tool-rpc.v1", "tools": {}}).encode()
        if cmd[0:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(cmd, 0, manifest, "")
        return super().run(cmd, **kwargs)


def test_read_baked_manifest_fails_on_docker_error(tmp_path: Path) -> None:
    class _FailingExecutor(_FakeExecutor):
        def run(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if cmd[0:2] == ["docker", "run"]:
                return subprocess.CompletedProcess(cmd, 1, b"", b"image missing")
            return super().run(cmd, **kwargs)

    backend = _backend(tmp_path, _FailingExecutor())
    with pytest.raises(RuntimeError, match="failed to read baked worker manifest"):
        backend.read_baked_manifest()


def _hardened_inspect(
    scope: str, *, image_id: str, port: int, sandbox_root: Path
) -> dict[str, Any]:
    return {
        "Id": "cid-" + scope[:12],
        "Image": image_id,
        "Created": "2026-01-01T00:00:00Z",
        "Config": {
            "User": "1000:1000",
            "Labels": {"competitive-app.agent-tool-sandbox": "v1"},
        },
        "HostConfig": {
            "ReadonlyRootfs": True,
            "Privileged": False,
            "NetworkMode": "bridge",
            "PidMode": "",
            "IpcMode": "private",
            "CapAdd": [],
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "PidsLimit": 128,
            "Memory": 2 * 1024 * 1024 * 1024,
            "MemorySwap": 2 * 1024 * 1024 * 1024,
            "NanoCpus": 1_000_000_000,
            "Ulimits": [
                {"Name": "nofile", "Soft": 1024, "Hard": 1024},
                {"Name": "fsize", "Soft": 104857600, "Hard": 104857600},
            ],
            "Tmpfs": {path: f"rw,nosuid,size={TMPFS_SIZE}" for path in TMPFS_PATHS},
            "Binds": None,
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": str((sandbox_root / scope).resolve()),
                "Destination": VIRTUAL_WORKSPACE_PREFIX,
                "RW": True,
            }
        ],
        "NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]}},
    }


def test_validate_inspect_accepts_hardened_container(tmp_path: Path) -> None:
    executor = _FakeExecutor()
    backend = _backend(tmp_path, executor)
    inspected = _hardened_inspect(SCOPE, image_id=executor.image_id, port=18080, sandbox_root=tmp_path)
    assert backend._validate_inspect(inspected, SCOPE) is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["Config"].update(User="root"),
        lambda d: d["HostConfig"].update(ReadonlyRootfs=False),
        lambda d: d["HostConfig"].update(CapDrop=["NET_ADMIN"]),
        lambda d: d["HostConfig"].update(SecurityOpt=[]),
        lambda d: d["HostConfig"].update(PidsLimit=None),
        lambda d: d["HostConfig"].update(Memory=1 * 1024 * 1024 * 1024),
        lambda d: d["HostConfig"].update(NetworkMode="host"),
        lambda d: d["HostConfig"].pop("Tmpfs"),
        lambda d: d["HostConfig"].update(Binds=["/etc:/etc"]),
        lambda d: d["Mounts"].append({"Type": "bind", "Source": "/etc", "Destination": "/etc", "RW": True}),
        lambda d: d["Mounts"][0].update(Destination="/mnt/other"),
        lambda d: d["HostConfig"].update(MemorySwap=1 * 1024 * 1024 * 1024),
        lambda d: d.update(Image="sha256:" + "e" * 64),
        lambda d: d["HostConfig"].update(Ulimits=[{"Name": "nofile", "Soft": 1024, "Hard": 1024}]),
    ],
)
def test_validate_inspect_rejects_weakened_container(tmp_path: Path, mutate: Any) -> None:
    executor = _FakeExecutor()
    backend = _backend(tmp_path, executor)
    inspected = _hardened_inspect(SCOPE, image_id=executor.image_id, port=18080, sandbox_root=tmp_path)
    mutate(inspected)
    assert backend._validate_inspect(inspected, SCOPE) is False
