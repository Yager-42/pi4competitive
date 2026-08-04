from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from competitive_app.application.workflow.runtime_registry import RuntimeRegistry
from competitive_app.application.workflow.session_service import (
    SessionAbortedError,
    SessionService,
)


@pytest.mark.asyncio
async def test_stream_events_are_fanned_out_to_each_subscriber() -> None:
    registry = RuntimeRegistry()
    registry.register_stream("task")
    first = registry.get_stream("task")
    second = registry.get_stream("task")
    assert first is not None and second is not None and first is not second
    event = {"type": "done", "data": {"status": "completed"}}
    registry.publish_stream("task", event)
    assert await first.get() == event
    assert await second.get() == event


@pytest.mark.asyncio
async def test_abort_task_handles_runner_exception_and_returns_boolean() -> None:
    registry = RuntimeRegistry()
    started = asyncio.Event()

    async def operation() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise RuntimeError("cleanup failed")

    registry.start_task("task", None, operation())
    await started.wait()
    assert await registry.abort_task("task", "test") is True


@pytest.mark.asyncio
async def test_stream_unsubscribe_bounds_abandoned_subscribers() -> None:
    registry = RuntimeRegistry()
    registry.register_stream("task")
    queue = registry.get_stream("task")
    assert queue is not None
    assert registry.unsubscribe_stream("task", queue) is True
    for index in range(300):
        registry.publish_stream("task", {"type": "stage", "data": {"i": index}})
    assert queue.qsize() == 0
    assert queue.maxsize == 256
    current = registry.get_stream("task")
    assert current is not None
    registry.publish_stream("task", {"type": "stage", "data": {"i": "current"}})
    event = await current.get()
    while not current.empty():
        event = current.get_nowait()
    assert event["data"]["i"] == "current"
    assert registry.unsubscribe_stream("task", current) is True


@pytest.mark.asyncio
async def test_concurrent_stream_registration_does_not_replace_live_owner() -> None:
    registry = RuntimeRegistry()
    first = registry.register_stream("task")
    second = registry.register_stream("task")
    registry.publish_stream("task", {"type": "stage", "data": {"i": 1}})
    assert await first.get() == await second.get()
    release = asyncio.Event()
    task = registry.start_task("task", None, release.wait())
    assert isinstance(task, asyncio.Task)
    registry.unregister_stream("task")
    registry.publish_stream("task", {"type": "stage", "data": {"i": 2}})
    assert first.empty() and second.empty()
    release.set()
    await task

@pytest.mark.asyncio
async def test_terminal_eviction_never_removes_live_replacement(monkeypatch) -> None:
    from competitive_app.application.workflow import runtime_registry as registry_module

    monkeypatch.setattr(registry_module, "_TERMINAL_STREAM_LIMIT", 1)
    registry = RuntimeRegistry()
    registry.register_stream("same")
    registry.publish_stream("same", {"type": "done", "data": {}})
    live = registry.register_stream("same")
    registry.register_stream("other")
    registry.publish_stream("other", {"type": "done", "data": {}})
    current = registry.get_stream("same")
    assert current is not None
    registry.publish_stream("same", {"type": "stage", "data": {"i": 1}})
    assert await live.get() == await current.get()


@pytest.mark.asyncio
async def test_shutdown_closes_all_harnesses_after_one_failure() -> None:
    registry = RuntimeRegistry()
    closed: list[str] = []

    class Harness:
        def __init__(self, name: str, fail: bool = False) -> None:
            self.name = name
            self.fail = fail
            self.agent = SimpleNamespace(abort=lambda: None)

        async def shutdown(self) -> None:
            closed.append(self.name)
            if self.fail:
                raise RuntimeError("shutdown failed")

    registry.register_harness("one", Harness("one", True))
    registry.register_harness("two", Harness("two"))
    await registry.shutdown()
    assert closed == ["one", "two"]
    assert registry.get_harness("one") is None
    assert registry.get_harness("two") is None

@pytest.mark.asyncio
async def test_queued_prompt_is_cancelled_by_session_abort() -> None:
    lock_started = asyncio.Event()
    release = asyncio.Event()

    class Agent:
        signal = None
        state = SimpleNamespace(messages=[])

        def abort(self) -> None:
            self.signal = object()

    class Harness:
        agent = Agent()

        async def prompt(self, _content: object) -> None:
            lock_started.set()
            await release.wait()

    class Store:
        async def get_session(self, _session_id: str) -> dict:
            return {"session_id": "s", "cwd": "test", "file_path": "s.jsonl", "model": "", "system_prompt": ""}

    class Resolver:
        def resolve(self, _model: str) -> dict:
            return {}

    registry = RuntimeRegistry()
    queued = asyncio.Event()
    queue_calls = 0
    original_register_queued = registry.register_queued

    def register_queued(session_id: str, waiter: asyncio.Task) -> None:
        nonlocal queue_calls
        original_register_queued(session_id, waiter)
        queue_calls += 1
        if queue_calls >= 2:
            queued.set()

    registry.register_queued = register_queued  # type: ignore[method-assign]
    harness = Harness()
    registry.register_harness("s", harness)
    service = SessionService(
        repo=SimpleNamespace(),
        store=Store(),
        registry=registry,
        harness_factory=SimpleNamespace(),
        model_resolver=Resolver(),
        prompt_lock_timeout=5,
    )
    first = asyncio.create_task(service.prompt("s", "first"))
    await lock_started.wait()
    second = asyncio.create_task(service.prompt("s", "second"))
    await queued.wait()
    await registry.abort_session("s")
    with pytest.raises(SessionAbortedError):
        await second
    release.set()
    await first


@pytest.mark.asyncio
async def test_create_task_index_failure_removes_session_artifacts() -> None:
    from competitive_app.application.workflow.task_service import TaskService
    from competitive_app.domain.research_brief import ResearchBrief

    removed: list[str] = []

    class Session:
        async def get_metadata(self) -> dict[str, str]:
            return {"id": "s", "path": "s.jsonl"}

    class Repo:
        async def create(self, _options: dict) -> Session:
            return Session()

        async def delete(self, _metadata: dict) -> None:
            removed.append("jsonl")

    class Store:
        async def get_task(self, _task_id: str) -> None:
            return None

        async def index_session(self, **_kwargs: object) -> None:
            raise RuntimeError("index failed")

        async def delete_session(self, _session_id: str) -> None:
            removed.append("index")

    service = TaskService(
        store=Store(), repo=Repo(), registry=RuntimeRegistry(), harness_factory=SimpleNamespace()
    )
    brief = ResearchBrief(
        target={"name": "A", "category": "SaaS"},
        goal="compare",
        competitors=["B"],
        dimensions=["pricing"],
    )
    with pytest.raises(RuntimeError, match="index failed"):
        await service._start_research_task(brief, {})
    assert removed == ["jsonl", "index"]


@pytest.mark.asyncio
async def test_resume_prerequisite_failure_keeps_terminal_status() -> None:
    from competitive_app.application.workflow.task_service import TaskConflictError, TaskService

    updates: list[str] = []

    class Store:
        async def get_task(self, _task_id: str) -> dict:
            return {"task_id": "t", "status": "failed", "session_id": None, "projection": {}}

        async def update_task_status(self, _task_id: str, status: str, **_kwargs: object) -> None:
            updates.append(status)

    service = TaskService(
        store=Store(), repo=SimpleNamespace(), registry=RuntimeRegistry(), harness_factory=SimpleNamespace()
    )
    with pytest.raises(TaskConflictError, match="no session"):
        await service.resume_task("t")
    assert updates == []


@pytest.mark.asyncio
async def test_create_session_index_failure_cleans_harness_and_jsonl() -> None:
    removed: list[str] = []

    class Session:
        async def get_metadata(self) -> dict[str, str]:
            return {"id": "s", "path": "s.jsonl"}

    class Repo:
        async def create(self, _options: dict) -> Session:
            return Session()

        async def delete(self, _metadata: dict) -> None:
            removed.append("jsonl")

    class Harness:
        async def shutdown(self) -> None:
            removed.append("harness")

    class Factory:
        async def build(self, **_kwargs: object) -> Harness:
            return Harness()

    class Store:
        async def index_session(self, **_kwargs: object) -> None:
            raise RuntimeError("sqlite failed")

        async def delete_session(self, _session_id: str) -> None:
            removed.append("index")

    class Resolver:
        def resolve(self, _model: str) -> dict:
            return {}

    service = SessionService(
        repo=Repo(),
        store=Store(),
        registry=RuntimeRegistry(),
        harness_factory=Factory(),
        model_resolver=Resolver(),
    )
    with pytest.raises(RuntimeError, match="sqlite failed"):
        await service.create_session(model="", system_prompt="", metadata={}, cwd="test")
    assert removed == ["harness", "jsonl", "index"]


@pytest.mark.asyncio
async def test_post_task_evolution_failure_does_not_fail_run(tmp_path, monkeypatch) -> None:
    import competitive_app.application.workflow.task_service as task_module
    from competitive_app.application.workflow.task_service import TaskService
    from competitive_app.domain.research_brief import ResearchBrief

    statuses: list[str] = []
    evaluations: list[tuple[str, str, object]] = []
    evolution_calls: list[str] = []

    class Agent:
        def abort(self) -> None:
            pass

    class Harness:
        agent = Agent()

    class Factory:
        async def build(self, **_kwargs: object) -> Harness:
            return Harness()

    class Store:
        async def update_task_status(self, _task_id: str, status: str, **_kwargs: object) -> None:
            statuses.append(status)

    class Runner:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def run(self, **_kwargs: object) -> str:
            return "completed"

    class Evolution:
        async def run_cycle(self) -> None:
            evolution_calls.append("run")
            raise RuntimeError("evolution unavailable")

    async def post_eval(task_id: str, status: str, runner: object) -> None:
        evaluations.append((task_id, status, runner))

    monkeypatch.setattr(task_module, "ResearchRunner", Runner)
    service = TaskService(
        store=Store(),
        repo=SimpleNamespace(),
        registry=RuntimeRegistry(),
        harness_factory=Factory(),
        evolution_cycle_runner=Evolution(),
        runs_root=str(tmp_path / "runs"),
    )
    service._post_task_eval = post_eval  # type: ignore[method-assign]
    brief = ResearchBrief(
        target={"name": "A", "category": "SaaS"},
        goal="compare",
        competitors=["B"],
        dimensions=["pricing"],
    )
    await service._run_research("t", brief, SimpleNamespace(), "s")
    assert len(evaluations) == 1
    task_id, status, runner = evaluations[0]
    assert (task_id, status) == ("t", "completed")
    assert isinstance(runner, Runner)
    assert evolution_calls == ["run"]
    assert statuses == []

@pytest.mark.asyncio
async def test_shutdown_logs_harness_cleanup_failures(caplog: pytest.LogCaptureFixture) -> None:
    registry = RuntimeRegistry()

    class Harness:
        agent = SimpleNamespace(abort=lambda: (_ for _ in ()).throw(RuntimeError("abort boom")))

        async def shutdown(self) -> None:
            raise RuntimeError("shutdown boom")

    registry.register_harness("session-1", Harness())
    with caplog.at_level("WARNING"):
        await registry.shutdown()
    assert "session-1" in caplog.text
    assert "abort failed" in caplog.text
    assert "shutdown failed" in caplog.text


def _resume_service(task: dict, *, brief: object | None = object()):
    from competitive_app.application.workflow.task_service import TaskService

    class Store:
        prepared: list[tuple[str, str, dict]] = []

        async def get_task(self, _task_id):
            return task

        async def prepare_resume_if_current(
            self, task_id, *, expected_status, metadata, expected_updated_at
        ):
            self.prepared.append((task_id, expected_status, metadata))
            return True

    store = Store()
    service = TaskService(
        store=store,
        repo=SimpleNamespace(),
        registry=RuntimeRegistry(),
        harness_factory=SimpleNamespace(),
    )

    async def load_brief(_session_id):
        return brief

    service._load_research_brief = load_brief  # type: ignore[method-assign]
    return service, store


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"status": "pending"}, "not resumable"),
        ({"projection": {"stages": {"plan": "ok", "search": "ok", "write": "ok"}}}, "no incomplete"),
        ({"session_id": ""}, "no session"),
        ({"metadata": {}}, "no stop_after_stage"),
    ],
)
async def test_prepare_resume_rejects_missing_prerequisites(change, message) -> None:
    from competitive_app.application.workflow.task_service import TaskConflictError

    task = {
        "task_id": "task",
        "status": "failed",
        "projection": {"stages": {"plan": "ok", "search": "pending"}},
        "session_id": "session",
        "metadata": {"stop_after_stage": "search", "keep": True},
        "updated_at": "v1",
        **change,
    }
    service, store = _resume_service(task)
    with pytest.raises(TaskConflictError, match=message):
        await service.prepare_resume_task("task")
    assert store.prepared == []


@pytest.mark.asyncio
async def test_prepare_resume_requires_brief_and_atomically_removes_stop_marker() -> None:
    from competitive_app.application.workflow.task_service import TaskConflictError

    task = {
        "task_id": "task",
        "status": "failed",
        "projection": {"stages": {"plan": "ok", "search": "pending"}},
        "session_id": "session",
        "metadata": {"stop_after_stage": "search", "keep": True},
        "updated_at": "v1",
    }
    missing, store = _resume_service(task, brief=None)
    with pytest.raises(TaskConflictError, match="brief not recoverable"):
        await missing.prepare_resume_task("task")
    assert store.prepared == []

    service, store = _resume_service(task)
    assert await service.prepare_resume_task("task") == {
        "task_id": "task",
        "status": "pending",
    }
    assert store.prepared == [("task", "failed", {"keep": True})]


@pytest.mark.asyncio
async def test_task_rollback_reports_conditional_conflicts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from competitive_app.application.workflow.task_service import TaskService

    class Store:
        async def restore_task_if_current(self, *_args, **_kwargs):
            return False

        async def delete_task_if_current(self, *_args, **_kwargs):
            return False

    service = TaskService(
        store=Store(),
        repo=SimpleNamespace(),
        registry=RuntimeRegistry(),
        harness_factory=SimpleNamespace(),
    )
    with caplog.at_level("WARNING"):
        await service._rollback_task_row("existing", {"task_id": "existing"}, session_id="s")
        await service._rollback_task_row("created", None, session_id="s")
    assert "rollback skipped after concurrent change: existing" in caplog.text
    assert "delete skipped after concurrent change: created" in caplog.text


@pytest.mark.asyncio
async def test_partial_session_metadata_uses_opaque_cleanup() -> None:
    from competitive_app.application.workflow.task_service import TaskService

    removed: list[object] = []

    class Repo:
        async def delete(self, value):
            removed.append(value)

    session = object()
    service = TaskService(
        store=SimpleNamespace(),
        repo=Repo(),
        registry=RuntimeRegistry(),
        harness_factory=SimpleNamespace(),
    )
    await service._cleanup_created_session({"path": "session.jsonl"}, session=session)
    assert removed == [session]
