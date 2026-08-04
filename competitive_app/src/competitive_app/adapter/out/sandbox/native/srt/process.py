"""SRT process-layer utilities — logging, platform, shell quoting, exec discovery, ripgrep.

Source: sandbox-runtime@0.0.67 ``src/utils/{debug,platform,ripgrep,shell-quote,which}.ts``
Repository: anthropics/sandbox-runtime @ 21d8f75e1bc00eede09b3103e68b2eae097110d1
License: Apache-2.0 (retained under the native sandbox license directory)

Host delta (ADAPT): TypeScript synchronous/spawnSync helpers become Python
stdlib equivalents; ``getPlatform`` is reduced to the Linux/macOS scope
(Windows/WSL product branches rejected per G0 map §4.1 — ``get_wsl_version``
is kept only because the manager's platform-support check rejects WSL1);
``ripGrep`` becomes asyncio; ``quote`` is an exact port of the upstream
shell-quote algorithm (NOT ``shlex.quote``, whose safe set differs).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
from typing import Iterable

logger = logging.getLogger("competitive_app.adapter.out.sandbox.native.srt")

# ---------------------------------------------------------------------------
# debug.ts — logForDebugging
# ---------------------------------------------------------------------------

_DEBUG_ENABLED: bool | None = None


def _debug_on() -> bool:
    global _DEBUG_ENABLED
    if _DEBUG_ENABLED is None:
        _DEBUG_ENABLED = bool(os.environ.get("SRT_DEBUG"))
    return _DEBUG_ENABLED


def log_for_debugging(message: str, *, level: str = "info") -> None:
    """SRT debug logging, gated on SRT_DEBUG like upstream (never DEBUG).

    Always logs to the Python logger; the SRT_DEBUG gate mirrors the
    upstream behavior of staying silent unless explicitly requested.
    """
    if not _debug_on():
        return
    if level == "error":
        logger.error("[SandboxDebug] %s", message)
    elif level == "warn":
        logger.warning("[SandboxDebug] %s", message)
    else:
        logger.info("[SandboxDebug] %s", message)


# ---------------------------------------------------------------------------
# platform.ts — getPlatform / getWslVersion
# ---------------------------------------------------------------------------

PLATFORM_LINUX = "linux"
PLATFORM_MACOS = "macos"
PLATFORM_WINDOWS = "windows"
PLATFORM_UNKNOWN = "unknown"


def get_platform() -> str:
    """Current platform: 'macos' | 'linux' | 'windows' | 'unknown'."""
    if sys.platform == "darwin":
        return PLATFORM_MACOS
    if sys.platform.startswith("linux"):
        return PLATFORM_LINUX
    if sys.platform in ("win32", "cygwin", "msys"):
        return PLATFORM_WINDOWS
    return PLATFORM_UNKNOWN


def get_wsl_version() -> str | None:
    """WSL version ('1'/'2') when running under WSL, else None."""
    if get_platform() != PLATFORM_LINUX:
        return None
    try:
        proc_version = _read_proc_version()
        match = re.search(r"WSL(\d+)", proc_version, re.IGNORECASE)
        if match:
            return match.group(1)
        if "microsoft" in proc_version.lower():
            return "1"
    except OSError:
        pass
    return None


def _read_proc_version() -> str:
    with open("/proc/version", encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# which.ts — whichSync
# ---------------------------------------------------------------------------

def which(bin_name: str) -> str | None:
    """Find an executable on PATH (like ``which``); None when absent."""
    found = shutil.which(bin_name)
    return found if found is not None else None


# ---------------------------------------------------------------------------
# shell-quote.ts — quote
# ---------------------------------------------------------------------------

_SAFE_BARE_RE = re.compile(r"^[A-Za-z0-9_./:@+,-][A-Za-z0-9_./:=@+,-]*$")


def shell_quote(args: Iterable[str]) -> str:
    """Shell-escape an argument list for ``<shell> -c`` — exact upstream port.

    Single-quoting strategy with the ``'"'"'`` idiom; never the
    double-quote+backslash mode of the npm ``shell-quote`` package. The bare
    fast path matches upstream's regex, including the leading ``=`` guard for
    zsh equals expansion (shlex.quote would leave ``=foo`` bare — wrong).
    """
    return " ".join(
        arg
        if _SAFE_BARE_RE.match(arg)
        else "'" + arg.replace("'", "'\"'\"'") + "'"
        for arg in args
    )


# ---------------------------------------------------------------------------
# ripgrep.ts — hasRipgrepSync / ripGrep
# ---------------------------------------------------------------------------

RIPGREP_TIMEOUT_SECONDS = 10.0


def has_ripgrep_sync() -> bool:
    return which("rg") is not None


async def ripgrep(
    args: list[str],
    target: str,
    abort_signal: asyncio.Future | None = None,
    *,
    command: str = "rg",
    command_args: list[str] | None = None,
    argv0: str | None = None,
) -> list[str]:
    """Run ripgrep and return matching lines; exit 1 (no matches) → [].

    ADAPT: upstream spawns with a 10s timeout and AbortSignal; Python uses
    asyncio subprocess with the same timeout and an optional abort future.
    """
    argv = [command, *(command_args or []), *args, target]
    try:
        process = await asyncio.create_subprocess_exec(
            argv[0],
            *argv[1:],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            executable=argv0,
        )
    except OSError as exc:
        raise RuntimeError(f"ripgrep failed to start: {exc}") from exc

    async def _wait() -> tuple[bytes, bytes, int]:
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=RIPGREP_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            _kill_process(process)
            await process.wait()  # reap; SIGKILL alone leaves a zombie
            raise RuntimeError(
                f"ripgrep timed out after {RIPGREP_TIMEOUT_SECONDS}s"
            ) from None
        return stdout, stderr, process.returncode or 0

    wait_task = asyncio.ensure_future(_wait())
    abort_task: asyncio.Future | None = None
    try:
        if abort_signal is not None:
            abort_task = asyncio.ensure_future(asyncio.shield(abort_signal))
            done, _pending = await asyncio.wait(
                {wait_task, abort_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if wait_task not in done:
                _kill_process(process)
                await process.wait()  # reap before cancellation abandons pipes
                wait_task.cancel()
                await asyncio.gather(wait_task, return_exceptions=True)
                raise asyncio.CancelledError("ripgrep aborted")
        else:
            await wait_task
        stdout, stderr, code = wait_task.result()
    finally:
        if abort_task is not None and not abort_task.done():
            abort_task.cancel()
        if abort_task is not None:
            await asyncio.gather(abort_task, return_exceptions=True)
        if process.returncode is None:
            _kill_process(process)
            await process.wait()  # reap: SIGKILL alone leaves a zombie
        if not wait_task.done():
            wait_task.cancel()
        await asyncio.gather(wait_task, return_exceptions=True)
    return _parse_ripgrep_output(stdout, stderr, code)



def _parse_ripgrep_output(
    stdout: bytes, stderr: bytes, code: int
) -> list[str]:
    if code == 0:
        text = stdout.decode("utf-8", errors="replace").strip()
        return [line for line in text.split("\n") if line] if text else []
    if code == 1:
        # Exit code 1 means "no matches found" - this is normal
        return []
    raise RuntimeError(
        f"ripgrep failed with exit code {code}: "
        f"{stderr.decode('utf-8', errors='replace')}"
    )


def _kill_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
