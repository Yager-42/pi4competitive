#!/usr/bin/env bash
# Sparse-fetch earendil-works/pi packages needed for isomorphic ports.
# Usage:
#   scripts/fetch_upstream.sh              # ai + agent
#   scripts/fetch_upstream.sh ai agent     # explicit packages
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/vendor/earendil-works-pi"
SHA_FILE="$ROOT/docs/plans/UPSTREAM_SHA.txt"

PACKAGES=("${@:-ai agent}")
SPARSE_PATHS=()
for p in "${PACKAGES[@]}"; do
  SPARSE_PATHS+=("packages/${p}")
done

rm -rf "$DEST"
git clone --depth 1 --filter=blob:none --sparse https://github.com/earendil-works/pi.git "$DEST"
git -C "$DEST" sparse-checkout set "${SPARSE_PATHS[@]}"
SHA="$(git -C "$DEST" rev-parse HEAD)"

{
  echo "$SHA"
  echo "# sparse paths: ${SPARSE_PATHS[*]}"
  echo "# npm: @earendil-works/pi-ai / @earendil-works/pi-agent-core (match package.json versions in vendor tree)"
} | tee "$SHA_FILE"

echo "Upstream at $SHA → $DEST (${SPARSE_PATHS[*]})"
