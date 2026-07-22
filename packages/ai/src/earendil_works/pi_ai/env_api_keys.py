"""env-api-keys helpers."""
from __future__ import annotations
import os
from typing import Iterable

def first_env(*names: str) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None
