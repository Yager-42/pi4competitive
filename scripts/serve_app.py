"""pi4 后端 dev 启动器 —— 前后端联调用。

加载 .env(复用 wiring.load_config_from_env)后跑 uvicorn 在 :8010(create_app 是
factory,config=None → lifespan 读 .env)。前端 vite :3400 proxy /api → :8010。

用法:
  uv run python scripts/serve_app.py            # :8010 + reload
  uv run python scripts/serve_app.py --port 9000 # 自定义端口
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (setdefault — never overrides real env vars)."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key:
            os.environ.setdefault(key, val)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the pi4 FastAPI app (dev).")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--reload", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    _load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    import uvicorn

    uvicorn.run(
        "competitive_app.adapter.in_.fastapi.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
