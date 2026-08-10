"""Contract: gold isolation (D6 闸 4).

运行进程代码 (eval/runner, eval/adapter, eval/normalizer, eval/manifest_builder) 不得
import widesearch_gold 路径或含 data/benchmarks gold 路径字符串. evaluator 独立,
允许调官方 scorer (subprocess), 但不直接 open() gold CSV.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVAL_SRC = ROOT / "eval" / "src" / "eval"

# 运行进程目录 (不能碰 gold)
RUNNER_PATHS = [
    EVAL_SRC / "runner",
    EVAL_SRC / "adapter",
    EVAL_SRC / "normalizer",
    EVAL_SRC / "manifest.py",
    EVAL_SRC / "manifest_builder.py",
    EVAL_SRC / "operations",
]

# gold 相关字符串 (出现在 import 或字符串字面量里 = 泄漏)
GOLD_MARKERS = ["widesearch_gold", "data/benchmarks", "tasks_and_rubrics", "rubric"]


def _import_roots(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    roots: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.append(node.module)
    return roots


def _scan_string_markers(path: Path) -> list[str]:
    """扫描字符串字面量是否含 gold 路径标记."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for marker in GOLD_MARKERS:
                if marker in node.value:
                    hits.append(f"{path.name}: string contains {marker!r}")
    return hits


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for p in RUNNER_PATHS:
        if p.is_file() and p.suffix == ".py":
            files.append(p)
        elif p.is_dir():
            files.extend(p.rglob("*.py"))
    return files


def test_runner_does_not_import_gold():
    offenders: list[str] = []
    for f in _iter_py_files():
        for root in _import_roots(f):
            if any(m in root for m in GOLD_MARKERS):
                offenders.append(f"{f}: import {root}")
    assert not offenders, f"gold import violations: {offenders}"


def test_runner_no_gold_path_strings():
    offenders: list[str] = []
    for f in _iter_py_files():
        offenders.extend(_scan_string_markers(f))
    assert not offenders, f"gold path string violations: {offenders}"


def test_evaluator_does_not_open_gold_csv():
    """evaluator 只调官方 scorer (subprocess), 不直接 open() gold CSV."""
    ev = EVAL_SRC / "evaluator" / "widesearch.py"
    if not ev.is_file():
        return  # not built yet; skip
    tree = ast.parse(ev.read_text(encoding="utf-8"), filename=str(ev))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    assert "widesearch_gold" not in arg.value, "evaluator opens gold CSV directly"
