"""Local resource collection helpers.

upstream: packages/coding-agent/src/core/package-manager.ts
  collectFiles, collectSkillEntries, collectAutoExtensionEntries,
  collectResourceFiles, readPiManifest, applyPatterns, filters
"""
from __future__ import annotations

import json
import re
from fnmatch import fnmatch
from pathlib import Path

from .types import FILE_PATTERNS, PiManifest, ResourceType

_EXTENSION_RE = re.compile(FILE_PATTERNS["extensions"])
_SKILL_RE = re.compile(FILE_PATTERNS["skills"])
_PROMPT_RE = re.compile(FILE_PATTERNS["prompts"])
_THEME_RE = re.compile(FILE_PATTERNS["themes"])

_PATTERN_RES: dict[ResourceType, re.Pattern[str]] = {
    "extensions": _EXTENSION_RE,
    "skills": _SKILL_RE,
    "prompts": _PROMPT_RE,
    "themes": _THEME_RE,
}

_SKIP_DIR_NAMES = frozenset({"node_modules", "__pycache__", ".git", ".venv", "venv"})


def to_posix_path(p: str | Path) -> str:
    return str(p).replace("\\", "/")


def has_glob_pattern(s: str) -> bool:
    return any(ch in s for ch in ("*", "?", "[", "{"))


def is_override_pattern(s: str) -> bool:
    return s.startswith("!") or s.startswith("+") or s.startswith("-")


def is_pattern(s: str) -> bool:
    return is_override_pattern(s) or has_glob_pattern(s)


def split_patterns(entries: list[str]) -> tuple[list[str], list[str]]:
    plain: list[str] = []
    patterns: list[str] = []
    for entry in entries:
        if is_pattern(entry):
            patterns.append(entry)
        else:
            plain.append(entry)
    return plain, patterns


def _should_skip_name(name: str) -> bool:
    return name.startswith(".") or name in _SKIP_DIR_NAMES


def collect_files(dir_path: Path, file_pattern: re.Pattern[str], *, skip_node_modules: bool = True) -> list[str]:
    """Recursively collect files matching *file_pattern* under *dir_path*."""
    files: list[str] = []
    if not dir_path.is_dir():
        return files

    def walk(current: Path) -> None:
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for entry in entries:
            name = entry.name
            if name.startswith("."):
                continue
            if skip_node_modules and name in _SKIP_DIR_NAMES:
                continue
            try:
                if entry.is_symlink():
                    target = entry.resolve(strict=False)
                    is_dir = target.is_dir()
                    is_file = target.is_file()
                else:
                    is_dir = entry.is_dir()
                    is_file = entry.is_file()
            except OSError:
                continue
            if is_dir:
                walk(entry)
            elif is_file and file_pattern.search(name):
                files.append(str(entry.resolve()))

    walk(dir_path)
    return files


def collect_skill_entries(dir_path: Path, *, mode: str = "pi") -> list[str]:
    """Discover SKILL.md folders + top-level .md skills (mode=pi)."""
    entries: list[str] = []
    if not dir_path.is_dir():
        return entries

    def walk(current: Path, *, is_root: bool) -> None:
        try:
            dir_entries = list(current.iterdir())
        except OSError:
            return

        skill_md = current / "SKILL.md"
        if skill_md.is_file():
            entries.append(str(skill_md.resolve()))
            return

        for entry in sorted(dir_entries, key=lambda p: p.name):
            name = entry.name
            if name.startswith(".") or name in _SKIP_DIR_NAMES:
                continue
            try:
                is_dir = entry.is_dir()
                is_file = entry.is_file()
            except OSError:
                continue
            if mode == "pi" and is_root and is_file and name.endswith(".md"):
                entries.append(str(entry.resolve()))
                continue
            if is_dir:
                walk(entry, is_root=False)

    walk(dir_path, is_root=True)
    return entries


def resolve_extension_entries(dir_path: Path) -> list[str] | None:
    """Explicit extension entries from package.json pi.extensions, index.py, or register.py."""
    package_json = dir_path / "package.json"
    if package_json.is_file():
        manifest = read_pi_manifest(dir_path)
        if manifest and manifest.extensions:
            found: list[str] = []
            for ext_path in manifest.extensions:
                if is_override_pattern(ext_path):
                    continue
                resolved = (dir_path / ext_path).resolve()
                if resolved.exists():
                    found.append(str(resolved))
            if found:
                return found

    for candidate in ("register.py", "index.py"):
        index = dir_path / candidate
        if index.is_file():
            return [str(index.resolve())]
    return None


def collect_auto_extension_entries(dir_path: Path) -> list[str]:
    """Discover Python extension modules under a directory."""
    if not dir_path.is_dir():
        return []

    root_entries = resolve_extension_entries(dir_path)
    if root_entries is not None:
        return root_entries

    entries: list[str] = []
    try:
        dir_entries = sorted(dir_path.iterdir(), key=lambda p: p.name)
    except OSError:
        return entries

    for entry in dir_entries:
        name = entry.name
        if name.startswith(".") or name in _SKIP_DIR_NAMES:
            continue
        try:
            is_dir = entry.is_dir()
            is_file = entry.is_file()
        except OSError:
            continue
        if is_file and name.endswith(".py") and name != "__init__.py":
            entries.append(str(entry.resolve()))
        elif is_dir:
            nested = resolve_extension_entries(entry)
            if nested:
                entries.extend(nested)
    return entries


def collect_resource_files(dir_path: Path, resource_type: ResourceType) -> list[str]:
    if resource_type == "skills":
        return collect_skill_entries(dir_path, mode="pi")
    if resource_type == "extensions":
        return collect_auto_extension_entries(dir_path)
    return collect_files(dir_path, _PATTERN_RES[resource_type])


def read_pi_manifest(package_root: Path) -> PiManifest | None:
    package_json = package_root / "package.json"
    if not package_json.is_file():
        return None
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    pi = data.get("pi")
    if not isinstance(pi, dict):
        return None
    return PiManifest(
        extensions=_str_list(pi.get("extensions")),
        skills=_str_list(pi.get("skills")),
        prompts=_str_list(pi.get("prompts")),
        themes=_str_list(pi.get("themes")),
    )


def _str_list(value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    return [str(v) for v in value]


def normalize_exact_pattern(pattern: str) -> str:
    normalized = pattern[2:] if pattern.startswith("./") or pattern.startswith(".\\") else pattern
    return to_posix_path(normalized)


def matches_any_pattern(file_path: str, patterns: list[str], base_dir: str) -> bool:
    if not patterns:
        return False
    path = Path(file_path)
    rel = to_posix_path(Path(file_path).resolve().relative_to(Path(base_dir).resolve()) if _is_relative(file_path, base_dir) else path.name)
    name = path.name
    file_posix = to_posix_path(file_path)
    is_skill = name == "SKILL.md"
    parent = path.parent if is_skill else None
    parent_rel = (
        to_posix_path(parent.resolve().relative_to(Path(base_dir).resolve()))
        if is_skill and parent is not None and _is_relative(str(parent), base_dir)
        else None
    )
    parent_name = parent.name if parent is not None else None
    parent_posix = to_posix_path(parent) if parent is not None else None

    for pattern in patterns:
        normalized = to_posix_path(pattern)
        if _match_one(rel, name, file_posix, normalized):
            return True
        if is_skill and (
            (parent_rel and _match_one(parent_rel, parent_name or "", parent_posix or "", normalized))
            or (parent_name and fnmatch(parent_name, normalized))
        ):
            return True
    return False


def matches_any_exact_pattern(file_path: str, patterns: list[str], base_dir: str) -> bool:
    if not patterns:
        return False
    path = Path(file_path)
    rel = (
        to_posix_path(Path(file_path).resolve().relative_to(Path(base_dir).resolve()))
        if _is_relative(file_path, base_dir)
        else path.name
    )
    file_posix = to_posix_path(file_path)
    is_skill = path.name == "SKILL.md"
    parent = path.parent if is_skill else None
    parent_rel = (
        to_posix_path(parent.resolve().relative_to(Path(base_dir).resolve()))
        if is_skill and parent is not None and _is_relative(str(parent), base_dir)
        else None
    )
    parent_posix = to_posix_path(parent) if parent is not None else None

    for pattern in patterns:
        normalized = normalize_exact_pattern(pattern)
        if normalized == rel or normalized == file_posix:
            return True
        if is_skill and (normalized == parent_rel or normalized == parent_posix):
            return True
    return False


def apply_patterns(all_paths: list[str], patterns: list[str], base_dir: str) -> set[str]:
    """Apply include / !exclude / +force / -force patterns. Returns enabled paths."""
    includes: list[str] = []
    excludes: list[str] = []
    force_includes: list[str] = []
    force_excludes: list[str] = []

    for p in patterns:
        if p.startswith("+"):
            force_includes.append(p[1:])
        elif p.startswith("-"):
            force_excludes.append(p[1:])
        elif p.startswith("!"):
            excludes.append(p[1:])
        else:
            includes.append(p)

    if not includes:
        result = list(all_paths)
    else:
        result = [fp for fp in all_paths if matches_any_pattern(fp, includes, base_dir)]

    if excludes:
        result = [fp for fp in result if not matches_any_pattern(fp, excludes, base_dir)]

    if force_includes:
        for fp in all_paths:
            if fp not in result and matches_any_exact_pattern(fp, force_includes, base_dir):
                result.append(fp)

    if force_excludes:
        result = [fp for fp in result if not matches_any_exact_pattern(fp, force_excludes, base_dir)]

    return set(result)


def collect_files_from_paths(paths: list[str], resource_type: ResourceType) -> list[str]:
    files: list[str] = []
    for p in paths:
        path = Path(p)
        if not path.exists():
            continue
        try:
            if path.is_file():
                files.append(str(path.resolve()))
            elif path.is_dir():
                files.extend(collect_resource_files(path, resource_type))
        except OSError:
            continue
    return files


def collect_files_from_manifest_entries(
    entries: list[str],
    root: Path,
    resource_type: ResourceType,
) -> list[str]:
    source_entries = [e for e in entries if not is_override_pattern(e)]
    resolved: list[str] = []
    for entry in source_entries:
        if not has_glob_pattern(entry):
            resolved.append(str((root / entry).resolve()))
            continue
        # pathlib glob relative to package root
        for match in root.glob(entry):
            resolved.append(str(match.resolve()))
    return collect_files_from_paths(resolved, resource_type)


def _is_relative(path: str, base_dir: str) -> bool:
    try:
        Path(path).resolve().relative_to(Path(base_dir).resolve())
        return True
    except ValueError:
        return False


def _match_one(rel: str, name: str, file_posix: str, pattern: str) -> bool:
    return (
        fnmatch(rel, pattern)
        or fnmatch(name, pattern)
        or fnmatch(file_posix, pattern)
        or _path_match(rel, pattern)
    )


def _path_match(rel: str, pattern: str) -> bool:
    try:
        return Path(rel).match(pattern)
    except (ValueError, re.error):
        return False


__all__ = [
    "apply_patterns",
    "collect_auto_extension_entries",
    "collect_files",
    "collect_files_from_manifest_entries",
    "collect_files_from_paths",
    "collect_resource_files",
    "collect_skill_entries",
    "has_glob_pattern",
    "is_override_pattern",
    "is_pattern",
    "matches_any_exact_pattern",
    "matches_any_pattern",
    "normalize_exact_pattern",
    "read_pi_manifest",
    "resolve_extension_entries",
    "split_patterns",
    "to_posix_path",
]
