"""Minimal stdin-echo worker fixture for the direct-invocation test."""
from __future__ import annotations

import sys

data = sys.stdin.buffer.read(65536)
sys.stdout.buffer.write(data)
sys.stdout.buffer.flush()
