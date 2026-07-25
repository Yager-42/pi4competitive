"""CompetitorLens P4 application — DDD + FastAPI over earendil_works.pi_agent.

Architecture (contract v0.3.4 §3.2 / §6.3 / feature competitive-app-http-v1 v0.1.3):

    adapter/in/fastapi  →  application/workflow  →  domain
                              │
                              └──→ packages/agent → packages/ai
                              └──→ adapter/out/persistence (SQLite projection)

Conversation history SoT = JSONL via pi_agent.JsonlSessionRepo (data/sessions/).
Task projection + session index = App SQLite (data/app.db).
"""
from __future__ import annotations

__version__ = "0.1.0"
