"""O10 — generic boundary-approval service publication/lifetime; no App dependency.

Source: pi-auto-review@0.3.2 ``service.ts`` ADAPT — generic Pi extension service
publication/lookup. The seam must stay importable from ``packages/agent`` alone
(stdlib only) and must never reference App/sandbox/policy modules.
"""
from __future__ import annotations

import pytest
from earendil_works.pi_agent.boundary_approval import (
    BOUNDARY_BROKER_SERVICE_KEY,
    BoundaryApprovalBrokerService,
    get_boundary_broker,
    publish_boundary_broker,
)


class _FakeBroker:
    def __init__(self) -> None:
        self.reviewed: list[tuple[object, object]] = []
        self.consumed: list[tuple[object, str, str]] = []

    async def review(self, request: object, context: object) -> dict[str, str]:
        self.reviewed.append((request, context))
        return {"kind": "allow"}

    def consumeGrant(self, request: object, session_id: str, token: str) -> bool:
        self.consumed.append((request, session_id, token))
        return token == "good-token"


@pytest.fixture(autouse=True)
def _clean_service_registry():
    from earendil_works.pi_agent import boundary_approval

    boundary_approval._registry.clear()
    yield
    boundary_approval._registry.clear()


def test_publish_and_get_service() -> None:
    broker = _FakeBroker()
    unpublish = publish_boundary_broker(broker)  # type: ignore[arg-type]
    service = get_boundary_broker()
    assert service is not None
    assert isinstance(service, BoundaryApprovalBrokerService)
    unpublish()
    assert get_boundary_broker() is None


def test_double_publish_raises() -> None:
    publish_boundary_broker(_FakeBroker())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="already published"):
        publish_boundary_broker(_FakeBroker())  # type: ignore[arg-type]


def test_unpublish_is_idempotent_and_scoped() -> None:
    broker = _FakeBroker()
    unpublish = publish_boundary_broker(broker)  # type: ignore[arg-type]
    unpublish()
    unpublish()  # second call is a no-op
    assert get_boundary_broker() is None
    # a fresh publication after unpublish works
    publish_boundary_broker(_FakeBroker())  # type: ignore[arg-type]
    assert get_boundary_broker() is not None


@pytest.mark.asyncio
async def test_service_delegates_review_and_consume() -> None:
    broker = _FakeBroker()
    unpublish = publish_boundary_broker(broker)  # type: ignore[arg-type]
    service = get_boundary_broker()
    assert service is not None

    request = {"id": "r1", "surface": "network"}
    context = {"sessionId": "s", "scopeKey": "k"}

    decision = await service.review(request, context)  # type: ignore[arg-type]
    assert decision == {"kind": "allow"}
    assert broker.reviewed == [(request, context)]
    assert service.consumeGrant(request, "s", "good-token") is True
    assert service.consumeGrant(request, "s", "bad-token") is False
    assert broker.consumed == [(request, "s", "good-token"), (request, "s", "bad-token")]
    unpublish()


def test_service_key_is_stable() -> None:
    assert BOUNDARY_BROKER_SERVICE_KEY == "pi-auto-review:boundary-approval-broker"


def test_boundary_approval_module_has_no_app_dependency() -> None:
    """The generic seam must be pure: no App/sandbox/OS imports."""
    import inspect

    import earendil_works.pi_agent.boundary_approval as module

    source = inspect.getsource(module)
    assert "competitive_app" not in source
    assert "subprocess" not in source
    assert "import os" not in source
    assert "import sys" not in source
    assert "import pathlib" not in source
