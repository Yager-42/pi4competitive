# Feature 边界契约目录

本目录存放 **按特性拆分的业务/能力边界契约**（grill 冻结后的 SoT）。  
架构、import 方向、Pi package 机制仍以 [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) 为准。

| 文档 | feature_id | 状态 | 实现计划 |
|------|------------|------|----------|
| [`search_capability_packages_v1.md`](search_capability_packages_v1.md) | `search-capability-packages-v1` | **frozen** v0.1.12 | [`P4_search_capability_packages.md`](../plans/P4_search_capability_packages.md) **completed**；三包五工具 |
| [`agent_engine_extensions_v1.md`](agent_engine_extensions_v1.md) | `agent-engine-extensions-v1` | **frozen** v0.3.0 | [`P3_1_agent_engine_extensions.md`](../plans/P3_1_agent_engine_extensions.md) **completed v0.2.4 baseline**；P3.2 delta；ADR 0008/0009 |
| [`reasonix_prefix_cache_v1.md`](reasonix_prefix_cache_v1.md) | `reasonix-prefix-cache-v1` | **frozen** v0.1.0 | [`P3_2_pi_extension_capability_enablement.md`](../plans/P3_2_pi_extension_capability_enablement.md) **completed v0.1.2**；ADR 0009 |
| [`competitive_app_http_v1.md`](competitive_app_http_v1.md) | `competitive-app-http-v1` | **frozen** v0.3.3 | [`P4_competitive_app_http.md`](../plans/P4_competitive_app_http.md) **completed**；27 路由；task 行为由 research-workflow-v1 v0.2.3 提供 |
| [`research_workflow_v1.md`](research_workflow_v1.md) | `research-workflow-v1` | **frozen** v0.2.3 | [`P4_research_workflow_v2.md`](../plans/P4_research_workflow_v2.md) 随 PR2 起补；三阶段研究 workflow（SearchOS coverage 引擎；ADR 0010）；v1 plan `P4_research_workflow.md` completed v0.1.1（历史保留） |
| [`workflow_skill_self_evolution_v1.md`](workflow_skill_self_evolution_v1.md) | `workflow-skill-self-evolution-v1` | **frozen** v0.2.1；G1–G29 resolved；implementation verified；真实 provider L1–L4 green | [`P4_workflow_skill_self_evolution.md`](../plans/P4_workflow_skill_self_evolution.md) **v0.1.2 completed**；Poirot transplant-first |

> 状态板与 changelog 见 [`docs/ROADMAP.md`](../ROADMAP.md)（roadmap v0.1.34 / 架构契约 v0.3.6）。本目录只索引 feature 边界契约。

## 约定

1. **一特性一文件**（或同特性多版本时带 `_vN` 后缀）。
2. 文件名 ≈ `feature_id` 的 snake_case。
3. 冻结前 `status: draft`；冻结后改 `frozen`，变更须升 `feature_contract_version` 并更新 Roadmap。
4. **禁止**再用根级 `docs/FEATURES.md` 堆叠多个无关特性。
5. 实现细节与 checklist 写在 `docs/plans/*`，边界写在本目录。
