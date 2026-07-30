"""Process-global serialized evolution cycle runner (NEW-HOST).

One asyncio lock protects every cycle. Trigger/metric scans happen after lock
acquisition inside EvolutionManager; no distributed lock, crash recovery, or job
reconciliation is introduced.
"""
from __future__ import annotations

import asyncio
from typing import Any

_EVOLUTION_LOCK = asyncio.Lock()


class EvolutionCycleRunner:
    def __init__(self, manager: Any, ratchet: Any | None = None, store: Any | None = None,
                 skill_files: Any | None = None) -> None:
        self._manager = manager
        self._ratchet = ratchet
        self._store = store or getattr(manager, "_store", None)
        self._skill_files = skill_files

    async def run_cycle(self) -> list[Any]:
        async with _EVOLUTION_LOCK:
            records = await self._manager.run_cycle()
            if self._ratchet is not None and self._store is not None:
                for current in await self._store.list_active():
                    rolled_to = await self._ratchet.check_and_rollback(self._store, current)
                    if rolled_to is not None and self._skill_files is not None:
                        await self._skill_files.update_manifest()
            return records

    async def run_context(self, context: Any) -> Any:
        async with _EVOLUTION_LOCK:
            record = await self._manager.run_context(context)
            if self._ratchet is not None and self._store is not None:
                for current in await self._store.list_active():
                    rolled_to = await self._ratchet.check_and_rollback(self._store, current)
                    if rolled_to is not None and self._skill_files is not None:
                        await self._skill_files.update_manifest()
            return record

    @property
    def lock(self) -> asyncio.Lock:
        return _EVOLUTION_LOCK


__all__ = ["EvolutionCycleRunner", "_EVOLUTION_LOCK"]
