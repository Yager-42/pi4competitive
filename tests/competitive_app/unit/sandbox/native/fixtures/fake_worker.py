"""Fake protocol worker fixture for NativeRuntime unit tests.

Emits valid ``agent-tool-rpc.v1`` frames from the request identity, with
env-controlled failure modes (no app imports — the runner spawns this file
directly through the fake broker)."""
from __future__ import annotations

import json
import os
import sys
import time


def _emit(stream, payload: dict) -> None:
    stream.write((json.dumps(payload) + "\n").encode("utf-8"))
    stream.flush()


def main() -> int:
    line = sys.stdin.buffer.readline()
    if not line:
        return 2
    request = json.loads(line)
    scope_id = request["scopeId"]
    tool_call_id = request["toolCallId"]
    out = sys.stdout.buffer

    if os.environ.get("FAKE_WORKER_SLEEP"):
        time.sleep(5)
    if os.environ.get("FAKE_WORKER_EXIT"):
        return int(os.environ["FAKE_WORKER_EXIT"])
    if os.environ.get("FAKE_WORKER_EMPTY"):
        return 0
    if os.environ.get("FAKE_WORKER_BAD_SCOPE"):
        scope_id = "0" * 64

    partial = "partial"
    manifest = os.environ.get("PI4COMPETITIVE_MANIFEST_PATH")
    if manifest:
        partial += f" manifest={manifest}"
    _emit(
        out,
        {
            "protocolVersion": 1,
            "scopeId": scope_id,
            "toolCallId": tool_call_id,
            "sequence": 1,
            "type": "update",
            "result": {"content": [{"type": "text", "text": partial}]},
        },
    )
    _emit(
        out,
        {
            "protocolVersion": 1,
            "scopeId": scope_id,
            "toolCallId": tool_call_id,
            "sequence": 2,
            "type": "result",
            "result": {"content": [{"type": "text", "text": "final"}]},
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
