"""Python host environment adapter (cwd, env, paths, FileSystem).

upstream: packages/agent/src/harness/env/nodejs.ts
host-delta: Node APIs → Python stdlib
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..types import FileError, FileInfo, Result, err, ok, to_error


class LocalFileSystem:
    """Local disk FileSystem implementing the harness Result-based contract."""

    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = str(Path(cwd or os.getcwd()).resolve())

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return Path(self.cwd) / p

    async def absolutePath(self, path: str, abort_signal: Any = None) -> Result[str, FileError]:
        try:
            return ok(str(self._resolve(path).resolve()))
        except Exception as e:
            return err(FileError("unknown", str(e), path, to_error(e)))

    async def joinPath(self, parts: list[str], abort_signal: Any = None) -> Result[str, FileError]:
        try:
            if not parts:
                return ok(self.cwd)
            base = Path(parts[0])
            for part in parts[1:]:
                base = base / part
            if not base.is_absolute():
                base = Path(self.cwd) / base
            return ok(str(base))
        except Exception as e:
            return err(FileError("unknown", str(e), cause=to_error(e)))

    async def readTextFile(self, path: str, abort_signal: Any = None) -> Result[str, FileError]:
        p = self._resolve(path)
        try:
            return ok(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return err(FileError("not_found", f"not found: {p}", str(p)))
        except IsADirectoryError:
            return err(FileError("is_directory", f"is directory: {p}", str(p)))
        except PermissionError as e:
            return err(FileError("permission_denied", str(e), str(p), e))
        except Exception as e:
            return err(FileError("unknown", str(e), str(p), to_error(e)))

    async def readTextLines(
        self,
        path: str,
        options: dict[str, Any] | None = None,
        abort_signal: Any = None,
    ) -> Result[list[str], FileError]:
        result = await self.readTextFile(path, abort_signal)
        if not result["ok"]:
            return result  # type: ignore[return-value]
        lines = result["value"].splitlines()
        max_lines = (options or {}).get("maxLines")
        if max_lines is not None:
            lines = lines[: int(max_lines)]
        return ok(lines)

    async def writeFile(self, path: str, content: str, abort_signal: Any = None) -> Result[None, FileError]:
        p = self._resolve(path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ok(None)
        except PermissionError as e:
            return err(FileError("permission_denied", str(e), str(p), e))
        except Exception as e:
            return err(FileError("unknown", str(e), str(p), to_error(e)))

    async def appendFile(self, path: str, content: str, abort_signal: Any = None) -> Result[None, FileError]:
        p = self._resolve(path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(content)
            return ok(None)
        except PermissionError as e:
            return err(FileError("permission_denied", str(e), str(p), e))
        except Exception as e:
            return err(FileError("unknown", str(e), str(p), to_error(e)))

    async def listDir(self, path: str, abort_signal: Any = None) -> Result[list[FileInfo], FileError]:
        p = self._resolve(path)
        try:
            if not p.exists():
                return err(FileError("not_found", f"not found: {p}", str(p)))
            if not p.is_dir():
                return err(FileError("not_directory", f"not a directory: {p}", str(p)))
            out: list[FileInfo] = []
            for child in sorted(p.iterdir(), key=lambda x: x.name):
                kind: str
                if child.is_symlink():
                    kind = "symlink"
                elif child.is_dir():
                    kind = "directory"
                else:
                    kind = "file"
                st = child.lstat()
                out.append(
                    {
                        "name": child.name,
                        "path": str(child.resolve() if kind != "symlink" else child),
                        "kind": kind,  # type: ignore[typeddict-item]
                        "size": int(st.st_size),
                        "mtimeMs": float(st.st_mtime * 1000),
                    }
                )
            return ok(out)
        except PermissionError as e:
            return err(FileError("permission_denied", str(e), str(p), e))
        except Exception as e:
            return err(FileError("unknown", str(e), str(p), to_error(e)))

    async def exists(self, path: str, abort_signal: Any = None) -> Result[bool, FileError]:
        try:
            return ok(self._resolve(path).exists())
        except Exception as e:
            return err(FileError("unknown", str(e), path, to_error(e)))

    async def createDir(
        self,
        path: str,
        options: dict[str, Any] | None = None,
        abort_signal: Any = None,
    ) -> Result[None, FileError]:
        p = self._resolve(path)
        try:
            p.mkdir(parents=bool((options or {}).get("recursive", False)), exist_ok=True)
            return ok(None)
        except FileExistsError:
            return ok(None)
        except PermissionError as e:
            return err(FileError("permission_denied", str(e), str(p), e))
        except Exception as e:
            return err(FileError("unknown", str(e), str(p), to_error(e)))

    async def remove(
        self,
        path: str,
        options: dict[str, Any] | None = None,
        abort_signal: Any = None,
    ) -> Result[None, FileError]:
        p = self._resolve(path)
        force = bool((options or {}).get("force", False))
        try:
            if not p.exists():
                if force:
                    return ok(None)
                return err(FileError("not_found", f"not found: {p}", str(p)))
            if p.is_dir() and not p.is_symlink():
                import shutil

                shutil.rmtree(p)
            else:
                p.unlink()
            return ok(None)
        except PermissionError as e:
            return err(FileError("permission_denied", str(e), str(p), e))
        except Exception as e:
            return err(FileError("unknown", str(e), str(p), to_error(e)))


# camelCase alias
PythonExecutionEnv = LocalFileSystem

__all__ = ["LocalFileSystem", "PythonExecutionEnv"]
