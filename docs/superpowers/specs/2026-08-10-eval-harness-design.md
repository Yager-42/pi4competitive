# Eval Harness Design — CompetitorLens Benchmark 评测环境

| 字段 | 值 |
|------|-----|
| **document_version** | `0.1.0` |
| **status** | `draft`(等用户复核) |
| **created** | 2026-08-10 |
| **scope** | 根据 [`docs/competitorlens_benchmark_evaluation.md`](../../competitorlens_benchmark_evaluation.md) v0.1.0 搭建评测环境,本期交付 **C2-wide**:框架全套 + WideSearch Smoke 5 题真实 provider 跑通出第一份 scores |
| **runtime_under_test** | `competitive_app` 三阶段 workflow(`plan -> search -> write`) + A1 single_agent 基线 |
| **architecture_change** | 否;`eval/` 是评测外围包,不改 `competitive_app` HTTP/domain 契约,不改 `packages/ai|agent` |
| **release_gate** | 否;对齐基准文档 §0"不设通过标准" |

---

## 0. 决策树汇总(grill 收敛 2026-08-10)

本设计由 13 支决策(D0–D13)grill 收敛而成。每支决策记录在 §1–§13 对应小节。

| # | 决策 | 锁定值 |
|---|------|--------|
| D0 | 交付边界 | C2-wide:框架全套 + WideSearch Smoke 5 题真实跑通 |
| D1 | 双轨取舍 | C2-wide:双轨通用骨架,DRB II 留空壳,只 WideSearch 真接通 |
| D2 | Smoke 分组 | A1 + A2(出第一份 paired delta) |
| D3 | 代码落点 | L1:`eval/` 独立顶层 workspace 包 |
| D4 | 运行对接 | W1:HTTP 黑盒,进程边界即 gold 隔离边界 |
| D5 | 数据来源 | S4(挑明确点名实体题)+ P2(仓外 data/) |
| D6 | gold 隔离 | G2 三道闸:工具面裁剪 + cwd 隔离 + evaluator 独立进程 |
| D7 | 预算档 | B2:search 20 / fetch 40 / wall-clock 720s,A1/A2 同口径 |
| D8 | search provider | Tavily(`tavily_search`+`tavily_fetch`) |
| D9 | A1 造法 | A1-a+(i):复用 `_HarnessFactory` + `search_tavily`,独立 ASGI 服务 |
| D10 | evaluator wiring | M1(文件名带 variant)+ 全 LLM deepseek-v4-flash + N1(提表造 JSONL)+ H1(HF cache 离线)+ config 注册待定 |
| D11 | 结果产物 | 照搬基准文档 §9 目录;A1 socm 占位;Smoke 只 mean@1 |
| D12 | 测试纪律 | `tests/eval/` + CLI `eval.run`;复用 `tests/live_env.py`;§11 九条全落 |
| D13 | 失败 case 零分 | F1-F5 记 0;F6 null 单列;F2 照常评;completed 并列报分母 |

---

## 1. D0 交付边界:C2-wide

### 1.1 范围

本期交付:

1. **框架全套**:`eval/` 包(adapter / case manifest / orchestrator / normalizer / operations collector / evaluator wiring),双轨通用骨架。
2. **WideSearch Smoke 5 题真实跑通**:拉 WideSearch 数据 + Tavily 真实 provider + deepseek-v4-flash 主模型,跑 5 题 × A1/A2 × 1 重复,产出 `scores/widesearch.jsonl` + `paired_deltas.json`。

### 1.2 不做(D1 双轨的"wide"边界)

- DRB II 只搭接口空壳(adapter/normalizer 的 DRB II 分支 `raise NotImplementedError`),不拉数据、不接通 evaluator、不跑题。
- A0(model_only)、A3(serial_ablation)是诊断组,Smoke 不跑(基准文档 §2)。
- Pilot(20 题 × 3 重复)留下一期。

### 1.3 C2 的硬核

C2 不只搭框架,还**必须验证官方 evaluator 链路**——基准文档 §10.3 的 WideSearch scorer(`run_infer_and_eval_batching.py --stage=eval`)是官方仓库脚本,输入 schema(JSONL `WideSearchResponse`)、文件名规则(`{model_config_name}_{instance_id}_{trial_idx}_response.jsonl`)、gold 加载(`WideSearchDataLoaderHF`)只有真跑才知道对不对得上。框架代码不接通 scorer 等于没验证这一步。

---

## 2. D1 双轨取舍:C2-wide

### 2.1 双轨通用骨架

orchestrator / case manifest schema 按 benchmark-neutral 设计,基准文档 §5.1 的通用 manifest 字段(`benchmark` / `benchmark_revision` / `language` / `category` / `source_task_id` / `query` / `research_brief` / `license`)是所有 benchmark 共用。结果目录(§9)的 `normalized/widesearch_predictions/` 与 `normalized/drb2_reports/`、`scores/widesearch.jsonl` 与 `scores/drb2.jsonl` 本就是双轨并列。

### 2.2 DRB II 留空壳

DRB II 的 adapter(input/output)、normalizer 接口存在但 `raise NotImplementedError("DRB II track: C2-wide reserves shape, not wired (D1)")`。后面接 DRB II 是填空,不是改架构。

---

## 3. D2 Smoke 分组:A1 + A2

### 3.1 两组

- **A2 `competitorlens`**:`competitive_app` 完整 `plan -> CoverageEngine search -> write`,走 `POST /tasks`。
- **A1 `single_agent`**:裸 agent + 同款 `search_tavily` 工具 + 同款主模型 + 同款 budget,独立 ASGI 服务,不进 workflow。

### 3.2 不跑

A0(model_only)、A3(serial_ablation=`SEARCH_MAX_PARALLEL=1`)是诊断组,Smoke 不跑。基准文档 §2 明确"A0/A3 不要求每次都运行"。

### 3.3 增益口径

`Implementation Gain(metric, case) = metric(A2, case) - metric(A1, case)`。Smoke 5 题 × 1 重复,报 5 个 paired delta 的均值 + 逐题原始分。统计意义有限(Smoke 目标是连通不是结论),但能证 evaluator 出分且 paired 口径对。

---

## 4. D3 代码落点:L1 `eval/` 独立包

### 4.1 形态

新建顶层 `eval/` 目录,与 `competitive_app/`、`packages/` 平级。有自己的 `pyproject.toml`,加入 workspace(`根 pyproject.toml` 的 `members`)。

### 4.2 内部结构

```text
eval/
  pyproject.toml                # workspace member
  src/eval/
    __init__.py
    manifest.py                 # case manifest schema + 加载/校验
    adapter/
      __init__.py
      widesearch.py             # WideSearch case -> ResearchBrief (input)
      drb2.py                   # DRB II adapter 空壳 (NotImplementedError)
    runner/
      __init__.py
      http_client.py            # W1: httpx 打 POST /tasks, poll, 取 report
      single_agent_app.py       # A1 独立 ASGI 服务 (D9)
      budget_guard.py           # A1 工具 wrapper 计 search/fetch
    normalizer/
      __init__.py
      widesearch.py             # report.md -> WideSearchResponse JSONL (D10 N1)
      drb2.py                   # 空壳
    operations/
      __init__.py
      collector.py              # events.jsonl + projection + SOCM -> operations.json
    evaluator/
      __init__.py
      widesearch.py             # 调官方 scorer (D10 H1)
      drb2.py                   # 空壳
    orchestrator.py             # CLI 入口: eval.run --stage smoke
    manifest_builder.py         # 从 WideSearch widesearch.jsonl 挑 5 题 (S4)
  README.md
```

### 4.3 契约零风险

`tests/competitive_app/contract/test_deps.py` 只扫 `competitive_app/src/competitive_app/{domain,adapter/in_,adapter/out}`。`eval/` 不在其扫描范围,不受分层契约约束。但 `eval/` 仍遵守:`eval/` → `competitive_app` → `packages/agent` → `packages/ai` 单向依赖,不反向。

### 4.4 依赖

`eval/` 的 `pyproject.toml` 依赖:`httpx`(W1 HTTP)、`fastapi`(A1 ASGI)、`competitive_app`(workspace,内部 import)、`earendil_works.pi_agent`(A1 直接组装 harness)、复用 `tests/live_env.py`(门控)。第三方新增仅 `httpx`/`fastapi`(已是 competitive_app 依赖,不引入新库)。

---

## 5. D4 运行对接:W1 HTTP 黑盒

### 5.1 orchestrator → competitive_app(A2)

orchestrator 起独立 `competitive_app` 进程(`uv run competitive_app serve` 或复用 `scripts/serve_app.py`),走 HTTP:

1. `POST /api/v2/tasks`,body = `WorkflowTaskRequest(research_brief=..., search_overrides=...)`,返回 `task_id`(202)。
2. poll `GET /api/v2/tasks/{task_id}` 直到 `terminal_status ∈ {completed, failed, aborted}`(轮询间隔 5s)。
3. `GET /api/v2/tasks/{task_id}/report` 取 Markdown;`GET /api/v2/tasks/{task_id}/sessions` 取 trace;`data/runs/{task_id}/events.jsonl` 直接读文件取 operations 事件流。
4. 总 wall-clock guard 900s,超了 `POST /api/v2/tasks/{task_id}/abort`(D13)。

### 5.2 orchestrator → A1 single_agent 服务(A1)

A1 是独立 ASGI 服务(`eval serve --variant single_agent`),orchestrator 走同一 HTTP 模式打它。A1 暴露 `POST /eval/run` 接 `ResearchBrief`/query,返回 `task_id`,poll `GET /eval/run/{task_id}`。

### 5.3 为什么黑盒

- **gold 隔离**:运行进程(App + A1)起在独立进程,环境只给 `OPENAI_*`/`TAVILY_*`,不给 gold 路径;evaluator 进程才挂 gold。进程边界 = 隔离边界(D6 闸 3)。
- **测的是真实产品**:外围走 HTTP 黑盒,证评测的是 `competitive_app` 真实入口,不是内部 API 切面。基准文档 §0.1"不改 HTTP/domain 契约"对齐。
- **顺带验证可观测性**:orchestrator 靠 `events.jsonl` + `task_spans` + `/health` 拿 operations 指标。够用说明可观测面够;不够则暴露缺口(本期额外价值)。

---

## 6. D5 数据来源:S4 + P2

### 6.1 Smoke 5 题选择(S4)

从 WideSearch 200 题里选 5 题英文(`ws_en_*`),规则:**query 中明确点名 ≥2 个公司/产品/品牌/比较对象**(对齐基准文档 §3.2 business subset 倾向 + §5.2"只列题目中明确出现的公司/产品")。筛选流程:

1. 脚本扫 100 英文题 query,关键词预筛(`vs`/`compared to`/` or `/多个首字母大写实体)。
2. 人工 confirm 5 题,保证 `ResearchBrief.competitors`(`min_length=1`)能从 query 合法填出。
3. 固化为 `eval/manifests/widesearch_smoke.jsonl`(versioned manifest,SHA 进 run manifest)。

### 6.2 物理存放(P2)

| 内容 | 位置 | git | 说明 |
|------|------|-----|------|
| WideSearch 仓 scorer 代码 | `vendor/widesearch/` | ✅ 进 git | 公开代码,可版本 pin;`scripts/fetch_upstream.sh` 模式 sparse-checkout |
| WideSearch gold CSV | `data/benchmarks/widesearch/widesearch_gold/` | ❌ gitignore | gold 不进仓;运行进程不可见(D6) |
| HF dataset 缓存 | `data/benchmarks/hf_cache/` | ❌ gitignore | `huggingface-cli download` 预填;scorer 走 `HF_DATASETS_CACHE` 离线 |
| WideSearch query/gold 数据 | `data/benchmarks/widesearch/widesearch.jsonl` | ❌ gitignore | 从 HF 拉;含 gold,运行进程不直接读 |
| `REVISION.txt` | `data/benchmarks/widesearch/REVISION.txt` | ✅ 进 git | 记 HF dataset commit SHA + 仓 SHA;manifest 引用 |

### 6.3 gold 与代码物理分离

WideSearch 仓的 **代码**(scorer)进 `vendor/widesearch/`(可 git,无 gold);**gold CSV** 不进 git,放 `data/benchmarks/`。代码与 gold 物理分离——evaluator 进程 import scorer 代码 + 挂 gold 路径,运行进程两都不碰。

---

## 7. D6 gold 隔离:G2 三道闸

### 7.1 闸 1 工具面裁剪(最强)

A2 的 `all_tools` = `capability_tools`,capability packages 只注册 `search_tavily`/`search_anysearch`/`search_grok`/`reasonix_prefix_cache`/`pi_auto_review`/`echo_example`——**没有 `create_coding_tools`/read/write/bash**。A2 subagent 工具集经 `is_search_tool(t.name)` 过滤(`research_runner.py:432`),只拿 search 工具。**A2 天然读不到文件系统**。

A1 runner 必须坚持同款裁剪:`enabled=["search_tavily"]`,**不装 coding tools**。这是 `eval/runner/single_agent_app.py` 的硬约束,且 contract 测试 guard:`eval/runner/` 不得注册 read/write/bash 类工具。

### 7.2 闸 2 cwd + 目录隔离

运行进程(App + A1)cwd = `eval/runs/<run_id>/work/`。gold 在 `data/benchmarks/widesearch/widesearch_gold/`,不在运行进程 cwd 子树。`data/benchmarks/` gitignore 不进仓。

### 7.3 闸 3 evaluator 独立进程

gold 只挂给 evaluator 进程(`eval/evaluator/` 独立 venv + 独立 cwd)。evaluator 调官方 scorer 读 gold CSV + normalized predictions 出分。**所有 case × variant × repetition 跑完才起 evaluator**(基准文档 §10.2.6),避免逐题分数反馈影响后续运行。运行进程不调 evaluator。

### 7.4 contract guard

`tests/eval/contract/test_gold_isolation.py`:AST 扫 `eval/runner/` + `eval/adapter/`,assert 不 import `widesearch_gold` 路径、不 `open()` `data/benchmarks/`。manifest builder 代码不 import gold(§7.5)。

### 7.5 manifest 不含 gold

manifest 是 orchestrator↔evaluator 的契约。manifest 记 gold 路径(给 evaluator 用),但运行进程的 env 不含 gold 路径,运行进程不读 manifest 的 gold 字段。manifest builder(`eval/manifest_builder.py`)只从 `widesearch.jsonl` 的 `query`/`evaluation.required` 推导 `ResearchBrief`,不读 gold CSV cell。

---

## 8. D7 预算档:B2

### 8.1 预算

| 项 | 值 | 说明 |
|----|----|------|
| search 上限 | 20 | A2:`SearchOverrides.max_queries=20`;A1:工具 wrapper 计数 |
| fetch 上限 | 40 | A2:不直接限(SearchOverrides 无 max_fetches),subagent search→fetch 联动;A1:wrapper 限 40 |
| wall-clock(search) | 720s | A2:`SearchOverrides.max_wall_seconds=720`;A1:budget guard 720s |
| wall-clock(总) | 900s | orchestrator hard guard,超 abort |
| coverage_threshold | 0.8(A2 默认) | 不改 |
| max_parallel(A2) | 默认 | Smoke 不做 A3 ablation,不动 |

### 8.2 A1/A2 同口径

A1 和 A2 的 search 上限都是 20、wall-clock 都是 720s。A2 的 fetch 不直接限(实际不会爆,`max_queries` 限了 search→fetch 联动),A1 的 fetch 限 40。**真实调用数都从 `events.jsonl` 的 `tool.called` 事后统计**,进 `operations.json`(基准文档 §6.2 兜底口径)。

### 8.3 fetch 2× 比例

fetch 40 = search 20 × 2,对齐基准文档 §6.2 Pilot 档的 1:2(30:60)。B2 是 Pilot 档的 2/3,Smoke 过渡。

---

## 9. D8 search provider:Tavily

### 9.1 选择

A1/A2 共用 `search_tavily` capability package(`tavily_search` + `tavily_fetch`,分离的两个工具)。

### 9.2 理由

- WideSearch 是英文通用网页信息收集题,Tavily 专为 agent 网页检索设计,英文覆盖稳。
- `tavily_search`/`tavily_fetch` 分离,能分别计数(D7 预算分计)。
- live test 已证 Tavily 链路通(`tests/capability_loader/integration/live/test_live_search_capability.py`),Smoke 不会卡在 provider 调通。
- 主模型 deepseek-v4-flash 跟搜索 provider 解耦,paired delta 只反映 CoverageEngine 差异。

### 9.3 排除

Grok(LLM+搜索一体,会跟主模型混淆;X 实时数据非通用网页)。Anysearch 留 Pilot 对照变量,Smoke 先锁 Tavily。

### 9.4 配置

`.env` 已有 `TAVILY_API_KEY` + `TAVILY_API_URL`。运行进程 env 传这两个;`SEARCH_PROVIDER` 不需要(A2 的 capability_packages_enabled 决定装哪个包,orchestrator 起进程时配 `enabled=["search_tavily"]`)。

---

## 10. D9 A1 造法:A1-a + (i)

### 10.1 复用底座

A1 复用 `competitive_app.wiring._HarnessFactory` 组装 harness + `load_capability_packages(enabled=["search_tavily"])` 装同款工具 + 同款 `create_models()` 配 deepseek-v4-flash + `OPENAI_BASE_URL=chatanywhere.tech`。**工具/模型/budget 与 A2 字面同一份代码**,paired delta 才干净。

### 10.2 不进 workflow

A1 不进 `ResearchRunner`/CoverageEngine。直接给 agent 一个 prompt:

> 用给定的 `tavily_search`/`tavily_fetch` 工具,在 20 次 search + 40 次 fetch 预算内,完成 query 并输出 Markdown 表(列头必须含 required headers)。

prompt pin 进 manifest(基准文档 §6.1"system prompt 固定")。跑 `agent_loop` 到结束或 budget 耗尽。

### 10.3 budget guard

`eval/runner/budget_guard.py`:tool wrapper 计 `search_count`/`fetch_count`,超 20/40 拒绝(返回 error 让 agent 收手);wall-clock 720s asyncio 超时。

### 10.4 独立 ASGI 服务(i)

`eval serve --variant single_agent` 起一个 ASGI app(`eval/runner/single_agent_app.py`),暴露 `POST /eval/run` + `GET /eval/run/{task_id}` + `GET /eval/run/{task_id}/report`。orchestrator 走 W1 同款 HTTP 黑盒打它,与 A2 对称。A1 工具是 eval 包资产,不污染 `competitive_app` 产品代码。

### 10.5 排除 A1-b / A1-c

A1-b(裸 pi_agent + 自复刻装载)有 drift 风险,grill 要可比性,排除。A1-c(给 competitive_app 加 single_agent 模式)改产品代码,违反 §0.1,排除。

---

## 11. D10 evaluator wiring

### 11.1 M1:文件名带 variant

A1 用 `model_config_name=competitorlens_a1`,A2 用 `competitorlens_a2`。官方 scorer 文件名 `{model_config_name}_{instance_id}_{trial_idx}_response.jsonl` 天然区分 variant,不撞名,一次/两次 scorer 调用出两组分。

### 11.2 全 LLM 用 deepseek-v4-flash

| LLM 角色 | 模型 |
|---------|------|
| A2 主模型(plan/search/write + judge 抽 evidence) | deepseek-v4-flash |
| A1 主模型(裸 agent) | deepseek-v4-flash |
| WideSearch evaluator LLM judge(`--eval_model_config_name`) | deepseek-v4-flash |

被测与评判同款,有 self-judge bias 风险,但本期明确决策(省事),manifest pin。Pilot 阶段再评估换独立 judge。

### 11.3 N1:normalizer 造 WideSearchResponse JSONL

A2 产物 `report.md`(Markdown 含表)→ `eval/normalizer/widesearch.py`:

1. 确定性 Markdown parser 提取含 required headers 的表(基准文档 §5.3)。
2. 去外围 fenced-code 标记,不改写 cell。
3. 造 `WideSearchResponse(instance_id=ws_en_001, response=<表字符串>, messages=[], trial_idx=0)`。
4. 写 `normalized/widesearch_predictions/competitorlens_a2_ws_en_001_0_response.jsonl`。

A1 同流程,产 `competitorlens_a1_...`。`messages` 留 `[]`(scorer 不用)。

### 11.4 H1:scorer 走 HF cache 离线

`HF_DATASETS_CACHE=data/benchmarks/hf_cache`,首次 `huggingface-cli download ByteDance-Seed/WideSearch` 预填。scorer 跑时 `HF_HUB_OFFLINE=1` 离线。不改官方 scorer 代码(基准文档 §10.3"官方脚本原样调")。版本 pin = HF dataset commit SHA(进 manifest `benchmark_revision`)。

### 11.5 config 注册:待定

WideSearch 仓 `src/utils/config.py` 要注册一个指向 `deepseek-v4-flash` + `chatanywhere.tech` 的 model config(主)+ eval config(judge)。注册方式:

- **C-reg-1**:patch `vendor/widesearch/` 的 config 文件加 `deepseek-v4-flash` config(改官方代码,记 patch diff)。
- **C-reg-2**:用 WideSearch 的 custom config 机制(若 `config.py` 支持 env 注入,不改代码)。

**待 `vendor/widesearch/` 拉下来看 `config.py` 后确认**。design 标 `待定`,实现计划第一步拉仓确认。不阻塞其他工作。

### 11.6 scorer 命令

```bash
HF_DATASETS_CACHE=data/benchmarks/hf_cache \
HF_HUB_OFFLINE=1 \
python3 vendor/widesearch/scripts/run_infer_and_eval_batching.py \
  --trial_num=1 \
  --model_config_name=competitorlens_a2 \
  --eval_model_config_name=deepseek-v4-flash \
  --response_root=data/evaluations/<run_id>/normalized/widesearch_predictions \
  --result_save_root=data/evaluations/<run_id>/scores/widesearch_raw \
  --stage=eval
```

A1 同命令换 `--model_config_name=competitorlens_a1`。命令串原样进 run manifest(基准文档 §10.3"调用命令必须原样写入 run manifest")。

---

## 12. D11 结果产物

### 12.1 目录结构(照搬基准文档 §9)

```text
data/evaluations/<run_id>/
  manifest.json
  cases.jsonl
  raw/
    widesearch/<case_id>/<variant>/<repetition>/
      request.json
      task_projection.json
      report.md
      socm.json
      trace.json
      operations.json
  normalized/
    widesearch_predictions/      # WideSearchResponse JSONL
    drb2_reports/                # 空目录占位 (D1)
  scores/
    widesearch_raw/              # scorer 原始输出 (eval_result.json × N)
    widesearch.jsonl             # 汇总 (case/variant/repetition 一行)
    drb2.jsonl                   # 空文件占位 (D1)
    operations.jsonl
    paired_deltas.json
  summary/
    metrics.json
    metrics.csv
    report.md
```

### 12.2 A1 socm 占位

A1 无 SOCM,`raw/.../a1/.../socm.json` 写 `{"variant": "a1", "note": "single_agent has no SOCM"}`。保结构对称,汇总脚本不用特殊处理。

### 12.3 Smoke summary 只 mean@1

Smoke 每 case 1 次重复。summary 产 `mean@1` + 逐题原始分 + paired delta(5 题)。**不报 max@3/std**(分母 1 无意义,留 Pilot)。manifest `repetitions=1` 标清。

### 12.4 run_id

`run_id = smoke-ws-<manifest_rev>-<short-sha>`(如 `smoke-ws-a1b2c3-a80dab2`)。manifest_rev 是 case manifest 文件 SHA,short-sha 是 repo commit。从 run_id 就能定位配置。

### 12.5 operations 三源汇总

`eval/operations/collector.py` 读:
- `data/runs/<task_id>/events.jsonl`(RunJournal 事件流)→ `tool.called`/`tool.finished`/`llm.request`/`llm.response`/`llm.fallback_*`/`budget`/`agent.started`/`agent.finished`
- `task_projection.json` → terminal status / 失败阶段
- `socm.json` → evidence node 数 / filled/unknown/conflict cell 数(A2 only;A1 无)

产 `operations.json`(每 case/variant/repetition 一份)+ 汇总 `scores/operations.jsonl`。token/cost 从 `llm.request`/`llm.response` payload 提 usage 字段。

### 12.6 .gitignore 补

`.gitignore` 加 `data/evaluations/`(基准文档 §9 说"已 gitignore",实际没加,本期补)。

### 12.7 manifest.json 字段

照搬基准文档 §9:repo commit + dirty 标记、benchmark/dataset revision、case-manifest revision、model/provider/参数、capability package + evaluator revision、预算/timeout/并行度/env 变量名(不记 secret value)、run start/end 时区、scorer 命令及退出码。

### 12.8 不可变

原始运行产物(raw/)不可由 scorer 覆盖。normalization 和 scoring 始终写新文件(normalized/、scores/),使结果可重放(基准文档 §9)。

---

## 13. D12 测试纪律与可复现性

### 13.1 测试目录

eval 离线单测放 `tests/eval/`(仓库根 `tests/` 下,与 `tests/competitive_app/`、`tests/packages/` 平级):

```text
tests/eval/
  unit/              # 离线,CI 全跑 (faux provider)
    test_manifest.py
    test_normalizer_widesearch.py
    test_operations_collector.py
    test_budget_guard.py
  contract/          # gold 隔离 guard
    test_gold_isolation.py
  integration/
    live/            # @pytest.mark.live, 1 题烟测, 无 key skip
      conftest.py    # 复用 tests/live_env.py
      test_smoke_one_case.py
```

### 13.2 复用门控

`tests/eval/integration/live/conftest.py` 复用 `tests/live_env.py` 的 `load_dotenv()` + `live_credentials()`(无 key skip)。pytest markers `live`/`slow` 已注册。

### 13.3 Smoke 完整跑走 CLI

Smoke 5 题 × 2 variant × 12 分钟 ≈ 2 小时,不是 pytest 形态。走 CLI:

```bash
uv run python -m eval.run --stage smoke --benchmark widesearch --variants a1,a2
```

`eval.run` 是 orchestrator 入口,参数化 stage/benchmark/variants。产物落 `data/evaluations/<run_id>/`。

### 13.4 §11 九条偏差控制 Smoke 落地

| §11 风险 | Smoke 落地 |
|---------|----------|
| 网页随时间变 | ✅ `events.jsonl` 记访问时间+URL+原始 tool result;operations collector 汇总 |
| 搜索排序不稳 | ⚠️ Smoke 1 次不报 variance,留 Pilot(基准文档 §6.3) |
| evaluator 漂移 | ✅ pin evaluator model(deepseek-v4-flash)+ prompt + scorer 仓 SHA 进 manifest |
| gold 泄漏 | ✅ D6 三道闸 + contract guard |
| 手工 subset 偏差 | ✅ S4 规则固化 + 5 题 case ID 清单 + manifest 版本化 |
| 输出后处理掩盖失败 | ✅ 只确定性 normalization(N1 提表),禁 LLM 修复(基准文档 §5.3.6) |
| 内部 confidence 冒充正确率 | ✅ SOCM coverage 与 gold recall 分名分报(基准文档 §7.1) |
| 不同组预算不一致 | ✅ A1/A2 同 B2 预算,manifest 记 |
| evaluator 成本遗漏 | ✅ evaluator token/耗时进 operations,不改质量分 |

### 13.5 manifest 一次性冻结

run 开始时 `manifest.json` 一次性写死,run 过程中不改。pin:

- `repo_commit` + `dirty`(`git rev-parse HEAD` + `git status --porcelain`)
- `benchmark_revision`(WideSearch 仓 SHA + HF dataset SHA)
- `manifest_revision`(case manifest 文件 SHA)
- `model`/`provider`/`base_url`/`eval_model_config_name`(全 deepseek-v4-flash)
- `budget`(B2:search 20 / fetch 40 / 720s)
- `search_provider`(tavily)
- `scorer_command`(原样命令串)

---

## 14. D13 失败 case 零分规则

### 14.1 失败形态

| 形态 | 来源 | 判据 |
|------|------|------|
| F1 任务超时 | wall-clock 720s 耗尽 | `terminal_status=timeout/aborted` |
| F2 预算耗尽半空 | search 20 跑完 coverage 没达标 | `exhausted_dim` 或 report 缺列 |
| F3 搜索 provider 失败 | Tavily 限流/key 错 | `events.jsonl` 多次 tool error |
| F4 LLM 失败 | deepseek 5xx/超时 | `llm.fallback_exhausted` |
| F5 不可评分输出 | report.md 无合法表/缺 headers | normalizer 返回 null |
| F6 evaluator 失败 | scorer 崩 | scorer 退出码非 0 |

### 14.2 规则

- **F1-F5(被测系统失败)**:scorer 不出分 → `scores/widesearch.jsonl` 该 case 行记 `score=0` + `failure_stage` + `terminal_status` + 原始输出。进 all-case 均值(分母含)。基准文档 §8.3"不从 macro average 中静默删除"。
- **F6(evaluator 崩)**:该 case `score=null` + `failure_stage=evaluator`,**不记 0**(不是被测系统错),单独计数 `evaluator_failures`。summary 单列。
- **F2(预算耗尽半空表)**:照常进 scorer 评分。半空是实验条件(预算不足),不是失败。`Item Recall` 低真实反映;`Item Precision` 该多少多少。paired delta 在同 B2 预算下公平(A1 也只 20 search)。**例外**:A2 因预算耗尽连表都没产出(write 崩)→ F5,走 0 分。

### 14.3 completed 定义

`completed` = 被测系统 `terminal_status=completed` 且 scorer 出分(排除 F6)。all-case 分母 = 全部 5 题 × variant;completed-only 分母 = 排除 F6 后。两数并列报(基准文档 §8.3)。

### 14.4 wall-clock

- A2 search budget:`SearchOverrides.max_wall_seconds=720`(CoverageEngine 自己超了停)。
- A1 budget guard:720s asyncio 超时。
- orchestrator 总 900s hard guard:超 `POST /tasks/{id}/abort`,拿半成品。

---

## 15. 待定项与不阻塞说明

### 15.1 D10 config 注册待定

WideSearch model config 注册方式(C-reg-1 patch vs C-reg-2 env)待 `vendor/widesearch/` 拉下来看 `src/utils/config.py` 后定。**实现计划第一步:拉仓确认**。不阻塞其他组件设计。

### 15.2 不阻塞 design 落地

其余 12 支决策全部锁定,design 可据此进入 writing-plans。config 注册的实现细节在计划里标"待拉仓确认",不卡流程。

---

## 16. 验收(C2-wide Smoke 跑通口径)

1. `eval/` 包可 `uv sync` 安装,`tests/eval/unit/` 全绿(CI `-m "not live"`)。
2. `tests/eval/contract/test_gold_isolation.py` 绿(gold 隔离 guard)。
3. `tests/eval/integration/live/test_smoke_one_case.py` 在有 key 时跑通 1 题(无 key skip 不阻塞)。
4. CLI `uv run python -m eval.run --stage smoke --benchmark widesearch --variants a1,a2` 跑完 5 题 × 2 variant,产 `data/evaluations/<run_id>/` 完整目录。
5. `scores/widesearch.jsonl` 含 10 行(5 题 × 2 variant),每行有官方 scorer 的 `score`/`precision_by_item`/`recall_by_item`/`f1_by_item`/`precision_by_line`/`recall_by_line`/`f1_by_line`。
6. `scores/paired_deltas.json` 含 5 个 paired delta(A2-A1)+ 均值。
7. `summary/metrics.json` 含 mean@1 + completed-only(分母标注)。
8. `manifest.json` 含 §12.7 全部字段,scorer 命令原样写入。
9. 失败 case(F1-F5)记 0 进 all-case,F6 记 null 单列(若有)。

---

## 17. 版本记录

| 版本 | 日期 | 变化 |
|------|------|------|
| 0.1.0 | 2026-08-10 | 初版:grill 收敛 D0-D13 决策树,C2-wide 范围,WideSearch Smoke 跑通 |
