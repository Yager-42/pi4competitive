"""Poirot audit guard.

Transplant source: HezaoHezao/poirot
Path: poirot/backend/agents/sandbox/guards/audit_guard.py
SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
License: MIT (see deploy/tool-sandbox/licenses/POIROT-MIT.txt)
Host delta: import/package path only; production does not inject a journal (COPY).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ..exceptions import SandboxPermissionError

_logger = logging.getLogger(__name__)

_BLOCK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"rm\s+-rf?\s+/(?!\w)"), "rm -rf /"),
    (re.compile(r"rm\s+-rf?\s+~(?!\w)"), "rm -rf ~"),
    (re.compile(r"rm\s+-rf?\s+\$HOME"), "rm -rf $HOME"),
    (re.compile(r"rm\s+-rf?\s+/\*"), "rm -rf /*"),
    (re.compile(r"mkfs\.\w+"), "mkfs"),
    (re.compile(r"dd\s+.*\bof=/dev/"), "dd to device"),
    (re.compile(r":\s*\(\)\s*\{.*:.*\|.*:.*\}.*;"), "fork bomb"),
]
_WARN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"curl\s+[^|]*\|\s*(bash|sh)\b"), "curl pipe to shell"),
    (re.compile(r"wget\s+[^|]*\|\s*(bash|sh)\b"), "wget pipe to shell"),
    (re.compile(r"\bsudo\b"), "sudo"),
    (re.compile(r"\bchmod\s+777\b"), "chmod 777"),
    (re.compile(r"\beval\b"), "eval"),
    (re.compile(r"\bexec\b(?!\s*\.py)"), "exec builtin"),
]


def _classify(command: str) -> tuple[str, str | None]:
    for pattern, description in _BLOCK_PATTERNS:
        if pattern.search(command):
            return "block", description
    for pattern, description in _WARN_PATTERNS:
        if pattern.search(command):
            return "warn", description
    return "pass", None


class AuditGuard:
    """Command classification and logging around a path/security guard."""

    def __init__(self, inner: Any, journal: Any = None) -> None:
        self._inner = inner
        self._journal = journal

    def validate_path(self, path: str, *, write: bool = False) -> None:
        self._inner.validate_path(path, write=write)

    def validate_command(self, command: str) -> None:
        level, description = _classify(command)
        self._audit(command, level, description)
        if level == "block":
            raise SandboxPermissionError(
                f"dangerous command blocked: {description}",
                path=command[:100],
                operation="validate_command",
            )
        self._inner.validate_command(command)

    def _audit(self, command: str, level: str, description: str | None) -> None:
        message = f"sandbox.command level={level}"
        if description:
            message += f" desc={description}"
        message += f" cmd={command[:100]}"
        if level in ("block", "warn"):
            _logger.warning(message)
        else:
            _logger.debug(message)
        if self._journal is not None:
            try:
                self._journal.append(
                    "sandbox.command",
                    {"level": level, "desc": description or "", "command": command[:200]},
                )
            except Exception:  # noqa: BLE001
                pass


__all__ = ["AuditGuard"]
