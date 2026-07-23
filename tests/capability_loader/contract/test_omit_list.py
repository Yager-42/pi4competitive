"""Contract: package_manager must not ship install/npm/git/home roots."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PM_SRC = ROOT / "packages/agent/src/earendil_works/pi_agent/package_manager"

# Forbidden substrings in shipped package_manager Python (case-sensitive where noted).
FORBIDDEN_SNIPPETS = [
    "npm install",
    "npm:install",
    "git clone",
    "git+ssh",
    "subprocess.Popen",  # no shell-out install helpers
    'homedir()',
    "pathlib.Path.home()",
    "~/.pi",
    "getExtensionTempFolder",
    "installAndPersist",
    "checkForAvailableUpdates",
]

FORBIDDEN_CALL_NAMES = {
    "npm_install",
    "install_npm",
    "install_git",
    "clone_git",
    "git_clone",
}


def _py_files() -> list[Path]:
    return sorted(PM_SRC.rglob("*.py"))


def test_package_manager_package_exists() -> None:
    assert PM_SRC.is_dir()
    assert (PM_SRC / "package_manager.py").is_file()
    assert (PM_SRC / "collect.py").is_file()


def test_no_forbidden_install_snippets() -> None:
    offenders: list[str] = []
    for path in _py_files():
        text = path.read_text(encoding="utf-8")
        for snippet in FORBIDDEN_SNIPPETS:
            if snippet in text:
                # allow mentioning in comments that say "omitted" on same line only for UnsupportedInstallError messages
                for i, line in enumerate(text.splitlines(), 1):
                    if snippet in line and "omit" not in line.lower() and "UnsupportedInstallError" not in line:
                        offenders.append(f"{path.relative_to(ROOT)}:{i}:{snippet}")
    assert not offenders, offenders


def test_no_install_function_bodies_that_run_npm_or_git() -> None:
    """Install methods must raise UnsupportedInstallError, not perform work."""
    pm_file = PM_SRC / "package_manager.py"
    tree = ast.parse(pm_file.read_text(encoding="utf-8"), filename=str(pm_file))
    forbidden_raises_missing = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {
            "install",
            "install_and_persist",
            "remove",
            "update",
            "check_for_available_updates",
        }:
            # body should raise UnsupportedInstallError
            body = node.body
            assert body, f"{node.name} empty"
            first = body[0]
            assert isinstance(first, ast.Raise), f"{node.name} must raise, got {type(first)}"


def test_no_capability_packages_import_as_package() -> None:
    """Extensions load via importlib path — never `import capability_packages`."""
    offenders: list[str] = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "capability_packages":
                        offenders.append(f"{path}:import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] == "capability_packages":
                    offenders.append(f"{path}:from {node.module}")
            elif isinstance(node, ast.ImportFrom) and node.module is None:
                pass
    assert not offenders, offenders


def test_no_competitive_app_imports() -> None:
    offenders: list[str] = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "competitive_app":
                        offenders.append(str(path))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] == "competitive_app":
                    offenders.append(str(path))
    assert not offenders, offenders


def test_unsupported_install_raises() -> None:
    from earendil_works.pi_agent.package_manager import LocalPackageManager, UnsupportedInstallError

    pm = LocalPackageManager(root=ROOT / "capability_packages")
    for method in ("install", "install_and_persist", "remove", "update", "check_for_available_updates"):
        try:
            getattr(pm, method)("npm:evil")
            raise AssertionError(f"{method} should raise")
        except UnsupportedInstallError:
            pass


def test_default_root_name_is_capability_packages() -> None:
    from earendil_works.pi_agent.package_manager import PACKAGE_ROOT_DEFAULT

    assert PACKAGE_ROOT_DEFAULT == "capability_packages"


def test_no_home_pi_path_construction() -> None:
    home_pi = re.compile(r"""['"]~/?\.pi|/agent/npm|/agent/git""")
    offenders: list[str] = []
    for path in _py_files():
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if home_pi.search(line) and "omit" not in line.lower() and "not supported" not in line.lower():
                offenders.append(f"{path.relative_to(ROOT)}:{i}:{line.strip()}")
    assert not offenders, offenders
