"""Unit: collect + LocalPackageManager.resolve local-only."""
from __future__ import annotations

from pathlib import Path

import pytest

from earendil_works.pi_agent.package_manager import LocalPackageManager, load_capability_packages_sync
from earendil_works.pi_agent.package_manager.collect import (
    apply_patterns,
    collect_resource_files,
    read_pi_manifest,
)

ROOT = Path(__file__).resolve().parents[3]
CAP_ROOT = ROOT / "capability_packages"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def tmp_pkg_root(tmp_path: Path) -> Path:
    root = tmp_path / "capability_packages"
    root.mkdir()
    return root


def test_echo_example_package_on_disk() -> None:
    assert (CAP_ROOT / "echo_example" / "package.json").is_file()
    assert (CAP_ROOT / "echo_example" / "extensions" / "echo_tools.py").is_file()


def test_read_pi_manifest_echo_example() -> None:
    manifest = read_pi_manifest(CAP_ROOT / "echo_example")
    assert manifest is not None
    assert manifest.extensions == ["./extensions"]


def test_resolve_echo_example() -> None:
    pm = LocalPackageManager(root=CAP_ROOT, enabled=["echo_example"])
    resolved = pm.resolve_sync()
    assert resolved.extensions
    assert any(Path(r.path).name == "echo_tools.py" for r in resolved.extensions)
    assert all(r.metadata.origin == "package" for r in resolved.extensions)
    assert all(r.metadata.scope == "project" for r in resolved.extensions)


def test_resolve_respects_disabled() -> None:
    pm = LocalPackageManager(root=CAP_ROOT, disabled=["echo_example"])
    resolved = pm.resolve_sync()
    assert not any("echo_example" in r.path for r in resolved.extensions)


def test_resolve_empty_root(tmp_pkg_root: Path) -> None:
    pm = LocalPackageManager(root=tmp_pkg_root)
    resolved = pm.resolve_sync()
    assert resolved.extensions == []
    assert resolved.skills == []


def test_convention_dirs_without_manifest(tmp_pkg_root: Path) -> None:
    pkg = tmp_pkg_root / "conv_pkg"
    (pkg / "extensions").mkdir(parents=True)
    (pkg / "skills").mkdir()
    (pkg / "extensions" / "tool_a.py").write_text(
        "def register(api):\n    pass\n",
        encoding="utf-8",
    )
    (pkg / "skills" / "hello.md").write_text(
        "---\nname: hello\ndescription: hi\n---\nbody\n",
        encoding="utf-8",
    )
    pm = LocalPackageManager(root=tmp_pkg_root)
    resolved = pm.resolve_sync()
    assert any(Path(r.path).name == "tool_a.py" for r in resolved.extensions)
    assert any(Path(r.path).name == "hello.md" for r in resolved.skills)


def test_root_register_py_host_delta(tmp_pkg_root: Path) -> None:
    pkg = tmp_pkg_root / "root_reg"
    pkg.mkdir()
    (pkg / "register.py").write_text("def register(api):\n    pass\n", encoding="utf-8")
    pm = LocalPackageManager(root=tmp_pkg_root)
    resolved = pm.resolve_sync()
    assert any(Path(r.path).name == "register.py" for r in resolved.extensions)


def test_apply_patterns_exclude_and_force() -> None:
    base = "/pkg"
    paths = [
        "/pkg/extensions/a.py",
        "/pkg/extensions/b.py",
        "/pkg/extensions/legacy.py",
    ]
    # include all then exclude legacy
    enabled = apply_patterns(paths, ["extensions/*.py", "!extensions/legacy.py"], base)
    assert "/pkg/extensions/a.py" in enabled
    assert "/pkg/extensions/legacy.py" not in enabled


def test_collect_resource_files_extensions(tmp_pkg_root: Path) -> None:
    ext = tmp_pkg_root / "p" / "extensions"
    ext.mkdir(parents=True)
    (ext / "x.py").write_text("pass\n", encoding="utf-8")
    (ext / "__init__.py").write_text("pass\n", encoding="utf-8")
    files = collect_resource_files(ext, "extensions")
    names = {Path(f).name for f in files}
    assert "x.py" in names
    assert "__init__.py" not in names


def test_load_capability_packages_sync_echo() -> None:
    report = load_capability_packages_sync(root=CAP_ROOT, enabled=["echo_example"])
    assert "echo" in report.tool_names()
    assert report.root == CAP_ROOT.resolve()
