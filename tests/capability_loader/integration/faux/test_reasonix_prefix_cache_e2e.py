from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from earendil_works.pi_ai.api.openai_completions import stream
from earendil_works.pi_agent.extensions import ExtensionRunner, load_extensions


@pytest.mark.asyncio
async def test_reasonix_warms_identical_canonical_prefix() -> None:
    seen = set()
    served = []

    async def handle(reader, writer):
        head = await reader.readuntil(b"\r\n\r\n")
        length = next(int(line.split(b":", 1)[1]) for line in head.split(b"\r\n")
                      if line.lower().startswith(b"content-length:"))
        payload = json.loads(await reader.readexactly(length))
        prefix = json.dumps(payload.get("tools"), sort_keys=True)
        cached = 5 if prefix in seen else 0
        served.append(cached)
        seen.add(prefix)
        chunk = {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 1,
                           "prompt_tokens_details": {"cached_tokens": cached}}}
        body = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: "
                     + str(len(body)).encode() + b"\r\n\r\n" + body)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    root = Path(__file__).parents[4]
    loaded = await load_extensions(
        [root / "capability_packages/reasonix_prefix_cache/extensions/reasonix_prefix_cache.py"], root
    )
    runner = ExtensionRunner.from_load_result(loaded, root)
    model = {"id": "m", "api": "openai-completions", "provider": "local",
             "baseUrl": f"http://127.0.0.1:{port}/v1", "contextWindow": 1000}
    context = {"messages": [{"role": "user", "content": "hello", "timestamp": 1}],
               "tools": [{"name": "z", "description": "", "parameters": {"type": "object"}},
                         {"name": "a", "description": "", "parameters": {"type": "object"}}]}
    reads = []
    async def on_payload(payload, _model):
        return await runner.emit_before_provider_request(payload)

    try:
        for _ in range(2):
            result = await stream(model, context, {"apiKey": "x", "onPayload": on_payload}).result()
            reads.append(result["usage"]["cacheRead"])
            assert result["stopReason"] != "error", result.get("errorMessage")
            await runner.emit_message_end({"type": "message_end", "message": result})
    finally:
        server.close()
        await server.wait_closed()
    assert served == [0, 5]
    assert reads == [0, 5]
    assert not runner.get_all_registered_tools()
