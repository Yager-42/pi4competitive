"""Deterministic Skill contract checks copied from Poirot.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/eval/analyzers/checks.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: import path only; files are local learned Skill resources.
"""
from __future__ import annotations

import re
from pathlib import Path

from typing import Any
HARD_MODES = ("nonempty", "json_parseable")
DIRECTIVE_WORDS = ("MUST", "ALWAYS", "NEVER", "SHOULD", "MUST NOT", "REQUIRED", "FORBIDDEN")
UNFOUNDED_WORDS = ("绝对", "一定", "必然", "毫无疑问", "absolutely", "definitely", "certainly")
CONCLUSION_WORDS = ("结论", "总结", "核心", "要点", "conclusion", "summary", "key")
CITE_PATTERN = re.compile(r"(https?://|@[\w-]+|来源|引用|source|cite)", re.IGNORECASE)
YAML_FRONTMATTER = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
PARAGRAPH_LIMIT = 20
SEMANTIC_DENSITY_MIN = 0.005
SEMANTIC_DENSITY_MAX = 0.15


def read_content(record: Any) -> str:
    try:
        return Path(record.path).read_text(encoding="utf-8")
    except Exception:
        return ""


def split_body(content: str) -> str:
    match = YAML_FRONTMATTER.match(content)
    return content[match.end():] if match else content


def check_nonempty(content: str) -> bool:
    return bool(split_body(content).strip())


def check_json_parseable(content: str) -> bool:
    match = YAML_FRONTMATTER.match(content)
    if not match:
        return True
    try:
        import yaml
        yaml.safe_load(match.group(1))
        return True
    except Exception:
        return False


def check_must_cite(content: str) -> bool:
    return bool(CITE_PATTERN.search(content))


def check_paragraph_limit(content: str, maximum: int = PARAGRAPH_LIMIT) -> bool:
    return len([p for p in split_body(content).split("\n\n") if p.strip()]) <= maximum


def check_lead_with_conclusion(content: str) -> bool:
    body = split_body(content).strip()
    return bool(body) and any(w.lower() in "\n\n".join(body.split("\n\n")[:3]).lower() for w in CONCLUSION_WORDS)


def check_no_unfounded_claims(content: str) -> bool:
    lower = content.lower()
    return not any(word.lower() in lower for word in UNFOUNDED_WORDS)


def semantic_density(content: str) -> float:
    if not content:
        return 0.0
    words = re.findall(r"\w+", content)
    if not words:
        return 0.0
    upper = content.upper()
    return sum(upper.count(word) for word in DIRECTIVE_WORDS) / len(words)
