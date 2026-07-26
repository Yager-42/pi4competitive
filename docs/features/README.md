# Feature 边界契约目录

本目录存放 **按特性拆分的业务/能力边界契约**（grill 冻结后的 SoT）。  
架构、import 方向、Pi package 机制仍以 [`docs/contracts/ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) 为准。

| 文档 | feature_id | 状态 | 实现计划 |
|------|------------|------|----------|
| [`search_capability_packages_v1.md`](search_capability_packages_v1.md) | `search-capability-packages-v1` | **frozen** v0.1.12 | [`docs/plans/P4_search_capability_packages.md`](../plans/P4_search_capability_packages.md) |
| [`agent_engine_extensions_v1.md`](agent_engine_extensions_v1.md) | `agent-engine-extensions-v1` | **frozen** v0.3.0 | [`P3_1_agent_engine_extensions.md`](../plans/P3_1_agent_engine_extensions.md) **completed v0.2.4 baseline**；P3.2 delta；ADR 0008/0009；契约 v0.3.5 |
| [`reasonix_prefix_cache_v1.md`](reasonix_prefix_cache_v1.md) | `reasonix-prefix-cache-v1` | **frozen** v0.1.0 | [`P3_2_pi_extension_capability_enablement.md`](../plans/P3_2_pi_extension_capability_enablement.md) **completed v0.1.2**；ADR 0009；契约 v0.3.5 |

## 约定

1. **一特性一文件**（或同特性多版本时带 `_vN` 后缀）。
2. 文件名 ≈ `feature_id` 的 snake_case。
3. 冻结前 `status: draft`；冻结后改 `frozen`，变更须升 `feature_contract_version` 并更新 Roadmap。
4. **禁止**再用根级 `docs/FEATURES.md` 堆叠多个无关特性。
5. 实现细节与 checklist 写在 `docs/plans/*`，边界写在本目录。
