# CompetitorLens 系统架构契约

| 字段 | 值 |
|------|-----|
| **contract_version** | `0.3.4` |
| **status** | **active**（0.3.4 + ADR 0008 agent engine extensions；变更仍须 ADR + 升版本） |
| **updated** | 2026-07-24 |
| **scope** | 运行时边界、分层、依赖方向、技术栈、Pi 移植、本地 package 加载、**engine extension 运行时**、P4 旧仓参考身份 |
| **roadmap** | 实现顺序与阶段门禁见 [`docs/ROADMAP.md`](../ROADMAP.md) |
| **out of scope for this doc** | 业务特性 backlog 细则、各业务 JSON Schema 字段表（另文） |

---

## 0. 效力与变更

1. **效力**：实现、评审、重构以本文为准。冲突代码不得合并，除非先改契约。
2. **变更**：改决策摘要/分层/依赖/技术栈/移植范围与顺序 → 升 `contract_version` + 必要 ADR。
3. **Grill 决策**：确认后必须改本文。
4. **禁止**：第二套 agent 内核、Domain IO、对 `packages/ai|agent` 自创架构替代 main 同构；**禁止**为不存在的 coding TUI 产品复刻 install/发现商店。

---

## 1. 决策摘要（Binding）

| ID | 主题 | 决定 | 禁止 |
|----|------|------|------|
| D1 | 进程拓扑 | **单进程 Python** | Node+Flask/FastAPI 双进程 Pi |
| D2 | Agent 基座 | **Python 移植官方 Pi**（main）作基座 | npm 当运行时；灵感式 loop |
| D3 | agent 深度 | **C 档**：main `packages/agent` core+harness 目标面 | demo loop + App 再造 session |
| D4 | 复刻方式 | **TS→Python 同构**（行为+模块边界+包组织） | 自创简化架构冒充 port |
| D5 | 能力包 | **仅本地**；P3 = package-manager 本地同构子集（ADR 0006）；**P3.1 = coding-agent extension 运行时引擎子集**（ADR 0008 + feature `agent-engine-extensions-v1`） | 远程 install；home 默认发现；扩展商店；**全文** package-manager/TUI；自创平行 Hook 品牌 |
| D6 | 执行面 | package 内 tools/extensions 为 **Python** | 嵌 Node 跑 TS 包 |
| D7 | 语言绑定 | jiti/TUI 不字面移植；agent 内核职责与次序对齐 main | 乱删 agent 状态机步骤 |
| D8 | 产品 | `competitive_app` DDD + 六边形 | 六阶段写进 `packages/agent` |
| D9 | 过程执行 | Application Process Manager | Domain 内跑 IO 流程 |
| D10 | Domain | 契约/不变量/纯校验 | fastapi/网络/装包 IO |
| D11 | 真相源 | agent Session/Transcript；App 可投影 | 仅内存当唯一史实 |
| D12 | 旧仓 | **能力参考** = `competitive-agent`（https://github.com/xj120/competitive-agent）；本地与本仓并排检出；见 §1.3 | 抄旧仓当 Pi 父本；1:1 复刻清单当 backlog |
| D13 | 技术栈 | Python 3.12 + **FastAPI** + Pydantic | 未 ADR 换主框架/内核 |
| D14 | 上游 | **只对齐 main 当前实现** | 钉死过期 tag 当永久真理 |
| D15 | `packages/ai` | **全量**对齐 main | 单兼容层；LangChain 替代 |
| D16 | 实现顺序 | **串行**：① ai → ② agent → ③ package 本地子集 → **③.1 extension 运行时（P3.1）** → ④ `competitive_app` | 跳阶段；App 先于基座；未完成 P3.1 宣称 extension 钩子完成 |
| D17 | 路径同构 | 上游包 → `packages/ai`、`packages/agent` | 自创顶层 `pi_core` 等替代路径 |
| D18 | import 名 | `earendil_works.pi_ai` / `pi_agent` /（加载器可在 agent 或薄模块） | 打平无边界命名空间 |
| D19 | HTTP | **FastAPI** | Flask 默认（已废） |
| D20 | 异步 | **asyncio** 为主 | 内核全 sync 迁就入站 |
| D21 | 校验 | **Pydantic v2**（tool 参数 + App domain） | 多套校验库混用 |
| D22 | 本地能力包根 | **`capability_packages/`** 仅加载其下已实现子包 | 远程下载；`~/.pi` 默认发现 |
| D23 | 模型/密钥配置 | **配置文件 + env 覆盖（C）**；密钥不入 git | 密钥提交仓库 |
| D24 | Agent Session 默认存储 | **JSONL** 作对话/tool SoT | 仅内存当默认 SoT |
| D25 | JSONL 落盘路径 | 默认 **`data/sessions/`**（`data/` 不入库） | 默认写系统临时目录导致无法稳定 resume |
| D26 | 架构冻结 | v0.3.1 baseline；**0.3.2+** 按 ADR 演进（含 0006、0007、**0008**） | 仅聊天改架构不改本文 |

### 1.1 已废弃

| 废弃 | 替代 |
|------|------|
| 双进程 Node Pi | 单进程 Python port |
| Flask 默认 | FastAPI |
| coding-agent **全文** package-manager（install/npm/git/用户 home 发现）作为必选 | **D22 本地目录加载** |
| v0.2.x 中「阶段③ = 全文同构 package-manager」 | 阶段③ = 本地 loader + 目录约定 |

### 1.2 上游规范源（D14）

| 项 | 约定 |
|----|------|
| 仓库 | https://github.com/earendil-works/pi |
| 分支 | **main only** |
| `packages/ai`、`packages/agent` | 行为与目录 **同构移植** |
| 能力包加载 | **不**再要求 coding-agent package-manager 全文同构；仅借鉴「包内如何声明 tool/skill」若 main 有清晰约定，否则用最小约定（§5） |

### 1.3 旧仓（D12）— P4 能力参考源

| 项 | 约定 |
|----|------|
| 角色 | **仅** P4 业务 / workflow / 领域与能力形状的参考；**不是** agent 内核规范源 |
| 仓库名 | `competitive-agent`（产品名 CompetitorLens 旧实现） |
| 远程（权威） | https://github.com/xj120/competitive-agent |
| 本地约定 | 与 `pi4competitive` **并排** 检出 `competitive-agent/`（例：`…/revive/competitive-agent`） |
| 优先参考 | `backend/workflows/competitive/`、业务 API、搜抓/packages 面 |
| **禁止** | 以旧仓 `backend/agent/**` 替代 `packages/ai|agent`；把旧仓范围当必须 1:1 复刻清单 |
| 对照 | **Pi 父本** 仍只为 §1.2 `earendil-works/pi` **main**（ADR 0007） |

---

## 2. 系统是什么 / 不是什么

### 2.1 是什么

- 单进程：**FastAPI 竞品 App** + **Python 移植的 Pi（ai+agent）** + **本地 `capability_packages/` 能力包**。  
- 基座用途：给研究 workflow 提供模型/tool/session/事件，**不是** coding TUI 产品。

### 2.2 不是什么

- coding-agent CLI/TUI/扩展市场；  
- 自动从网络装第三方包；  
- LangChain 第二内核。

---

## 3. 逻辑架构

```text
Clients → FastAPI (competitive_app)
                │
                ▼
         application / domain
                │
                ▼
         packages/agent  ←── 注册 tools/resources
                │                    ▲
                ▼                    │
         packages/ai          capability_packages/*（本地实现）
```

**依赖：**

```text
competitive_app → packages/agent → packages/ai
capability_packages → 只通过加载器注册进 agent（不依赖 competitive domain）
packages/agent|ai ↛ competitive_app.domain
```

### 3.2 competitive_app

DDD：`adapter/in/fastapi`、`application/workflow`、`domain`、`adapter/out`、`wiring`。  
Runner 在 Application；Domain 无 IO。

### 3.3 `packages/ai` / `packages/agent`

同构 main 全量（D15/D3）；串行完成（D16）。

### 3.4 本地能力包（D5/D22）— 你要的形态

| 规则 | 约定 |
|------|------|
| 根目录 | 仓库 **`capability_packages/`**（名称固定，避免与 `packages/ai` 冲突） |
| 加载范围 | **仅**该目录下的子包（每个子目录一个 package 实现） |
| 不做什么 | 不扫描 `~/.pi`；不 git/npm install；不远程自动发现 |
| 包内有什么 | Python 实现的 tools（及可选 skills/prompts 资源文件） |
| 声明方式 | **最小约定**（见 §5）：入口模块注册 tools；可选 manifest |
| 启用 | 默认加载根下全部 **或** settings 白名单（实现选一种写进代码配置，默认：**加载全部合法子目录**） |

**不是** coding-agent 的 package 产品；**是**「可插拔本地能力目录」。

---

## 4. App ↔ agent

进程内 async API；阶段：Domain → agent.prompt → Domain 校验 → 持久化。  
对外业务事件脱敏。

---

## 5. 本地 package（coding-agent 本地同构子集）

### 5.1 目录

```text
capability_packages/
  echo_example/
    package.json          # 可选 pi manifest（对齐 packages.md 本地结构）
    extensions/           # Python 扩展 → AgentTool
    skills/               # 可选 SKILL.md
    prompts/              # 可选
    register.py           # 可选：Python 注册入口（host-delta）
```

根目录名固定 **`capability_packages/`**（D22）。

### 5.2 规范源与职责（阶段 ③ / P3 + P3.1）

| 项 | 约定 |
|----|------|
| 规范源（P3） | main `packages/coding-agent` 的 **package-manager / resource-loader** 中与 **本地发现、资源 resolve、加载** 相关的部分（ADR 0006） |
| 规范源（P3.1） | main `packages/coding-agent/src/core/extensions/**`（types/loader/runner/wrapper）及 host **引擎路径** emit（ADR 0008） |
| 实现方式 | TS→Python **同构子集**（行为 + 模块边界可 map） |
| 加载结果（P3） | 资源路径 → tools / skills / prompts |
| 运行时（P3.1） | `ExtensionRunner` + `registerTool` + §3.1 IN 事件；Context = **C-engine**（无 `ui`） |
| 落点 | `earendil_works.pi_agent.package_manager` + **`earendil_works.pi_agent.extensions`** |
| 失败 | 可观测；默认不因单包失败拖垮进程 |

**禁止实现（默认路径）：** npm/git 源安装、`pi install` CLI、lock 远程解、`~/.pi` 默认发现、update/remove 远程包、扩展商店、**coding TUI / `ui.*` / session 树 UX 事件**（详见 feature `agent-engine-extensions-v1` §3.1 OUT）。

### 5.3 与上游的关系

- tool **运行语义**：对齐 main `packages/agent`（P2 已同构）。  
- package **发现/解析（本地）**：对齐 coding-agent package-manager **子集**（ADR 0006）。  
- package **安装/分发**：对齐 **禁止**（D5/D22/G10）。  
- extension **引擎运行时**：对齐 coding-agent `core/extensions` **S-engine 裁切**（ADR 0008）。  
- 扩展语言：upstream TS/jiti → **Python host-delta**。  
- 挂载公开 API：对齐上游 runtime/runner 符号语义（feature **AP3**）；禁止与临时 `apply_capability_report` **长期双 SoT**。  
- 改 context/payload：**仅** extension 事件（feature **H1**），禁止平行公共 host 钩子长期并存。

### 5.4 相对 v0.3.1–0.3.3 的策略升级

| 版本 | 表述 |
|------|------|
| v0.3.1 | 阶段③ = 非全文 package-manager 的薄本地加载 |
| v0.3.2 | 阶段③ = **coding-agent 本地同构子集**（仍无 install） |
| **v0.3.4** | **P3.1** = 同子集上加厚 **extension 运行时（引擎）**；仍无 install/TUI |

---

## 6. 技术栈

| 层次 | 选择 |
|------|------|
| 语言 | Python 3.12+ |
| HTTP | **FastAPI**（ASGI） |
| 校验 | **Pydantic v2** |
| 异步 | **asyncio** |
| 工程 | uv/pip + pytest + import-linter（推荐） |
| LLM | 仅 `packages/ai` + `packages/agent` |
| 投影 | App **SQLite**（任务列表/进度，非 agent 对话史实） |
| Agent Session 存储 | **JSONL（D24）** @ **`data/sessions/`（D25）** |
| Node | 非运行时依赖 |
| 配置 | **文件 + env 覆盖（D23）**；示例 `config/settings.yaml` + `.env`；密钥仅 env/密钥管理 |

### 6.3 FastAPI

```text
FastAPI route → application → domain + packages/agent + repos
```

### 6.4 仓库布局

```text
pi4competitive/
  docs/contracts/
  packages/
    ai/                 # ← main packages/ai（阶段①）
    agent/              # ← main packages/agent（阶段②）
  capability_packages/  # 本地能力包根（D22，阶段③加载）
  competitive_app/      # 阶段④
    domain/
    application/workflow/
    adapter/in/fastapi/
    adapter/out/persistence/
    wiring.py
  pyproject.toml
  config/
    settings.example.yaml
  data/
    sessions/                 # JSONL SoT（D25）；整棵 data/ gitignore
  # .env：不入库
  tests/
    packages/ai/
    packages/agent/
    capability_packages/
    competitive_app/
```

加载器/同构子集代码放在 `packages/agent` 扩展面（`earendil_works.pi_agent.package_manager` + **`pi_agent.extensions`**），**不**另起第二 agent 内核；**不**要求移植完整 coding-agent 树（TUI/CLI/install）。规范源与删除清单见 **ADR 0006**、**ADR 0008** 与 `docs/plans/P3_capability_loader.md` / `P3_1_agent_engine_extensions.md`。

### 6.5 import 映射

| 路径 | import |
|------|--------|
| `packages/ai/` | `earendil_works.pi_ai` |
| `packages/agent/` | `earendil_works.pi_agent` |
| `competitive_app/` | `competitive_app` |

---

## 7. 真相源

| 数据 | 权威 |
|------|------|
| 对话/tool/session 树 | `packages/agent` JSONL，默认目录 **`data/sessions/`（D24/D25）** |
| 能力包代码 | 仓库 `capability_packages/`（随 git） |
| 任务投影 | App **SQLite** |
| 锁定研究输入 | App 与/或 session 约定条目；创建后只读 |
| 内存 running | 非 SoT |


---

## 8. 质量门禁

| ID | 要求 |
|----|------|
| G1 | domain 无 IO/FastAPI/SDK |
| G2 | FastAPI 无阶段编排 |
| G3 | 唯一 agent 内核 = `packages/agent` |
| G4 | ai/agent **及 P3 package 本地子集** 移植对照 main（coding-agent 限定文件） |
| G5 | 能力包仅 Python，且仅来自 `capability_packages/` |
| G6 | 契约同步 |
| G7 | Resume 不单靠内存 |
| G8 | D16 串行：① ai → ② agent → ③ package 本地子集 → ④ app |
| G9 | `packages/ai|agent` 目录同构；禁止并行自创内核树 |
| G10 | **禁止**实现远程 package 下载作为默认路径 |

---

## 9. 非目标

- coding TUI/扩展商店；  
- 业务 backlog 细则；  
- 业务 JSON 终表；  
- 生产鉴权细节。

---

## 10. 术语

| 术语 | 含义 |
|------|------|
| 上游 main | earendil-works/pi `main`（**Pi 父本**；P1–P3 同构源） |
| 旧仓 | `competitive-agent` @ https://github.com/xj120/competitive-agent（**P4 能力参考**；D12 / ADR 0007） |
| `capability_packages/` | **本地**可加载能力包根（搜抓等） |
| 同构 | **ai/agent** 全量；**P3** package 本地子集（ADR 0006）；**P3.1** extension 运行时引擎子集（ADR 0008） |
| Process Manager | App 阶段编排 |
| package 本地子集 | resolve/collect/load；**不含** install/npm/git/home |
| extension 运行时（S-engine） | `pi_agent.extensions`：runner + registerTool + engine 事件；**不含** TUI/ui/session 树/install |

---

## 11. ADR

重大转向写 `docs/contracts/adr/`。Grill 改 D* 必须改本文。

---

## 12. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.1.0 | 2026-07-22 | 双进程 Node + Flask |
| 0.2.0–0.2.4 | 2026-07-22 | 单进程移植、main、ai 全量、串行、同构、import 名 |
| 0.2.5 | 2026-07-22 | FastAPI + asyncio |
| 0.2.6 | 2026-07-22 | Pydantic tool 参数 |
| **0.2.7** | 2026-07-22 | 能力包仅本地加载 |
| **0.2.8** | 2026-07-22 | 确认根目录 `capability_packages/` |
| **0.2.9** | 2026-07-22 | **D23**：配置文件 + env 覆盖密钥 |
| **0.3.0** | 2026-07-22 | D24：JSONL Session SoT |
| **0.3.1** | 2026-07-22 | D25：`data/sessions/`；**D26 架构冻结为 baseline** |
| **0.3.2** | 2026-07-23 | **ADR 0006**：P3 = coding-agent package-manager **本地同构子集**；D5/D16/§5 更新；仍禁止远程/home/install |
| **0.3.3** | 2026-07-23 | **ADR 0007**：钉死 D12 旧仓身份（`competitive-agent` / xj120）；§1.3 + 术语表；角色仍仅为能力参考 |
| **0.3.4** | 2026-07-24 | **ADR 0008**：P3.1 agent engine extension 运行时；D5/D16/§5；feature `agent-engine-extensions-v1` frozen v0.2.0 |
