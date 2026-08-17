#!/usr/bin/env bash
# CompetitorLens eval harness — WSL2 one-shot setup (run inside Ubuntu).
# Usage: bash wsl_setup.sh
# Idempotent-ish: safe to re-run. Needs sudo (will prompt).
set -u

REPO_DIR="$HOME/pi4competitive"
BRANCH="p4/eval-harness-widesearch-smoke"
REMOTE="https://github.com/Yager-42/pi4competitive.git"
WIN_REPO="/mnt/d/python/pi4competitive"

echo "==> [1/6] system deps (python3-pip / git / curl)"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv git curl >/dev/null

echo "==> [2/6] uv (if missing)"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "==> [3/6] clone branch into $REPO_DIR"
if [ ! -d "$REPO_DIR/.git" ]; then
  git clone --branch "$BRANCH" "$REMOTE" "$REPO_DIR"
else
  echo "    repo exists — pulling $BRANCH"
  git -C "$REPO_DIR" fetch origin "$BRANCH"
  git -C "$REPO_DIR" checkout "$BRANCH"
  git -C "$REPO_DIR" pull --ff-only origin "$BRANCH"
fi
cd "$REPO_DIR"

echo "==> [4/6] uv sync (workspace deps)"
export PATH="$HOME/.local/bin:$PATH"
uv sync

echo "==> [5/6] scorer deps into system python3 (run_scorer uses 'python3')"
python3 -m pip install -q --break-system-packages \
  openai loguru tenacity datasets huggingface_hub \
  pandarallel pydantic volcenginesdkarkruntime \
  aiohttp dateparser numpy pandas 2>&1 | tail -3

echo "==> [6/6] .env + benchmark gold data"
# .env (secrets) copied from the Windows checkout
if [ -f "$WIN_REPO/.env" ]; then
  cp "$WIN_REPO/.env" "$REPO_DIR/.env"
  echo "    .env copied from $WIN_REPO"
else
  echo "    WARNING: no .env at $WIN_REPO — copy it manually into $REPO_DIR/.env"
fi

# WideSearch HF dataset + gold (plan Step 3). Needs network (once).
mkdir -p data/benchmarks/widesearch
if [ ! -d data/benchmarks/widesearch/dataset ]; then
  HF_HOME=data/benchmarks/hf_cache python3 -m huggingface_hub download \
    ByteDance-Seed/WideSearch --repo-type dataset \
    --local-dir data/benchmarks/widesearch/dataset
  HF_HOME=data/benchmarks/hf_cache python3 -c \
    "from huggingface_hub import HfApi; print(HfApi().dataset_info('ByteDance-Seed/WideSearch').sha)" \
    > data/benchmarks/widesearch/HF_DATASET_SHA.txt
  { echo "wideSearch repo SHA: $(git -C vendor/widesearch rev-parse HEAD 2>/dev/null || echo unknown)";
    echo "HF dataset SHA: $(cat data/benchmarks/widesearch/HF_DATASET_SHA.txt 2>/dev/null)";
    echo "fetched: $(date +%Y-%m-%d)"; } > data/benchmarks/widesearch/REVISION.txt
else
  echo "    dataset already present — skip download"
fi

echo
echo "==> DONE. Run the harness:"
echo "  cd $REPO_DIR"
echo "  # terminal 1:"
echo "  uv run python scripts/serve_app.py --port 8000 --host 127.0.0.1 --no-reload &"
echo "  # terminal 2:"
echo "  uv run python -m eval.runner.single_agent_app --host 127.0.0.1 --port 8001 &"
echo "  # terminal 3:"
echo "  uv run python -m eval --stage smoke --benchmark widesearch --variants a1,a2"
