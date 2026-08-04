"""Observability out adapter: run-level journal (COPY from poirot journal).

Host additions (non-copied): journal event whitelist + guarded append
(feature llm-fallback-observability-v1 B9/B10) and secret redaction.
"""

from __future__ import annotations

import re
import logging
from typing import Any

from competitive_app.adapter.out.observability.events import RunEvent, utc_now_iso
from competitive_app.adapter.out.observability.run_journal import RunJournal

logger = logging.getLogger(__name__)

# B10 事件白名单（feature §3.3）：未知事件类型拒绝 + 告警，不落盘。
JOURNAL_EVENT_TYPES = frozenset(
    {
        "agent.started",
        "agent.finished",
        "llm.request",
        "llm.response",
        "llm.fallback_start",
        "llm.fallback_switch",
        "llm.fallback_exhausted",
        "tool.called",
        "tool.finished",
        "budget",
        "skill.select",
        "skill.apply",
        "help.requested",
        "help.exhausted",
        "report.generated",
        "trace.span",
    }
)
JOURNAL_EVENT_PREFIXES = ("compaction.", "task.")


def is_journal_event_allowed(event_type: str) -> bool:
    return event_type in JOURNAL_EVENT_TYPES or event_type.startswith(JOURNAL_EVENT_PREFIXES)


# B9 脱敏黑名单：密钥/凭据/Authorization 头永不落 journal。
_REDACT_KEYS = frozenset(
    {
        "apikey",
        "api_key",
        "authorization",
        "auth",
        "credential",
        "credentials",
        "password",
        "passwd",
        "secret",
        "token",
        "private_key",
        "access_key",
    }
)
_REDACTED = "[REDACTED]"


def _is_redacted_key(key: str) -> bool:
    """Recognize credential keys across snake/camel/kebab/header conventions."""
    raw = str(key)
    words = re.findall(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[0-9]+", raw)
    normalized_words = [word.lower() for word in words]
    compact = "".join(normalized_words)
    compact_lower = re.sub(r"[^a-z0-9]", "", raw.lower())
    if any(marker in compact_lower for marker in ("authorization", "secret", "password", "passwd", "credential")):
        return True
    # ``max_tokens`` is ordinary model metadata; only redact a singular token
    # key when it is a distinct separator-delimited word.
    if re.search(r"(?:^|[^a-z])token(?:$|[^a-z])", raw.lower()):
        return True
    if compact in _REDACT_KEYS or compact in {
        "apikey", "accesstoken", "refreshtoken", "privatekey", "clientsecret",
    }:
        return True
    credential_words = {
        "key", "token", "secret", "password", "passwd", "credential",
        "credentials", "authorization", "auth",
    }
    return any(word in credential_words for word in normalized_words)


def redact_payload(payload: Any, _seen: set[int] | None = None) -> Any:
    """深拷贝并脱敏（密钥/凭据键值替换为 [REDACTED]）。"""
    if _seen is None:
        _seen = set()
    if isinstance(payload, dict):
        if id(payload) in _seen:
            return _REDACTED
        _seen.add(id(payload))
        out: dict[str, Any] = {}
        for key, value in payload.items():
            if _is_redacted_key(key):
                out[key] = _REDACTED
            else:
                out[key] = redact_payload(value, _seen)
        return out
    if isinstance(payload, list):
        return [redact_payload(item, _seen) for item in payload]
    if isinstance(payload, tuple):
        return tuple(redact_payload(item, _seen) for item in payload)
    return payload


def guarded_append(journal: RunJournal, event_type: str, payload: dict[str, Any] | None = None) -> bool:
    """白名单 + 脱敏 + 落盘失败不阻断（B4/B9/B10）。返回是否落盘。"""
    if not is_journal_event_allowed(event_type):
        logger.warning("journal: unknown event type rejected: %s", event_type)
        return False
    try:
        journal.append(event_type, redact_payload(payload or {}))
        return True
    except Exception:
        logger.warning("journal append failed: %s", event_type, exc_info=True)
        return False


__all__ = [
    "JOURNAL_EVENT_PREFIXES",
    "JOURNAL_EVENT_TYPES",
    "RunEvent",
    "RunJournal",
    "guarded_append",
    "is_journal_event_allowed",
    "redact_payload",
    "utc_now_iso",
]
