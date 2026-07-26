# Feature 边界契约目录

本目录存放 **按特性拆分的业务/能力边界契约**（grill 冻结后的 SoT）。  
架构、import 方向、Pi package 机制仍以 [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) 为准。

| 文档 | feature_id | 状态 | 实现计划 |
|------|------------|------|----------|
| [`search_capability_packages_v1.md`](search_capability_packages_v1.md) | `search-capability-packages-v1` | **frozen** v0.1.12 | [`docs/plans/P4_search_capability_packages.md`](../plans/P4_search_capability_packages.md) |
2: | [`docs/features/agent_engine_extensions_v1.md`](docs/features/agent_engine_extensions_v1.md) | agent engine extensions **frozen v0.3.0**（P3.1 completed baseline + P3.2 delta） |
| [`docs/features/reasonix_prefix_cache_v1.md`](docs/features/reasonix_prefix_cache_v1.md) | reasonix prefix cache v1 **frozen v0.1.0**（P3.2；A+B+E） |
| [`docs/features/competitive_app_http_v1.md`](docs/features/competitive_app_http_v1.md) | P4 app HTTP 边界 **frozen v0.2.0**（`competitive-app-http-v1`；14 路由；task 行为由 research-workflow-v1 提供） |
| [`docs/features/research_workflow_v1.md`](docs/features/research_workflow_v1.md) | P4 六阶段研究 workflow **frozen v0.1.1**（`research-workflow-v1`；替换占位 runner；24 决策） |
3: | [`agent_engine_extensions_v1.md`](agent_engine_extensions_v1.md) | `agent-engine-extensions-v1` | **frozen** v0.3.0 | [`P3_1_agent_engine_extensions.md`](../plans/P3_1_agent_engine_extensions.md) **completed v0.2.4 baseline**；P3.2 delta；ADR 0008/0009；契约 v0.3.5 |
| [`reasonix_prefix_cache_v1.md`](reasonix_prefix_cache_v1.md) | `reasonix-prefix-cache-v1` | **frozen** v0.1.0 | [`P3_2_pi_extension_capability_enablement.md`](../plans/P3_2_pi_extension_capability_enablement.md) **completed v0.1.2**；ADR 0009；契约 v0.3.5 |
| [`competitive_app_http_v1.md`](competitive_app_http_v1.md) | `competitive-app-http-v1` | **frozen** v0.2.0 | [`P4_competitive_app_http.md`](../plans/P4_competitive_app_http.md) **completed**；14 路由；task 行为由 research-workflow-v1 提供 |
| [`research_workflow_v1.md`](research_workflow_v1.md) | `research-workflow-v1` | **frozen** v0.1.1 | [`P4_research_workflow.md`](../plans/P4_research_workflow.md) **completed v0.1.1**；六阶段研究 workflow；替换占位 runner；L1 live 真搜索验证 |
4: | **roadmap_version** | `0.1.23` |
| **status** | active |
| **updated** | 2026-07-26 |
| **架构契约** | [`docs/contracts/ARCHITECTURE_CONTRACT.md`](contracts/ARCHITECTURE_CONTRACT.md) **v0.3.5** |
5: | P3.1 agent engine extensions | **done** | 2026-07-24 | feature v0.3.0（P3.2 delta）；plan v0.2.4 remains completed；Offline 124 passed；Live 24 passed |
| P3.2 Pi extension capability enablement | **done** | 2026-07-26 | A+B+E；Offline 139 passed；full-stack Live warm-cache green；plan v0.1.2 |
| P4 `competitive_app` | **in_progress** | | HTTP 骨架（`competitive-app-http-v1` v0.2.0）+ 六阶段研究 workflow（`research-workflow-v1` v0.1.1 frozen；plan v0.1.1 **completed**；替换占位 runner；offline 35+159 passed；L1 live 真搜索验证）；后续：多角色评审/缺口补搜/报告 schema |
| 业务能力 v1 | **partial**（搜索 capability **done** + 研究闭环 **done**） | 2026-07-26 | search packages + 六阶段研究 workflow 落地；完整 fact_report schema 仍 todo |
6: | 0.1.16 | 2026-07-26 | **ADR 0009 / contract 0.3.5**：新增 P3.2 Pi extension capability enablement，位于 P3.1 与 P4；Reasonix 不归 P4 App |
| 0.1.17 | 2026-07-26 | **P3.2**：Reasonix feature **v0.1.0 frozen**；新增 plan `P3_2_pi_extension_capability_enablement.md` v0.1.0 |
| 0.1.18 | 2026-07-26 | P3.2 plan v0.1.1：C8 收紧为正式 loader/Harness 全栈 live close gate；普通 CI 可 skip，但关闭阶段必须有脱敏 green 证据 |
| 0.1.19 | 2026-07-26 | P3.2 implementation started；D0 publishes extension feature v0.3.0 + P3.1 plan v0.2.4 delta without reopening P3.1 |
| 0.1.20 | 2026-07-26 | P3.2 done：Reasonix prefix cache A+B+E；Offline 139 passed；full-stack Live warm-cache green；plan v0.1.2 completed |
| 0.1.21 | 2026-07-26 | P4 `competitive_app` → **in_progress**：HTTP 骨架切片落地（feature `competitive-app-http-v1` frozen v0.1.3；14 路由；DDD 分层门禁；offline 19+124 passed）；研究 workflow 仍占位 |
| 0.1.22 | 2026-07-26 | 六阶段研究 workflow 落地（feature `research-workflow-v1` frozen v0.1.1；替换占位 runner；24 决策；offline 35+124 passed）；`competitive-app-http-v1` 升 v0.2.0 |
| 0.1.23 | 2026-07-26 | research-workflow-v1 plan **completed** v0.1.1：L1 live 真搜索验证（DeepSeek + tavily/anysearch/grok；165s；六阶段全 ok；报告非空）；修 5 个 live bug；全仓 offline 159 passed |

## 约定

1. **一特性一文件**（或同特性多版本时带 `_vN` 后缀）。
2. 文件名 ≈ `feature_id` 的 snake_case。
3. 冻结前 `status: draft`；冻结后改 `frozen`，变更须升 `feature_contract_version` 并更新 Roadmap。
4. **禁止**再用根级 `docs/FEATURES.md` 堆叠多个无关特性。
5. 实现细节与 checklist 写在 `docs/plans/*`，边界写在本目录。
