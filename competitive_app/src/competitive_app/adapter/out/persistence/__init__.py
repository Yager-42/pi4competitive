"""SQLite projection store — tasks table + sessions index table.

Contract §7 / feature F-A5: this is the App SQLite projection (data/app.db),
NOT conversation history (that's JSONL via pi_agent.JsonlSessionRepo).
Single connection + asyncio.Lock serializes writes (feature F-A24).
"""
from __future__ import annotations
