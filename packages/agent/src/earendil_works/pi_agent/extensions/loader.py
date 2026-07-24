"""Python extension loading.

upstream: packages/coding-agent/src/core/extensions/loader.ts
host-delta: TypeScript/jiti becomes Python/importlib.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from .types import (
    Extension, ExtensionAPI, ExtensionFactory, ExtensionRuntime, LoadExtensionsResult, SourceInfo,
)


def create_extension_runtime() -> ExtensionRuntime:
    return ExtensionRuntime()


def _create_extension(path: str, resolved: str) -> Extension:
    base = None if path.startswith("<") else str(Path(resolved).parent)
    source = path[1:-1].split(":", 1)[0] if path.startswith("<") else "local"
    return Extension(path, resolved, SourceInfo(path=path, source=source, baseDir=base))


async def load_extension_from_factory(
    factory: ExtensionFactory,
    cwd: str | Path,
    runtime: ExtensionRuntime,
    extension_path: str = "<inline>",
) -> Extension:
    extension = _create_extension(extension_path, extension_path)
    result = factory(ExtensionAPI(extension, runtime))
    if asyncio.iscoroutine(result):
        await result
    return extension


def _import_file(path: Path) -> ModuleType:
    name = f"pi_extension_{abs(hash(str(path))) & 0xFFFFFFFF:x}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot create import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


async def load_extensions(
    paths: list[str | Path],
    cwd: str | Path,
    runtime: ExtensionRuntime | None = None,
) -> LoadExtensionsResult:
    resolved_runtime = runtime or create_extension_runtime()
    resolved_cwd = Path(cwd).resolve()
    extensions: list[Extension] = []
    errors: list[dict[str, str]] = []

    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = resolved_cwd / path
        path = path.resolve()
        if not path.is_file() or path.suffix != ".py":
            errors.append({"path": str(raw_path), "error": f"Extension is not a Python file: {path}"})
            continue
        try:
            module = _import_file(path)
            factory: Any = getattr(module, "register", None)
            if not callable(factory):
                extensions.append(_create_extension(str(raw_path), str(path)))
                continue
            extension = await load_extension_from_factory(
                factory, resolved_cwd, resolved_runtime, str(raw_path)
            )
            extension.resolvedPath = str(path)
            extensions.append(extension)
        except Exception as exc:  # noqa: BLE001
            errors.append({"path": str(raw_path), "error": f"Failed to load extension: {exc}"})

    return LoadExtensionsResult(extensions, errors, resolved_runtime)


__all__ = ["create_extension_runtime", "load_extension_from_factory", "load_extensions"]
