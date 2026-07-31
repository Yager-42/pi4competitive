# Feature 边界契约:competitive_app_frontend_v1

| 字段 | 值 |
|------|-----|
| **feature_contract_version** | `0.1.0` |
| **status** | **frozen** |
| **updated** | 2026-07-31 |
| **feature_id** | `competitive_app_frontend_v1` |
| **roadmap_stage** | **P4** `competitive_app` —— FastAPI 后端的前端 SPA(选择性复现 VerdaAI,以 pi4 能力为本) |
| **architecture_contract** | [`ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.6** |
| **后端契约** | [`competitive_app_http_v1.md`](competitive_app_http_v1.md) **v0.3.3**(27 路由)+ `research-workflow-v1` v0.2.3 |
| **参考源** | `/Users/huangyaokai/VerdaAI-Investigator/frontend`(React19/TS6/Vite8 技术栈 + 莫兰迪设计系统;**选择性复现,非照搬**) |
| **path** | `docs/features/competitive_app_frontend_v1.md` |

---

## 0. 效力与状态

1. 本文是 pi4 前端 SPA 的 **frozen** 功能边界(v0.1.0 grill 收敛于 2026-07-31,10 决策见 §8)。
2. 分 3 子批次实现:**F1 建任务闭环**(本文 v0.1.0,frozen)/ F2 报告闭环(v0.2.0,待)/ F3 情报闭环(v0.3.0,待)。每 F 一 commit+merge。
3. 标为 locked 的决定不得由实现者自行改写;变更须重新 grill 并升 version。
4. 前端独立技术栈(React/TS/Vite),**不进 uv workspace**;不碰 `packages/ai|agent`,不动后端 27 路由行为(F1 零后端改动)。

---

## 1. 范围

### 1.1 全批页面规划(11 → 复现 7 + 砍 2 + 改造 2)

| VerdaAI 页面 | pi4 后端支撑 | 处理 | 批次 |
|---|---|---|---|
| HomePage(工作台/建任务) | POST /tasks | ✅ 复现(砍专家墙/mode) | F1 |
| ClarifyPage(澄清问卷) | POST /tasks + /clarify | ✅ 复现(近原样) | F1 |
| WorkspacePage(SSE 工作台) | SSE /stream | ✅ 复现(改造事件消费) | F1 |
| ReportPage(报告全文) | GET /reports/{id} | ✅ 复现(降级富结构) | F2 |
| LibraryPage(我的调研) | GET /reports | ✅ 复现 | F2 |
| TracePage(决策回放) | GET /tasks/{id}/trace | ✅ 复现(降级) | F2 |
| GraphPage(覆盖图谱) | GET /reports/{id}(后端补 coverage_map,F2) | ✅ 改造(coverage 矩阵) | F2 |
| DashboardPage(竞争情报中心) | GET /dashboard | ✅ 复现 | F3 |
| KnowledgePage → 证据库 | GET /evidences | ✅ 改造(证据库浏览) | F3 |
| ExpertsPage | ❌ pi4 无多角色专家 | ❌ 砍 | — |
| ExpertDetailPage | ❌ 同上 | ❌ 砍 | — |

### 1.2 F1 范围(v0.1.0)

- 建任务闭环:输 query → 澄清 3 问 → SSE 工作台看进度。
- 零后端改动,只消费 pi4 已有接口:`POST /api/v2/tasks {query}`(batch3 clarify 路径)+ `POST /api/v2/tasks/{id}/clarify` + SSE `GET /api/v2/tasks/{id}/stream`(batch1)。
- 落点:`frontend/` 子目录(仓内)。

---

## 2. 技术栈(locked)

照搬 VerdaAI 全套(选择性页面 + 全套依赖):

- React 19 + TypeScript 6 + Vite 8
- react-router-dom 7(路由)+ zustand 5(状态)
- tailwindcss 3 + 莫兰迪设计系统(`src/index.css` token + `tailwind.config.js` palette)
- framer-motion(动画)+ lucide-react(图标)+ react-markdown(F2 ReportPage)
- echarts / reactflow / d3(F3 图表/图谱用,先装)

**不进 uv workspace**(独立 npm);`.gitignore` 忽略 `frontend/node_modules`、`frontend/dist`。

---

## 3. 接口调用契约(locked —— 前端 api.ts 直按 pi4 后端)

前端 `src/lib/api.ts` 直按 pi4 契约写(**`/api/v2` + snake_case,后端不动**),不走 camelCase 转换层。

### 3.1 createTask(F1)

```ts
createTask(query: string) → POST /api/v2/tasks {query}
→ {task_id, status: 'awaiting_clarify'|'pending', session_id?, query?, questions?: ClarifyQuestion[]}
```
- `status==='awaiting_clarify'` + questions → 跳 `/clarify/{task_id}`(带 state.query + state.clarify)
- 否则(degrade 直跑)→ 跳 `/workspace/{task_id}`

### 3.2 submitClarify(F1)

```ts
submitClarify(taskId, answers: ClarifyAnswer[]) → POST /api/v2/tasks/{id}/clarify {answers: [{id, value: str|str[]}]}
→ {task_id, session_id, status: 'pending', query}
```

### 3.3 openTaskStream(F1)

```ts
openTaskStream(taskId, handlers) → EventSource /api/v2/tasks/{id}/stream
```
- 监听 pi4 12 事件(§4);heartbeat `:` 注释 EventSource 自动忽略。
- dev 走 vite proxy(`/api → 127.0.0.1:8010`,API_BASE 空串);prod 用 `VITE_API_BASE` 指后端。

### 3.4 字段命名规范(locked)

前端统一 **snake_case**(对齐 pi4 后端原生,`task_id`/`clarify_questions` 等),不引入 camelCase 转换。TS interface 照 pi4 响应字段写。URL 路径参数(`/clarify/:taskId` 等)可保留 camelCase(前端内部约定)。

---

## 4. SSE 事件契约(locked —— Q5 降级映射)

pi4 SSE 推 12 事件(`span` 不推 SSE,只写 SQLite,走 GET /trace)。前端 `taskStore.ingest` 按下表消费:

| pi4 事件 | data schema | 前端 UI 槽位 | VerdaAI 对应(降级) |
|---|---|---|---|
| `state_snapshot` | `{task_id, status, current_stage, stages{plan,search,write}, coverage, iteration, evidence_count}` | 初始化阶段/coverage | (VerdaAI 无,新增) |
| `stage_start` | `{stage, task_id}` | 阶段卡置 running | node_update(专家→阶段) |
| `stage_end` | `{stage, ok, task_id, error?}` | 阶段卡置 ok/failed | node_update |
| `coverage_update` | `{filled, total, unknown?, conflict?, ratio?}` | coverage 进度条 | progress.percent(降级为覆盖率) |
| `evidence` | Evidence 节点 | 证据流 | evidence(原样) |
| `subagent_start` | `{entity/entity_id, task_id}` | sub-agent 节点 running | node_update(专家节点→sub-agent) |
| `subagent_end` | `{entity/entity_id, task_id}` | sub-agent 节点 done | node_update |
| `iteration_start` | `{iteration, task_id}` | 迭代轮次计数 | (VerdaAI 无) |
| `report_ready` | `{report_id, task_id}` | reportId 设 | report_ready(原样) |
| `done` | `{task_id, status}` | running=false, finished=true | done(原样) |
| `error` | `{task_id, status, message?}` | error 显示 | error(原样) |

**砍掉**(pi4 没有,前端不渲染):`thought`(思维流)、`chart`(图表)、`image`、`progress`(VerdaAI percent/token,pi4 用 coverage 替代)、`trace`(SSE 推 trace——pi4 不推,走 GET /trace 事后查)。

**进度条降级**:VerdaAI 用 `progress.percent`,pi4 改用 `coverage.filled/total` 比例 + `current_stage` 文字。

**sub-agent 替代专家节点**:VerdaAI `node_update` 是 48 专家状态,pi4 改造成 sub-agent 派发/完成卡片(`subagent_start/end`,带 entity)。

---

## 5. ReportPage 降级映射(F2,v0.2.0)

VerdaAI 富 Report → pi4 精简 Report:

| VerdaAI 字段 | pi4 对应 | 渲染 |
|---|---|---|
| sections[]{claims/charts/data_grid/...} | sections[{id,title,body,refined?}] | markdown 渲染(react-markdown) |
| title | title | 标题 |
| markdown(pi4 独有) | markdown | 兜底:无 sections 时整体渲染 |
| coverage(metrics.coverage) | coverage{filled,total,unknown,conflict,ratio} | 侧栏覆盖率卡 |
| evidence_count + sources[] | evidence_count + sources[] | 侧栏 |
| claims[]/charts[]/sentiment/audit_review/dispatch/experts/glossary/figures | ❌ pi4 无 | 砍(不造假) |

保留闭环:refine(`POST /reports/{id}/refine`)+ feedback(`POST /reports/{id}/feedback`)+ trace 入口(跳 `/trace/{id}`)。

---

## 6. GraphPage coverage_map schema(F2,v0.2.0)

后端 `GET /reports/{id}` 补返 `coverage_map` 矩阵(patch 加字段,不动现有路由行为):

```json
{"coverage_map": {
  "entities": [{"id":"e_acme","name":"ACME","kind":"target"}],
  "attributes": [{"id":"a_price","name":"Price","dimension":"pricing","type":"money_usd"}],
  "cells": [{"entity_id":"e_acme","attribute_id":"a_price","status":"filled","value":"$10","confidence":0.9,"source":"..."}]
}}
```
GraphPage 用 reactflow 或矩阵表格渲染(实体×属性,cell 四态着色)。

---

## 7. 验收

### 7.1 F1(本文 v0.1.0)
- `frontend/` 基建 + 8 文件(api.ts/types/taskStore/useTaskStream/uiStore/motion/AppLayout/VSidebar/ui)+ HomePage/ClarifyPage/WorkspacePage + App.tsx + serve_app.py。
- 联调:后端 `uv run python scripts/serve_app.py`(:8010)+ 前端 `npm run dev`(:3400)+ 浏览器:输 query → awaiting_clarify 3 问 → 提交 → SSE 工作台实时显示 stage/coverage/evidence/sub-agent → done。
- `git diff --stat packages/` 空(前端不碰 packages)。
- `cd frontend && npm run build` 通过(tsc + vite build)。
- 后端 27 路由不回归(`uv run pytest tests/competitive_app/contract -q`)。

---

## 8. 决策记录(grill 收敛)

| ID | 状态 | 决定 |
|----|------|------|
| Q1 | locked | 落点 = pi4 仓内 `frontend/` 子目录(对齐 VerdaAI 布局 + 契约同仓不漂移) |
| Q2 | locked | 技术栈照搬 VerdaAI 全套(选择性页面 + 全套依赖;前端不进 Python gate) |
| Q3 | locked | 复现 7 页 + 砍 Experts×2 + 改造 GraphPage(coverage 图谱)/KnowledgePage(证据库) |
| Q4 | locked | 适配层:前端 api.ts 直按 pi4 契约(`/api/v2`+snake_case),后端不动,不引 camelCase 转换 |
| Q5 | locked | SSE 映射:coverage 替 percent、sub-agent 替专家节点、砍 thought/chart/image/progress |
| Q6 | locked | ReportPage 降级:markdown+coverage 侧栏+refine/feedback+trace 入口,砍 claims/charts/sentiment/audit |
| Q7 | locked | GraphPage:后端补返 coverage_map 矩阵(patch 加字段,F2) |
| Q8 | locked | 契约文档:独立 `competitive_app_frontend_v1.md`,F1 v0.1.0 |
| Q9 | locked | 节奏:分 3 子批次(F1/F2/F3),每 F 一 commit+merge |
| Q10 | locked | F1 范围:建任务闭环,8 前端文件 + 联调 + 契约 v0.1.0,零后端改动 |

---

## 9. 修订

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.1.0 | 2026-07-31 | **grill frozen(F1)**:建任务闭环 —— pi4 仓内 `frontend/` + 照搬 VerdaAI 技术栈 + HomePage/ClarifyPage/WorkspacePage(api.ts 适配层直按 pi4 契约 /api/v2+snake_case / taskStore 按 12 事件 ingest / SSE 映射 coverage 替 percent+sub-agent 替专家)+ serve_app.py + 独立契约文档 v0.1.0;零后端改动,F2/F3 待续 |
