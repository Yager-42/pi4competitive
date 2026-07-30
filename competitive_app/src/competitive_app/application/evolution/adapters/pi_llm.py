"""PiLlmAdapter host glue for transplanted Poirot components.

No new model framework is introduced. The adapter maps string prompts to the
existing ``pi_ai.completeSimple`` async API and provides tolerant JSON parsing.
"""
from __future__ import annotations

import json
from typing import Any


class PiLlmAdapter:
    def __init__(self, models: Any, model: dict[str, Any]) -> None:
        self._models = models
        self._model = model

    async def complete_simple(self, prompt: str) -> str:
        response = await self._models.completeSimple(
            self._model, {"messages": [{"role": "user", "content": prompt}]}
        )
        return self._text(response)

    async def complete_json(self, prompt: str) -> dict[str, Any] | list[Any] | None:
        text = await self.complete_simple(prompt)
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        return None

    async def invoke(self, prompt: str) -> str:
        return await self.complete_simple(prompt)

    @staticmethod
    def _text(response: Any) -> str:
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            content = response.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
        content = getattr(response, "content", None)
        return content if isinstance(content, str) else str(response or "")


__all__ = ["PiLlmAdapter"]
