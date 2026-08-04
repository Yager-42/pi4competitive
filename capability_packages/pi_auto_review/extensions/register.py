"""pi_auto_review extension entry (NEW-HOST, ``src/index.ts`` registration split).

Source: pi-auto-review@0.3.2 ``src/index.ts`` (extension registration portion)
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: MIT (retained under the native sandbox license directory)

Host delta (ADAPT):
- ``register(pi)`` is the local capability entry loaded by the package manager;
  the capability's importable subpackage is bootstrapped onto ``sys.path`` once
  (loader imports one entry ``.py`` per capability; siblings are not importable
  otherwise).
- Per-session broker lifecycle mirrors upstream ``session_start`` /
  ``session_shutdown``: trusted config per session cwd, broker creation,
  publication of the generic boundary-broker service
  (``pi_agent.boundary_approval``), and cleanup on shutdown. Failure at any
  step disables the session's broker and fails closed (no service published).
- The reviewer's host dependencies (model registry, transcript entries, session
  id, session signal, audit sink) are injected by App wiring through
  ``bind_runtime(...)`` — explicit DI, never global-singleton guessing.
  Absent dependencies make the reviewer raise, which the broker converts to a
  deny.
- Permission-system authorizer, TUI ``/approve`` command, auto-confirm and
  user-feedback UI are OMIT per G0 map §3.1.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextvars import ContextVar
from collections.abc import Callable
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pi_auto_review import (
    create_reviewer_broker,
    load_config,
    session_config,
    validate_config,
)
from pi_auto_review.reviewer import Config

logger = logging.getLogger("pi_auto_review")

# Keep host dependencies scoped to the current extension-loading context.  A
# process-global dictionary could leak one session's model/transcript callbacks
# into another concurrently loaded harness.
_RUNTIME: ContextVar[dict[str, Any] | None] = ContextVar(
    "pi_auto_review_runtime", default=None
)


def bind_runtime(
    *,
    model_registry: Any = None,
    entries_provider: Callable[[], list[Any]] | None = None,
    session_id_provider: Callable[[], str] | None = None,
    signal_provider: Callable[[], Any] | None = None,
    audit: Callable[[Any], None] | None = None,
) -> Callable[[], None]:
    """Bind reviewer host surfaces and return a cleanup callback.

    Bindings are context-local and replacement-safe.  Host wiring should invoke
    the returned callback when its owning extension/session is torn down.
    """
    values = dict(_RUNTIME.get() or {})
    if model_registry is not None:
        values["model_registry"] = model_registry
    if entries_provider is not None:
        values["entries_provider"] = entries_provider
    if session_id_provider is not None:
        values["session_id_provider"] = session_id_provider
    if signal_provider is not None:
        values["signal_provider"] = signal_provider
    if audit is not None:
        values["audit"] = audit
    token = _RUNTIME.set(values)

    def cleanup() -> None:
        try:
            _RUNTIME.reset(token)
        except ValueError:
            # ContextVar tokens cannot be reset from a different context.
            _RUNTIME.set(None)

    return cleanup


def _unbind_runtime() -> None:
    _RUNTIME.set(None)


def _runtime_values() -> dict[str, Any]:
    return _RUNTIME.get() or {}


def _registry(ctx: Any | None = None) -> Any:
    registry = _runtime_values().get("model_registry")
    if registry is None and ctx is not None:
        registry = getattr(ctx, "modelRegistry", None)
    if registry is None:
        raise ValueError("pi-auto-review model registry is not bound")
    return registry


def _entries(ctx: Any) -> list[Any]:
    provider = _runtime_values().get("entries_provider")
    if provider is not None:
        entries = provider()
        if asyncio.iscoroutine(entries):
            raise RuntimeError("entries_provider must return a synchronous snapshot")
        return list(entries)
    manager = getattr(ctx, "sessionManager", None)
    build = getattr(manager, "build_context", None)
    if build is None:
        return []
    try:
        context = build()
        if asyncio.iscoroutine(context):
            context.close()
            raise RuntimeError("async session context requires an entries_provider")
        return [{"message": message} for message in (context.get("messages") or [])]
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001
        return []


def _session_id(ctx: Any) -> str:
    provider = _runtime_values().get("session_id_provider")
    if provider is not None:
        return provider()
    manager = getattr(ctx, "sessionManager", None)
    get_id = getattr(manager, "get_session_id", None) or getattr(manager, "session_id", None)
    if callable(get_id):
        try:
            return str(get_id())
        except Exception:  # noqa: BLE001
            return ""
    return str(get_id or "")


def _signal(ctx: Any) -> Any:
    provider = _runtime_values().get("signal_provider")
    if provider is not None:
        return provider()
    return getattr(ctx, "signal", None)


def _audit() -> Callable[[Any], None] | None:
    return _runtime_values().get("audit")


def create_pi_auto_review_extension(
    options: dict[str, Any] | None = None,
) -> Callable[[Any], None]:
    """Return the ``(pi: ExtensionAPI) -> None`` installer (upstream factory)."""
    options = options or {}
    allow_untrusted = bool(
        options.get("allowUntrustedWorkspace")
        or os.environ.get("PI_AUTO_REVIEW_ALLOW_UNTRUSTED_DEV") == "1"
    )
    trusted: Config = (
        validate_config(options["config"], "trusted config")
        if "config" in options
        else load_config()
    )

    def install(pi: Any) -> None:
        broker: Any = None
        unpublish: Callable[[], None] | None = None
        trusted_config = trusted

        def on_session_start(event: dict[str, Any], ctx: Any) -> None:
            nonlocal broker, unpublish
            if unpublish is not None:
                unpublish()
                unpublish = None
            if broker is not None:
                broker.clear()
                broker = None
            try:
                session_conf = session_config(
                    str(ctx.cwd), trusted_config, allow_untrusted
                )
                registry = _registry(ctx)
                broker = create_reviewer_broker(
                    registry,
                    session_conf,
                    entries_provider=lambda: _entries(ctx),
                    session_id_provider=lambda: _session_id(ctx),
                    signal_provider=lambda: _signal(ctx),
                    audit=_audit(),
                )
                from earendil_works.pi_agent.boundary_approval import publish_boundary_broker

                unpublish = publish_boundary_broker(broker)
                logger.debug("pi-auto-review broker active for session")
            except Exception as error:  # noqa: BLE001
                if broker is not None:
                    broker.clear()
                    broker = None
                unpublish = None
                logger.error("pi-auto-review: session disabled: %s", error)

        def on_session_shutdown(event: dict[str, Any], ctx: Any) -> None:
            nonlocal broker, unpublish
            if unpublish is not None:
                unpublish()
                unpublish = None
            if broker is not None:
                broker.clear()
                broker = None

        pi.on("session_start", on_session_start)
        pi.on("session_shutdown", on_session_shutdown)

    return install


def register(pi: Any) -> None:
    """Local capability entry: install the boundary-approval extension."""
    create_pi_auto_review_extension()(pi)


__all__ = [
    "bind_runtime",
    "create_pi_auto_review_extension",
    "register",
]
