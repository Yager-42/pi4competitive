"""Best-effort partial JSON parse for streaming tool arguments."""

from __future__ import annotations

import json
from typing import Any


def parse_partial_json(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try closing open braces/brackets
        repaired = text
        open_braces = repaired.count("{") - repaired.count("}")
        open_brackets = repaired.count("[") - repaired.count("]")
        if repaired.endswith(","):
            repaired = repaired[:-1]
        repaired += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return {}
