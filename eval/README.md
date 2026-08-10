# eval — CompetitorLens Benchmark Harness

评测 `competitive_app` 的搜索覆盖、事实收集和报告生成效果。

- 基准方案:[`docs/competitorlens_benchmark_evaluation.md`](../docs/competitorlens_benchmark_evaluation.md)
- 设计:[`docs/superpowers/specs/2026-08-10-eval-harness-design.md`](../docs/superpowers/specs/2026-08-10-eval-harness-design.md)
- 实现计划:[`docs/superpowers/plans/2026-08-10-eval-harness.md`](../docs/superpowers/plans/2026-08-10-eval-harness.md)

## 本期范围(C2-wide)

- **框架全套**:`eval/` 包(adapter / manifest / orchestrator / normalizer / operations collector / evaluator),双轨通用骨架(DRB II 留空壳)。
- **WideSearch Smoke 5 题跑通**:A1(single_agent)+ A2(competitorlens)× 1 重复,真实 provider。
- DRB II / A0 / A3 / Pilot 不在本期。

## 跑 Smoke(5 题 × A1/A2)

```bash
# 1. 起 competitive_app (A2)
uv run competitive_app serve --host 127.0.0.1 --port 8000 &

# 2. 起 A1 single_agent 服务
uv run python -m eval.runner.single_agent_app --port 8001 &

# 3. 跑 Smoke
uv run python -m eval --stage smoke --benchmark widesearch --variants a1,a2
```

产物落 `data/evaluations/<run_id>/`(`manifest.json` / `raw/` / `normalized/` / `scores/` / `summary/`)。

## 测试

```bash
uv run pytest tests/eval -m "not live" -q    # 离线全跑 (CI)
uv run pytest tests/eval -m live -q           # 真实 provider (需 .env + competitive_app 起着)
```

## 结构

```text
eval/src/eval/
  manifest.py              # CaseManifest schema (D5)
  manifest_builder.py      # load_smoke_manifest + candidate helper (S4)
  adapter/                 # official task -> CaseManifest (widesearch 实装, drb2 空壳)
  runner/                  # http_client (A2 W1) + single_agent_app (A1 ASGI) + budget_guard
  normalizer/              # report.md -> WideSearchResponse JSONL (widesearch 实装, drb2 空壳)
  operations/              # events.jsonl + projection + SOCM -> operations.json
  evaluator/               # 调官方 WideSearch scorer (widesearch 实装, drb2 空壳)
  orchestrator.py          # CLI driver: eval.run --stage smoke
vendor/widesearch/         # 官方 scorer (patch config.py + llm.py 注册 deepseek-v4-flash)
data/benchmarks/widesearch/  # gold + HF cache (gitignored, 运行进程不可见 D6)
data/evaluations/<run_id>/  # 结果产物 (gitignored)
```

## gold 隔离(D6 三道闸)

1. **工具面裁剪**:A2/A1 只装 `search_tavily`,无 read/write/bash。
2. **cwd 隔离**:运行进程 cwd = `eval/runs/`,gold 在 `data/benchmarks/`。
3. **evaluator 独立进程**:所有 case 跑完才起 scorer,gold 只挂给 evaluator。
4. **contract guard**:`tests/eval/contract/test_gold_isolation.py` AST 扫描保证运行进程代码不碰 gold。
