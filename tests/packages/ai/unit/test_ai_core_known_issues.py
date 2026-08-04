from __future__ import annotations

import asyncio
import io
import json
import time
from pathlib import Path

import pytest

from earendil_works.pi_ai.auth.credential_store import InMemoryCredentialStore
from earendil_works.pi_ai.auth.resolve import ModelsError, _resolve_stored_oauth
from earendil_works.pi_ai.model_catalog import _read_json, flatten_model_catalog
from earendil_works.pi_ai.models import create_models, create_provider
from earendil_works.pi_ai.models_store import InMemoryModelsStore
from earendil_works.pi_ai.providers.faux import _with_usage_estimate, create_faux_core, faux_assistant_message
from earendil_works.pi_ai.providers.mistral import mistral_provider
from earendil_works.pi_ai.utils.diagnostics import redacted_diagnostic
from earendil_works.pi_ai.utils.event_stream import EventStream, create_assistant_message_event_stream
from earendil_works.pi_ai.utils.json_parse import parse_partial_json


def _model(provider: str = "p", api: str = "test") -> dict:
    return {
        "id": "m",
        "name": "m",
        "api": api,
        "provider": provider,
        "reasoning": False,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 100,
        "maxTokens": 10,
    }


@pytest.mark.asyncio
async def test_credential_modify_none_is_no_write_and_empty_rejected() -> None:
    store = InMemoryCredentialStore()
    await store.write("p", {"type": "api_key", "key": "secret"})
    result = await store.modify("p", lambda _: _async_none())
    assert result == {"type": "api_key", "key": "secret"}
    assert await store.read("p") == result
    with pytest.raises(ValueError):
        await store.write("empty", {})  # type: ignore[arg-type]
    store._entries["legacy"] = {}  # type: ignore[assignment]
    assert await store.read("legacy") == {}


async def _async_none():
    return None


@pytest.mark.asyncio
async def test_oauth_refresh_race_and_errors_are_normalized() -> None:
    store = InMemoryCredentialStore()
    fresh = {"type": "oauth", "access": "new", "refresh": "r", "expires": int(time.time() * 1000) + 60_000}
    await store.write("p", fresh)
    stale = {"type": "oauth", "access": "old", "refresh": "r", "expires": 0}
    oauth = {"toAuth": lambda c: _to_auth(c), "refresh": lambda c: _raise_refresh()}
    result = await _resolve_stored_oauth(store, "p", oauth, stale)  # type: ignore[arg-type]
    assert result and result["auth"]["apiKey"] == "new"

    async def bad_to_auth(_c):
        raise RuntimeError("conversion failed")

    oauth_bad = {"toAuth": bad_to_auth, "refresh": lambda c: _raise_refresh()}
    await store.write("p", stale)
    with pytest.raises(ModelsError) as refresh_exc:
        await _resolve_stored_oauth(store, "p", oauth, stale)  # type: ignore[arg-type]
    assert refresh_exc.value.code == "auth"
    await store.write("p", fresh)
    with pytest.raises(ModelsError) as exc:
        await _resolve_stored_oauth(store, "p", oauth_bad, fresh)  # type: ignore[arg-type]
    assert exc.value.code == "auth"



@pytest.mark.asyncio
async def test_oauth_refresh_is_coordinated_for_concurrent_expired_requests() -> None:
    store = InMemoryCredentialStore()
    stale = {"type": "oauth", "access": "old", "refresh": "r", "expires": 0}
    fresh = {"type": "oauth", "access": "new", "refresh": "r", "expires": int(time.time() * 1000) + 60_000}
    await store.write("p", stale)
    first_started = asyncio.Event()
    release = asyncio.Event()
    refresh_calls = 0

    async def refresh(_credential):
        nonlocal refresh_calls
        refresh_calls += 1
        if refresh_calls == 1:
            first_started.set()
            await release.wait()
        return fresh

    async def to_auth(credential):
        return {"auth": {"apiKey": credential["access"]}, "source": "oauth"}

    oauth = {"toAuth": to_auth, "refresh": refresh}
    tasks = [
        asyncio.create_task(_resolve_stored_oauth(store, "p", oauth, stale)),
        asyncio.create_task(_resolve_stored_oauth(store, "p", oauth, stale)),
    ]
    await asyncio.wait_for(first_started.wait(), timeout=1)
    release.set()
    results = await asyncio.gather(*tasks)
    assert refresh_calls == 1
    assert results == [{"auth": {"apiKey": "new"}, "source": "oauth"}] * 2

async def _to_auth(credential):
    return {"auth": {"apiKey": credential["access"]}, "source": "oauth"}


async def _raise_refresh():
    raise RuntimeError("refresh failed")



def test_grouped_catalog_preserves_api() -> None:
    result = flatten_model_catalog("p", {"api-a": {"one": {"name": "One"}}})
    assert result["one"]["api"] == "api-a"
    assert result["one"]["provider"] == "p"


def test_catalog_json_errors_are_not_silenced(monkeypatch: pytest.MonkeyPatch) -> None:
    class BadPath:
        def open(self, *args, **kwargs):
            return io.StringIO("{")

    class Package:
        def joinpath(self, *args):
            return BadPath()

    monkeypatch.setattr("earendil_works.pi_ai.model_catalog.resources.files", lambda _: Package())
    with pytest.raises(json.JSONDecodeError):
        _read_json("bad")


@pytest.mark.asyncio
async def test_unknown_provider_availability_is_empty() -> None:
    models = create_models()
    assert await models.getAvailable("missing") == []


@pytest.mark.asyncio
async def test_create_provider_accepts_single_api_object() -> None:
    stream = create_assistant_message_event_stream()

    class Api:
        def stream(self, model, context, options=None):
            stream.push({"type": "done", "reason": "stop", "message": faux_assistant_message("ok")})
            return stream

    provider = create_provider({"id": "p", "auth": {}, "models": [_model()], "api": Api()})
    assert await provider.stream(provider.getModels()[0], {"messages": []}).result()


@pytest.mark.asyncio
async def test_provider_refresh_is_shared_between_concurrent_callers() -> None:
    calls = 0

    async def fetch(_context):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return [_model()]

    class Store:
        async def read(self):
            return None

        async def write(self, _entry):
            return None

    provider = create_provider({"id": "p", "auth": {}, "models": [], "api": {}, "fetchModels": fetch})
    await asyncio.gather(
        provider.refreshModels({"store": Store(), "allowNetwork": True}),
        provider.refreshModels({"store": Store(), "allowNetwork": True}),
    )
    assert calls == 1


@pytest.mark.asyncio
async def test_empty_models_store_entry_round_trips() -> None:
    store = InMemoryModelsStore()
    await store.write("p", {})
    assert await store.read("p") == {}


def test_faux_usage_has_consistent_cache_buckets() -> None:
    message = faux_assistant_message("answer")
    result = _with_usage_estimate(message, {"messages": [{"role": "user", "content": "hello"}]}, None, {})
    usage = result["usage"]
    assert usage["totalTokens"] == usage["input"] + usage["output"] + usage["cacheRead"] + usage["cacheWrite"]
    assert usage["input"] > 0
    assert usage["cacheRead"] == 0
    assert usage["cacheWrite"] == 0


def test_mistral_base_url_does_not_duplicate_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "earendil_works.pi_ai.providers.mistral.get_models",
        lambda: [{"id": "m", "name": "m", "baseUrl": "https://api.mistral.ai/v1"}],
    )
    provider = mistral_provider()
    assert provider.getModels()[0]["baseUrl"] == "https://api.mistral.ai/v1"


def test_mistral_models_use_v1_base_url() -> None:
    provider = mistral_provider()
    assert provider.getModels()
    assert all(model["baseUrl"].endswith("/v1") for model in provider.getModels())


def test_diagnostics_redacts_nested_sensitive_values() -> None:
    diagnostic = redacted_diagnostic(
        "request failed",
        apiKey="secret",
        nested={"token": "abc", "safe": 1},
        headers={"Authorization": "Bearer abc", "x-request-id": "id"},
    )
    assert diagnostic["apiKey"] == "[REDACTED]"
    assert diagnostic["nested"] == {"token": "[REDACTED]", "safe": 1}
    assert diagnostic["headers"]["Authorization"] == "[REDACTED]"
    assert diagnostic["headers"]["x-request-id"] == "id"


def test_event_stream_can_move_from_sync_construction_to_new_loop() -> None:
    stream = create_assistant_message_event_stream()

    async def consume():
        message = faux_assistant_message("ok")
        stream.push({"type": "done", "reason": "stop", "message": message})
        return await stream.result()

    assert asyncio.run(consume())["content"][0]["text"] == "ok"


@pytest.mark.asyncio
async def test_event_stream_end_without_result_fails_result_waiter() -> None:
    stream = create_assistant_message_event_stream()
    stream.end()
    with pytest.raises(RuntimeError, match="without a result"):
        await stream.result()


def test_partial_json_closes_mixed_nesting_stack() -> None:
    assert parse_partial_json('[{"a": [1') == [{"a": [1]}]
    assert parse_partial_json('{"text": "[not nesting"') == {"text": "[not nesting"}


def test_partial_json_preserves_trailing_comma_in_string() -> None:
    assert parse_partial_json('{"text":"hello,') == {"text": "hello,"}


def test_faux_stream_started_after_sync_construction() -> None:
    core = create_faux_core()
    core["setResponses"]([faux_assistant_message("offline")])
    stream = core["stream"](core["models"][0], {"messages": []})

    async def consume():
        return [event async for event in stream]

    events = asyncio.run(consume())
    assert events[-1]["type"] == "done"
    assert events[-1]["reason"] == "stop"
    assert events[-1]["message"]["content"] == [{"type": "text", "text": "offline"}]
    assert not any(event["type"] == "error" for event in events)


def test_event_stream_result_can_be_constructed_before_a_loop() -> None:
    stream = EventStream(lambda event: event == "done", lambda _event: "ok")
    pending = stream.result()

    async def complete() -> str:
        stream.push("done")
        return await pending

    assert asyncio.run(complete()) == "ok"


def test_event_stream_deferred_runner_starts_in_consuming_loop() -> None:
    stream = EventStream(lambda event: event == "done", lambda _event: "ok")

    async def run() -> None:
        stream.push("done")

    stream.start(run)
    pending = stream.result()
    assert asyncio.run(pending) == "ok"


def test_event_stream_producer_and_consumer_can_use_different_loops() -> None:
    stream = EventStream(lambda event: event == "done", lambda _event: "ok")

    async def produce() -> None:
        stream.push("intermediate")
        stream.push("done")

    asyncio.run(produce())

    async def consume() -> tuple[list[str], str]:
        events = [event async for event in stream]
        return events, await stream.result()

    events, result = asyncio.run(consume())
    assert events == ["intermediate", "done"]
    assert result == "ok"


@pytest.mark.asyncio
async def test_event_stream_runner_cancellation_wakes_iterator_and_result() -> None:
    stream = EventStream(lambda event: event == "done", lambda _event: "ok")
    started = asyncio.Event()

    async def run() -> None:
        started.set()
        raise asyncio.CancelledError()

    stream.start(run)
    iterator = asyncio.create_task(collect_stream(stream))
    await started.wait()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(stream.await_result(), timeout=1)
    assert await asyncio.wait_for(iterator, timeout=1) == []
    assert stream._final_result is not None and stream._final_result.done()
    assert stream._runner_task is not None and stream._runner_task.done()


@pytest.mark.asyncio
async def test_event_stream_runner_failure_wakes_iterator_and_result() -> None:
    stream = EventStream(lambda event: event == "done", lambda _event: "ok")
    started = asyncio.Event()

    async def run() -> None:
        started.set()
        raise RuntimeError("producer failed")

    stream.start(run)
    iterator = asyncio.create_task(collect_stream(stream))
    await started.wait()
    with pytest.raises(RuntimeError, match="producer failed"):
        await asyncio.wait_for(stream.await_result(), timeout=1)
    assert await asyncio.wait_for(iterator, timeout=1) == []
    assert stream._final_result is not None and stream._final_result.done()
    assert stream._runner_task is not None and stream._runner_task.done()


async def collect_stream(stream: EventStream[str, str]) -> list[str]:
    return [event async for event in stream]


@pytest.mark.asyncio
async def test_credential_write_serializes_with_modify() -> None:
    """write/delete must not interleave with an in-flight modify."""
    store = InMemoryCredentialStore()
    order: list[str] = []

    async def slow_mutator(_cred):
        order.append("modify-start")
        await asyncio.sleep(0.05)
        order.append("modify-end")
        return {"type": "api_key", "key": "m"}
    modify_task = asyncio.create_task(store.modify("p", slow_mutator))
    await asyncio.sleep(0.01)
    await store.write("p", {"type": "api_key", "key": "w"})
    await modify_task
    assert order == ["modify-start", "modify-end"]
    # write queued behind the modify lock and applied afterwards.
    assert (await store.read("p"))["key"] == "w"


@pytest.mark.asyncio
async def test_credential_delete_serializes_with_modify() -> None:
    store = InMemoryCredentialStore()
    await store.write("p", {"type": "api_key", "key": "old"})
    entered = asyncio.Event()

    async def slow_mutator(_cred):
        entered.set()
        await asyncio.sleep(0.05)
        return {"type": "api_key", "key": "m"}

    modify_task = asyncio.create_task(store.modify("p", slow_mutator))
    await entered.wait()
    await store.delete("p")
    await modify_task
    # delete queued behind the modify lock and applied afterwards.
    assert await store.read("p") is None
