"""Built-in harness tools (read/write/edit/bash/…).

upstream: packages/agent/src/harness/tools/*
"""
from __future__ import annotations

from .read import create_read_tool
from .write import create_write_tool


def create_coding_tools() -> list:
    return [create_read_tool(), create_write_tool()]


__all__ = ["create_coding_tools", "create_read_tool", "create_write_tool"]
