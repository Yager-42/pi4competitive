# CompetitorLens 项目速览

> 一页读懂 `pi4competitive`。详细 SoT 以 `agents.md`、`CLAUDE.md`、`docs/contracts/ARCHITECTURE_CONTRACT.md` 为准。

## 这是什么

**TS 上游 [`earendil-works/pi`](https://github.com/earendil-works/pi)（`main`）的 Python 同构移植**，再包装成一个**竞品情报（competitive intelligence）FastAPI 应用**。
同构移植 = 模块边界与行为对齐上游 `main`，**不是**灵感式重写。单进程、asyncio、Pydantic v2。

## 关键技术栈

| 项 | 值 |
|----|----|
| 语言 / 运行时 | Python 3.12+、asyncio（公开 API 全异步） |
| 校验 | Pydantic v2 |
| 工作区 / 依赖 | `uv` workspace（members: `packages/ai`、`packages/agent`） |
| 测试 | pytest（`--import-mode=importlib`、`asyncio_mode=auto`、markers: `live`/`slow`/`native_sandbox`/`linux`/`macos`） |
| 代码导航 | CodeGraph（`.codegraph/`，首选） |
| 上游 npm 版本 | `@earendil-works/pi-ai@0.81.1` / `@earendil-works/pi-agent-core@0.81.1` |
| 运行平台 | **POSIX only**：原生沙箱强制且无 fallback（ADR 0013），依赖 `os.O_NOFOLLOW` / `dir_fd`，Windows 上跑不起来 → 走 WSL2 |
| 架构契约 | `docs/contracts/ARCHITECTURE_CONTRACT.md` **v0.3.13**；ADR 0001–0016 |

## 仓库结构（依赖方向）

```text
competitive_app  →  packages/agent  →  packages/ai
      ↑
capability_packages/  →  加载进 agent（package_manager），绝不反向 import
```

| 路径 | import | 职责 |
|------|--------|------|
| `packages/ai` | `earendil_works.pi_ai` | LLM 抽象层：models/types、~37 个 provider 工厂、wire api、auth |
| `packages/agent` | `earendil_works.pi_agent` | agent 内核：loop/tools/harness/JSONL session、P3 loader、P3.1 extensions |
| `capability_packages/` | 本地加载 | 7 个扩展包：search_tavily / search_anysearch / search_grok / pi_auto_review / reasonix_prefix_cache / learned_skills / echo_example |
| `competitive_app` | `competitive_app` | P4 应用：DDD（domain / application / adapter），`wiring.py` 为组合根 |

## 阶段进度（截至 2026-09-03 状态板）

| 阶段 | 状态 | 一句话 |
|------|------|--------|
| P1 `packages/ai` | ✅ done | 上游全量同构移植 |
| P2 `packages/agent` | ✅ done | C 档同构：loop + JSONL + harness |
| P3 capability 本地加载器 | ✅ done | 本地同构子集（ADR 0006），禁 install/npm/git/home |
| P3.1 agent engine extensions | ✅ done | S-engine 运行时（ADR 0008） |
| P3.2 Pi extension enablement | ✅ done | Reasonix prefix cache（ADR 0009） |
| P3.3 AgentTool native sandbox | ✅ done | Linux/macOS 原生沙箱；V2 Linux real 可选（ADR 0014，Linux 生产前必过） |
| P4 `competitive_app` | 🟡 in_progress | 见下 |

**P4 现状**：HTTP **30 路由**（`competitive-app-http-v1` v0.3.5）+ 三阶段研究 workflow plan/search/write（`research-workflow-v1` v0.2.8，SearchOS coverage 引擎）+ 前端 SPA（`competitive_app_frontend_v1` v0.3.1 F4）+ LLM fallback & RunJournal 可观测性（v0.2.1）+ 原生沙箱出网 gate（ADR 0016）。**剩余**：完整 fact_report schema、报告版本 diff、真监控、逐连接出网审计。

## 核心约束（红线，契约测试强制）

1. **同构移植**，非重写；模块边界对照上游 `main`。
2. **单一 agent 内核** = `packages/agent`；禁第二 agent 包 / 第二 LLM 框架（LangChain 等会被 AST 扫描拦截）。
3. **无业务类型泄漏**进 `packages/ai|agent`；`pi_agent → pi_ai` 单向依赖。
4. **会话 SoT 是 JSONL**（`data/sessions/`）；SQLite 只是任务/进度投影。
5. **capability packages 本地优先**，无远程下载；运行时拥有完整进程权限。
6. **架构变更必须先 ADR + 契约版本升级**；纯聊天式变更无效。
7. **P4 分层**：路由只调 application；domain 无 IO。
8. **AgentTool 一律走原生沙箱**（ADR 0013），无 host/Direct/Local/Docker fallback；出网判定只在组合根 `wiring._build_native_review_domain`（ADR 0016 / G14），broker 侧 `validate_public_hostname` 双验不得绕过。

## 快速开始

```bash
uv sync                                          # 安装 workspace + dev deps
uv run pytest -m "not live" -q                   # 全量离线套件（默认 CI）
uv run pytest tests/packages/ai -m "not live" -q    # P1 层
uv run pytest tests/packages/agent -m "not live" -q # P2/P3/P3.1 层
ruff check . && ruff format .                    # lint + format（line-length 100, py312）

codegraph status                                 # 确认 CodeGraph 索引非空
codegraph explore "Agent agent_loop Session"     # 符号 + 调用路径
codegraph node <SymbolName>                      # 符号源码 + 调用者/被调者
```

`data/`（含 sessions JSONL）与 `.env` 均 gitignored；live 测试需要 `.env` gateway，非退出阻塞。

> **Windows 用户**：后端与测试必须在 WSL2 里跑（原生沙箱是 POSIX-only）。用独立 venv 避免覆盖 Windows 的 `.venv`：
> `wsl -e bash -lc "cd /mnt/e/project/pi4competitive && UV_PROJECT_ENVIRONMENT=.venv-linux uv run pytest -m 'not live' -q"`

## 文档地图（SoT 精简版）

| 文档 | 角色 |
|------|------|
| `agents.md` / `CLAUDE.md` | 仓库导航 + 约定 + CodeGraph 用法 |
| `docs/contracts/ARCHITECTURE_CONTRACT.md` | 架构唯一事实源（v0.3.13） |
| `docs/ROADMAP.md` | 串行阶段 + 状态板 + 漂移检查清单 |
| `docs/contracts/adr/*` | 设计决策（0001→0016，按时间读 = 项目"为什么"） |
| `docs/features/*` | 按特性冻结的边界契约（frozen 才可实现） |
| `docs/plans/*_module_map.md` | 每层文件 ↔ 上游模块映射 |
| `docs/plans/P*_*.md` | 各阶段实现计划 + checklist |

> 学习建议：先读本速览 → agents.md → 架构契约 → ADR 时间线 → 模块图 → 按依赖方向读代码 + 跑测试验证。**不要从头读完所有 docs**，按需查阅。
