from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AI_SRC = ROOT / "packages" / "ai" / "src"
AGENT_SRC = ROOT / "packages" / "agent" / "src"
for src in (AI_SRC, AGENT_SRC):
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
