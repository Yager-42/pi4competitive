"""CLI entry: uv run python -m eval --stage smoke (D12)."""
from __future__ import annotations

import argparse
import asyncio
import sys

from eval.orchestrator import run_smoke


def main() -> int:
    p = argparse.ArgumentParser(prog="eval.run")
    p.add_argument("--stage", default="smoke", choices=["smoke", "pilot"])
    p.add_argument("--benchmark", default="widesearch", choices=["widesearch", "drb2"])
    p.add_argument("--variants", default="a1,a2")
    p.add_argument("--manifest", default="eval/manifests/widesearch_smoke.jsonl")
    p.add_argument("--app-url", default="http://127.0.0.1:8000")
    p.add_argument("--a1-url", default="http://127.0.0.1:8001")
    args = p.parse_args()

    if args.benchmark == "drb2":
        print("DRB II not wired (D1 C2-wide)", file=sys.stderr)
        return 2

    variants = args.variants.split(",")
    run_id = asyncio.run(run_smoke(
        manifest_path=args.manifest, variants=variants,
        app_url=args.app_url, a1_url=args.a1_url,
    ))
    print(f"run complete: {run_id}")
    print(f"  data/evaluations/{run_id}/scores/widesearch.jsonl")
    print(f"  data/evaluations/{run_id}/scores/paired_deltas.json")
    print(f"  data/evaluations/{run_id}/summary/metrics.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
