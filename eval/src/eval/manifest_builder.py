"""manifest_builder (D5 S4 adjusted).

Smoke manifest is HAND-CURATED (S4 rule: query explicitly names >=2 entities;
real WideSearch queries have no 'vs' pattern, so auto-extraction fails —
human curation aligns with benchmark doc §3.2 'versioned manifest, no ad-hoc
case changes'). This module loads the curated manifest and provides a helper
to list candidate cases for future Pilot/Business subset curation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from eval.manifest import CaseManifest, load_manifest

_PROPER_NOUN = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b")
_STOP = {
    "I",
    "Could",
    "Please",
    "The",
    "My",
    "We",
    "Our",
    "This",
    "That",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
    "US",
    "UK",
    "EU",
    "NY",
    "LA",
    "January",
    "February",
    "March",
    "April",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
    "Markdown",
    "Note",
    "Notes",
}


def load_smoke_manifest(
    path: Path | str = "eval/manifests/widesearch_smoke.jsonl",
) -> list[CaseManifest]:
    """Load the hand-curated Smoke case manifest."""
    return load_manifest(path)


def list_candidate_cases(src: Path | str, *, min_proper: int = 3) -> list[dict[str, Any]]:
    """Helper: scan widesearch.jsonl for queries with many proper nouns.

    For future human curation of Pilot/Business subsets (NOT used for Smoke).
    Returns raw rows; humans read these to pick cases.
    """
    src = Path(src)
    candidates: list[dict[str, Any]] = []
    with src.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("language") != "en":
                continue
            q = row.get("query", "")[:400]
            matches = _PROPER_NOUN.findall(q)
            proper = [m for m in matches if m.split()[0] not in _STOP and len(m) >= 3]
            unique = list(dict.fromkeys(proper))
            if len(unique) >= min_proper:
                candidates.append(
                    {
                        "instance_id": row["instance_id"],
                        "proper_nouns": unique[:8],
                        "query_preview": q[:120],
                    }
                )
    return candidates


__all__ = ["list_candidate_cases", "load_smoke_manifest"]
