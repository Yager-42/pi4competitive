"""Contract O2 — layering AST guard (feature F-A25).

domain/        : no fastapi / aiosqlite / pi_agent / pi_ai  (pydantic allowed)
adapter/in_/   : no pi_agent / pi_ai / aiosqlite            (only call application)
adapter/out/   : no fastapi / pi_agent / pi_ai              (aiosqlite + domain only)
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP_SRC = ROOT / "competitive_app" / "src" / "competitive_app"

DOMAIN_FORBIDDEN = {"fastapi", "aiosqlite", "earendil_works", "uvicorn"}
ADAPTER_IN_FORBIDDEN = {"earendil_works", "aiosqlite"}
ADAPTER_OUT_FORBIDDEN = {"fastapi", "earendil_works", "uvicorn"}


def _import_roots(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.append(node.module.split(".")[0])
    return roots


def _scan(directory: Path, forbidden: set[str]) -> list[str]:
    offenders: list[str] = []
    for path in directory.rglob("*.py"):
        for root in _import_roots(path):
            if root in forbidden:
                offenders.append(f"{path.relative_to(ROOT)}:{root}")
    return offenders


def test_domain_no_io_or_pi_imports() -> None:
    offenders = _scan(APP_SRC / "domain", DOMAIN_FORBIDDEN)
    assert not offenders, f"domain layer violations: {offenders}"


def test_adapter_in_no_pi_or_db_imports() -> None:
    offenders = _scan(APP_SRC / "adapter" / "in_", ADAPTER_IN_FORBIDDEN)
    assert not offenders, f"adapter/in layer violations: {offenders}"


def test_adapter_out_no_fastapi_or_pi_imports() -> None:
    """adapter/out is store-only and never imports FastAPI.

    P3.3 host delta: the ``sandbox`` adapter subtree is the consumer of Pi's
    provider-neutral executor seam (``earendil_works.pi_agent`` types are its
    message contract); it still must never import FastAPI/uvicorn.  Every other
    out-layer module keeps the full ban.
    """
    sandbox_dir = (APP_SRC / "adapter" / "out" / "sandbox").resolve()
    offenders: list[str] = []
    for path in (APP_SRC / "adapter" / "out").rglob("*.py"):
        relative = path.relative_to(ROOT)
        if path.resolve().is_relative_to(sandbox_dir):
            forbidden = {"fastapi", "uvicorn"}
        else:
            forbidden = ADAPTER_OUT_FORBIDDEN
        for root in _import_roots(path):
            if root in forbidden:
                offenders.append(f"{relative}:{root}")
    assert not offenders, f"adapter/out layer violations: {offenders}"


def test_application_does_not_import_fastapi() -> None:
    # application may import pi_agent + adapter/out store, but NOT fastapi.
    offenders = _scan(APP_SRC / "application", {"fastapi", "uvicorn"})
    assert not offenders, f"application layer violations: {offenders}"
def test_workflow_code_in_competitive_app_not_packages() -> None:
    """F-R3/D8: three-stage workflow lives in competitive_app, not packages/agent.

    P3.3 host delta: the provider-neutral AgentTool executor seam (plan A1–A4)
    is a documented packages/agent change; nothing else may touch packages/.
    """
    import subprocess

    P3_3_SEAM_FILES = {
        "packages/agent/src/earendil_works/pi_agent/__init__.py",
        "packages/agent/src/earendil_works/pi_agent/agent.py",
        "packages/agent/src/earendil_works/pi_agent/agent_loop.py",
        "packages/agent/src/earendil_works/pi_agent/boundary_approval.py",
        "packages/agent/src/earendil_works/pi_agent/extensions/wrapper.py",
        "packages/agent/src/earendil_works/pi_agent/harness/agent_harness.py",
        "packages/agent/src/earendil_works/pi_agent/tool_execution.py",
        "packages/agent/src/earendil_works/pi_agent/types.py",
    }
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", "packages/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    tracked = {line for line in result.stdout.splitlines() if line}
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "packages/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    new_files = {line for line in untracked.stdout.splitlines() if line}
    changed = tracked | new_files
    assert changed <= P3_3_SEAM_FILES, (
        f"packages/ must not be modified by research-workflow-v1; changed: {sorted(changed)}"
    )


# Constraint 3 (CLAUDE.md) + ADR 0010 D-S1: SearchOS is architecture reference only.
# langgraph / langchain / deepagents are forbidden across the whole app — the v0.2.0
# SearchOS engine port must reimplement on pi_agent, not import its langgraph stack.
FORBIDDEN_FRAMEWORKS_APP = {
    "langchain",
    "langchain_core",
    "langchain_anthropic",
    "langchain_openai",
    "langgraph",
    "deepagents",
    "llama_index",
    "haystack",
    "semantic_kernel",
}


def test_no_forbidden_llm_frameworks_in_app() -> None:
    """ADR 0010 D-S1: no langgraph/langchain/deepagents anywhere in competitive_app."""
    offenders = _scan(APP_SRC, FORBIDDEN_FRAMEWORKS_APP)
    assert not offenders, f"forbidden LLM frameworks in competitive_app: {offenders}"
