"""Make the pi_auto_review capability importable for unit tests.

The capability is not an installed package; the root test conftest adds only
packages/*/src and competitive_app/src to sys.path. Mirror that convention for
the capability root so ``import pi_auto_review`` resolves to the subpackage.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repo root
CAPABILITY_ROOT = ROOT / "capability_packages" / "pi_auto_review"
if CAPABILITY_ROOT.is_dir() and str(CAPABILITY_ROOT) not in sys.path:
    sys.path.insert(0, str(CAPABILITY_ROOT))
