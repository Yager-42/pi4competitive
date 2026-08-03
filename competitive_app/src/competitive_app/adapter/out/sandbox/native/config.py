"""Strict pi-sandbox trusted configuration parser (COPY-semantics).

Source: pi-sandbox@0.4.2 ``src/config.ts``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta:
- The accepted schema omits the ``subagents`` and ``hostIPC`` product
  sections (G0 map §2.1: "omit Host IPC/subagent product fields from
  accepted native schema"). Supplying either key fails validation with a
  "not supported" error instead of silently accepting or pretending
  support (same rule as the SRT port's unsupported fields).
- File loading (``getPiSandboxConfigPath``/``loadPiSandboxConfig`` over
  ``~/.pi``) is omitted: the App owns trusted configuration loading and
  passes the parsed value through the wiring channel. ``parse_*`` and
  defaults preserve upstream strictness exactly.
- ``[...new Set(...)]`` deduplication preserved.
"""
from __future__ import annotations

from typing import NotRequired, TypedDict


class FilesystemConfig(TypedDict):
    additionalAllowRead: list[str]


class PiSandboxConfig(TypedDict):
    filesystem: FilesystemConfig


DEFAULT_PI_SANDBOX_CONFIG: PiSandboxConfig = {
    "filesystem": {"additionalAllowRead": []},
}

_NOT_SUPPORTED_SECTIONS = ("subagents", "hostIPC")


def _is_record(value: object) -> bool:
    return isinstance(value, dict)


def _reject_unknown_keys(
    value: dict[str, object],
    allowed: list[str],
    location: str,
) -> None:
    unknown = [key for key in value if key not in allowed]
    if unknown:
        raise ValueError(
            "invalid pi-sandbox configuration: unknown "
            f"{location} {'key' if len(unknown) == 1 else 'keys'}: "
            f"{', '.join(unknown)}"
        )


def parse_pi_sandbox_config(value: object) -> PiSandboxConfig:
    """Parse and strictly validate a trusted pi-sandbox config value.

    Raises ``ValueError`` on any unknown, malformed, or unsupported field.
    """
    if not _is_record(value):
        raise ValueError(
            "invalid pi-sandbox configuration: root must be an object"
        )
    for section in _NOT_SUPPORTED_SECTIONS:
        if section in value:
            raise ValueError(
                f"invalid pi-sandbox configuration: {section} is not "
                "supported in the native sandbox schema"
            )
    _reject_unknown_keys(value, ["filesystem"], "root")

    if "filesystem" in value and not _is_record(value["filesystem"]):
        raise ValueError(
            "invalid pi-sandbox configuration: filesystem must be an object"
        )
    filesystem = value.get("filesystem") or {}
    _reject_unknown_keys(filesystem, ["additionalAllowRead"], "filesystem")

    additional_allow_read = filesystem.get(
        "additionalAllowRead",
        DEFAULT_PI_SANDBOX_CONFIG["filesystem"]["additionalAllowRead"],
    )
    if not isinstance(additional_allow_read, list) or any(
        not isinstance(path, str)
        or path.strip() == ""
        or not path.startswith("/")
        for path in additional_allow_read
    ):
        raise ValueError(
            "invalid pi-sandbox configuration: "
            "filesystem.additionalAllowRead must be an array of "
            "absolute paths"
        )

    return {
        "filesystem": {
            "additionalAllowRead": list(dict.fromkeys(additional_allow_read)),
        },
    }


def default_pi_sandbox_config() -> PiSandboxConfig:
    return {
        "filesystem": {
            "additionalAllowRead": [
                *DEFAULT_PI_SANDBOX_CONFIG["filesystem"]["additionalAllowRead"],
            ],
        },
    }


__all__ = [
    "DEFAULT_PI_SANDBOX_CONFIG",
    "FilesystemConfig",
    "PiSandboxConfig",
    "default_pi_sandbox_config",
    "parse_pi_sandbox_config",
]
