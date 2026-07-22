#!/usr/bin/env python3
"""Live smoke: stream/complete against credentials in repo-root .env.

Does not print secrets. Exit 0 on stop/toolUse/length; non-zero on error.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "packages" / "ai" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        # Do not overwrite already-exported values
        os.environ.setdefault(key, val)


async def main() -> int:
    load_dotenv(ROOT / ".env")

    api_key = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("MODEL_API_KEY")
        or ""
    ).strip()
    base_url = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("MODEL_BASE_URL")
        or "https://api.openai.com/v1"
    ).strip().rstrip("/")
    model_id = (
        os.environ.get("OPENAI_MODEL")
        or os.environ.get("MODEL_NAME")
        or "gpt-4o-mini"
    ).strip()

    if not api_key:
        print("FAIL: no OPENAI_API_KEY / MODEL_API_KEY in env or .env")
        return 2

    from earendil_works.pi_ai import create_models
    from earendil_works.pi_ai.providers.openai import openai_provider

    models = create_models()
    models.setProvider(openai_provider())

    # Gateway model may not be in static catalog — build an OpenAI-compatible Model.
    model = {
        "id": model_id,
        "name": model_id,
        "api": "openai-completions",
        "provider": "openai",
        "baseUrl": base_url,
        "reasoning": False,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": int(os.environ.get("MODEL_CONTEXT_WINDOW_TOKENS") or 128000),
        "maxTokens": 1024,
    }

    print(f"provider=openai model={model_id} baseUrl={base_url}")
    print("request: completeSimple('Reply with exactly: pong') …")

    msg = await models.completeSimple(
        model,
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Reply with exactly one word: pong",
                    "timestamp": 0,
                }
            ]
        },
        {"apiKey": api_key, "maxTokens": 64},
    )

    stop = msg.get("stopReason")
    err = msg.get("errorMessage")
    text = ""
    for block in msg.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text") or ""

    print(f"stopReason={stop}")
    if err:
        print(f"errorMessage={err[:500]}")
    print(f"text={text[:300]!r}")
    print(f"usage={msg.get('usage')}")

    if stop in ("stop", "length", "toolUse"):
        print("OK: live smoke passed")
        return 0
    print("FAIL: live smoke failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
