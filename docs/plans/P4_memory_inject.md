# Plan: P4 跨任务记忆——evidences recall+inject(write stage)

> 最小切片。**复用 evidences 表当记忆库**,只加"忆+注入"这层;不新造表/compiler/consolidate/agent 工具。
> 落点:主仓 `/Users/huangyaokai/pi4competitive`,分支 `p4/research-workflow-v2-searchos`(FF-merge main)。
> 参考:`competitive-analysis-agent/backend/memory/`(ADR 0007 capability reference only,不 1:1 抄)。

## Context(为什么)

pi4 的 evidences 表(batch3)**已经是跨任务事实库**(entity/attribute/value/finding/brand/confidence/captured_at/task_id,任务完成时 `index_evidences` 入库)。但它**只躺那,新任务开始没人 recall+inject**。

价值场景:subscriptions 每月重跑同一竞品——没记忆每次从零搜/重抽同样事实;有记忆→跳过已知 + 能做变化检测(上次 $10,这次 $12)。变化检测是 user 已标的 remaining,记忆库是其地基。

## Grill 决策(Q1-Q6,全确认)

| Q | 决策 |
|---|---|
| Q1 注入哪个 stage | **只 write**(报告上下文 + 变化检测;plan 整形价值弱;search 走 CoverageEngine 提示词注入没用) |
| Q2 recall 策略 | 每 (entity,attribute) **留最新一条**(captured_at desc)+ captured_at + confidence + source;min_conf=0.3;25KB cap;~40 软上限 |
| Q3 alias | **归一化**(小写/去空格/去 Inc·Ltd·官网·公司 后缀);别名表/语义留后;订阅(主用例)同 query 同名不受影响 |
| Q4 blob 格式 | 按竞品分组 `## {brand}` / `- attr: value (src,conf,captured_at)`;变化检测指令揉 blob 头("compare to current search; flag old→new");不改 write 的 locked system_prompt;25KB 按竞品块整块丢 + `(memory truncated)`(UTF-8 字节截断);空→不注入(连头都不加) |
| Q5 代码落点 | 新建 `application/workflow/memory_inject.py` 导出 `recall_prior_findings(store, brands, *, min_conf, cap) -> str | None`;research_runner `_build_prompt` write 分支调它;**lazy**(建 write prompt 时才 recall) |
| Q6 版本/scope | research-workflow v0.2.4→**v0.2.5**;http v0.3.4 不动;**契约 0.3.9 不动,无 ADR**(复用 evidences,非架构变更);ROADMAP 0.1.44→0.1.45。**诚实边界**:只保证记忆到达 write prompt;"LLM 据此标 old→new"是 policy-only,不测、不保证 |

## 落点文件

### 1. `competitive_app/src/competitive_app/application/workflow/memory_inject.py`(新)

```python
INJECTION_LIMIT = 25 * 1024  # 25KB(对齐 competitive-analysis-agent INJECTION_LIMIT)
_HEADER = ("Prior findings (from previous research; captured_at shown for staleness. "
           "Compare each to your CURRENT search results — if a value changed, flag it "
           'in the report as "old → new"):\n\n')

def _normalize_brand(b: str) -> str:
    # 小写 + 去空格 + 去 Inc/Ltd/官网/公司/Corp/Co. 等后缀
    ...

def recall_prior_findings(store, brands, *, min_conf=0.3, cap=INJECTION_LIMIT) -> str | None:
    # 1. 归一化 brands → 查 evidences(store.query_evidences 按 brand;单 brand 接口 → 循环 or 扩 list)
    # 2. group by (entity, attribute),每组 captured_at desc 留最新一条
    # 3. min_conf 过滤
    # 4. 按竞品分组渲染:## {display_brand}\n- {attr}: {value} ({src}, conf {x}, {captured_at})
    # 5. 25KB:按竞品块整块丢(不切半行),超 cap 末尾 + "\n(memory truncated)";UTF-8 字节截断
    # 6. 空召回 → None
```

纯函数,不读 env,不触 pi_ai(守分层)。

### 2. `research_runner.py` `_build_prompt`(line 257-275)

write 分支:在 `parts.append("Now run...")` **之前**:
```python
if name == "write":
    blob = await recall_prior_findings(
        self.store, [self.research_brief.target.name, *self.research_brief.competitors])
    if blob:
        parts.append(blob)
```
brands 用 brief 原值(归一化在 helper 内)。不动 `profile.system_prompt`(locked)。

### 3. 测试

**offline(必过):**
- `tests/competitive_app/unit/test_memory_inject.py`:
  - 归一化:`飞书`/`Lark`/`Feishu`→? (注:归一化只去后缀/大小写,**飞书↔Lark 真同义不在 B 范围**——单测只验大小写/后缀:`Notion, Inc.`→`notion`、` 飞书官网 `→`飞书`)。
  - 去重:同 (entity,attr) 2 条不同 captured_at → 留最新。
  - 截断:构造 >25KB → 按竞品块丢 + `(memory truncated)`;多字节中文不切半。
  - 空→None;min_conf 过滤低置信。
- `tests/competitive_app/integration/test_memory_inject.py`:
  - seed 2 任务同竞品(Notion)不同 captured_at 的 evidences(pricing=$10 7月 / pricing=$12 8月)→ 跑任务(faux,brief 含 Notion)→ 断言 write 的 user prompt(session JSONL 或 `_build_prompt` 输出)含 `## Notion` + `pricing` + 最新那条($12,8月)+ 变化检测指令头;**旧那条($10,7月)不出现**(只留最新)。
  - 空 evidences → write prompt 无 `Prior findings`。

**live(env-gated,不 exit-blocking):**
- `tests/competitive_app/integration/live/test_live_memory_inject.py`:
  - pre-seed app.db 一条 Notion 的 evidence(`captured_at` 早于今天,value=$10/mo)。
  - 跑 1 个真任务(brief target=Notion,fake 竞品,faux gateway 真 LLM)→ 读 session JSONL 找 write stage 的 user message → 断言含 `Prior findings` + `$10/mo`。
  - 验证记忆真流到 write prompt(端到端,过 gateway)。LLM 是否据此标变化=policy-only,不测。

### 4. 文档

- `docs/features/research_workflow_v1.md`:v0.2.4→**v0.2.5** patch(加 memory inject 段:write prompt 注入 evidences 历史 finding,按竞品分组 + 变化检测指令;复用 evidences,无新表)。
- `docs/ROADMAP.md`:0.1.44→**0.1.45** +1 行。
- `ARCHITECTURE_CONTRACT`:0.3.9 不动,无 ADR。
- `competitive_app_http_v1.md`:v0.3.4 不动(无新路由)。

## 实现顺序

1. memory_inject.py helper
2. 单测 helper(先红后绿)
3. wire 进 research_runner._build_prompt
4. 集成测试(faux)
5. live 测试
6. 文档 v0.2.5 + ROADMAP 0.1.45
7. 跑 offline suite + ruff + commit + FF-merge main + push

## 复用现有实现

- `TaskProjectionStore.query_evidences(brand, source_type, min_confidence, limit)`(task_projection_store.py:557)——recall 查询(单 brand,helper 循环或扩 list)。
- `TaskProjectionStore.index_evidences`(research_runner.py:342 任务完成调)——"记"这边已 done,不动。
- evidences 表 schema(task_projection_store.py:186):entity/attribute/value/finding/source_url/source_type/domain/brand/confidence/captured_at/task_id。
- `ResearchBrief.target.name` + `.competitors`——brands 来源。
- competitive-analysis-agent `memory/inject.py` 的 `truncate_injection`(UTF-8 字节截断 + `(index truncated)`)+ 25KB cap——截断逻辑参照(不抄全模块)。

## 明确不做(边界)

- 新表(`competitor_memory`)/ compiler(LLM 抽事实)/ consolidate(遗忘)/ `competitor_memory_search` agent 工具(route A)/ 别名表/语义召回(embedding)——都不在最小切片。
- 不改 write 的 locked `system_prompt`(变化检测指令只进 user prompt blob 头)。
- 不改 search stage(CoverageEngine 自管;预填 cell 是深集成,不做)。
- 不保证 LLM 真用记忆标变化(policy-only,留 QA)。

## Verification

```bash
cd /Users/huangyaokai/pi4competitive
.venv/bin/python -m pytest tests/competitive_app/unit/test_memory_inject.py tests/competitive_app/integration/test_memory_inject.py -q   # offline
.venv/bin/python -m pytest tests/competitive_app -m "not live" -q --ignore=tests/competitive_app/unit/evolution  # 无回归(排除 evolution/pyyaml)
.venv/bin/ruff check <新文件>  # clean
.venv/bin/python -m pytest tests/competitive_app/integration/live/test_live_memory_inject.py -m live -q  # live(可选,需 gateway)
```
