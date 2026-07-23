# CompetitorLens 实现路线图（Roadmap）

| 字段 | 值 |
|------|-----|
| **roadmap_version** | `0.1.1` |
| **status** | active |
| **updated** | 2026-07-22 |
| **架构契约** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](contracts/ARCHITECTURE_CONTRACT.md) **v0.3.1 frozen** |
| **目的** | 排期与完成门禁；**防止实现顺序/范围漂移** |

---

## 0. 怎么用这份文档

1. **架构冲突 → 先改契约 + ADR**，再改 roadmap。  
2. **范围冲突 → 改本文**，升 `roadmap_version`。  
3. 实现 PR 须标明：**阶段 ID（P1–P4）** + 对照上游（若移植）。  
4. **禁止**在 P1–P3 未完成时合并依赖真基座的 `competitive_app` 主路径（契约 D16/G8）。

### 还要不要继续聊？

| 话题 | 状态 | 建议 |
|------|------|------|
| **包组织 / 路径 / import / 进程 / 技术栈** | **已冻结**（契约 v0.3.1） | **不必再聊**；要改走 ADR |
| **实现顺序与完成标准** | 见本文阶段 | 按 roadmap 执行；细节可在阶段开工时补 checklist |
| **业务能力（研究流程、报告等）** | **未在架构契约展开** | **P4 开工前**再开短文 `docs/FEATURES.md` 或开 grill；**现在不阻塞 P1** |
| **capability 里具体有哪些搜抓包** | 未定 | P3 前定最小集合即可 |

---

## 1. 总顺序（不可跳）

```text
P1  packages/ai          全量同构 main
        ↓
P2  packages/agent       C 档同构 main
        ↓
P3  capability 本地加载器 + capability_packages/ 约定
        ↓
P4  competitive_app      DDD + FastAPI + workflow（业务能力在此阶段引入）
```

| 阶段 | 仓库路径 | import | 完成前禁止 |
|------|----------|--------|------------|
| **P1** | `packages/ai/` | `earendil_works.pi_ai` | 宣称 agent 完成；写 competitive 主路径 |
| **P2** | `packages/agent/` | `earendil_works.pi_agent` | 宣称 loader/app 可依赖未完成 agent |
| **P3** | loader + `capability_packages/` | （loader 挂在 agent 扩展点或薄模块） | 远程 install；家目录发现 |
| **P4** | `competitive_app/` | `competitive_app` | 绕过 agent 直连厂商 SDK 当内核 |

**上游对照：** 一律 `https://github.com/earendil-works/pi` 的 **`main`**。

---

## 2. 阶段详解

### P1 — `packages/ai`（全量）

| 项 | 内容 |
|----|------|
| **目标** | main `packages/ai` **整包** TS→Python 同构移植（契约 D15） |
| **规范源** | `packages/ai/**` on main |
| **技术** | asyncio、与上游模块边界一致；Pydantic 用于需校验处（与 agent tool 衔接在 P2） |
| **完成标准（必须全部满足）** | ① 目录/模块职责可映射 upstream；② 公开 stream/model/usage 等行为可对照 main；③ `tests/packages/ai/` 有行为/回归测试（含 faux/录制策略任选，但要可重复）；④ 无 LangChain 等第二框架 |
| **显式不做** | competitive 业务；capability 搜抓实现 |
| **退出条件** | 阶段评审：对照 main 抽查 N 个 provider/入口 + 测试绿 → 标 `P1=done` |

### P2 — `packages/agent`（C 档）

| 项 | 内容 |
|----|------|
| **目标** | main `packages/agent` core+harness 目标面同构（契约 D3） |
| **依赖** | **P1 done** |
| **实现计划** | [`docs/plans/P2_packages_agent.md`](plans/P2_packages_agent.md) |
| **必含能力族** | loop/agent/tools/events/abort；session 树；**JSONL @ `data/sessions/`**；compaction/branch；skills/prompt 资源语义；steering/follow-up 等 main 已有控制面 |
| **完成标准** | ① 依赖 `earendil_works.pi_ai` 真包而非永久假实现；② JSONL session 可恢复；③ tool 校验时机对齐 TypeBox→Pydantic 语义；④ `tests/packages/agent/` 覆盖 loop+tool+session 主路径；⑤ 无竞品 domain 类型泄漏 |
| **显式不做** | 六阶段研究 DAG；远程 package-manager |
| **退出条件** | 用本地假 tool 跑通 prompt→tool→session 落盘→resume 冒烟 → `P2=done` |

### P3 — 本地 capability 加载

| 项 | 内容 |
|----|------|
| **目标** | 从 **`capability_packages/`** 加载本地 Python 包并注册 tools（契约 D5/D22） |
| **依赖** | **P2 done** |
| **必含** | 列举子目录；导入约定入口；注册 `AgentTool`；加载失败可观测 |
| **可选** | skills/prompts 资源文件；启用白名单 |
| **显式不做** | npm/git 下载、`~/.pi` 扫描、`pi install` CLI、全文 coding package-manager |
| **完成标准** | ① 至少一个示例包（可 no-op/echo tool）可被 agent 调用；② 非法包失败不拖垮进程（策略明确）；③ 测试覆盖加载与注册 |
| **退出条件** | 文档化子包目录约定 + 测试绿 → `P3=done` |

### P4 — `competitive_app`

| 项 | 内容 |
|----|------|
| **目标** | FastAPI + DDD + workflow Process Manager；引入**业务能力**（研究闭环） |
| **依赖** | **P1+P2+P3 done** |
| **结构** | `domain` / `application/workflow` / `adapter/in/fastapi` / `adapter/out` / `wiring` |
| **配置** | `config/settings.example.yaml` + env 覆盖密钥（D23） |
| **投影** | App SQLite（与 JSONL 史实分离） |
| **业务能力** | **不在架构契约写死清单**；P4 开工前用 §4 冻结「本期能力」 |
| **完成标准（骨架）** | ① 路由只调 application；② domain 无 IO；③ 至少一条「假业务阶段」调用真 agent+capability；④ import-linter/分层检查 |
| **退出条件** | 骨架 + 分层门禁绿；业务能力按 §4 迭代 |

---

## 3. 横切（全阶段）

| 项 | 要求 |
|----|------|
| 上游 | 只对照 **main**；PR 可附 SHA（非强制 lock） |
| 异步 | asyncio 为 pi 公开 API 默认 |
| 校验 | Pydantic v2 |
| 密钥 | 不入 git |
| 数据 | `data/` gitignore（sessions 等） |
| 文档 | 移植模块建议 `upstream: packages/...` |
| 禁止 | 第二 agent 框架；跳阶段合并；Domain 调网络 |

---

## 4. 业务能力引入（P4，单独控漂移）

架构冻结 **不等于** 业务范围冻结。

| 步骤 | 动作 |
|------|------|
| 1 | P3 完成前可起草稿 `docs/FEATURES.md`（可选） |
| 2 | **P4 开工前**冻结「本期能力」短列表（宁少） |
| 3 | 能力只进 `competitive_app` + `capability_packages/*`，**不**进 `packages/ai|agent` |
| 4 | 旧仓 = 能力参考，非 1:1 复刻清单 |

**建议 P4 第一期能力（草案，未冻结，可改）：**

1. 本地搜/抓 capability（各至少一）  
2. 可运行的研究阶段骨架（可先少于六段）  
3. 任务 API + 进度/会话关联  
4. 结构化结果校验门槛（报告可后补完整 fact_report）  

正式冻结时改本节状态为 **frozen** 并升 roadmap 版本。

---

## 5. 状态板（实现时更新）

| 阶段 | 状态 | 完成日期 | 备注 |
|------|------|----------|------|
| P1 `packages/ai` | **done** | 2026-07-22 | branch `p1/packages-ai`; offline tests green |
| P2 `packages/agent` | **in_progress** | | branch `p2/packages-agent`; Phase A scaffold done |
| P3 capability loader | blocked on P2 | | |
| P4 `competitive_app` | blocked on P3 | | |
| 业务能力 v1 | blocked on P4 开工前冻结 | | |

状态枚举：`todo` | `in_progress` | `done` | `blocked`。

---

## 6. 漂移检查清单（每个 PR）

- [ ] 阶段是否允许本 PR 的范围？  
- [ ] 是否改了 `packages/ai|agent` 的边界/语义？若是，是否对照 main？  
- [ ] 是否把业务类型写进 agent/ai？  
- [ ] 是否引入远程 package 下载或第二内核？  
- [ ] 是否需要改架构契约（若是先 ADR）？  

---

## 7. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.1.0 | 2026-07-22 | 初版：对齐契约 v0.3.1；P1–P4 门禁；业务能力延后冻结 |
| 0.1.1 | 2026-07-22 | P1 packages/ai 完成（同构 port + 契约测试绿） |
