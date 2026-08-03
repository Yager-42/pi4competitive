"""Make the pi_auto_review capability importable for native sandbox tests.

The root test conftest adds packages/*/src and competitive_app/src only;
native modules re-export capability-owned types (pi-sandbox upstream depends
on @erichll/pi-auto-review), so mirror the capability-conftest convention here.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]  # repo root
CAPABILITY_ROOT = ROOT / "capability_packages" / "pi_auto_review"
if CAPABILITY_ROOT.is_dir() and str(CAPABILITY_ROOT) not in sys.path:
    sys.path.insert(0, str(CAPABILITY_ROOT))
