"""O1 — strict pi-sandbox config parsing (PORT of config.test.ts).

Source: pi-sandbox@0.4.2 ``config.test.ts``
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta: the ``subagents``/``hostIPC`` sections are rejected as "not
supported" (G0 §2.1), so the upstream provider/host-IPC acceptance vectors
become negative vectors here.
"""
from __future__ import annotations

import pytest

from competitive_app.adapter.out.sandbox.native.config import (
    default_pi_sandbox_config,
    parse_pi_sandbox_config,
)


def test_defaults_omitted_sections() -> None:
    assert parse_pi_sandbox_config({}) == {
        "filesystem": {"additionalAllowRead": []}
    }
    assert parse_pi_sandbox_config({"filesystem": {}}) == {
        "filesystem": {"additionalAllowRead": []}
    }
    assert default_pi_sandbox_config() == {"filesystem": {"additionalAllowRead": []}}


def test_accepts_unique_absolute_additional_read_paths() -> None:
    assert parse_pi_sandbox_config(
        {
            "filesystem": {
                "additionalAllowRead": [
                    "/home/user/.local/bin/rtk",
                    "/home/user/.local/bin/rtk",
                    "/opt/tools/helper",
                ],
            },
        }
    ) == {
        "filesystem": {
            "additionalAllowRead": [
                "/home/user/.local/bin/rtk",
                "/opt/tools/helper",
            ]
        }
    }


def test_rejects_unsafe_additional_read_path_shapes() -> None:
    for bad in ["not-an-array", ["relative/path"], [""], [42]]:
        with pytest.raises(
            ValueError, match=r"additionalAllowRead must be an array of absolute paths"
        ):
            parse_pi_sandbox_config({"filesystem": {"additionalAllowRead": bad}})


def test_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match=r"unknown filesystem key: allowWrite"):
        parse_pi_sandbox_config(
            {"filesystem": {"additionalAllowRead": [], "allowWrite": ["/tmp"]}}
        )
    with pytest.raises(ValueError, match=r"unknown root key: provider"):
        parse_pi_sandbox_config({"provider": "off"})


def test_rejects_non_object_sections() -> None:
    with pytest.raises(ValueError, match=r"filesystem must be an object"):
        parse_pi_sandbox_config({"filesystem": []})
    with pytest.raises(ValueError, match=r"filesystem must be an object"):
        parse_pi_sandbox_config({"filesystem": None})
    with pytest.raises(ValueError, match=r"root must be an object"):
        parse_pi_sandbox_config([])
    with pytest.raises(ValueError, match=r"root must be an object"):
        parse_pi_sandbox_config(None)


def test_subagents_and_host_ipc_are_not_supported() -> None:
    """G0 §2.1: Host IPC/subagent product fields are omitted from the
    accepted native schema; supplying them fails, never silently weakens."""
    for section, value in [
        ("subagents", {"provider": "builtin"}),
        ("subagents", {"provider": "off"}),
        ("hostIPC", {"mode": "off"}),
        ("hostIPC", {"mode": "ask", "preflightCommandPrefixes": ["tmux"]}),
    ]:
        with pytest.raises(ValueError, match=f"{section} is not supported"):
            parse_pi_sandbox_config({section: value})
