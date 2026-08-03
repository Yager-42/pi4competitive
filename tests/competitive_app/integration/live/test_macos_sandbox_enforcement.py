"""V3 — arm64 macOS real enforcement gate (S1–S9 + e2e).

G0 map §8.2: the macOS Seatbelt path must really enforce the production
policy, not just parse it. This suite drives the REAL broker process
(``native/broker.py``) with the REAL production policy builder
(``create_default_policy`` + ``to_sandbox_runtime_config``) through the
REAL ``sandbox-exec`` wrapper, on this host.

Host gate: runs only on macOS with ``sandbox-exec`` present (the macOS
gate is required per ADR 0012/0013; other platforms skip). No network
egress is needed: every outbound attempt is denied either by the Seatbelt
profile or by the broker's public-hostname validation before any dial.

S1–S5 filesystem enforcement, S6–S8 network default/endpoint deny,
S9 approval round trip, plus real parallel + parent-disconnect cleanup.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import sys
from pathlib import Path
from typing import Any

import pytest

from competitive_app.adapter.out.sandbox.native.policy import (
    create_default_policy,
    to_sandbox_runtime_config,
)

BROKER_MODULE = (
    Path(__file__).resolve().parents[4]
    / "competitive_app"
    / "src"
    / "competitive_app"
    / "adapter"
    / "out"
    / "sandbox"
    / "native"
    / "broker.py"
)

requires_macos_sandbox = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("sandbox-exec") is None,
    reason="macOS real enforcement requires sandbox-exec (macOS gate)",
)


def _runtime_config(
    workspace: Path,
    *,
    bundle: Path | None = None,
    deny_read_extra: list[Path] = (),
    network: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = create_default_policy(
        str(workspace),
        additional_allow_read=[str(bundle)] if bundle is not None else None,
    )
    cfg = to_sandbox_runtime_config(policy)
    if deny_read_extra:
        cfg["filesystem"]["denyRead"] = [
            *cfg["filesystem"]["denyRead"],
            *(str(p) for p in deny_read_extra),
        ]
    if network is not None:
        cfg["network"] = network
    return cfg


async def _spawn_broker(
    tmp_path: Path,
) -> tuple[asyncio.subprocess.Process, asyncio.StreamReader, asyncio.StreamWriter, socket.socket]:
    ipc_parent, ipc_child = socket.socketpair()
    os.set_inheritable(ipc_child.fileno(), True)
    env = {**os.environ, "PI_SANDBOX_IPC_FD": str(ipc_child.fileno())}
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(BROKER_MODULE),
        cwd=str(tmp_path),
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        pass_fds=(ipc_child.fileno(),),
    )
    ipc_child.close()
    ipc_reader, ipc_writer = await asyncio.open_connection(sock=ipc_parent)
    return proc, ipc_reader, ipc_writer, ipc_parent


async def _run_broker_command(
    tmp_path: Path,
    command: str,
    *,
    runtime_config: dict[str, Any],
    network_handler: Any = None,
) -> tuple[int, str, str, list[dict[str, Any]]]:
    """Run one real sandboxed command; answer network requests via the
    handler ``(message) -> "allow" | "deny"`` (default deny)."""
    proc, ipc_reader, ipc_writer, ipc_parent = await _spawn_broker(tmp_path)
    requests: list[dict[str, Any]] = []

    async def _ipc_loop() -> None:
        try:
            while True:
                line = await ipc_reader.readline()
                if not line:
                    break
                message = json.loads(line)
                if message.get("type") != "network-request":
                    continue
                requests.append(message)
                action = "deny"
                if network_handler is not None:
                    action = network_handler(message) or "deny"
                ipc_writer.write(
                    (
                        json.dumps(
                            {
                                "type": "network-response",
                                "id": message["id"],
                                "action": action,
                            }
                        )
                        + "\n"
                    ).encode()
                )
                await ipc_writer.drain()
        except (json.JSONDecodeError, ConnectionError, OSError):
            pass

    proc.stdin.write(command.encode())
    await proc.stdin.drain()
    proc.stdin.close()
    init = {
        "type": "init",
        "invocation": ["/bin/bash"],
        "runtimeConfig": runtime_config,
    }
    ipc_writer.write((json.dumps(init) + "\n").encode())
    await ipc_writer.drain()
    ipc_task = asyncio.create_task(_ipc_loop())
    out, err = await proc.communicate()
    ipc_writer.close()
    ipc_parent.close()
    await ipc_task
    return proc.returncode or 0, out.decode(), err.decode(), requests


def _py_multi(target: str) -> str:
    """Multiline ``python3 -c`` payload: real newlines inside double quotes
    survive bash line parsing; the code must not contain double quotes."""
    return f'"{sys.executable}" -c "{target}"'


def _py(target: str) -> str:
    """Sandboxed python3 one-liner using the test interpreter."""
    return f'"{sys.executable}" -c {json.dumps(target)}'


# ---------------------------------------------------------------------------
# S1–S3 filesystem
# ---------------------------------------------------------------------------


@requires_macos_sandbox
@pytest.mark.macos
@pytest.mark.asyncio
async def test_s1_workspace_read_write(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    code, out, err, _ = await _run_broker_command(
        tmp_path,
        f'printf "wrote" > "{ws}/out.txt" && cat "{ws}/out.txt"\n',
        runtime_config=_runtime_config(ws),
    )
    assert code == 0, (out, err)
    assert "wrote" in out


@requires_macos_sandbox
@pytest.mark.macos
@pytest.mark.asyncio
async def test_s2_tool_bundle_is_read_only(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "keep.txt").write_text("bundle-content", encoding="utf-8")
    code, out, err, _ = await _run_broker_command(
        tmp_path,
        f'cat "{bundle}/keep.txt" && ! touch "{bundle}/new.txt" 2>/dev/null && echo bundle-ro-ok\n',
        runtime_config=_runtime_config(ws, bundle=bundle),
    )
    assert code == 0, (out, err)
    assert "bundle-content" in out and "bundle-ro-ok" in out
    assert not (bundle / "new.txt").exists()


@requires_macos_sandbox
@pytest.mark.macos
@pytest.mark.asyncio
async def test_s3_host_app_session_db_other_scope_deny(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    app_db = tmp_path / "app.db"
    app_db.write_text("db-secret", encoding="utf-8")
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "session.jsonl").write_text("session-secret", encoding="utf-8")
    other_scope = tmp_path / "other-scope"
    other_scope.mkdir()
    (other_scope / "f.txt").write_text("other-scope-secret", encoding="utf-8")
    app_config = tmp_path / "settings.yaml"
    app_config.write_text("config-secret", encoding="utf-8")
    deny_read = [app_db, sessions, other_scope, app_config]
    # denyRead=[home] (production) plus the App/session/DB/other-scope roots.
    code, out, err, _ = await _run_broker_command(
        tmp_path,
        f"""
set +e
cat "{app_db}" >/dev/null 2>&1; [ $? -ne 0 ] || echo db-leaked
cat "{sessions}/session.jsonl" >/dev/null 2>&1; [ $? -ne 0 ] || echo session-leaked
cat "{other_scope}/f.txt" >/dev/null 2>&1; [ $? -ne 0 ] || echo scope-leaked
cat "{app_config}" >/dev/null 2>&1; [ $? -ne 0 ] || echo config-leaked
cat "$HOME/.ssh/known_hosts" >/dev/null 2>&1; [ $? -ne 0 ] || echo home-leaked
echo done
""",
        runtime_config=_runtime_config(ws, deny_read_extra=deny_read),
    )
    assert code == 0, (out, err)
    assert "leaked" not in out, out
    assert "done" in out


# ---------------------------------------------------------------------------
# S4–S5 boundary + secrets
# ---------------------------------------------------------------------------


@requires_macos_sandbox
@pytest.mark.macos
@pytest.mark.asyncio
async def test_s4_symlink_and_traversal_do_not_escape(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    app_db = tmp_path / "app.db"
    app_db.write_text("db-secret", encoding="utf-8")
    (ws / "link").symlink_to(app_db, target_is_directory=False)
    code, out, err, _ = await _run_broker_command(
        tmp_path,
        f"""
set +e
cat "{ws}/link" >/dev/null 2>&1; [ $? -ne 0 ] || echo symlink-leaked
cat "{ws}/../app.db" >/dev/null 2>&1; [ $? -ne 0 ] || echo traversal-leaked
echo done
""",
        runtime_config=_runtime_config(ws, deny_read_extra=[app_db]),
    )
    assert code == 0, (out, err)
    assert "leaked" not in out, out
    assert "done" in out


@requires_macos_sandbox
@pytest.mark.macos
@pytest.mark.asyncio
async def test_s5_workspace_secret_deny_write(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    nested = ws / "nested"
    nested.mkdir()
    (nested / "existing.key").write_text("old", encoding="utf-8")
    # Policy is built AFTER the nested secret exists: the shallow scan must
    # deny writes to discovered secrets, root-level new secrets, and globs.
    code, out, err, _ = await _run_broker_command(
        tmp_path,
        f"""
set +e
touch "{ws}/ok.txt" || echo plain-write-denied
touch "{ws}/.env" 2>/dev/null && echo root-env-leaked
mkdir "{ws}/secrets" 2>/dev/null && echo secrets-dir-leaked
touch "{ws}/nested/existing.key" 2>/dev/null && echo nested-key-leaked
touch "{ws}/nested/new.pem" 2>/dev/null && echo nested-pem-leaked
echo done
""",
        runtime_config=_runtime_config(ws),
    )
    assert code == 0, (out, err)
    assert (ws / "ok.txt").exists()
    assert "leaked" not in out, out
    assert "done" in out


# ---------------------------------------------------------------------------
# S6–S8 network
# ---------------------------------------------------------------------------

PRODUCTION_NETWORK = {
    "allowedDomains": [],
    "deniedDomains": [],
    "allowLocalBinding": False,
    "allowAllUnixSockets": False,
    "allowUnixSockets": [],
}


@requires_macos_sandbox
@pytest.mark.macos
@pytest.mark.asyncio
async def test_s6_network_default_deny(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    code, out, err, _ = await _run_broker_command(
        tmp_path,
        f"""
set +e
{_py("import socket; s=socket.socket(); s.settimeout(2); s.connect(('93.184.216.34', 443))")} 2>/dev/null && echo public-leaked
{_py("import socket; s=socket.socket(); s.settimeout(2); s.connect(('127.0.0.1', 9))")} 2>/dev/null && echo loopback-leaked
{_py("import socket; s=socket.socket(); s.settimeout(2); s.connect(('169.254.169.254', 80))")} 2>/dev/null && echo metadata-leaked
echo done
""",
        runtime_config=_runtime_config(ws, network=dict(PRODUCTION_NETWORK)),
    )
    assert code == 0, (out, err)
    assert "leaked" not in out, out
    assert "done" in out


@requires_macos_sandbox
@pytest.mark.macos
@pytest.mark.asyncio
async def test_s7_only_proxy_endpoint_reachable(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    network = dict(PRODUCTION_NETWORK)
    network["allowedDomains"] = ["example.com"]
    # One broker run: parse THIS run's mux port, then prove the profile
    # allows exactly that endpoint and nothing adjacent (a fresh mux binds
    # a fresh port per broker, so the port cannot cross broker runs).
    probe = """import os, re, socket
m = re.search(r'localhost:(\\d+)', os.environ['HTTPS_PROXY'])
p = int(m.group(1))
s = socket.socket(); s.settimeout(2)
try:
    s.connect(('127.0.0.1', p)); print('PROXY_PORT_OK')
except Exception as e:
    print('PROXY_PORT_FAIL', str(e)[:40])
s = socket.socket(); s.settimeout(2)
try:
    s.connect(('127.0.0.1', p + 1)); print('OTHER_PORT_OPEN')
except Exception as e:
    print('OTHER_PORT_DENIED', str(e)[:40])
"""
    code, out, err, _ = await _run_broker_command(
        tmp_path,
        _py_multi(probe) + "\n",
        runtime_config=_runtime_config(ws, network=network),
    )
    assert code == 0, (out, err)
    assert "PROXY_PORT_OK" in out, (out, err)
    assert "OTHER_PORT_DENIED" in out, (out, err)
    assert "OTHER_PORT_OPEN" not in out, out


@requires_macos_sandbox
@pytest.mark.macos
@pytest.mark.asyncio
async def test_s8_private_hosts_never_reach_approval(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    network = dict(PRODUCTION_NETWORK)
    network["allowedDomains"] = ["example.com"]
    # urllib honors HTTP_PROXY for http://; NO_PROXY does not list 10.x.
    code, out, err, requests = await _run_broker_command(
        tmp_path,
        _py(
            "import urllib.request; "
            "urllib.request.urlopen('http://10.0.0.1/', timeout=5)"
        )
        + "\n",
        runtime_config=_runtime_config(ws, network=network),
    )
    assert code != 0, (out, err)
    # The broker rejects private/loopback/metadata BEFORE asking: no
    # network-request may ever reach the parent for a private address.
    assert requests == [], requests


@requires_macos_sandbox
@pytest.mark.macos
@pytest.mark.asyncio
async def test_s9_grant_decision_round_trip_is_exact_and_per_connection(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    # Production shape: no allowed domains, so example.com reaches the ask
    # callback (hosts in allowedDomains are auto-allowed at the mux).
    network = dict(PRODUCTION_NETWORK)

    async def _attempt() -> tuple[int, str, str, list[dict[str, Any]]]:
        return await _run_broker_command(
            tmp_path,
            _py(
                "import urllib.request; "
                "urllib.request.urlopen('https://example.com/', timeout=5)"
            )
            + "\n",
            runtime_config=_runtime_config(ws, network=network),
        )

    code, out, err, requests = await _attempt()
    assert code != 0, (out, err, requests)
    assert len(requests) == 1, requests
    assert requests[0]["hostname"] == "example.com", requests
    assert requests[0]["port"] == 443, requests
    # Second attempt: the previous deny grants nothing — a fresh request is
    # emitted and independently denied (no cached allow, no expiry semantics
    # to leak across connections).
    code, out, err, requests2 = await _attempt()
    assert code != 0, (out, err)
    assert len(requests2) == 1, requests2
    assert requests2[0]["id"] != requests[0]["id"], (requests, requests2)





# ---------------------------------------------------------------------------
# e2e: parallel + cleanup
# ---------------------------------------------------------------------------


@requires_macos_sandbox
@pytest.mark.macos
@pytest.mark.asyncio
async def test_parallel_calls_share_workspace_with_independent_brokers(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = _runtime_config(ws)

    async def _call(tag: str) -> tuple[int, str]:
        code, out, err, _ = await _run_broker_command(
            tmp_path,
            f'printf "{tag}" > "{ws}/p_{tag}" && cat "{ws}/p_{tag}"\n',
            runtime_config=cfg,
        )
        return code, out

    results = await asyncio.gather(_call("a"), _call("b"))
    for code, out in results:
        assert code == 0, out
    assert (ws / "p_a").read_text(encoding="utf-8") == "a"
    assert (ws / "p_b").read_text(encoding="utf-8") == "b"


@requires_macos_sandbox
@pytest.mark.macos
@pytest.mark.asyncio
async def test_parent_disconnect_kills_sandboxed_target_no_orphan(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    proc, ipc_reader, ipc_writer, ipc_parent = await _spawn_broker(tmp_path)
    proc.stdin.write(f'echo $$ > "{ws}/pid"; exec sleep 60\n'.encode())
    await proc.stdin.drain()
    proc.stdin.close()
    init = {
        "type": "init",
        "invocation": ["/bin/bash"],
        "runtimeConfig": _runtime_config(ws),
    }
    ipc_writer.write((json.dumps(init) + "\n").encode())
    await ipc_writer.drain()
    pid_file = ws / "pid"
    deadline = asyncio.get_event_loop().time() + 15
    while not pid_file.exists():
        assert asyncio.get_event_loop().time() < deadline, "target never started"
        await asyncio.sleep(0.05)
    target_pid = int(pid_file.read_text(encoding="utf-8").strip())
    # Parent disconnect (IPC EOF) must kill the sandboxed target (parity with
    # the runner abort path that closes the IPC channel).
    ipc_writer.close()
    ipc_parent.close()
    out, err = await proc.communicate()
    assert proc.returncode != 0, (out, err)
    # No orphan: the recorded PID must be gone.
    deadline = asyncio.get_event_loop().time() + 5
    while True:
        try:
            os.kill(target_pid, 0)
        except ProcessLookupError:
            break
        assert asyncio.get_event_loop().time() < deadline, "sandboxed target survived"
        await asyncio.sleep(0.05)

