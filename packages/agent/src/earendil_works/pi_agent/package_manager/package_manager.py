"""Local-only package manager.

upstream: packages/coding-agent/src/core/package-manager.ts
  DefaultPackageManager.resolve local path packages only (ADR 0006).

Omit: install / remove / update / npm / git / ~/.pi / temp installs.
"""
from __future__ import annotations

from pathlib import Path

from . import collect as C
from .errors import UnsupportedInstallError
from .types import (
    PACKAGE_ROOT_DEFAULT,
    RESOURCE_TYPES,
    PackageFilter,
    PathMetadata,
    ResourceAccumulator,
    ResourceMap,
    ResourceType,
    ResolvedPaths,
    ResolvedResource,
)


def resource_precedence_rank(m: PathMetadata) -> int:
    """Lower rank = higher precedence (upstream resourcePrecedenceRank)."""
    if m.origin == "package":
        return 4
    scope_base = 0 if m.scope == "project" else 2
    return scope_base + (0 if m.source == "local" else 1)


def default_capability_root(cwd: Path | None = None) -> Path:
    base = Path(cwd) if cwd is not None else Path.cwd()
    return (base / PACKAGE_ROOT_DEFAULT).resolve()


class LocalPackageManager:
    """Resolve resources under a fixed local capability_packages root.

    Each immediate child directory is one local package source.
    Identity = resolved absolute path (upstream local identity rule).
    """

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        enabled: list[str] | None = None,
        disabled: list[str] | None = None,
        cwd: Path | str | None = None,
    ) -> None:
        if root is None:
            self.root = default_capability_root(Path(cwd) if cwd is not None else None)
        else:
            self.root = Path(root).resolve()
        self.enabled = set(enabled) if enabled is not None else None
        self.disabled = set(disabled or [])

    def list_package_dirs(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        dirs: list[Path] = []
        try:
            children = sorted(self.root.iterdir(), key=lambda p: p.name)
        except OSError:
            return []
        for child in children:
            try:
                resolved_child = child.resolve(strict=False)
                resolved_child.relative_to(self.root)
            except (OSError, RuntimeError, ValueError):
                continue
            if resolved_child == self.root or not resolved_child.is_dir():
                continue
            if child.name.startswith(".") or child.name == "__pycache__":
                continue
            if self.disabled and child.name in self.disabled:
                continue
            if self.enabled is not None and child.name not in self.enabled:
                continue
            dirs.append(resolved_child)
        return dirs

    async def resolve(self) -> ResolvedPaths:
        """Async for upstream isomorphism; all work is local FS."""
        return self.resolve_sync()

    def resolve_sync(self) -> ResolvedPaths:
        accumulator = self._create_accumulator()
        for package_dir in self.list_package_dirs():
            metadata = PathMetadata(
                source=package_dir.name,
                scope="project",
                origin="package",
                baseDir=str(package_dir),
            )
            self._collect_package_resources(package_dir, accumulator, filter=None, metadata=metadata)
        return self._to_resolved_paths(accumulator)

    # ------------------------------------------------------------------
    # Explicitly omitted install surfaces (contract-tested)
    # ------------------------------------------------------------------

    def install(self, *_args: object, **_kwargs: object) -> None:
        raise UnsupportedInstallError("install is omitted (ADR 0006 local-only)")

    def install_and_persist(self, *_args: object, **_kwargs: object) -> None:
        raise UnsupportedInstallError("installAndPersist is omitted (ADR 0006 local-only)")

    def remove(self, *_args: object, **_kwargs: object) -> None:
        raise UnsupportedInstallError("remove is omitted (ADR 0006 local-only)")

    def update(self, *_args: object, **_kwargs: object) -> None:
        raise UnsupportedInstallError("update is omitted (ADR 0006 local-only)")

    def check_for_available_updates(self, *_args: object, **_kwargs: object) -> None:
        raise UnsupportedInstallError("checkForAvailableUpdates is omitted (ADR 0006 local-only)")

    # ------------------------------------------------------------------
    # collect package resources (local subset of collectPackageResources)
    # ------------------------------------------------------------------

    def _collect_package_resources(
        self,
        package_root: Path,
        accumulator: ResourceAccumulator,
        filter: PackageFilter | None,
        metadata: PathMetadata,
    ) -> bool:
        if filter is not None:
            for resource_type in RESOURCE_TYPES:
                patterns = getattr(filter, resource_type)
                target = self._get_target_map(accumulator, resource_type)
                if filter.autoload is False:
                    self._apply_package_delta_filter(package_root, patterns or [], resource_type, target, metadata)
                elif patterns is not None:
                    self._apply_package_filter(package_root, patterns, resource_type, target, metadata)
                else:
                    self._collect_default_resources(package_root, resource_type, target, metadata)
            return True

        manifest = C.read_pi_manifest(package_root)
        if manifest is not None:
            for resource_type in RESOURCE_TYPES:
                entries = getattr(manifest, resource_type)
                self._add_manifest_entries(
                    entries,
                    package_root,
                    resource_type,
                    self._get_target_map(accumulator, resource_type),
                    metadata,
                )
            return True
        has_any_dir = False
        for resource_type in RESOURCE_TYPES:
            directory = package_root / resource_type
            if directory.is_dir():
                files = C.collect_resource_files(directory, resource_type, boundary=package_root)
                target = self._get_target_map(accumulator, resource_type)
                for f in files:
                    self._add_resource(target, f, metadata, True)
                has_any_dir = True

        # Host-delta: package-root register.py / index.py as single extension
        if not has_any_dir:
            root_ext = C.resolve_extension_entries(package_root, boundary=package_root)
            if root_ext:
                target = self._get_target_map(accumulator, "extensions")
                for f in root_ext:
                    self._add_resource(target, f, metadata, True)
                return True
        else:
            # Also pick up root-level register.py alongside convention dirs
            for candidate in ("register.py", "index.py"):
                reg = C._resolve_within(package_root / candidate, package_root)
                if reg is not None and reg.is_file():
                    self._add_resource(
                        self._get_target_map(accumulator, "extensions"),
                        str(reg),
                        metadata,
                        True,
                    )
        return has_any_dir

    def _collect_default_resources(
        self,
        package_root: Path,
        resource_type: ResourceType,
        target: ResourceMap,
        metadata: PathMetadata,
    ) -> None:
        manifest = C.read_pi_manifest(package_root)
        entries = getattr(manifest, resource_type) if manifest else None
        if entries:
            self._add_manifest_entries(entries, package_root, resource_type, target, metadata)
            return
        directory = package_root / resource_type
        if directory.is_dir():
            for f in C.collect_resource_files(directory, resource_type, boundary=package_root):
                self._add_resource(target, f, metadata, True)

    def _apply_package_filter(
        self,
        package_root: Path,
        user_patterns: list[str],
        resource_type: ResourceType,
        target: ResourceMap,
        metadata: PathMetadata,
    ) -> None:
        all_files, _ = self._collect_manifest_files(package_root, resource_type)
        if len(user_patterns) == 0:
            for f in all_files:
                self._add_resource(target, f, metadata, False)
            return
        enabled = C.apply_patterns(all_files, user_patterns, str(package_root))
        for f in all_files:
            self._add_resource(target, f, metadata, f in enabled)

    def _apply_package_delta_filter(
        self,
        package_root: Path,
        user_patterns: list[str],
        resource_type: ResourceType,
        target: ResourceMap,
        metadata: PathMetadata,
    ) -> None:
        if not user_patterns:
            return
        all_files, _ = self._collect_manifest_files(package_root, resource_type)
        for pattern in user_patterns:
            target_pat = pattern[1:] if pattern[:1] in {"+", "-", "!"} else pattern
            enabled = not pattern.startswith("-") and not pattern.startswith("!")
            exact = pattern.startswith("+") or pattern.startswith("-")
            for file_path in all_files:
                matched = (
                    C.matches_any_exact_pattern(file_path, [target_pat], str(package_root))
                    if exact
                    else C.matches_any_pattern(file_path, [target_pat], str(package_root))
                )
                if matched:
                    self._add_resource(target, file_path, metadata, enabled)

    def _collect_manifest_files(
        self,
        package_root: Path,
        resource_type: ResourceType,
    ) -> tuple[list[str], set[str]]:
        manifest = C.read_pi_manifest(package_root)
        entries = getattr(manifest, resource_type) if manifest else None
        if entries and len(entries) > 0:
            all_files = C.collect_files_from_manifest_entries(entries, package_root, resource_type)
            manifest_patterns = [e for e in entries if C.is_override_pattern(e)]
            enabled = (
                C.apply_patterns(all_files, manifest_patterns, str(package_root))
                if manifest_patterns
                else set(all_files)
            )
            return list(enabled), enabled

        convention_dir = package_root / resource_type
        if not convention_dir.is_dir():
            return [], set()
        all_files = C.collect_resource_files(convention_dir, resource_type, boundary=package_root)
        return all_files, set(all_files)

    def _add_manifest_entries(
        self,
        entries: list[str] | None,
        root: Path,
        resource_type: ResourceType,
        target: ResourceMap,
        metadata: PathMetadata,
    ) -> None:
        if not entries:
            return
        all_files = C.collect_files_from_manifest_entries(entries, root, resource_type)
        patterns = [e for e in entries if C.is_override_pattern(e)]
        enabled_paths = C.apply_patterns(all_files, patterns, str(root)) if patterns else set(all_files)
        # When patterns exist, only patterns that are pure overrides still start from all;
        # apply_patterns already handles empty includes → all.
        if not patterns:
            enabled_paths = set(all_files)
        for f in all_files:
            if f in enabled_paths:
                self._add_resource(target, f, metadata, True)

    @staticmethod
    def _get_target_map(accumulator: ResourceAccumulator, resource_type: ResourceType) -> ResourceMap:
        return getattr(accumulator, resource_type)

    @staticmethod
    def _add_resource(
        map_: ResourceMap,
        path: str,
        metadata: PathMetadata,
        enabled: bool,
    ) -> None:
        if not path:
            return
        if path not in map_:
            map_[path] = {"metadata": metadata, "enabled": enabled}

    @staticmethod
    def _create_accumulator() -> ResourceAccumulator:
        return ResourceAccumulator()

    def _to_resolved_paths(self, accumulator: ResourceAccumulator) -> ResolvedPaths:
        return ResolvedPaths(
            extensions=self._map_to_resolved(accumulator.extensions),
            skills=self._map_to_resolved(accumulator.skills),
            prompts=self._map_to_resolved(accumulator.prompts),
            themes=self._map_to_resolved(accumulator.themes),
        )

    @staticmethod
    def _map_to_resolved(entries: ResourceMap) -> list[ResolvedResource]:
        resolved = [
            ResolvedResource(path=path, enabled=bool(data["enabled"]), metadata=data["metadata"])
            for path, data in entries.items()
        ]
        resolved.sort(key=lambda r: resource_precedence_rank(r.metadata))
        seen: set[str] = set()
        out: list[ResolvedResource] = []
        for entry in resolved:
            key = str(Path(entry.path).resolve())
            if key in seen:
                continue
            seen.add(key)
            out.append(entry)
        return out


__all__ = [
    "LocalPackageManager",
    "default_capability_root",
    "resource_precedence_rank",
]
