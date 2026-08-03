"""RunJournal unit tests — transplant of poirot test (assertions verbatim).

Transplant source: HezaoHezao/poirot
Path: poirot/backend/tests/v1/unit/journal/test_run_journal.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see native/vendor/licenses/POIROT-MIT.txt)
Host delta: import path + workspace dir via pytest tmp_path (scaffolding only;
assertions unchanged).
"""
import json

from competitive_app.adapter.out.observability.run_journal import RunJournal


def test_run_journal_writes_event_jsonl(tmp_path) -> None:
    journal = RunJournal(run_id="run-1", events_path=tmp_path / "events.jsonl")

    journal.append("run.started", {"mode": "general"})

    content = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    # Events are now pretty-printed JSON blocks separated by blank lines.
    blocks = [b for b in content.split("\n\n") if b.strip()]
    assert json.loads(blocks[0])["event_type"] == "run.started"
