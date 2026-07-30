"""LLMMutator adapted from Poirot FIX/CAPTURED mutator.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/evolution/mutators/llm_mutator.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: async Pi LLM, learned-skills candidate directories, and only
SKILL.md/.skill_id artifacts. No scripts, executables, or manual capture path.
Budget, single-section, frontmatter and unified-diff behavior remain.
"""
from __future__ import annotations

import difflib
import inspect
import re
import uuid
from pathlib import Path
from typing import Any

from ....domain.evolution.evolution_types import EvolutionContext
from ....domain.evolution.skill_types import SkillLineage, SkillRecord


class LLMMutator:
    def __init__(self, root_dir: str | Path = "capability_packages/learned_skills", max_changed_lines: int = 20,
                 max_steps: int = 5, llm: Any | None = None) -> None:
        self._root = Path(root_dir)
        self._max_changed_lines = max_changed_lines
        self._max_steps = max_steps
        self._llm = llm

    async def mutate(self, ctx: EvolutionContext, llm: Any | None = None) -> tuple[SkillRecord, str]:
        active_llm = llm or self._llm
        if ctx.evolution_type == "FIX":
            return await self._mutate_fix(ctx, active_llm)
        if ctx.evolution_type == "CAPTURED":
            return await self._mutate_capture(ctx, active_llm)
        raise ValueError(f"unsupported evolution_type: {ctx.evolution_type}")

    async def _mutate_fix(self, ctx: EvolutionContext, llm: Any | None) -> tuple[SkillRecord, str]:
        baseline = ctx.target_skill
        if baseline is None:
            raise ValueError("FIX requires target Skill")
        original = await self._read(baseline.path)
        frontmatter, body = self._split_frontmatter(original)
        new_body = await self._edit_body(body, ctx, llm)
        new_body = self._enforce_budget(body, new_body, self._max_changed_lines)
        content = frontmatter + new_body if frontmatter else new_body
        candidate_id = f"{baseline.name}__v{baseline.lineage.generation + 1}_{uuid.uuid4().hex[:8]}"
        path = self._write_candidate(candidate_id, content)
        digest = __import__("hashlib").sha256(content.encode()).hexdigest()[:16]
        candidate = SkillRecord(
            skill_id=candidate_id, name=baseline.name, path=str(path), content_hash=digest, is_active=False,
            lineage=SkillLineage((baseline.skill_id,), baseline.lineage.generation + 1, "FIXED", digest, "llm_mutator"),
            description=baseline.description, allowed_tools=baseline.allowed_tools, enabled=True,
        )
        return candidate, self._compute_diff(body, new_body)

    async def _mutate_capture(self, ctx: EvolutionContext, llm: Any | None) -> tuple[SkillRecord, str]:
        if llm is None:
            raise ValueError("CAPTURED needs LLM generated SKILL.md")
        content = await self._generate(ctx, llm)
        frontmatter, body = self._split_frontmatter(content)
        name = self._frontmatter_field(frontmatter, "name") or ctx.suggested_name
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise ValueError(f"invalid skill name from LLM: {name!r}")
        description = self._frontmatter_field(frontmatter, "description") or f"Captured workflow guidance for {name}"
        scope = ctx.scope or "plan"
        frontmatter = self._set_frontmatter(frontmatter, "name", name)
        frontmatter = self._set_frontmatter(frontmatter, "description", description)
        frontmatter = self._set_frontmatter(frontmatter, "scope", scope)
        # CAPTURED tools are always empty, regardless of model output.
        frontmatter = self._set_frontmatter(frontmatter, "allowed-tools", "[]")
        content = frontmatter + body
        candidate_id = f"{name}__v0_{uuid.uuid4().hex[:8]}"
        path = self._write_candidate(candidate_id, content)
        digest = __import__("hashlib").sha256(content.encode()).hexdigest()[:16]
        return SkillRecord(candidate_id, name, str(path), digest, False,
                           SkillLineage((), 0, "CAPTURED", digest, "llm_mutator"), description, (), True), "+ full new SKILL.md (CAPTURED)"

    async def _edit_body(self, body: str, ctx: EvolutionContext, llm: Any | None) -> str:
        if llm is None:
            return body
        prompt = (f"修复方向: {ctx.fix_direction}\n当前 SKILL.md body:\n{body}\n"
                  f"只改一个 section，最多改 {self._max_changed_lines} 行；只返 body 全文。")
        try:
            value = llm.complete_simple(prompt) if hasattr(llm, "complete_simple") else llm.invoke(prompt)
            if inspect.isawaitable(value):
                value = await value
            return str(getattr(value, "content", value))
        except Exception:
            return body

    async def _generate(self, ctx: EvolutionContext, llm: Any) -> str:
        prompt = f"可复用模式: {ctx.capture_pattern}\n建议名称: {ctx.suggested_name}\n生成完整 SKILL.md，含 name 与 description frontmatter。"
        value = llm.complete_simple(prompt) if hasattr(llm, "complete_simple") else llm.invoke(prompt)
        if inspect.isawaitable(value):
            value = await value
        return str(getattr(value, "content", value))

    async def _read(self, path: str) -> str:
        import asyncio
        return await asyncio.to_thread(Path(path).read_text, encoding="utf-8")

    def _write_candidate(self, candidate_id: str, content: str) -> Path:
        directory = self._root / "skills" / candidate_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "SKILL.md"
        path.write_text(content, encoding="utf-8")
        (directory / ".skill_id").write_text(candidate_id, encoding="utf-8")
        return path

    @staticmethod
    def _split_frontmatter(content: str) -> tuple[str, str]:
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                return "---" + parts[1] + "---\n", parts[2].lstrip("\r\n")
        return "", content

    @staticmethod
    def _frontmatter_field(frontmatter: str, field: str) -> str:
        match = re.search(rf"^{re.escape(field)}:\s*(.+)$", frontmatter, re.MULTILINE)
        return match.group(1).strip().strip("\"'") if match else ""

    @staticmethod
    def _set_frontmatter(frontmatter: str, field: str, value: str) -> str:
        line = f"{field}: {value}"
        pattern = rf"^{re.escape(field)}:.*$"
        if re.search(pattern, frontmatter, flags=re.MULTILINE):
            return re.sub(pattern, line, frontmatter, count=1, flags=re.MULTILINE)
        closing = frontmatter.rfind("---")
        if closing < 0:
            return f"---\n{line}\n---\n"
        return frontmatter[:closing] + line + "\n---\n"

    @staticmethod
    def _enforce_budget(original: str, new: str, budget: int) -> str:
        old_lines, new_lines = original.splitlines(), new.splitlines()
        opcodes = difflib.SequenceMatcher(a=old_lines, b=new_lines).get_opcodes()
        changed = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in opcodes if tag != "equal")
        if changed <= budget:
            return new
        result: list[str] = []
        applied = 0
        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                result.extend(old_lines[i1:i2]); continue
            remaining = max(0, budget - applied)
            count = min(remaining, j2 - j1)
            result.extend(new_lines[j1:j1 + count])
            applied += count
            if count < j2 - j1 and tag == "replace":
                result.extend(old_lines[i1 + count:i2])
            elif count == 0:
                result.extend(old_lines[i1:i2])
        return "\n".join(result) + ("\n" if new.endswith("\n") else "")

    @staticmethod
    def _compute_diff(original: str, new: str) -> str:
        return "".join(difflib.unified_diff(original.splitlines(True), new.splitlines(True), fromfile="body", tofile="body_edited", n=2))


__all__ = ["LLMMutator"]
