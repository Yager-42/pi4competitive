from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SANDBOX_SRC = Path(__file__).resolve().parents[3] / "competitive_app/src/competitive_app/adapter/out/sandbox"


TOOL_MODULES = (
    "capability_packages.echo_example.extensions.echo_tools",
    "capability_packages.search_tavily.extensions.tavily_tools",
    "capability_packages.search_anysearch.extensions.anysearch_tools",
    "capability_packages.search_grok.extensions.grok_tools",
)


def test_worker_targets_import_without_pi_control_plane() -> None:
    script = "import importlib, sys; importlib.import_module(sys.argv[1]); print('earendil_works.pi_agent' in sys.modules)"
    for module in TOOL_MODULES:
        result = subprocess.run(
            [sys.executable, "-c", script, module],
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "False", (module, result.stderr)


def test_transplanted_sandbox_files_record_source_and_license() -> None:
    transplanted = (
        "exceptions.py",
        "types.py",
        "sandbox.py",
        "contracts/path_translator.py",
        "contracts/security_guard.py",
        "contracts/sandbox_runtime.py",
        "contracts/sandbox_provider.py",
        "native/workspace.py",
        "utils/sandbox_id.py",
    )
    for relative in transplanted:
        text = (SANDBOX_SRC / relative).read_text(encoding="utf-8")
        assert "86bf279ad90c180f0ba696755620dd7d6661465e" in text, relative
        assert "License: MIT" in text, relative


def test_omitted_local_runtime_and_artifact_surfaces_are_absent() -> None:
    omitted = (
        "runtimes/local_runtime.py",
        "local/local_sandbox_provider.py",
        "artifacts/server.py",
        "artifacts/local_store.py",
    )
    assert all(not (SANDBOX_SRC / relative).exists() for relative in omitted)
