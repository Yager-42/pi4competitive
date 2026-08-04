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
        # Track the actual nesting order so mixed arrays/objects are closed
        # inside-out. Delimiters in JSON strings do not affect the stack.
        stack: list[str] = []
        in_string = False
        escaped = False
        for char in text:
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char in "[{":
                stack.append(char)
            elif char in "]}":
                expected = "[" if char == "]" else "{"
                if stack and stack[-1] == expected:
                    stack.pop()

        repaired = text
        if repaired.endswith(",") and not in_string:
            repaired = repaired[:-1]
        if in_string:
            if escaped:
                repaired += "\\"
            repaired += '"'
        repaired += "".join("]" if opening == "[" else "}" for opening in reversed(stack))
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return {}
