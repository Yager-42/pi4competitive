"""Integration — recall_prior_findings against real TaskProjectionStore.

Verifies the new ``brands`` (case-insensitive list) query path + dedup-latest
+ render, against the real SQLite store (seeded via direct insert).
"""

from __future__ import annotations

from pathlib import Path  # noqa: F401

import pytest
from competitive_app.adapter.out.persistence.task_projection_store import (
    TaskProjectionStore,
)
from competitive_app.application.workflow.memory_inject import recall_prior_findings

_INSERT_SQL = (
    "insert or replace into evidences(evidence_id, task_id, entity, attribute, "
    "value, finding, source_url, source_type, domain, brand, confidence, "
    "captured_at) values(?,?,?,?,?,?,?,?,?,?,?,?)"
)


def _ev(eid: str, brand: str, attr: str, value: str, captured: str, conf: float = 0.9) -> tuple:
    return (eid, "t1", brand, attr, value, value, "url", "web", "d", brand, conf, captured)


async def _seed(store: TaskProjectionStore, rows: list[tuple]) -> None:
    await store.init()
    assert store._db is not None
    await store._db.executemany(_INSERT_SQL, rows)
    await store._db.commit()


@pytest.mark.asyncio
async def test_recall_real_store_dedup_latest(tmp_path) -> None:
    store = TaskProjectionStore(str(tmp_path / "app.db"))
    await _seed(
        store,
        [
            _ev("e1", "Notion", "pricing", "$10/mo", "2026-07-01"),
            _ev("e2", "Notion", "pricing", "$12/mo", "2026-08-01"),  # newer
            _ev("e3", "Notion", "features", "blocks", "2026-07-01"),
        ],
    )
    try:
        blob = await recall_prior_findings(store, ["Notion"])
    finally:
        await store.close()
    assert blob is not None
    assert "## Notion" in blob
    assert "$12/mo" in blob and "$10/mo" not in blob  # latest per (entity,attr) only
    assert "blocks" in blob  # other attr retained
    assert "Prior findings" in blob and "old → new" in blob  # change-detection header


@pytest.mark.asyncio
async def test_recall_empty_store_returns_none(tmp_path) -> None:
    store = TaskProjectionStore(str(tmp_path / "app.db"))
    await store.init()
    try:
        assert await recall_prior_findings(store, ["Notion"]) is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_recall_case_insensitive_match(tmp_path) -> None:
    store = TaskProjectionStore(str(tmp_path / "app.db"))
    await _seed(store, [_ev("e1", "Notion", "pricing", "$10/mo", "2026-07-01")])
    try:
        # helper normalizes query brand to lower; store matches lower(brand) IN (...)
        blob = await recall_prior_findings(store, ["NOTION"])
    finally:
        await store.close()
    assert blob is not None and "## Notion" in blob


@pytest.mark.asyncio
async def test_recall_min_conf_filters_low_confidence(tmp_path) -> None:
    store = TaskProjectionStore(str(tmp_path / "app.db"))
    await _seed(
        store,
        [
            _ev("e1", "Notion", "pricing", "$10/mo", "2026-07-01", conf=0.1),  # filtered
            _ev("e2", "Notion", "features", "blocks", "2026-07-01", conf=0.9),  # kept
        ],
    )
    try:
        blob = await recall_prior_findings(store, ["Notion"], min_confidence=0.3)
    finally:
        await store.close()
    assert blob is not None
    assert "blocks" in blob and "$10/mo" not in blob
