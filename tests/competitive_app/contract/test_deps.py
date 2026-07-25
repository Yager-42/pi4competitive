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
