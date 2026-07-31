"""Image-side minimal package marker for the AgentTool worker.

The host ``sandbox/__init__.py`` imports the host approved registry, which
imports ``earendil_works.pi_agent`` types (the host control plane).  The
derived worker image must not contain the Pi control plane, so this file
replaces the host initializer inside the image only; the worker imports
``.protocol`` and ``.worker`` directly and validates the baked manifest
instead of the host registry.
"""
from __future__ import annotations
