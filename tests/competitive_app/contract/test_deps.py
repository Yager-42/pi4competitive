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
    offenders = _scan(APP_SRC / "adapter" / "out", ADAPTER_OUT_FORBIDDEN)
    assert not offenders, f"adapter/out layer violations: {offenders}"


def test_application_does_not_import_fastapi() -> None:
    # application may import pi_agent + adapter/out store, but NOT fastapi.
    offenders = _scan(APP_SRC / "application", {"fastapi", "uvicorn"})
    assert not offenders, f"application layer violations: {offenders}"


def test_workflow_code_in_competitive_app_not_packages() -> None:
    """F-R3/D8: three-stage workflow lives in competitive_app, not packages/agent."""
    import subprocess

    result = subprocess.run(
        ["git", "diff", "--exit-code", "--name-only", "HEAD", "--", "packages/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    # Non-zero exit means packages/ has changes; the workflow must not touch it.
    assert result.returncode == 0, (
        f"packages/ must not be modified by research-workflow-v1; changed: {result.stdout}"
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
