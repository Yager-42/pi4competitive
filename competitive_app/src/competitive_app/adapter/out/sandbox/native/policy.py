"""Default sandbox policy builder — secret write denials + runtime config
(ADAPT).

Source: pi-sandbox@0.4.2 ``src/policy.ts``
Repository: erichll/pi-packages @ 10c8eeb8269ee478ff7383c7e6139301aa9665f9
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta (roots):
- ``PACKAGE_ROOT`` (upstream: pi-sandbox package dir) -> the native
  sandbox package dir.
- ``NODE_INSTALL_ROOT`` (upstream: Node install root) ->
  ``sys.prefix`` (the Python interpreter prefix).
- ``SANDBOX_RUNTIME_ROOT`` (upstream: SRT package dir) -> the native
  package dir (where ``srt/`` lives).
- ``dirname(process.execPath)`` (node bin dir) -> ``dirname(sys.executable)``
  (interpreter bin dir); host delta (macOS V3 gate): the interpreter's FULL
  symlink chain (intermediate link dirs + final binary/base dirs) is
  additionally read-allowed because venv binaries symlink into a base
  install that may live under the denied home.
- ``homedir()`` -> ``Path.home()``; ``resolve``/``join``/``parse`` keep
  POSIX semantics (no Windows branches — native scope is Linux/macOS).
- Workspace walk uses ``os.scandir`` (bounded, ``WORKSPACE_SECRET_SCAN_MAX_DEPTH``
  preserved); macOS globs identical.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, TypedDict

PACKAGE_ROOT = Path(__file__).resolve().parent
INTERPRETER_ROOT = Path(sys.prefix)
SANDBOX_RUNTIME_ROOT = PACKAGE_ROOT
INTERPRETER_BIN_DIR = Path(sys.executable).parent
# venv interpreter binaries are symlinks into a base install that often
# lives under the user home (uv/pyenv). Seatbelt evaluates each symlink hop
# as it is traversed, so denyRead=home blocks the worker exec unless the
# whole chain (intermediate link dirs AND the final binary/base dirs) is
# read-allowable (macOS V3 gate).
INTERPRETER_BIN_DIR_RESOLVED = Path(os.path.realpath(sys.executable)).parent
INTERPRETER_BASE_ROOT = Path(os.path.realpath(sys.executable)).parent.parent


def _interpreter_symlink_chain_roots() -> list[str]:
    """Distinct dirs the interpreter binary is reachable through.

    Walks the symlink chain one hop at a time (``resolve()`` collapses all
    hops, but Seatbelt evaluates every intermediate link path), then adds
    the final binary dir and base prefix. Empty when the interpreter is a
    real binary (no venv indirection).
    """
    roots: list[str] = []
    seen: set[str] = set()
    current = sys.executable
    for _ in range(32):
        if not os.path.islink(current):
            break
        target = os.path.normpath(
            os.path.join(os.path.dirname(current), os.readlink(current))
        )
        hop_dir = os.path.dirname(target)
        if hop_dir not in seen:
            seen.add(hop_dir)
            roots.append(hop_dir)
        current = target
    final = os.path.realpath(sys.executable)
    for root in (os.path.dirname(final), os.path.dirname(os.path.dirname(final))):
        if root not in seen:
            seen.add(root)
            roots.append(root)
    return roots

WORKSPACE_SECRET_DENY_WRITE_BASENAMES = [
    ".env",
    ".env.local",
    ".env.development",
    ".env.development.local",
    ".env.test",
    ".env.test.local",
    ".env.production",
    ".env.production.local",
    ".env.staging",
    ".env.staging.local",
    ".env.ci",
    # Linux bwrap cannot express extension globs for newly-created files;
    # deny the common root-level variants as concrete mount targets.
    ".env.preview",
    "server.key",
    "cert.pem",
]

WORKSPACE_SECRET_DENY_WRITE_DIRECTORIES = ["secrets", ".secrets"]

WORKSPACE_SECRET_DENY_WRITE_EXTENSIONS = [".pem", ".key", ".p12", ".pfx"]

WORKSPACE_SECRET_TEMPLATE_BASENAMES = frozenset(
    [".env.example", ".env.sample", ".env.template", ".env.dist"]
)

WALK_SKIP_DIRECTORIES = frozenset(
    [
        ".git",
        "node_modules",
        "dist",
        "build",
        "coverage",
        ".next",
        ".turbo",
        ".cache",
        "target",
        "vendor",
    ]
)

WORKSPACE_SECRET_SCAN_MAX_DEPTH = 4

DARWIN_SECRET_DENY_WRITE_GLOBS = [
    "**/.env",
    "**/.env.*",
    "**/.env.local",
    "**/.env.development",
    "**/.env.development.local",
    "**/.env.test",
    "**/.env.test.local",
    "**/.env.production",
    "**/.env.production.local",
    "**/.env.staging",
    "**/.env.staging.local",
    "**/.env.ci",
    "**/secrets",
    "**/secrets/**",
    "**/.secrets",
    "**/.secrets/**",
    "**/*.pem",
    "**/*.key",
    "**/*.p12",
    "**/*.pfx",
]


class SandboxPolicyFilesystem(TypedDict):
    denyRead: list[str]
    allowRead: list[str]
    allowWrite: list[str]
    denyWrite: list[str]


class SandboxPolicyNetwork(TypedDict):
    allowedDomains: list[str]
    deniedDomains: list[str]
    allowLocalBinding: bool
    allowAllUnixSockets: bool
    allowUnixSockets: list[str]


class SandboxPolicy(TypedDict):
    filesystem: SandboxPolicyFilesystem
    network: SandboxPolicyNetwork


def is_secret_deny_write_basename(name: str) -> bool:
    """True when *name* is a secret file basename (sparing templates)."""
    if name in WORKSPACE_SECRET_TEMPLATE_BASENAMES:
        return False
    if name in WORKSPACE_SECRET_DENY_WRITE_BASENAMES:
        return True
    # Catch less common variants such as `.env.preview` while sparing templates.
    if name.startswith(".env."):
        return True
    lower = name.lower()
    return any(lower.endswith(ext) for ext in WORKSPACE_SECRET_DENY_WRITE_EXTENSIONS)


def _collect_nested_secret_deny_write_paths(
    workspace: str, max_depth: int = WORKSPACE_SECRET_SCAN_MAX_DEPTH
) -> list[str]:
    discovered: list[str] = []

    def visit(directory: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        for entry in entries:
            if entry.name in (".", ".."):
                continue
            full_path = os.path.join(directory, entry.name)
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
                if entry.is_symlink():
                    continue
            except OSError:
                continue
            if is_dir:
                if entry.name in WALK_SKIP_DIRECTORIES:
                    continue
                if entry.name in WORKSPACE_SECRET_DENY_WRITE_DIRECTORIES:
                    discovered.append(full_path)
                    continue
                visit(full_path, depth + 1)
                continue
            if is_file and is_secret_deny_write_basename(entry.name):
                discovered.append(full_path)

    visit(workspace, 0)
    return discovered


def create_workspace_secret_deny_write_paths(
    workspace: str,
    platform: str = sys.platform,
) -> list[str]:
    """Workspace secret write denials: root-level basenames/directories
    (absolute, so Linux blocks existing files and first-time creation),
    nested existing secrets from a shallow scan, and Darwin-only globs."""
    root = os.path.realpath(os.path.abspath(workspace))
    paths = [os.path.join(root, name) for name in WORKSPACE_SECRET_DENY_WRITE_BASENAMES]
    paths += [
        os.path.join(root, name) for name in WORKSPACE_SECRET_DENY_WRITE_DIRECTORIES
    ]
    for discovered in _collect_nested_secret_deny_write_paths(root):
        paths.append(discovered)
    if platform == "darwin":
        paths.extend(DARWIN_SECRET_DENY_WRITE_GLOBS)
    return list(dict.fromkeys(paths))


def create_default_policy(
    cwd: str,
    additional_allow_read: list[str] | None = None,
) -> SandboxPolicy:
    """Default policy for *cwd*: workspace read/write, home read-deny,
    interpreter/native roots + git config read-allow, protected config
    write-denials, secret deny paths, network fully closed."""
    workspace = os.path.realpath(os.path.abspath(cwd))
    home = os.path.realpath(os.path.expanduser("~"))
    deny_read: list[str] = [] if home == os.path.dirname(home) else [home]
    package_relative = os.path.relpath(PACKAGE_ROOT, workspace)
    package_is_in_workspace = package_relative == "." or (
        not package_relative.startswith("..") and not os.path.isabs(package_relative)
    )
    extra = list(additional_allow_read or [])
    return {
        "filesystem": {
            "denyRead": deny_read,
            "allowRead": [
                workspace,
                str(INTERPRETER_ROOT),
                *(_interpreter_symlink_chain_roots()),
                str(SANDBOX_RUNTIME_ROOT),
                os.path.join(home, ".gitconfig"),
                os.path.join(home, ".config", "git", "config"),
                "/dev/null",
                *extra,
            ],
            "allowWrite": [workspace, "/dev/null"],
            "denyWrite": [
                os.path.join(workspace, "approved_tools.json"),
                os.path.join(workspace, ".pi", "settings.json"),
                os.path.join(workspace, ".pi", "sandbox.json"),
                os.path.join(workspace, ".pi", "pi-auto-review.json"),
                os.path.join(home, ".pi", "agent", "settings.json"),
                os.path.join(home, ".pi", "agent", "permissions.json"),
                os.path.join(home, ".pi", "agent", "sandbox.json"),
                # Legacy config path kept write-protected during migration.
                os.path.join(home, ".pi", "agent", "pi-sandbox.json"),
                os.path.join(home, ".pi", "agent", "logs"),
                # Prevent the sandbox from installing or rewriting trusted
                # extensions (includes ~/.pi/agent/extensions/pi-sandbox/config.json).
                os.path.join(home, ".pi", "agent", "extensions"),
                os.path.join(
                    home, ".pi", "agent", "extensions", "pi-sandbox", "config.json"
                ),
                *( [] if package_is_in_workspace else [str(PACKAGE_ROOT)] ),
                str(INTERPRETER_BIN_DIR),
                *create_workspace_secret_deny_write_paths(workspace),
                # Linux bwrap cannot enforce wildcard denyWrite paths; keep
                # the rules explicit so manager initialization fails closed
                # instead of silently allowing arbitrary new secret files.
                *(DARWIN_SECRET_DENY_WRITE_GLOBS if sys.platform == "linux" else []),
            ],
        },
        "network": {
            "allowedDomains": [],
            "deniedDomains": [],
            "allowLocalBinding": False,
            "allowAllUnixSockets": False,
            "allowUnixSockets": [],
        },
    }


def to_sandbox_runtime_config(policy: SandboxPolicy) -> dict[str, Any]:
    """Translate a :class:`SandboxPolicy` to the SRT runtime config shape
    (SRT ``SandboxRuntimeConfig`` subset accepted by the Python manager)."""
    return {
        "filesystem": {
            "denyRead": [*policy["filesystem"]["denyRead"]],
            "allowRead": [*policy["filesystem"]["allowRead"]],
            "allowWrite": [*policy["filesystem"]["allowWrite"]],
            "denyWrite": [*policy["filesystem"]["denyWrite"]],
            # pi-sandbox historically allowed commands such as
            # `git remote set-url`; Sandbox Runtime protects hooks independently.
            "allowGitConfig": True,
        },
        "network": {
            "allowedDomains": [*policy["network"]["allowedDomains"]],
            "deniedDomains": [*policy["network"]["deniedDomains"]],
            "allowLocalBinding": policy["network"]["allowLocalBinding"],
            "allowAllUnixSockets": policy["network"]["allowAllUnixSockets"],
            "allowUnixSockets": [*policy["network"]["allowUnixSockets"]],
        },
    }


__all__ = [
    "DARWIN_SECRET_DENY_WRITE_GLOBS",
    "INTERPRETER_BIN_DIR",
    "INTERPRETER_ROOT",
    "PACKAGE_ROOT",
    "SANDBOX_RUNTIME_ROOT",
    "WALK_SKIP_DIRECTORIES",
    "WORKSPACE_SECRET_DENY_WRITE_BASENAMES",
    "WORKSPACE_SECRET_DENY_WRITE_DIRECTORIES",
    "WORKSPACE_SECRET_DENY_WRITE_EXTENSIONS",
    "WORKSPACE_SECRET_SCAN_MAX_DEPTH",
    "WORKSPACE_SECRET_TEMPLATE_BASENAMES",
    "SandboxPolicy",
    "SandboxPolicyFilesystem",
    "SandboxPolicyNetwork",
    "create_default_policy",
    "create_workspace_secret_deny_write_paths",
    "is_secret_deny_write_basename",
    "to_sandbox_runtime_config",
]
