"""CompetitorLens benchmark evaluation harness.

Spec: docs/superpowers/specs/2026-08-10-eval-harness-design.md
Drives competitive_app (A2) + single_agent service (A1) over HTTP (W1),
normalizes output, runs official WideSearch scorer in an isolated evaluator
process. Gold isolated by tool-surface裁剪 + cwd + evaluator process (D6).
"""

__version__ = "0.0.1"
