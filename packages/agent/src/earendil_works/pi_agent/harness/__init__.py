"""Harness surface: session, compaction, skills, tools.

upstream: packages/agent/src/harness/*
"""
from __future__ import annotations

from .agent_harness import AgentHarness
from .compaction import (
    compact,
    should_compact,
    prepare_compaction,
    estimate_context_tokens,
)
from .messages import convert_to_llm
from .prompt_templates import PromptTemplate, format_prompt_template_invocation
from .session import (
    DEFAULT_SESSIONS_DIR_NAME,
    InMemorySessionRepo,
    JsonlSessionRepo,
    Session,
)
from .skills import Skill, format_skills_for_system_prompt, load_skills_from_paths
from .system_prompt import build_system_prompt
from .tools import create_coding_tools, create_read_tool, create_write_tool

__all__ = [
    "AgentHarness",
    "DEFAULT_SESSIONS_DIR_NAME",
    "InMemorySessionRepo",
    "JsonlSessionRepo",
    "PromptTemplate",
    "Session",
    "Skill",
    "build_system_prompt",
    "compact",
    "convert_to_llm",
    "create_coding_tools",
    "create_read_tool",
    "create_write_tool",
    "estimate_context_tokens",
    "format_prompt_template_invocation",
    "format_skills_for_system_prompt",
    "load_skills_from_paths",
    "prepare_compaction",
    "should_compact",
]
