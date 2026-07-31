from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AGENT_SRC = ROOT / "packages/agent/src/earendil_works/pi_agent"

FORBIDDEN_FRAMEWORKS = {
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

FORBIDDEN_DOMAIN = {
    "competitive_app",
    "capability_packages",
}


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


def test_no_forbidden_llm_frameworks() -> None:
    offenders: list[str] = []
    for path in AGENT_SRC.rglob("*.py"):
        for root in _import_roots(path):
            if root in FORBIDDEN_FRAMEWORKS:
                offenders.append(f"{path}:{root}")
    assert not offenders, offenders


def test_no_competitive_domain_imports() -> None:
    offenders: list[str] = []
    for path in AGENT_SRC.rglob("*.py"):
        for root in _import_roots(path):
            if root in FORBIDDEN_DOMAIN:
                offenders.append(f"{path}:{root}")
    assert not offenders, offenders


def test_depends_on_real_pi_ai_package() -> None:
    # Workspace dependency: earendil-works-pi-ai must resolve as installed package.
    import earendil_works.pi_ai as pi_ai

    assert pi_ai is not None
    pyproject = (ROOT / "packages/agent/pyproject.toml").read_text(encoding="utf-8")
    assert "earendil-works-pi-ai" in pyproject


def test_pydantic_v2_available() -> None:
    import pydantic

    assert int(pydantic.VERSION.split(".")[0]) >= 2

def test_pi_agent_has_no_sandbox_imports() -> None:
    offenders: list[str] = []
    for path in AGENT_SRC.rglob("*.py"):
        for root in _import_roots(path):
            if root in {"agent_sandbox", "docker"}:
                offenders.append(f"{path}:{root}")
    assert not offenders, offenders
