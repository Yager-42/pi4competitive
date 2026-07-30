"""Workflow Skill configuration adapted from Poirot ``skill/config.py``.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/config.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: ``WORKFLOW_SKILL_*`` env prefix, existing ``AppConfig.app_db``
provided by wiring, local learned-skills root, and no Hub/builtin/install flags.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillEvalConfig:
    enabled: bool = False
    judgment_enabled: bool = True
    task_judge_enabled: bool = True
    contract_check: bool = True
    async_eval: bool = True
    skip_no_skill: bool = True
    runtime_window: int = 20
    degradation_delta: float = 0.15
    captured_min_score: float = 0.5
    max_messages_chars: int = 80000
    task_weights: tuple[float, ...] = (0.50, 0.35, 0.05, 0.10)


@dataclass(frozen=True)
class SkillConfig:
    enabled: bool = False
    root_dir: str = "capability_packages/learned_skills"
    max_inject: int = 3
    quality_threshold: float = 0.3
    min_selections: int = 5
    evolve_enabled: bool = False
    evolve_threshold: float = 0.3
    evolve_min_selections: int = 5
    evolve_cooldown_turns: int = 10
    evolve_mutate_budget: int = 20
    evolve_max_steps: int = 5
    eval_config: SkillEvalConfig = SkillEvalConfig()


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _root(value: str) -> str:
    return str(Path(value).expanduser())


def load_skill_config(root_dir: str | None = None) -> SkillConfig:
    """Load ``WORKFLOW_SKILL_*`` values; malformed numbers use frozen defaults."""
    eval_cfg = SkillEvalConfig(
        enabled=_bool("WORKFLOW_SKILL_EVAL_ENABLED", False),
        judgment_enabled=_bool("WORKFLOW_SKILL_EVAL_JUDGMENT_ENABLED", True),
        task_judge_enabled=_bool("WORKFLOW_SKILL_EVAL_TASK_JUDGE_ENABLED", True),
        contract_check=_bool("WORKFLOW_SKILL_EVAL_CONTRACT_CHECK", True),
        async_eval=_bool("WORKFLOW_SKILL_EVAL_ASYNC", True),
        skip_no_skill=_bool("WORKFLOW_SKILL_EVAL_SKIP_NO_SKILL", True),
        runtime_window=_int("WORKFLOW_SKILL_EVAL_RUNTIME_WINDOW", 20),
        degradation_delta=_float("WORKFLOW_SKILL_EVAL_DEGRADATION_DELTA", 0.15),
        captured_min_score=_float("WORKFLOW_SKILL_EVAL_CAPTURED_MIN_SCORE", 0.5),
        max_messages_chars=_int("WORKFLOW_SKILL_EVAL_MAX_MESSAGES_CHARS", 80000),
        task_weights=(0.50, 0.35, 0.05, 0.10),
    )
    return SkillConfig(
        enabled=_bool("WORKFLOW_SKILL_ENABLED", False),
        root_dir=_root(root_dir or os.environ.get("WORKFLOW_SKILL_ROOT", "capability_packages/learned_skills")),
        max_inject=_int("WORKFLOW_SKILL_MAX_INJECT", 3),
        quality_threshold=_float("WORKFLOW_SKILL_QUALITY_THRESHOLD", 0.3),
        min_selections=_int("WORKFLOW_SKILL_MIN_SELECTIONS", 5),
        evolve_enabled=_bool("WORKFLOW_SKILL_EVOLVE_ENABLED", False),
        evolve_threshold=_float("WORKFLOW_SKILL_EVOLVE_THRESHOLD", 0.3),
        evolve_min_selections=_int("WORKFLOW_SKILL_EVOLVE_MIN_SELECTIONS", 5),
        evolve_cooldown_turns=_int("WORKFLOW_SKILL_EVOLVE_COOLDOWN_SELECTIONS", _int("WORKFLOW_SKILL_EVOLVE_COOLDOWN_TURNS", 10)),
        evolve_mutate_budget=_int("WORKFLOW_SKILL_EVOLVE_MUTATE_BUDGET", 20),
        evolve_max_steps=_int("WORKFLOW_SKILL_EVOLVE_MAX_STEPS", 5),
        eval_config=eval_cfg,
    )


__all__ = ["SkillConfig", "SkillEvalConfig", "load_skill_config"]
