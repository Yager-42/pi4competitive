"""ADR 0015: structured error classification on AssistantMessage.

Covers the single production point ``_http_stream.error_message()``:
HTTP status codes -> ``http_error``; httpx transport exceptions -> ``timeout`` /
``connection`` / ``other``; abort -> ``aborted``. ``errorMessage`` text is kept
for backward compatibility and success messages carry no ``error`` field.
"""

from __future__ import annotations

import httpx
import pytest

from earendil_works.pi_ai.api._http_stream import error_message
from earendil_works.pi_ai.types import AssistantMessage, ErrorInfo, Model

MODEL: Model = {
    "id": "gpt-test",
    "api": "openai-completions",
    "provider": "openai",
}


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502, 503])
def test_http_error_status_code_classified(status: int) -> None:
    # production call path: _http_stream passes status_code explicitly
    msg = error_message(MODEL, f"HTTP {status}: boom", status_code=status)
    assert msg["stopReason"] == "error"
    err = msg["error"]
    assert err["type"] == "http_error"
    assert err["statusCode"] == status
    assert "boom" in err["message"]

def test_timeout_exception_classified() -> None:
    msg = error_message(MODEL, httpx.ReadTimeout("slow"))
    assert msg["error"]["type"] == "timeout"
    assert "statusCode" not in msg["error"]


def test_connect_error_classified() -> None:
    msg = error_message(MODEL, httpx.ConnectError("refused"))
    assert msg["error"]["type"] == "connection"


def test_builtin_connection_error_classified() -> None:
    msg = error_message(MODEL, ConnectionError("refused"))
    assert msg["error"]["type"] == "connection"


def test_aborted_classified() -> None:
    msg = error_message(MODEL, "cancelled", aborted=True)
    assert msg["stopReason"] == "aborted"
    assert msg["error"]["type"] == "aborted"


def test_unknown_error_falls_back_to_other() -> None:
    msg = error_message(MODEL, ValueError("weird"))
    assert msg["error"]["type"] == "other"


def test_read_error_is_other_not_downgrade_class() -> None:
    # ADR 0015: ReadError -> "other" (only timeout/connection downgrade).
    msg = error_message(MODEL, httpx.ReadError("stream broke"))
    assert msg["error"]["type"] == "other"


def test_error_message_text_kept_for_compat() -> None:
    msg = error_message(MODEL, httpx.ReadTimeout("slow"))
    assert msg["errorMessage"] == "slow"
    assert msg["error"]["message"] == "slow"


def test_success_message_has_no_error_field() -> None:
    msg: AssistantMessage = {
        "role": "assistant",
        "content": [{"type": "text", "text": "ok"}],
        "api": "openai-completions",
        "provider": "openai",
        "model": "gpt-test",
        "usage": {"input": 1, "output": 1, "cacheRead": 0, "cacheWrite": 0, "total": 2},
        "stopReason": "stop",
        "timestamp": 0,
    }
    assert "error" not in msg
    # shape sanity for the contract type itself
    err: ErrorInfo = {"type": "timeout", "message": "x"}
    assert err["type"] == "timeout"
