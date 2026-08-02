"""O22 — native sandbox ownership/import/config/no-Docker/no-Host-IPC contract.

G0 map §8.1: production AgentTool sandbox composition is native-only. This
suite proves the absence surface from the source tree: no Docker modules,
no agent-sandbox dependency, no Host IPC surface, no App imports from
packages/agent, and the retained Poirot notices + native license directory.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SANDBOX_SRC = ROOT / "competitive_app/src/competitive_app/adapter/out/sandbox"
COMPETITIVE_SRC = ROOT / "competitive_app/src"
AGENT_SRC = ROOT / "packages/agent/src"


def _py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "vendor" not in p.parts)


def test_no_docker_imports_or_modules_remain() -> None:
    docker_surface = (
        SANDBOX_SRC / "docker",
        SANDBOX_SRC / "runtimes",
        SANDBOX_SRC / "translators",
        SANDBOX_SRC / "guards",
        SANDBOX_SRC / "contracts" / "sandbox_backend.py",
    )
    for path in docker_surface:
        assert not any(p.is_file() and p.suffix == ".py" for p in path.rglob("*")) if path.exists() else True, path
    forbidden = re.compile(
        r"^\s*(import|from)\s+\S*(sandbox\.docker|docker_runtime|docker_path_|"
        r"local_container_backend|audit_guard)\b",
        re.MULTILINE,
    )
    offenders = [str(p) for p in _py_files(COMPETITIVE_SRC) if forbidden.search(p.read_text(encoding="utf-8"))]
    assert not offenders, offenders


def test_no_agent_sandbox_dependency_in_project_files() -> None:
    for project_file in (ROOT / "competitive_app" / "pyproject.toml", ROOT / "uv.lock"):
        text = project_file.read_text(encoding="utf-8")
        assert "agent-sandbox" not in text, project_file


def test_no_host_ipc_surface() -> None:
    # Only the documented OMIT header (approval.py) and the schema rejection
    # (config.py) may name Host IPC; no module, import, or accepted config.
    assert not (SANDBOX_SRC / "host_ipc.py").exists()
    assert not (SANDBOX_SRC / "native" / "host_ipc.py").exists()
    forbidden = re.compile(r"host[-_ ]?ipc|hostIpc|approveHostIPC", re.IGNORECASE)
    allowed = {
        SANDBOX_SRC / "native" / "approval.py",  # OMIT header only
        SANDBOX_SRC / "native" / "config.py",  # OMIT header + rejection tuple
    }
    for path in _py_files(SANDBOX_SRC):
        text = path.read_text(encoding="utf-8")
        if not forbidden.search(text):
            continue
        if path not in allowed:
            raise AssertionError(f"Host IPC surface outside documented files: {path}")
        for line in text.splitlines():
            if not forbidden.search(line):
                continue
            stripped = line.lstrip()
            if stripped.startswith(("#", "from ", "import ", "def ", "class ")):
                raise AssertionError(f"Host IPC in code: {path}: {line}")
            if re.match(r"^\w+.*=", stripped) and "_NOT_SUPPORTED_SECTIONS" not in stripped:
                raise AssertionError(f"Host IPC in assignment: {path}: {line}")


def test_wiring_composes_native_only() -> None:
    wiring = (COMPETITIVE_SRC / "competitive_app/wiring.py").read_text(encoding="utf-8")
    assert "NativeSandboxProvider" in wiring
    assert "sandbox.docker" not in wiring
    assert "SANDBOX_IMAGE" not in wiring
    assert not re.search(r'"(?:image|SANDBOX_IMAGE)"\s*[:=]', wiring), "no sandbox image config key"


def test_packages_agent_has_no_app_imports() -> None:
    forbidden = re.compile(r"^\s*(import|from)\s+(competitive_app|capability_packages)\b", re.MULTILINE)
    offenders = [str(p) for p in _py_files(AGENT_SRC) if forbidden.search(p.read_text(encoding="utf-8"))]
    assert not offenders, offenders


def test_poirot_license_notice_retained_in_native_directory() -> None:
    license_file = SANDBOX_SRC / "native" / "vendor" / "licenses" / "POIROT-MIT.txt"
    assert license_file.exists()
    text = license_file.read_text(encoding="utf-8")
    assert "MIT License" in text
    # Retained transplanted files point at the native license directory.
    workspace = (SANDBOX_SRC / "native" / "workspace.py").read_text(encoding="utf-8")
    assert "native/vendor/licenses/POIROT-MIT.txt" in workspace
    for retained in ("sandbox.py", "types.py", "exceptions.py", "utils/sandbox_id.py"):
        header = (SANDBOX_SRC / retained).read_text(encoding="utf-8")
        assert "deploy/tool-sandbox" not in header, retained
