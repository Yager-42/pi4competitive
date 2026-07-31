"""DockerSandboxProvider lifecycle tests (O10/O11, plan D3) with a fake backend.

Exercises acquire/release warm-reclaim, replica eviction, destroy, shutdown,
idle cleanup and orphan reconcile deterministically without Docker.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from competitive_app.adapter.out.sandbox.docker.docker_sandbox_provider import DockerSandboxProvider
from competitive_app.adapter.out.sandbox.types import SandboxInfo

SCOPE_A = "a" * 64
SCOPE_B = "b" * 64


class _FakeBackend:
    def __init__(self) -> None:
        self.containers: dict[str, SandboxInfo] = {}
        self.created: list[str] = []
        self.destroyed: list[str] = []
        self.create_count = 0

    async def create(self, scope_id: str) -> SandboxInfo:
        self.create_count += 1
        self.created.append(scope_id)
        info = SandboxInfo(
            sandbox_id=scope_id,
            sandbox_url=f"http://127.0.0.1:{10000 + self.create_count}",
            container_name=f"fake-{scope_id[:12]}",
            container_id=f"cid-{scope_id[:12]}",
        )
        self.containers[scope_id] = info
        return info

    async def destroy(self, info: SandboxInfo) -> None:
        self.destroyed.append(info.sandbox_id)
        self.containers.pop(info.sandbox_id, None)

    async def is_alive(self, info: SandboxInfo) -> bool | None:
        return info.sandbox_id in self.containers

    async def discover(self, scope_id: str) -> SandboxInfo | None:
        return self.containers.get(scope_id)

    async def list_running(self) -> list[SandboxInfo]:
        return list(self.containers.values())


async def _ready(_url: str) -> bool:
    return True


def _provider(tmp_path: Path, backend: _FakeBackend | None = None, **kwargs: Any) -> DockerSandboxProvider:
    return DockerSandboxProvider(
        image="registry.example/worker@sha256:" + "0" * 64,
        sandbox_root=tmp_path,
        environment={},
        backend=backend or _FakeBackend(),
        readiness_check=_ready,
        start_idle_checker=False,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_acquire_creates_once_and_reuses_active(tmp_path: Path) -> None:
    backend = _FakeBackend()
    provider = _provider(tmp_path, backend)
    first = await provider.acquire(SCOPE_A)
    second = await provider.acquire(SCOPE_A)
    assert first is second
    assert backend.create_count == 1
    assert await provider.get_info(SCOPE_A) is not None
    await provider.shutdown()


@pytest.mark.asyncio
async def test_warm_reclaim_reuses_container(tmp_path: Path) -> None:
    backend = _FakeBackend()
    provider = _provider(tmp_path, backend)
    first = await provider.acquire(SCOPE_A)
    await provider.release(SCOPE_A)
    second = await provider.acquire(SCOPE_A)
    assert second.id == first.id
    assert backend.create_count == 1  # warm reclaim, no second create
    await provider.shutdown()


@pytest.mark.asyncio
async def test_release_to_warm_then_shutdown_destroys_everything(tmp_path: Path) -> None:
    backend = _FakeBackend()
    provider = _provider(tmp_path, backend)
    await provider.acquire(SCOPE_A)
    await provider.release(SCOPE_A)  # → warm
    await provider.acquire(SCOPE_B)  # active
    await provider.shutdown()
    assert set(backend.destroyed) == {SCOPE_A, SCOPE_B}
    assert await provider.get_info(SCOPE_A) is None
    assert await provider.get_info(SCOPE_B) is None
    await provider.shutdown()  # idempotent


@pytest.mark.asyncio
async def test_destroy_scope_removes_active_and_warm(tmp_path: Path) -> None:
    backend = _FakeBackend()
    provider = _provider(tmp_path, backend)
    await provider.acquire(SCOPE_A)
    await provider.release(SCOPE_A)
    await provider.destroy_scope(SCOPE_A)
    assert backend.destroyed == [SCOPE_A]
    assert backend.containers == {}
    await provider.shutdown()


@pytest.mark.asyncio
async def test_replica_eviction_evicts_oldest_warm(tmp_path: Path) -> None:
    backend = _FakeBackend()
    provider = _provider(tmp_path, backend, replicas=1)
    await provider.acquire(SCOPE_A)
    await provider.release(SCOPE_A)  # warm A
    await provider.acquire(SCOPE_B)  # active B, evicts warm A
    assert SCOPE_A in backend.destroyed
    assert backend.containers == {SCOPE_B: backend.containers[SCOPE_B]}
    await provider.shutdown()


@pytest.mark.asyncio
async def test_acquire_after_shutdown_raises(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    await provider.shutdown()
    with pytest.raises(RuntimeError, match="shut down"):
        await provider.acquire(SCOPE_A)


@pytest.mark.asyncio
async def test_acquire_readiness_failure_destroys(tmp_path: Path) -> None:
    backend = _FakeBackend()
    provider = DockerSandboxProvider(
        image="registry.example/worker@sha256:" + "0" * 64,
        sandbox_root=tmp_path,
        environment={},
        backend=backend,
        readiness_check=lambda _url: _never_ready(),
        start_idle_checker=False,
    )
    with pytest.raises(RuntimeError, match="failed readiness"):
        await provider.acquire(SCOPE_A)
    assert backend.destroyed == [SCOPE_A]  # no orphan left behind
    assert backend.containers == {}
    await provider.shutdown()


async def _never_ready() -> bool:
    return False


@pytest.mark.asyncio
async def test_orphan_reconcile_adopts_running_containers(tmp_path: Path) -> None:
    backend = _FakeBackend()
    orphan = await backend.create(SCOPE_A)
    provider = _provider(tmp_path, backend)
    await provider.start()  # reconcile: adopted into warm
    assert await provider.get_info(SCOPE_A) is not None
    assert orphan.sandbox_id == SCOPE_A
    await provider.shutdown()
    assert backend.destroyed == [SCOPE_A]  # shutdown destroyed the adopted orphan


@pytest.mark.asyncio
async def test_idle_cleanup_destroys_stale_warm_and_active(tmp_path: Path) -> None:
    backend = _FakeBackend()
    provider = _provider(tmp_path, backend)
    await provider.acquire(SCOPE_A)
    await provider.release(SCOPE_A)  # warm A
    await provider.acquire(SCOPE_B)  # active B
    # age both past the idle timeout (exact loop code path, deterministic scan)
    now = asyncio.get_running_loop().time()
    provider._last_activity[SCOPE_B] = now - 1000
    provider._warm[SCOPE_A] = (provider._warm[SCOPE_A][0], now - 1000)
    await provider._cleanup_idle()
    assert SCOPE_A in backend.destroyed
    assert SCOPE_B in backend.destroyed
    await provider.shutdown()


@pytest.mark.asyncio
async def test_invalid_scope_ids_are_rejected(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    for bad in ("", "short", "../etc", "G" * 64, "x" * 65):
        with pytest.raises(ValueError, match="64-hex"):
            await provider.acquire(bad)
        with pytest.raises(ValueError, match="64-hex"):
            await provider.destroy_scope(bad)
    await provider.shutdown()
