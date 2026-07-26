from __future__ import annotations

import pytest

from earendil_works.pi_ai.api import anthropic_messages, openai_completions


class _Response:
    status_code = 429
    headers = {"retry-after": "1"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def aread(self):
        return b"limited"


class _Client:
    def __init__(self, **_):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    def stream(self, *_args, **_kwargs):
        return _Response()


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", [openai_completions, anthropic_messages])
async def test_callbacks_once_on_non_2xx(monkeypatch, adapter) -> None:
    monkeypatch.setattr("earendil_works.pi_ai.api._http_stream.httpx.AsyncClient", _Client)
    monkeypatch.setattr("earendil_works.pi_ai.api.anthropic_messages.httpx.AsyncClient", _Client)
    payloads, responses = [], []
    model = {"id": "m", "api": adapter.__name__.rsplit(".", 1)[-1].replace("_", "-"),
             "provider": "p", "baseUrl": "https://example.test", "maxTokens": 8}
    result = adapter.stream(
        model, {"messages": []},
        {"apiKey": "x", "onPayload": lambda body, _model: payloads.append(body),
         "onResponse": lambda response, _model: responses.append(response)},
    )
    await result.result()
    assert len(payloads) == len(responses) == 1
    assert responses[0]["status"] == 429
