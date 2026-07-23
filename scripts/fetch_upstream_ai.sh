#!/usr/bin/env bash
# Back-compat wrapper — prefer scripts/fetch_upstream.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/scripts/fetch_upstream.sh" ai
