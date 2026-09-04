"""Transient tool-call retry (P2-附).

``error.retryable`` has always been part of the frame contract, but every
worker error hard-coded False and nothing read it — so a search that lost its
connection consumed a coverage cell's attempt budget exactly like a malformed
request did. These tests pin both halves: the worker classifying the fault, and
the executor re-attempting only what was declared transient.
"""
from __future__ import annotations

from typing import Any

import pytest

from competitive_app.adapter.out.sandbox import sandbox_tool_executor as ste
from competitive_app.adapter.out.sandbox.protocol import PROTOCOL_VERSION, RpcFrame
from competitive_app.adapter.out.sandbox.sandbox_tool_executor import (
    TOOL_MAX_ATTEMPTS,
    SandboxToolExecutionError,
    SandboxToolExecutor,
)
from competitive_app.adapter.out.sandbox.worker import _is_transient
from earendil_works.pi_agent.types import AgentTool

SCOPE = "a" * 64


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ste, "TOOL_RETRY_BASE_DELAY_SECONDS", 0.0)


def _frame(kind: str, *, retryable: bool = False, seq: int = 1) -> RpcFrame:
    if kind == "error":
        return RpcFrame(
            protocol_version=PROTOCOL_VERSION, scope_id=SCOPE, tool_call_id="c1",
            sequence=seq, type="error",
            error={"code": "tool_execution_error", "safeMessage": "tool execution failed",
                   "retryable": retryable},
        )
    if kind == "update":
        return RpcFrame(
            protocol_version=PROTOCOL_VERSION, scope_id=SCOPE, tool_call_id="c1",
            sequence=seq, type="update",
            result={"content": [{"type": "text", "text": "partial"}]},
        )
    return RpcFrame(
        protocol_version=PROTOCOL_VERSION, scope_id=SCOPE, tool_call_id="c1",
        sequence=seq, type="result",
        result={"content": [{"type": "text", "text": "ok"}]},
    )


class _Sandbox:
    """Replays a scripted frame sequence, one entry per execute_worker call."""

    def __init__(self, script: list[list[RpcFrame]]) -> None:
        self.script = script
        self.calls = 0

    async def execute_worker(self, _request: Any, deliver: Any, signal: Any = None) -> RpcFrame:
        frames = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        for frame in frames:
            await deliver(frame)
        return frames[-1]


class _Provider:
    def __init__(self, sandbox: _Sandbox) -> None:
        self.sandbox = sandbox

    async def acquire(self, _scope_id: str) -> _Sandbox:
        return self.sandbox


class _Registry:
    bindings: dict[str, Any] = {}

    def binding_for(self, tool: AgentTool) -> Any:
        class _Binding:
            @staticmethod
            def to_mapping() -> dict[str, str]:
                return {"module": "m", "attribute": "a"}

        return _Binding()


def _executor(script: list[list[RpcFrame]]) -> tuple[SandboxToolExecutor, _Sandbox]:
    sandbox = _Sandbox(script)
    return (
        SandboxToolExecutor(registry=_Registry(), provider=_Provider(sandbox)),
        sandbox,
    )


async def _run(executor: SandboxToolExecutor, updates: list[Any] | None = None) -> Any:
    return await executor.execute(
        scope_id=SCOPE,
        tool=AgentTool(
            name="tavily_search",
            description="d",
            parameters={"type": "object"},
            label="tavily_search",
            execute=None,
        ),
        tool_call_id="c1",
        params={"query": "x"},
        signal=None,
        on_update=(updates.append if updates is not None else (lambda _r: None)),
    )


# --------------------------------------------------------------- executor half


@pytest.mark.asyncio
async def test_retryable_error_is_reattempted_and_succeeds() -> None:
    executor, sandbox = _executor([[_frame("error", retryable=True)], [_frame("result")]])
    result = await _run(executor)
    assert sandbox.calls == 2
    assert result["content"] == [{"type": "text", "text": "ok"}]


@pytest.mark.asyncio
async def test_non_retryable_error_fails_on_the_first_attempt() -> None:
    executor, sandbox = _executor([[_frame("error", retryable=False)], [_frame("result")]])
    with pytest.raises(SandboxToolExecutionError):
        await _run(executor)
    assert sandbox.calls == 1


@pytest.mark.asyncio
async def test_gives_up_after_max_attempts() -> None:
    executor, sandbox = _executor([[_frame("error", retryable=True)]])
    with pytest.raises(SandboxToolExecutionError) as caught:
        await _run(executor)
    assert sandbox.calls == TOOL_MAX_ATTEMPTS
    assert caught.value.details["retryable"] is True


@pytest.mark.asyncio
async def test_streamed_update_blocks_retry() -> None:
    """Partial content already reached the caller; a second attempt would
    contradict what it was told."""
    executor, sandbox = _executor(
        [[_frame("update"), _frame("error", retryable=True, seq=2)], [_frame("result")]]
    )
    updates: list[Any] = []
    with pytest.raises(SandboxToolExecutionError):
        await _run(executor, updates)
    assert sandbox.calls == 1
    assert len(updates) == 1


@pytest.mark.asyncio
async def test_success_on_first_attempt_does_not_retry() -> None:
    executor, sandbox = _executor([[_frame("result")]])
    await _run(executor)
    assert sandbox.calls == 1


# ----------------------------------------------------------------- worker half


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("read timeout"),
        ConnectionResetError("peer reset"),
        ConnectionError("refused"),
        OSError("network unreachable"),
    ],
)
def test_network_faults_are_transient(exc: BaseException) -> None:
    assert _is_transient(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("bad argument"),
        KeyError("missing field"),
        PermissionError("denied"),
        FileNotFoundError("no such file"),
        TypeError("wrong type"),
    ],
)
def test_request_faults_are_not_transient(exc: BaseException) -> None:
    assert _is_transient(exc) is False


def test_third_party_exception_matched_by_name() -> None:
    """httpx/aiohttp live inside the sandbox; the worker must not import them."""

    class ConnectTimeout(Exception):
        pass

    assert _is_transient(ConnectTimeout("slow")) is True


@pytest.mark.parametrize("status,expected", [(429, True), (503, True), (404, False), (401, False)])
def test_http_status_decides_transience(status: int, expected: bool) -> None:
    class Response:
        status_code = status

    class HTTPStatusError(Exception):
        def __init__(self) -> None:
            super().__init__("status")
            self.response = Response()

    assert _is_transient(HTTPStatusError()) is expected


def test_transience_is_read_through_the_cause_chain() -> None:
    """Capability packages wrap their own errors; the cause carries the fault."""
    try:
        try:
            raise ConnectionResetError("peer reset")
        except ConnectionResetError as inner:
            raise RuntimeError("search failed") from inner
    except RuntimeError as outer:
        assert _is_transient(outer) is True
