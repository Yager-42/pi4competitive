# CompetitorLens 组合基准评测方案

| 字段 | 值 |
|------|-----|
| **document_version** | `0.1.0` |
| **status** | `draft` |
| **updated** | 2026-08-05 |
| **scope** | 使用 WideSearch + DeepResearch Bench II 量化 `competitive_app` 的搜索覆盖、事实收集和报告生成效果 |
| **runtime_under_test** | `competitive_app` 三阶段 workflow：`plan -> search -> write` |
| **architecture_change** | 否；本文只定义评测适配、实验控制和结果口径 |
| **release_gate** | 否；本文不设置通过标准或发布门槛 |

---

## 0. 目的与边界

本文定义一套可重复执行的组合评测：

1. 使用 **WideSearch** 测量大规模实体×属性信息收集的完整性和事实正确性。
2. 使用 **DeepResearch Bench II** 测量最终研究报告的信息召回、分析和呈现质量。
3. 通过固定模型、搜索供应商和预算下的配对实验，量化当前 CoverageEngine 相对简单搜索基线的实现增益。
4. 同时记录成本、延迟、工具调用、来源和失败行为，使质量变化可以结合运行代价解释。

本文只规定“测什么、怎样测、怎样记录”。**不定义最低分数、通过阈值、验收门槛或发布阻断条件**。

### 0.1 非目标

| 非目标 | 说明 |
|--------|------|
| 复现 WideSearch 或 DRB II 的排行榜环境 | 排行榜模型、搜索供应商和运行预算与本项目不同 |
| 用 benchmark gold 指导搜索 | gold、rubric 和参考答案只能进入 evaluator |
| 以单一总分替代诊断指标 | 总分仅用于汇总展示，分项指标仍是解释结果的依据 |
| 修改生产 workflow 契约 | benchmark adapter 属于评测外围，不改变产品 HTTP/domain 契约 |
| 评测图片搜索 | 当前组合是文本网页检索与报告评测，不覆盖 MMSearch-Plus 的多模态能力 |

---

## 1. 两条评测轨道

| 轨道 | Benchmark | 被测能力 | 主要输出 | 主要指标 |
|------|-----------|----------|----------|----------|
| Search Track | WideSearch | 发现实体、覆盖属性、跨来源收集、结构化事实输出 | Markdown table | Item/Row Precision、Recall、F1 |
| Report Track | DeepResearch Bench II | 信息召回、综合分析、结构组织和表达 | Markdown report | Information Recall、Analysis、Presentation |

两个轨道分别报告，不互相替代：

- WideSearch 高分说明事实表格找得较全、较准，但不说明长报告有洞察。
- DRB II 高分说明报告满足专家 rubric，但不能单独定位搜索缺口来自哪个 coverage cell。

### 1.1 为什么匹配当前项目

当前 workflow 的 `plan` 生成 coverage schema，`search` 通过 CoverageEngine 迭代填充实体×属性 cell，`write` 从 SOCM 生成报告。WideSearch 对应前两阶段，DRB II 对应完整三阶段及最终产物，组合后覆盖当前产品主链。

---

## 2. 评测对象与实验分组

每个 benchmark case 在相同运行条件下执行以下分组：

| 组 | 名称 | 行为 | 测量目的 |
|----|------|------|----------|
| A0 | `model_only` | 相同主模型直接回答，不提供搜索工具 | 建立模型参数知识基线 |
| A1 | `single_agent` | 单个 agent 使用与项目相同的 search/fetch 工具，在固定预算内完成任务 | 建立普通 agentic search 基线 |
| A2 | `competitorlens` | 当前 `plan -> CoverageEngine search -> write` 完整链路 | 测量当前项目整体效果 |
| A3 | `serial_ablation` | 与 A2 相同，但 `SEARCH_MAX_PARALLEL=1` | 分离并行 sub-agent 的影响 |

如某轮只关心整体项目相对普通 agent 的增益，可执行 A1 和 A2；A0/A3 是诊断组，不要求每次都运行。

### 2.1 实现增益

每个 case 采用配对差值，而不是比较不同题目的总体均值：

```text
Implementation Gain(metric, case)
  = metric(A2, case) - metric(A1, case)
```

总体实现增益报告配对差值的均值、中位数、95% bootstrap confidence interval，以及 A2 相对 A1 的 win/tie/loss 数量。该统计只描述效果，不构成通过判定。

---

## 3. 数据集范围

### 3.1 分阶段规模

| 阶段 | WideSearch | DeepResearch Bench II | 每 case 重复次数 | 用途 |
|------|-----------:|----------------------:|------------------:|------|
| Smoke | 5 | 3 | 1 | 验证 adapter、输出和 scorer 连通 |
| Pilot | 20 | 10 | 3 | 形成第一版稳定对比结果 |
| Business subset | 约 66 个商业相关题 | 20–30 个公司/产品/市场题 | 3 | 产品定位下的主要结果 |
| Full benchmark | 200 | 132 | 3 | 与 benchmark 全量分布对照，按成本决定是否执行 |

阶段名称表示执行规模，不表示 gate。任何阶段均可独立运行和发布结果。

### 3.2 Case 选择规则

WideSearch business subset 优先选择题目中明确给出实体或比较范围的任务，例如：

- 公司财务和季度表现对比；
- 品牌市场份额和门店规模；
- 手机、汽车、家电等产品线与规格；
- 软件、平台或供应商横向比较；
- 明确要求来源、时间范围和 Markdown 表头的任务。

DRB II business subset 优先选择：

- 公司、厂商或产品对比；
- 市场规模、成本结构和竞争格局；
- 技术路线、商业化进度和主要参与者；
- 金融、软件、工业和消费产品研究。

选择清单必须固化为 versioned manifest；不能根据某次模型结果临时增删 case。

### 3.3 许可过滤

DeepResearch Bench II 数据为逐题许可：

- 129 题为 CC BY 4.0；
- `idx=26`、`idx=110` 为 CC BY-NC 4.0；
- `idx=119` 为 CC0。

用于商业场景的评测 manifest 默认排除 `idx=26` 和 `idx=110`，并在结果元数据中保存每题许可。WideSearch 仓库代码和随仓 LICENSE 为 MIT；使用时仍记录数据集版本和原始来源。

---

## 4. 评测数据流

```text
official task/query
        |
        v
case manifest (不含 gold/rubric)
        |
        v
benchmark adapter -> ResearchBrief -> competitive_app task
                                         |
                              plan -> search -> write
                                         |
                    report + SOCM + trace + usage
                         |                   |
                         v                   v
                 output normalizer     operations collector
                         |                   |
                         +---------+---------+
                                   v
                         official evaluator
                                   |
                                   v
                         normalized run result
```

### 4.1 Gold 隔离

运行进程只能访问：

- 原始任务 prompt/query；
- 题目公开要求的输出列和格式；
- manifest 中人工整理、仅由 prompt 推导的 ResearchBrief；
- 生产环境本来可访问的网页。

运行进程不得访问：

- WideSearch `widesearch_gold/*.csv`；
- DRB II `tasks_and_rubrics.jsonl` 中的 rubric 内容和专家参考内容；
- 其他系统已生成的 benchmark 报告；
- evaluator 的中间判断和分数。

Gold/rubric 仅挂载到独立 evaluator 进程。评测完成前，不向运行进程回传逐题错误信息。

---

## 5. Benchmark Adapter

### 5.1 通用 Case Manifest

建议每个 case 固化以下字段：

```json
{
  "case_id": "ws_en_001",
  "benchmark": "widesearch",
  "benchmark_revision": "<commit-or-dataset-sha>",
  "language": "en",
  "category": "business",
  "source_task_id": "ws_en_001",
  "query": "<verbatim official query>",
  "research_brief": {
    "target": {"name": "<scope name>", "category": "benchmark"},
    "goal": "<verbatim official query>",
    "competitors": ["<entities explicitly named in query>"],
    "dimensions": ["<columns or requirements explicitly named in query>"]
  },
  "license": "MIT",
  "notes": ""
}
```

Manifest 的 ResearchBrief 只允许从题目文本推导，并在任何正式运行前冻结。不能从 gold row、rubric 或参考报告补充实体和维度。

### 5.2 WideSearch 输入适配

| ResearchBrief 字段 | 映射规则 |
|---------------------|----------|
| `target.name` | 题目研究范围的简短名称；无法稳定命名时使用 `widesearch:<case_id>` |
| `target.category` | 固定为 `benchmark` 或预先冻结的商业类别 |
| `goal` | WideSearch 原始 query，逐字保留任务条件、时间范围和输出格式 |
| `competitors` | 只列题目中明确出现的公司、产品、品牌或比较对象 |
| `dimensions` | 题目要求的 Markdown 列；可读取公开 `evaluation.required`，不得读取 gold cell |

Pilot 优先使用明确列出比较实体的题目，避免用未知 gold entity 填充 `competitors`。需要开放式枚举的任务保留在 full benchmark，用于暴露当前 coverage schema 对动态实体发现的限制。

### 5.3 WideSearch 输出适配

1. 从 `GET /reports/{task_id}` 取得最终 Markdown。
2. 使用确定性 Markdown parser 寻找包含 required headers 的表格。
3. 去除外围 fenced-code 标记，但不改写 cell 内容。
4. 多个候选表格时，选择 required-header 覆盖最高且顺序最接近任务要求的表格；规则必须固定并记录版本。
5. 找不到合法表格时保留原始输出，并按官方 evaluator 的格式规则评分。
6. 禁止调用额外 LLM 重排、补列、翻译或修复表格。

### 5.4 DeepResearch Bench II 输入适配

| ResearchBrief 字段 | 映射规则 |
|---------------------|----------|
| `target.name` | prompt 中的研究对象或主题 |
| `target.category` | manifest 中预先冻结的领域分类 |
| `goal` | DRB II 原始 prompt，逐字保留 |
| `competitors` | prompt 明确列出的公司/产品；非竞品任务使用 prompt 明确列出的比较对象 |
| `dimensions` | prompt 的编号要求、章节要求或显式比较维度 |

DRB II rubric 不参与 ResearchBrief 构造。对于无法由 prompt 合法构造 `competitors>=1` 的题目，不临时读取 rubric 补齐；应在 manifest 中排除，或另行定义不依赖 gold 的固定映射规则并升 manifest 版本。

### 5.5 DeepResearch Bench II 输出适配

最终报告不做 LLM 后处理，按 benchmark case ID 保存为：

```text
report/<variant>/idx-<source_task_id>.md
```

只允许确定性处理：字符编码统一、换行规范化和 benchmark 要求的文件命名。引用、标题、章节、表格和正文内容保持原样。

---

## 6. 运行控制

### 6.1 跨组固定项

同一 case 的 A0–A3 固定：

- 主模型 ID、provider 和模型参数；
- judge/extraction 模型；
- 搜索供应商和 capability package 版本；
- search/fetch 调用预算；
- wall-clock timeout；
- temperature 和随机种子（provider 支持时）；
- system prompt、skill snapshot 和 capability manifest；
- benchmark revision、manifest revision 和 evaluator revision。

只有分组定义中明确指定的机制可以变化。

### 6.2 建议预算档

预算是实验自变量，按 run manifest 记录，不是通过标准：

| Track | 建议起始预算 | 建议 wall-clock timeout |
|-------|--------------|-------------------------|
| WideSearch Pilot | 30 search + 60 fetch | 15 分钟/case |
| DRB II Pilot | 60 search + 120 fetch | 30 分钟/case |

如实际工具不能分别限制 search/fetch，则记录统一 tool-call budget，并在结果中拆出真实调用次数。不同预算档必须使用不同 run ID，不合并为同一总体均值。

### 6.3 重复运行与顺序

- Smoke 每 case 运行 1 次。
- Pilot、business subset 和 full benchmark 默认每 case 运行 3 次。
- A0–A3 按 case 交错和随机排序，减少网页更新、供应商负载和时间段造成的系统偏差。
- WideSearch 同时报告官方 `max@3`、工程 `mean@3`、标准差和逐题三次原始分数。
- evaluator 模型和 prompt 必须 pin；更换 evaluator 后新建结果系列，不直接覆盖旧结果。

---

## 7. 指标

### 7.1 WideSearch 官方指标

| 指标 | 含义 |
|------|------|
| Item Precision | 预测 cell 中正确 cell 的比例 |
| Item Recall | gold cell 中被正确找回的比例 |
| Item F1 | cell precision/recall 的调和平均 |
| Row Precision | 预测完整正确 row 的比例 |
| Row Recall | gold 完整 row 被正确找回的比例 |
| Row F1 | row precision/recall 的调和平均 |

补充记录：

- Markdown table parse rate；
- required-header coverage；
- 输出 row/cell 数；
- SOCM coverage ratio 与 gold Item Recall 的差异；
- filled/unknown/conflict cell 数量。

SOCM coverage ratio 是内部自评，不能替代 WideSearch gold recall。二者的差值用于观察“系统认为已覆盖”与“实际上答对”之间的校准误差。

### 7.2 DeepResearch Bench II 官方指标

| 指标 | 含义 |
|------|------|
| Information Recall | 报告是否包含专家 rubric 要求的关键信息 |
| Analysis | 报告是否形成 rubric 要求的比较、因果、综合或洞察 |
| Presentation | 报告是否按要求组织和呈现信息 |
| Rubric Satisfaction Rate | 满足的有效 rubric 占比 |
| Blocked Reference Rate | 依赖 benchmark 明确禁止参考内容的比例 |

DRB II 不等价于逐引用网页支持验证。若后续需要 Citation Accuracy，可在独立轨道接入原版 DeepResearch Bench FACT；不得把当前项目的 confidence 字段直接命名为事实准确率。

### 7.3 运行指标

每个 case/variant/repetition 记录：

- terminal status 与失败阶段；
- 总耗时、各 stage 耗时、p50/p95 汇总；
- prompt/completion token；
- 可获得时的 provider cost；
- search/fetch/其他 tool call 数；
- distinct source/domain 数；
- evidence node 数与每个正确 gold cell 的成本；
- fallback 次数、首包失败、resume/abort 行为；
- evaluator token、耗时和成本。

质量指标与成本指标分开报告，不使用成本直接改写官方 benchmark 分数。

---

## 8. 汇总口径

### 8.1 两个主分数

默认 dashboard 可计算以下汇总值，所有输入均按 0–100 归一化：

```text
Search Score
  = 0.75 * WideSearch Item F1
  + 0.25 * WideSearch Row F1

Report Score
  = 0.50  * DRB2 Information Recall
  + 0.375 * DRB2 Analysis
  + 0.125 * DRB2 Presentation
```

权重表达当前产品对事实覆盖和分析质量的相对关注，只用于同一版本内汇总展示。原始分项必须随总分一起发布。

### 8.2 可选单一指数

需要单一趋势线时，可计算：

```text
CompetitorLens Quality Index
  = 0.60 * Search Score
  + 0.40 * Report Score
```

该指数不是 gate。修改权重必须升本文版本，并保留旧权重下的历史结果，避免时间序列断裂。

### 8.3 失败 case

任务失败、超时或产生不可评分输出时：

- benchmark 官方分数遵循对应官方 scorer 的零分/错误规则；
- 同时保留 `terminal_status`、失败阶段和原始输出；
- 不从 macro average 中静默删除；
- 可另报 completed-only 分数，但必须与 all-case 分数并列并标注分母。

---

## 9. 结果产物

运行产物建议落在已 gitignore 的 `data/evaluations/`：

```text
data/evaluations/<run_id>/
  manifest.json
  cases.jsonl
  raw/
    <benchmark>/<case_id>/<variant>/<repetition>/
      request.json
      task_projection.json
      report.md
      socm.json
      trace.json
      operations.json
  normalized/
    widesearch_predictions/
    drb2_reports/
  scores/
    widesearch.jsonl
    drb2.jsonl
    operations.jsonl
    paired_deltas.json
  summary/
    metrics.json
    metrics.csv
    report.md
```

`manifest.json` 至少包含：

- repo commit 和 dirty-worktree 标记；
- benchmark/dataset revision；
- case-manifest revision；
- model/provider/model parameters；
- capability package 与 evaluator revision；
- 预算、timeout、并行度和环境变量名（不记录 secret value）；
- run start/end 时间和时区；
- scorer 命令及退出码。

原始运行产物不可由 scorer 覆盖；normalization 和 scoring 始终写新文件，使结果可重放。

---

## 10. 执行步骤

### 10.1 准备

1. 固定 WideSearch、DRB II 和 evaluator revision。
2. 生成并评审 case manifest；确认 ResearchBrief 未使用 gold/rubric。
3. 建立 evaluator 独立环境和 gold 只读挂载。
4. 固定 A0–A3 配置、预算档和随机执行顺序。
5. 创建 run manifest，记录仓库和模型配置。

### 10.2 运行

1. Adapter 向 `competitive_app` 提交固定 ResearchBrief。
2. 等待 task terminal status，并保存 task projection、SSE/trace、SOCM 和 report。
3. 按 case/variant/repetition 写入不可变 raw 目录。
4. 对 WideSearch 报告做确定性表格提取。
5. 对 DRB II 报告只做编码/文件名规范化。
6. 所有运行结束后再启动 evaluator，避免逐题分数反馈影响后续运行。

### 10.3 评分

WideSearch 使用官方仓库的 batch inference/evaluation 入口；已有项目输出时只运行 evaluation stage：

```bash
python3 scripts/run_infer_and_eval_batching.py \
  --trial_num=<n> \
  --model_config_name=<eval-adapter-name> \
  --response_root=<normalized-widesearch-output> \
  --result_save_root=<score-output> \
  --stage=eval
```

DeepResearch Bench II 将报告放入 `report/<variant>/idx-*.md` 后运行：

```bash
uv run python run_evaluation.py

python aggregate_scores.py \
  --input result.jsonl \
  --tasks-file tasks_and_rubrics.jsonl
```

官方脚本的实际参数以 pin 的 benchmark revision 为准；调用命令必须原样写入 run manifest。

### 10.4 汇总

1. 将官方分数规范化为统一的 case/variant/repetition 表。
2. 合并 operations 指标，但不覆盖官方质量字段。
3. 计算 mean@3、max@3、标准差和 paired delta。
4. 对 paired delta 做 case-level bootstrap。
5. 输出全量、语言、类别、预算档和失败类型切片。

---

## 11. 可复现性与偏差控制

| 风险 | 控制方式 |
|------|----------|
| 网页内容随时间变化 | 同组交错运行；记录访问时间、URL 和原始 tool result |
| 搜索排序不稳定 | 三次重复；保存完整搜索轨迹；同时报告 mean/max/variance |
| evaluator 漂移 | pin evaluator model、prompt 和代码 SHA；换版本后另开结果系列 |
| gold 泄漏 | 运行/evaluator 进程隔离；manifest 评审；gold 路径不进入 agent sandbox |
| 手工 subset 偏差 | 固化选择规则与完整 case ID；同时保留 full benchmark 对照入口 |
| 输出后处理掩盖失败 | 只允许确定性 normalization；禁止 LLM 修复 benchmark 输出 |
| 内部 confidence 冒充正确率 | 内部 coverage/confidence 与官方 gold 指标分别命名、分别报告 |
| 不同组预算不一致 | 预算写入 manifest；不同预算档不混合汇总 |
| evaluator 成本遗漏 | evaluator token、耗时和费用计入 operations，但不改写质量分数 |

---

## 12. 来源

### WideSearch

- Repo: https://github.com/ByteDance-Seed/WideSearch
- Dataset: https://huggingface.co/datasets/ByteDance-Seed/WideSearch
- Paper: https://arxiv.org/abs/2508.07999

### DeepResearch Bench II

- Repo: https://github.com/imlrz/DeepResearch-Bench-II
- Dataset: https://huggingface.co/datasets/muset-ai/DeepResearch-Bench-II-Dataset
- Paper: https://arxiv.org/abs/2601.08536

---

## 13. 版本记录

| 版本 | 日期 | 变化 |
|------|------|------|
| 0.1.0 | 2026-08-05 | 初版：定义 WideSearch + DeepResearch Bench II 双轨评测、A0–A3 分组、adapter、指标、结果口径和可复现性要求；明确不设通过标准 |
