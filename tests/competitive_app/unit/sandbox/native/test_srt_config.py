"""O11 — SRT config validation golden vectors (sandbox-config.ts strict subset).

Source parity: sandbox-runtime@0.0.67 ``test/config-validation.test.ts`` (PORT)
License: Apache-2.0 (retained under the native sandbox license directory)
"""
from __future__ import annotations

import pytest

from competitive_app.adapter.out.sandbox.native.srt.policy import (
    DomainConfigError,
    deep_clone_config,
    validate_sandbox_runtime_config,
)


def _valid_config() -> dict:
    return {
        "filesystem": {
            "denyRead": ["/Users/me/private"],
            "allowRead": ["/Users/me/work"],
            "allowWrite": ["/Users/me/work"],
            "denyWrite": ["/Users/me/work/.env"],
            "allowGitConfig": True,
        },
        "network": {
            "allowedDomains": ["api.github.com", "*.npmjs.org"],
            "deniedDomains": [],
        },
    }


def test_valid_erichll_shape_accepted() -> None:
    cfg = validate_sandbox_runtime_config(_valid_config())
    assert cfg["filesystem"]["allowGitConfig"] is True
    assert cfg["network"]["allowedDomains"] == [
        "api.github.com",
        "*.npmjs.org",
    ]
    assert "strictAllowlist" not in cfg["network"]


def test_deep_clone_roundtrip() -> None:
    cfg = validate_sandbox_runtime_config(_valid_config())
    clone = deep_clone_config(cfg)
    assert clone == cfg
    clone["network"]["allowedDomains"].append("x.com")
    assert cfg["network"]["allowedDomains"] == [
        "api.github.com",
        "*.npmjs.org",
    ]


@pytest.mark.parametrize(
    "pattern",
    [
        "*",  # bare wildcard only valid in deniedDomains
        "*.com",  # too broad: single part after wildcard
        "*.example.com.",  # trailing dot
        "*.x.y.",  # trailing dot
        ".example.com",  # leading dot
        "example.com.",  # trailing dot
        "example",  # no dot
        "http://example.com",  # protocol
        "example.com/path",  # path
        "example.com:8080",  # port
        "*x.com",  # wildcard in middle
        "sub.*.com",  # wildcard in middle
    ],
)
def test_invalid_domain_patterns_rejected(pattern: str) -> None:
    with pytest.raises(DomainConfigError, match="domain pattern"):
        validate_sandbox_runtime_config(
            {"network": {"allowedDomains": [pattern], "deniedDomains": []}}
        )


def test_localhost_and_wildcard_accepted() -> None:
    cfg = validate_sandbox_runtime_config(
        {
            "network": {
                "allowedDomains": ["localhost", "*.example.com"],
                "deniedDomains": ["*", "blocked.example.com"],
            }
        }
    )
    assert cfg["network"]["allowedDomains"] == ["localhost", "*.example.com"]
    assert cfg["network"]["deniedDomains"] == ["*", "blocked.example.com"]


@pytest.mark.parametrize(
    "field",
    [
        "credentials",
        "enableWeakerNestedSandbox",
        "enableWeakerNetworkIsolation",
        "windows",
    ],
)
def test_unsupported_top_level_fields_fail(field: str) -> None:
    with pytest.raises(DomainConfigError, match="not supported"):
        validate_sandbox_runtime_config({**{"network": {"allowedDomains": [], "deniedDomains": []}}, field: {}})


@pytest.mark.parametrize(
    "field",
    ["mitmProxy", "filterRequest", "tlsTerminate", "parentProxy"],
)
def test_unsupported_network_fields_fail(field: str) -> None:
    with pytest.raises(DomainConfigError, match="not supported"):
        validate_sandbox_runtime_config(
            {"network": {"allowedDomains": [], "deniedDomains": [], field: {}}}
        )


def test_allow_all_unix_sockets_true_rejected() -> None:
    with pytest.raises(DomainConfigError, match="weakening switch"):
        validate_sandbox_runtime_config(
            {
                "network": {
                    "allowedDomains": [],
                    "deniedDomains": [],
                    "allowAllUnixSockets": True,
                }
            }
        )


def test_allow_all_unix_sockets_false_accepted() -> None:
    cfg = validate_sandbox_runtime_config(
        {
            "network": {
                "allowedDomains": [],
                "deniedDomains": [],
                "allowAllUnixSockets": False,
            }
        }
    )
    assert cfg["network"]["allowAllUnixSockets"] is False


@pytest.mark.parametrize(
    "data",
    [
        {"network": {"allowedDomains": "not-a-list", "deniedDomains": []}},
        {"network": {"allowedDomains": [1], "deniedDomains": []}},
        {"network": {"allowedDomains": [], "deniedDomains": [], "strictAllowlist": "yes"}},
        {"network": {"allowedDomains": [], "deniedDomains": [], "httpProxyPort": 0}},
        {"network": {"allowedDomains": [], "deniedDomains": [], "httpProxyPort": 65536}},
        {"network": {"allowedDomains": [], "deniedDomains": [], "socksProxyPort": 1.5}},
        {"filesystem": {"denyRead": [], "allowWrite": [], "denyWrite": [""]}},
        {"filesystem": {"denyRead": [], "allowWrite": "x", "denyWrite": []}},
        {"mandatoryDenySearchDepth": 0},
        {"mandatoryDenySearchDepth": 11},
        {"allowAppleEvents": "yes"},
        {"ripgrep": {"command": ""}},
        {"ripgrep": {"args": "x"}},
        {"seccomp": {"argv0": "srt"}},  # argv0 requires applyPath
        {"bwrapPath": "relative/path"},
        {"socatPath": ""},
        {"git": {"safeDirectories": [""]}},
        {"ignoreViolations": {"cmd": "not-a-list"}},
        {"allowMachLookup": ["a*b"]} if False else {"network": {"allowedDomains": [], "deniedDomains": [], "allowMachLookup": ["com.example.*x"]}},
    ],
)
def test_invalid_shapes_rejected(data: dict) -> None:
    with pytest.raises(DomainConfigError):
        validate_sandbox_runtime_config(data)


def test_unknown_keys_rejected() -> None:
    with pytest.raises(DomainConfigError, match="unknown root field"):
        validate_sandbox_runtime_config(
            {"filesystem": {"denyRead": [], "allowWrite": [], "denyWrite": []}, "bogus": 1}
        )
    with pytest.raises(DomainConfigError, match="unknown network field"):
        validate_sandbox_runtime_config(
            {"network": {"allowedDomains": [], "deniedDomains": [], "bogus": 1}}
        )
    with pytest.raises(DomainConfigError, match="unknown filesystem field"):
        validate_sandbox_runtime_config(
            {"filesystem": {"denyRead": [], "allowWrite": [], "denyWrite": [], "bogus": 1}}
        )
    with pytest.raises(DomainConfigError, match="unknown ripgrep field"):
        validate_sandbox_runtime_config(
            {
                "network": {"allowedDomains": [], "deniedDomains": []},
                "ripgrep": {"command": "rg", "bogus": 1},
            }
        )


def test_allow_mach_lookup_wildcard_rules() -> None:
    ok = validate_sandbox_runtime_config(
        {
            "network": {
                "allowedDomains": [],
                "deniedDomains": [],
                "allowMachLookup": ["2BUA8C4S2C.com.1password.*", "*"],
            }
        }
    )
    assert ok["network"]["allowMachLookup"] == [
        "2BUA8C4S2C.com.1password.*",
        "*",
    ]
    with pytest.raises(DomainConfigError, match="trailing"):
        validate_sandbox_runtime_config(
            {
                "network": {
                    "allowedDomains": [],
                    "deniedDomains": [],
                    "allowMachLookup": ["com.*.example"],
                }
            }
        )


def test_seccomp_apply_path_must_be_absolute() -> None:
    with pytest.raises(DomainConfigError, match="absolute"):
        validate_sandbox_runtime_config(
            {
                "network": {"allowedDomains": [], "deniedDomains": []},
                "seccomp": {"applyPath": "vendor/seccomp/x64/apply-seccomp"},
            }
        )
    cfg = validate_sandbox_runtime_config(
        {
            "network": {"allowedDomains": [], "deniedDomains": []},
            "seccomp": {"applyPath": "/opt/srt/apply-seccomp"},
        }
    )
    assert cfg["seccomp"]["applyPath"] == "/opt/srt/apply-seccomp"


def test_optional_fields_roundtrip() -> None:
    cfg = validate_sandbox_runtime_config(
        {
            "network": {"allowedDomains": [], "deniedDomains": []},
            "allowAppleEvents": True,
            "allowPty": True,
            "mandatoryDenySearchDepth": 5,
            "ripgrep": {"command": "rg", "args": ["--no-config"]},
            "seccomp": {"applyPath": "/x", "argv0": "srt-seccomp"},
            "bwrapPath": "/usr/bin/bwrap",
            "socatPath": "/usr/bin/socat",
            "git": {"safeDirectories": ["/repo"]},
            "ignoreViolations": {"*": ["/tmp/cache"], "npm": ["/tmp/npm"]},
        }
    )
    assert cfg["mandatoryDenySearchDepth"] == 5
    assert cfg["ripgrep"]["args"] == ["--no-config"]
    assert cfg["seccomp"] == {"applyPath": "/x", "argv0": "srt-seccomp"}
    assert cfg["ignoreViolations"] == {
        "*": ["/tmp/cache"],
        "npm": ["/tmp/npm"],
    }
