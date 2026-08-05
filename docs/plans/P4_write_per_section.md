# Plan: P4 write 逐 section 多 call(A 路线,research-workflow v0.2.6)

> write stage 从 one-shot(1 call 整篇)→ **逐 section sequential**(`harness.prompt` 主 session 上调 N+2 次)。
> 落点:主仓 `/Users/huangyaokai/pi4competitive`,分支 `p4/research-workflow-v2-searchos`(FF-merge main)。

## Context(为什么)

pi4 现 write = 1 次 LLM call 产整篇 markdown 报告(`profiles._WRITE_PROMPT` one-shot + `_run_stage("write")` 单次 `harness.prompt`)。问题:整篇塞 max_tokens(8192)易糙/截断;无 per-section 专注;质量低于 VerdaAI(它 7-10 call + audit/rework)。

A 路线:write 拆成 **overview + per-dimension + conclusion**(N+2 call,sequential),保 markdown 路线,不加 audit/rework(那是 B,deferred)。

## Grill 决策(Q1-Q5 + Q2/Q4 修订)

| Q | 决策 |
|---|---|
| Q1 section 结构 | **overview + per-dimension(brief.dimensions)+ conclusion + Sources**(N+2 call,N=dimensions 通常 1-3 → 3-5 call) |
| Q2 并行/串行 | **改 sequential**(`harness.prompt` 主 session 上调 N+2 次)—— parallel(completeSimple/ephemeral)会丢 session JSONL 持久化(D24)+ SSE 可见 + v0.2.5 测试;速度差可忽略 |
| Q3 每 call 上下文 | 整 coverage map + dimension 指令("聚焦该维度 cell")+ **memory blob(v0.2.5)每 section 注入** |
| Q4 输出/引用 | 每 call 输出 `{body, sources}`(prompt 指令 JSON,**不强求 response_format**——跟现 write 一致,容错解析);section 局部 [n]+ Sources 按分组列(无全局重编号);sections[] 顺序 id "1".."N+1"(跟 `_split_sections` 约定一致,refine 不变) |
| Q5 版本/scope | research-workflow v0.2.5→**v0.2.6**(write 契约变更,这次 grill 即 re-grill);契约 0.3.9 不动(无 ADR);http v0.3.4 不动;ROADMAP 0.1.46。**边界**:无 audit/rework(B deferred)、仍 markdown(非结构化组件,B deferred) |

## 落点文件

### 1. `profiles.py` —— `_WRITE_PROMPT` → per-section `_SECTION_WRITE_PROMPT`(re-grill v0.2.6)

```python
_SECTION_WRITE_PROMPT = """\
You are a research report section writer. Given the research brief, a coverage
map snapshot (entity × attribute cells, each filled/unknown/conflict), and
prior findings from earlier research (if any), write ONE section of the report.

Section: {title}
{section_focus}   # overview: 背景+关键发现摘要; dimension: 聚焦 <dim> cell; conclusion: 综合+建议

Use [n] citation markers anchored to your sources. For unknown/conflict cells,
note it. Output ONLY valid JSON: {{"body": "<markdown section body>", "sources": [{{"n":1,"url":"...","label":"..."}}]}}.
"""
```
`_WRITE_PROMPT`(one-shot)标记 v0.2.6 替换;`build_profiles()` write 仍 `tool_names=[]`(无工具)。

### 2. `research_runner.py` —— `_run_stage("write")` rewrite

```python
# write: per-section sequential harness.prompt + assemble
prior = await collect_prior_outputs(self.session, STAGE_DEPENDENCIES["write"])
memory_blob = await recall_prior_findings(self.store, [target.name, *competitors])
sections_to_write = [("overview", "概述", ""),
                      *[(f"dim:{d}", d, f"Focus on cells relevant to {d}.") for d in brief.dimensions],
                      ("conclusion", "结论与建议", "Synthesize + give recommendations.")]
t0 = time.monotonic()
section_results = []
for sid, title, focus in sections_to_write:
    prompt = self._build_section_prompt(title, focus, prior, memory_blob)
    try:
        await self.harness.prompt(prompt)
        body, sources = self._extract_section_output()  # 容错解析 {body,sources}
    except Exception:  # noqa: BLE001 — best-effort,单 section 挂不搞挂 write
        body, sources = "(本节生成失败)", []
    section_results.append({"title": title, "body": body, "sources": sources})
latency_ms = int((time.monotonic() - t0) * 1000)
emit span(kind=write, latency=latency_ms)  # 1 个 write span(总)
report_md, sections_out = _assemble_report(section_results)  # ## title\nbody... + ## Sources 分组 + sections[] 顺序 id
output = {"report": report_md, "sections": sections_out}
result = validate_stage_output("write", output)  # 校验 report 字段
if result.ok:
    await append_stage_output(self.session, "write", output)
return result
```

新 helper:
- `_build_section_prompt(title, focus, prior, memory_blob)` —— 拼 section prompt(brief + coverage map + memory blob + _SECTION_WRITE_PROMPT.format(title, focus))。
- `_extract_section_output()` —— 从 last assistant message 解析 `{body, sources}`(容错:`_try_parse_json` + fallback raw text 包成 body)。
- `_assemble_report(section_results)` —— 拼 `## {title}\n{body}` 顺序 + `## Sources\n` 按 section 分组(`### {title}\n[n] url\n...`)+ `sections=[{id:"1",title,body},...]` 顺序 id。

### 3. 测试

**offline:**
- `tests/competitive_app/unit/test_write_assemble.py`:`_assemble_report`(sections 顺序、Sources 分组、id "1".."N+1"、失败 section 兜底 body)+ `_build_section_prompt`(brief.dimensions→section 列表、memory_blob 注入)。
- `tests/competitive_app/integration/test_write_per_section.py`:faux 3-stage 跑完 → 断言 `sections[]` = overview+dims+conclusion+sources、report 含各 `##`、id 顺序、**refine 仍能按 id 定位重写**(保契约)。

**live(env-gated):**
- `tests/competitive_app/integration/live/test_live_write_per_section.py`:真任务(低 `SEARCH_COVERAGE_THRESHOLD`)→ report 含 `## 概述` + 各维度 `##` + `## Sources`;session JSONL 有 N+2 次 write user/assistant 对(per-section)。
- v0.2.5 `test_live_memory_inject` **仍应通过**(blob 在 section prompt 里,落 session JSONL)——回归确认。

### 4. 文档

- `research_workflow_v1.md`:v0.2.5→**v0.2.6** patch 段(write per-section:overview+dims+conclusion sequential,保 {report,sections},无 audit/rework)。
- `ROADMAP.md`:0.1.45→**0.1.46** +1 行。
- 契约 0.3.9 不动,无 ADR;http v0.3.4 不动。

## 复用现有实现

- `recall_prior_findings`(memory_inject.py,v0.2.5)—— 每 section 注入 memory blob。
- `collect_prior_outputs`(stage_outputs.py)—— 取 plan+search(coverage map)。
- `_try_parse_json` + `_extract_assistant_text_for_refine`(task_service)—— section 输出容错解析。
- `validate_stage_output` / `STAGE_OUTPUT_SCHEMA["write"]={"report"}`(stage.py)—— 保契约。
- `_split_sections`(现切 report 为 sections)—— per-section 后不再用切(sections 直接生成),但 refine 仍调它做 fallback(保兼容)。
- `harness.prompt`(agent_harness.py)—— 每 section 1 次(sequential,主 session,SSE 事件,compaction)。

## 明确不做(边界)

- **audit/rework**(B 路线):二审 + 返工 loop,deferred。A 只 draft 不审。
- **结构化 section**(B):pricing/feature 出 data→前端 `VPricingTable` 组件,deferred。仍 markdown。
- **parallel**:Q2 改 sequential(保 session+SSE+测试)。
- **response_format** for section:跟现 write 一致靠 prompt 指令 + 容错,不强求(若非确定性咬,再加)。
- **全局 [n] 重编号**:用 section 分组列 Sources 替代。
- **framing section 之外**(summary/overview 已含):不加更多。

## Verification

```bash
.venv/bin/python -m pytest tests/competitive_app/unit/test_write_assemble.py tests/competitive_app/integration/test_write_per_section.py -q
.venv/bin/python -m pytest tests/competitive_app -m "not live" -q --ignore=tests/competitive_app/unit/evolution  # 无回归
.venv/bin/python -m pytest tests/competitive_app/integration/live/test_live_write_per_section.py tests/competitive_app/integration/live/test_live_memory_inject.py -m live -q  # live + v0.2.5 回归
.venv/bin/ruff check <新文件>  # clean
```
