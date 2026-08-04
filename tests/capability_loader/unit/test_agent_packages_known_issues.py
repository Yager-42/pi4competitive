from __future__ import annotations

import os
from pathlib import Path

import pytest

from earendil_works.pi_agent.package_manager import LocalPackageManager
from earendil_works.pi_agent.package_manager.collect import (
    collect_files_from_manifest_entries,
    collect_resource_files,
)


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


def test_collectors_reject_symlink_targets_outside_boundary(tmp_path: Path) -> None:
    package = tmp_path / "package"
    skills = package / "skills"
    extensions = package / "extensions"
    skills.mkdir(parents=True)
    extensions.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("outside", encoding="utf-8")
    (outside / "escape.py").write_text("outside", encoding="utf-8")
    _symlink_or_skip(skills / "escape", outside)
    _symlink_or_skip(extensions / "escape.py", outside / "escape.py")

    assert collect_resource_files(skills, "skills", boundary=package) == []
    assert collect_resource_files(extensions, "extensions", boundary=package) == []


def test_manifest_literal_and_glob_entries_stay_inside_package(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "inside.py").write_text("inside", encoding="utf-8")
    (tmp_path / "outside.py").write_text("outside", encoding="utf-8")

    assert collect_files_from_manifest_entries(["../outside.py"], package, "extensions") == []
    assert collect_files_from_manifest_entries(["../*.py"], package, "extensions") == []
    assert [Path(p).name for p in collect_files_from_manifest_entries(["*.py"], package, "extensions")] == ["inside.py"]


def test_package_manager_rejects_package_symlink_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "capability_packages"
    root.mkdir()
    outside = tmp_path / "external_package"
    (outside / "extensions").mkdir(parents=True)
    (outside / "extensions" / "escape.py").write_text("outside", encoding="utf-8")
    _symlink_or_skip(root / "escape", outside)

    resolved = LocalPackageManager(root=root).resolve_sync()
    assert not resolved.extensions
