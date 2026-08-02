# ADR 0012 — pi_ai openai-completions response_format 透传(JSON 强制)

| 字段 | 值 |
|------|-----|
| **status** | accepted |
| **date** | 2026-07-31 |
| **deciders** | xj120 |
| **contract_version** | 0.3.8 → **0.3.9** |
| **pi_ai version** | 0.81.1 → **0.81.2**(patch) |
| **supersedes** | — |
| **relates** | ADR 0010(research-workflow-v2 / clarify)、CLAUDE.md 约束 1(isomorphic port) |

## 背景

reports/{id} 的 live 验证卡住。根因链:

1. pi4 经 gateway(`OPENAI_BASE_URL=https://api.chatanywhere.tech`,模型 `deepseek-v4-flash`)的结构化 LLM 调用(clarify discover / derive brief)要求严格 JSON 输出。
2. 上游 `earendil-works/pi@c55ae2f` 的 `openai-completions.ts` 的 `buildParams` **不透传 `response_format`**(连上游都没有)。pi4 的 isomorphic 移植 `build_openai_completions_payload`(`packages/ai/.../api/transform_messages.py`)忠实镜像,也无此透传。
3. 结果:模型**非确定性**——同样的英文 "Output ONLY the JSON" prompt,有时返纯 JSON(成功),有时返一整段散文分析(失败)。`_try_parse_json` 解析散文返 None → clarify discover 退化(Q3-A)→ 从 query 单独推的宽松 brief → plan 生成 60 cell 大 schema → search 卡死(iter 0、22 evidence、0 filled)。
4. 实测确认 gateway **支持** `response_format: {type:"json_object"}`(200 + 纯 JSON `{"subject":"Trae","competitors":[...]}`)。

OpenAI Chat Completions 的 `response_format: {type:"json_object"}`(JSON mode)是强制合法 JSON 输出的标准机制,正好根治"返散文"。

## 决策

在 `build_openai_completions_payload` 加**最小透传**:

```python
# ADR 0012: response_format 透传(JSON 强制)。上游 buildParams 无此字段,pi4 补最小透传。
if options.get("response_format") is not None:
    payload["response_format"] = options["response_format"]
```

- **不动 `StreamOptions` TypedDict**(`total=False`,额外键透传合法,零类型偏差)。
- **不改 builder 其余字段/语义**(只加一行透传,在 `return payload` 前)。
- 调用方(completeSimple options)传 `{"response_format": {"type": "json_object"}}`。

## 偏差说明(为何偏离上游)

- 上游 `buildParams`(c55ae2f)无 response_format 透传;pi4 补此为**移植偏差**。
- 理由:gateway 支持 response_format(实测 200);JSON 强制是结构化抽取(discover/derive/judge)的基础需求,否则模型非确定性返散文直接卡死研究流程。
- 偏差**最小**:只透传 dict,不新增 schema 校验/转换/typed wrapper 能力。`json_schema`(strict structured output)留后续(gateway 未测支持,且 json_object 保证合法 JSON 已够用)。

## 范围(哪些调用加)

只给**返 JSON object** 的 LLM 调用加 response_format:

| 调用 | 位置 | 输出形态 | 加 response_format? |
|------|------|----------|---------------------|
| clarify discover | `task_service._safe_discover_with_questions` | `{subject,domain,competitors}`(object) | ✅ 加 |
| clarify derive | `task_service._derive_brief` | `{target,goal,competitors,dimensions}`(object) | ✅ 加 |
| judge extraction | `extraction._call_judge` | JSON **array**(findings list) | ❌ 不加 |
| refine section | `task_service._rewrite_section` | markdown | ❌ 不加 |

**judge 不加的原因**:OpenAI JSON mode 只允许顶层 **object**(不允许 array)。给 judge 加 `json_object` 会让模型返 `{"findings":[...]}` wrapper,与 judge 的 list 解析逻辑冲突。judge 保持现状(batch3 live 验过 128 evidence 稳定)。

**refine 不加的原因**:返 markdown,非 JSON。

## 影响

- **pi_ai** 0.81.1 → 0.81.2(patch:新增向后兼容透传能力)。
- **contract_version** 0.3.8 → 0.3.9(pi_ai 是 P1 底座,加能力属架构层变更,需升契约)。
- **research-workflow-v1** v0.2.3 → v0.2.4 patch:clarify discover/derive 用 response_format 强制 JSON。
- **契约测试** `test_deps.py` 加 `ADR_SANCTIONED` 允许集(packages/ai 三文件),守"packages/ 冻结,偏差需 ADR + 显式列入"。
- 调用方(competitive_app)传 `options={"response_format":{"type":"json_object"}}`。

## 后果

**正向**:
- clarify discover/derive 带 response_format 稳定返 JSON(不再偶返散文)。
- 根治 discover 退化 → 不再生成宽松 brief → 不再 60 cell 卡死。
- reports/{id} live 验证跑通(任务能跑完 completed)。
- pi_ai 获 response_format 透传能力,后续任何返 object 的调用可复用。

**负向 / 风险**:
- packages/ai 从"零改动"变为"ADR 0012 透传"(底座偏差)。ADR_SANCTIONED 守其范围。
- JSON mode 不保证**字段 schema**(可能返 `{}` 或字段缺)——但 `_try_parse_json` + `.get()` 容错 + fallback brief 兜底,够用(比"返散文 100% 退化"是质提升)。
- judge(array)未受益——若日后 judge 也偶返散文,单独评估(改 judge 返 object wrapper 或换 json_schema)。

## 验收

- `build_openai_completions_payload` 透传测试绿(options 有 → payload 有;无 → 无)。
- P1(pi_ai)+ competitive_app(clarify/judge)全绿无回归。
- live:建 query → discover 带 response_format 返 JSON(不再退化)→ awaiting_clarify → 跑完 completed → `curl /reports/{id} | jq .coverage_map` 有矩阵。

## 替代方案(否决)

- **A 路(不碰 packages/ai)**:discover 容错 regex 抽竞品 + 退化收紧 brief + search cell 上限。治标不治根(discover 仍偶返散文,只是不卡死);且 pi_ai 永远缺 response_format 能力。否决(用户选 B 治根)。
- **json_schema(strict)**:gateway 未测支持 + json_object 已够。留后续。
- **给 judge 加 json_object**:array 冲突。否决。
