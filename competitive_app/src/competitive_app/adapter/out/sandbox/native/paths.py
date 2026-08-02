"""Native identity translator and fixed-command guard (NEW-HOST, Phase D).

P3.3 Phase D: the native worker runs directly on the host inside the SRT
sandbox, so virtual paths ARE host paths and output masking is identity.
The guard's only job is to keep the facade's fixed-worker invariant: the
only command that may be translated/executed is the fixed JSONL worker
invocation (G0 map §6.1: runtime-only Sandbox handle; Docker translator/
guard composition removed).

License: Apache-2.0 (native sandbox license directory)
"""
from __future__ import annotations

from ..exceptions import SandboxPermissionError
from ..sandbox import FIXED_WORKER_COMMAND


class NativePathTranslator:
    """Identity mapping: host path in, host path out, no masking."""

    def translate_path(self, virtual_path: str) -> str:
        return virtual_path

    def translate_command(self, command: str) -> str:
        return command

    def mask_output(self, output: str) -> str:
        return output

    def reverse_translate(self, virtual_path: str) -> str:
        return virtual_path


class NativeSecurityGuard:
    """Only the fixed worker command may pass the facade validate step."""

    def validate_path(self, path: str, *, write: bool = False) -> None:
        del path, write  # host paths; the SRT policy is the boundary

    def validate_command(self, command: str) -> None:
        if command != FIXED_WORKER_COMMAND:
            raise SandboxPermissionError(
                "native sandbox only executes the fixed worker command",
                path=command,
                operation="validate_command",
            )


__all__ = ["NativePathTranslator", "NativeSecurityGuard"]
