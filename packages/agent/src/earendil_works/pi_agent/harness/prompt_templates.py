"""Prompt templates.

upstream: packages/agent/src/harness/prompt-templates.ts
"""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass
class PromptTemplate:
    name: str
    content: str
    description: str | None = None


def format_prompt_template_invocation(template: PromptTemplate, args: str = "") -> str:
    """Format template content with `$ARGUMENTS` / `{{args}}` placeholders."""
    content = template.content
    content = content.replace("$ARGUMENTS", args)
    content = content.replace("{{args}}", args)
    content = re.sub(r"\{\{\s*arguments\s*\}\}", args, content)
    return content


__all__ = ["PromptTemplate", "format_prompt_template_invocation"]
