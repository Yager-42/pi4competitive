"""Unit — memory_inject helper: normalize / dedup-latest / render / truncate / empty."""

from __future__ import annotations

from typing import Any

import pytest
from competitive_app.application.workflow.memory_inject import (
    INJECTION_LIMIT,
    recall_prior_findings,
)


class _FakeStore:
    """Records the query call + returns scripted rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []
        self.last_brands: list[str] | None = None
        self.last_min_conf: float | None = None

    async def query_evidences(
        self, *, brands=None, min_confidence=0.0, limit=200, **_: Any
    ) -> list[dict[str, Any]]:
        self.last_brands = list(brands or [])
        self.last_min_conf = min_confidence
        return list(self._rows)


def _row(
    brand: str, entity: str, attr: str, value: str, captured: str, conf=0.9, src="url"
) -> dict:
    return {
        "evidence_id": f"{brand}-{attr}-{captured}",
        "task_id": "t1",
        "entity": entity,
        "attribute": attr,
        "value": value,
        "finding": value,
        "source_url": src,
        "source_type": "web",
        "domain": "x",
        "brand": brand,
        "confidence": conf,
        "captured_at": captured,
    }


@pytest.mark.asyncio
async def test_normalize_brands_passed_to_store() -> None:
    store = _FakeStore(rows=[_row("Notion", "Notion", "pricing", "$10", "2026-07-01")])
    await recall_prior_findings(store, [" Notion ", "NOTION"])
    # case-insensitive + whitespace-trim → lowercased brands
    assert store.last_brands == ["notion", "notion"]
    assert store.last_min_conf == 0.3


@pytest.mark.asyncio
async def test_empty_brands_returns_none_no_query() -> None:
    store = _FakeStore(rows=[])
    assert await recall_prior_findings(store, ["", "  "]) is None
    assert store.last_brands is None  # no query call


@pytest.mark.asyncio
async def test_empty_recall_returns_none() -> None:
    store = _FakeStore(rows=[])
    assert await recall_prior_findings(store, ["Notion"]) is None


@pytest.mark.asyncio
async def test_dedup_keeps_latest_per_entity_attr() -> None:
    store = _FakeStore(
        rows=[
            _row("Notion", "Notion", "pricing", "$10", "2026-07-01"),
            _row("Notion", "Notion", "pricing", "$12", "2026-08-01"),  # newer
            _row("Notion", "Notion", "features", "blocks", "2026-07-01"),
        ]
    )
    blob = await recall_prior_findings(store, ["Notion"])
    assert blob is not None
    assert "$12" in blob and "$10" not in blob  # only latest pricing kept
    assert "blocks" in blob  # other attr retained
    assert "## Notion" in blob


@pytest.mark.asyncio
async def test_grouping_multiple_brands() -> None:
    store = _FakeStore(
        rows=[
            _row("Notion", "Notion", "pricing", "$10", "2026-07-01"),
            _row("飞书", "飞书", "pricing", "50元", "2026-07-01"),
        ]
    )
    blob = await recall_prior_findings(store, ["Notion", "飞书"])
    assert "## Notion" in blob and "## 飞书" in blob


@pytest.mark.asyncio
async def test_header_has_change_detection_instruction() -> None:
    store = _FakeStore(rows=[_row("Notion", "Notion", "pricing", "$10", "2026-07-01")])
    blob = await recall_prior_findings(store, ["Notion"])
    assert "Prior findings" in blob
    assert "old → new" in blob  # change-detection instruction baked in header


@pytest.mark.asyncio
async def test_truncation_drops_blocks_and_marks() -> None:
    # 40 brands × 5 attrs × 200-char values → > 25KB → whole-block drop + marker
    rows = [
        _row(f"Brand{i:03d}", f"Brand{i:03d}", f"attr{j}", "v" * 200, "2026-07-01")
        for i in range(40)
        for j in range(5)
    ]
    store = _FakeStore(rows=rows)
    blob = await recall_prior_findings(store, [f"Brand{i:03d}" for i in range(40)])
    assert blob is not None
    assert blob.endswith("(memory truncated)")
    assert len(blob.encode("utf-8")) <= INJECTION_LIMIT + 64  # marker slack


@pytest.mark.asyncio
async def test_min_conf_passthrough() -> None:
    store = _FakeStore(rows=[])
    await recall_prior_findings(store, ["Notion"], min_confidence=0.5)
    assert store.last_min_conf == 0.5
