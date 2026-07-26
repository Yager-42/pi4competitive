"""FastAPI inbound adapter.

Package name `in_` (not `in`) because `in` is a Python keyword and cannot be
imported. Maps to contract §6.4 logical layout `adapter/in/fastapi`.
Routes here only call competitive_app.application — never pi_agent / pi_ai /
aiosqlite directly (contract G2, feature F-A25).
"""
from __future__ import annotations
