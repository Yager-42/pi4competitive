"""UUIDv7-ish id helper."""

from __future__ import annotations

import os
import time
import uuid


def uuidv7() -> str:
    """Generate a time-ordered UUID string (UUIDv7 when available, else uuid4)."""
    try:
        # Python 3.14+ may have uuid7; try uuid.uuid7 if present
        if hasattr(uuid, "uuid7"):
            return str(uuid.uuid7())  # type: ignore[attr-defined]
    except Exception:
        pass
    # Fallback: timestamp prefix + random for ordering
    ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand = int.from_bytes(os.urandom(10), "big")
    return f"{ms:012x}-{rand:020x}"[:36]
