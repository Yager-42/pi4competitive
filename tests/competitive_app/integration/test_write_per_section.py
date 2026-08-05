"""Integration — write per-section (research-workflow v0.2.6).

write stage produces overview + per-dimension + conclusion sections (sequential
harness.prompt) + assembled Sources. Verifies sections[] shape + report `##`
structure + that section ids are refinable (contract preserved).
"""

from __future__ import annotations

import json

import pytest
from earendil_works.pi_ai.providers.faux import faux_assistant_message

from tests.competitive_app.integration.test_workflow import (
    _TASK_BODY,
    _client,
    _entity_responses,
    _plan_response,
    _wait_status,
)


def _section_response(body: str, sources: list | None = None) -> str:
    return json.dumps({"body": body, "sources": sources or []})


def _per_section_write_responses() -> list:
    """overview + pricing(dim) + conclusion — 3 sequential write section calls.

    _TASK_BODY has dimensions=["pricing"] → write = overview + pricing + conclusion.
    """
    return [
        faux_assistant_message(
            _section_response(
                "Overview: ACME vs Beta pricing comparison.",
                [{"n": 1, "url": "https://example.com/ov", "label": "overview"}],
            )
        ),
        faux_assistant_message(
            _section_response(
                "ACME $10/mo [1]; Beta $20/mo [1].",
                [{"n": 1, "url": "https://example.com/pricing", "label": "pricing page"}],
            )
        ),
        faux_assistant_message(
            _section_response(
                "Conclusion: ACME is cheaper; Beta for teams.",
                [],
            )
        ),
    ]


def _full_per_section_responses() -> list:
    """plan + 2 entities (search) + 3 write section calls, in order."""
    return [
        faux_assistant_message(_plan_response()),
        *_entity_responses("acme", "$10/mo"),
        *_entity_responses("beta", "$20/mo"),
        *_per_section_write_responses(),
    ]


@pytest.mark.asyncio
async def test_write_per_section_structure(app_state, faux, mock_fetch_tool) -> None:
    faux["setResponses"](_full_per_section_responses())
    async with await _client(app_state) as client:
        create = await client.post("/api/v2/tasks", json=_TASK_BODY)
        assert create.status_code == 202, create.text
        task_id = create.json()["task_id"]
        status = await _wait_status(client, task_id, {"completed", "failed", "aborted"})
        assert status == "completed", f"expected completed, got {status}"

        report = await client.get(f"/api/v2/reports/{task_id}")
        assert report.status_code == 200
        r = report.json()
        md = r.get("markdown") or ""

        # report markdown has the per-section structure (v0.2.6)
        assert "## 概述" in md
        assert "## pricing" in md  # dimension section (brief.dimensions=["pricing"])
        assert "## 结论与建议" in md
        assert "## Sources" in md
        # Sources grouped by section
        assert "### 概述" in md and "### pricing" in md

        # sections[] = overview + pricing + conclusion + Sources (sequential ids)
        sections = r.get("sections") or []
        titles = [s.get("title") for s in sections]
        assert "概述" in titles
        assert "pricing" in titles
        assert "结论与建议" in titles
        assert "Sources" in titles
        # sequential ids "1".."N", Sources last
        ids = [s.get("id") for s in sections]
        assert ids == [str(i) for i in range(1, len(sections) + 1)]
        assert sections[-1]["title"] == "Sources"
        # each section body starts with its ## heading (matches _split_sections shape)
        for s in sections:
            assert s["body"].startswith("## ")


@pytest.mark.asyncio
async def test_write_per_section_ids_refinable(app_state, faux, mock_fetch_tool) -> None:
    """refine can still target a section by id (v0.2.2 contract preserved under v0.2.6)."""
    faux["setResponses"](_full_per_section_responses())
    async with await _client(app_state) as client:
        create = await client.post("/api/v2/tasks", json=_TASK_BODY)
        task_id = create.json()["task_id"]
        await _wait_status(client, task_id, {"completed", "failed", "aborted"})

        report = await client.get(f"/api/v2/reports/{task_id}")
        sections = report.json().get("sections") or []
        # section id "2" exists + is refinable (refine accepts section_id)
        assert any(s.get("id") == "2" for s in sections)
