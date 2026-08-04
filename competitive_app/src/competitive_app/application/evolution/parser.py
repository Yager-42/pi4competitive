"""SKILL.md parser adapted from Poirot.

Upstream: https://github.com/HezaoHezao/poirot/blob/86bf279ad90c180f0ba696755620dd7d6661465e/poirot/backend/agents/skill/parser.py
Frozen SHA: 86bf279ad90c180f0ba696755620dd7d6661465e
Copyright (c) HezaoHezao; upstream project MIT licensed.
Host delta: learned-skills root/layout and async wrappers; no remote Hub/install
path. ``.skill_id``, UUID8, hash16, YAML/frontmatter, enabled and allowed-tools
semantics are preserved.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

import yaml

from ...domain.evolution.skill_types import SkillLineage, SkillRecord

_SKILL_ID_FILE = ".skill_id"
_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)", re.DOTALL)
_NAME_RE = re.compile(r"[a-z0-9-]+")


def _generate_skill_id(name: str, origin: str, generation: int = 0) -> str:
    if origin == "BUILTIN":
        return f"{name}__builtin"
    short = uuid.uuid4().hex[:8]
    if origin == "IMPORTED":
        return f"{name}__imp_{short}"
    return f"{name}__v{generation}_{short}"


def read_or_create_skill_id(
    skill_dir: Path, name: str, origin: str = "IMPORTED", generation: int = 0
) -> str:
    if origin == "BUILTIN":
        return _generate_skill_id(name, origin, generation)
    sidecar = skill_dir / _SKILL_ID_FILE
    if sidecar.is_file():
        value = sidecar.read_text(encoding="utf-8").strip()
        if value:
            return value
    skill_dir.mkdir(parents=True, exist_ok=True)
    value = _generate_skill_id(name, origin, generation)
    sidecar.write_text(value, encoding="utf-8")
    return value


def _frontmatter(content: str, path: Path) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise ValueError(f"SKILL.md {path} missing YAML frontmatter")
    try:
        raw = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"SKILL.md {path} frontmatter YAML parse error: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"SKILL.md {path} frontmatter must be a mapping")
    return raw, match.group(2)


def parse_skill_file(
    skill_file: Path | str,
    origin: str = "IMPORTED",
    generation: int = 0,
) -> SkillRecord:
    path = Path(skill_file)
    content = path.read_text(encoding="utf-8")
    fm, _body = _frontmatter(content, path)
    name = fm.get("name")
    description = fm.get("description")
    if not isinstance(name, str) or not name:
        raise ValueError(f"SKILL.md {path} frontmatter missing required field 'name'")
    if not isinstance(description, str) or not description:
        raise ValueError(f"SKILL.md {path} frontmatter missing required field 'description'")
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"invalid skill name: {name!r}")
    allowed_raw = fm.get("allowed-tools") or fm.get("allowed_tools") or []
    if isinstance(allowed_raw, str):
        allowed = (allowed_raw,)
    elif isinstance(allowed_raw, (list, tuple)):
        allowed = tuple(str(v) for v in allowed_raw)
    else:
        raise ValueError("allowed-tools must be a list or string")
    enabled_raw = fm.get("enabled", True)
    if isinstance(enabled_raw, str):
        normalized = enabled_raw.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            enabled = True
        elif normalized in {"false", "no", "off", "0"}:
            enabled = False
        else:
            raise ValueError("enabled must be a boolean")
    elif isinstance(enabled_raw, bool):
        enabled = enabled_raw
    else:
        raise ValueError("enabled must be a boolean")
    skill_id = read_or_create_skill_id(path.parent, name, origin, generation)
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return SkillRecord(
        skill_id=skill_id,
        name=name,
        path=str(path),
        content_hash=content_hash,
        is_active=True,
        lineage=SkillLineage(
            generation=generation,
            origin=origin,
            version_hash=content_hash,
            created_by=fm.get("created-by") if isinstance(fm.get("created-by"), str) else None,
        ),
        description=description,
        allowed_tools=allowed,
        enabled=enabled,
    )


async def parse_skill_file_async(skill_file: Path | str, origin: str = "IMPORTED", generation: int = 0) -> SkillRecord:
    """Async filesystem boundary; delegates the pure parser to a worker thread."""
    import asyncio
    return await asyncio.to_thread(parse_skill_file, skill_file, origin, generation)


def scope_from_skill_file(skill_file: Path | str) -> str | None:
    """Read optional scope metadata without changing the original SkillRecord."""
    path = Path(skill_file)
    try:
        fm, _ = _frontmatter(path.read_text(encoding="utf-8"), path)
    except (OSError, ValueError):
        return None
    value = fm.get("scope")
    return value if value in {"plan", "search", "extraction", "write"} else None


def install_local(source_dir: Path | str, name: str, dest_root: Path | str) -> str:
    """Copy and validate a local skill without destroying a valid install."""
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"invalid skill name: {name!r}")
    source = Path(source_dir)
    if not source.is_dir():
        raise NotADirectoryError(f"skill source directory not found: {source}")
    source_skill = source / "SKILL.md"
    if not source_skill.is_file():
        raise FileNotFoundError(f"skill source dir {source} has no SKILL.md")
    parse_skill_file(source_skill, origin="BUILTIN")

    destination = Path(dest_root) / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=str(destination.parent)))
    staged = staging_root / name
    try:
        shutil.copytree(source, staged)
        parse_skill_file(staged / "SKILL.md")
        if destination.exists():
            shutil.rmtree(destination)
        staged.replace(destination)
        return parse_skill_file(destination / "SKILL.md").skill_id
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


# Compatibility alias for the upstream local-copy helper; no remote operation.
install = install_local

__all__ = [
    "parse_skill_file", "parse_skill_file_async", "read_or_create_skill_id",
    "scope_from_skill_file", "install_local", "install",
]
