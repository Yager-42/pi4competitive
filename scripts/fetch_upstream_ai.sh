#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/vendor/earendil-works-pi"
SHA_FILE="$ROOT/docs/plans/UPSTREAM_SHA.txt"
rm -rf "$DEST"
git clone --depth 1 --filter=blob:none --sparse https://github.com/earendil-works/pi.git "$DEST"
git -C "$DEST" sparse-checkout set packages/ai
git -C "$DEST" rev-parse HEAD | tee "$SHA_FILE"
echo "Upstream packages/ai at $(cat "$SHA_FILE")"
