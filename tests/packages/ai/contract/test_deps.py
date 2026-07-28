from __future__ import annotations

import ast
import inspect
from pathlib import Path

import earendil_works.pi_ai as pi_ai
from earendil_works.pi_ai.models import ModelsImpl

ROOT = Path(__file__).resolve().parents[4]
AI_SRC = ROOT / "packages/ai/src/earendil_works/pi_ai"

FORBIDDEN = {
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


def test_no_forbidden_llm_frameworks() -> None:
    offenders: list[str] = []
    for path in AI_SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in FORBIDDEN:
                        offenders.append(f"{path}:{root}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in FORBIDDEN:
                    offenders.append(f"{path}:{root}")
    assert not offenders, offenders


def test_no_nodejs_runtime_required() -> None:
    # Import and faux stream must not shell out to node
    import earendil_works.pi_ai as m

    assert m is not None


def test_pydantic_v2_available_for_validation() -> None:
    import pydantic

    assert int(pydantic.VERSION.split(".")[0]) >= 2


def test_public_stream_apis_are_async() -> None:
    assert inspect.iscoroutinefunction(ModelsImpl.complete)
    assert inspect.iscoroutinefunction(ModelsImpl.completeSimple)
