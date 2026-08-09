# ADR 0016 — AgentHarness.attach_extension_runtime_and_rebind（迟挂 extension 后重绑 context_actions）

| 字段 | 值 |
|------|-----|
| **status** | accepted |
| **date** | 2026-08-09 |
| **deciders** | xj120 |
| **contract_version** | 0.3.12（不变） |
| **pi_agent version** | 0.81.1 → **0.81.2**（patch，新增向后兼容 public 方法） |
| **supersedes** | — |
| **relates** | ADR 0008（extension runtime）、ADR 0010（coverage engine / 子 agent ephemeral）、feature [`research-workflow-v1`](../../features/research_workflow_v1.md) v0.2.8 → **0.2.9** |

## 背景

pi4 的上下文压缩（compaction）机制在线但**从不工作**。实验 C（降 `contextWindow=8k` 强制触发，硬证据 `/tmp/reasonix_debug.log`）定位到两层根因：

1. **context_actions 没绑**（本 ADR 治）：
   - ephemeral 子 agent 在 `build_ephemeral` 里以 `capability_report=None` 构造 `AgentHarness`（`wiring.py`），所以 `__init__` 不调 `apply_capability_report`，`extension_runner` 在 `__init__` 结束时仍为 `None`。
   - `AgentHarness._bind_extension_context()`（`agent_harness.py`）在 `__init__` 末尾被调，但此时 `runner is None` → 早返（`if not runner: return`）→ `getContextUsage`/`compact` **从未绑**。
   - 之后 `build_ephemeral` 调 `attach_extension_runtime(agent, result, ...)` → `Agent.set_extension_runner(runner)`（`agent.py`）会给 runner 绑**默认** context_actions：`"getContextUsage": lambda: None`、`"compact": unavailable`。
   - 结果：子 agent 迟挂的 extension（reasonix）在 `turn_end` 里 `ctx.getContextUsage()` 拿到 `None` → 追加 `context_usage_unavailable` → 早返 → `compact()` 永不调 → compaction 永不触发。

2. **activeTurnEntryIds=全部**（治于 feature v0.2.9，不在本 ADR）：子 agent 单 prompt ReAct → session 只有 1 条 user → reasonix `before_compact` 看到 `activeTurnEntryIds=全部` → fold=∅ → 即便触发也不产 entry。feature v0.2.9 把单 prompt 改 2 轮（第二轮补空 cell），让 session 有多 user 消息，reasonix 有旧轮可压。

## 决策

给 `AgentHarness` 加一个 **public 方法**，包装"挂 runtime + 重绑 context_actions"两步：

```python
def attach_extension_runtime_and_rebind(
    self, result, cwd, *, replace: bool = False
):
    runner = attach_extension_runtime(self.agent, result, cwd, replace=replace)
    self._bind_extension_context()   # 重绑到新 runner
    return runner
```

- `attach_extension_runtime`（底层，原样复用）+ `_bind_extension_context`（private，原样复用）**均不改**。
- 新方法只是 harness 层包装：attach 之后立即 rebind，让迟挂的 runner 拿到真实 `getContextUsage`（读 `self.agent.state` 的 usage/contextWindow）与 `compact`（`request_compaction`，置 `_compaction_pending`），覆盖 `Agent.set_extension_runner` 留下的默认值。
- 主 harness 路径不变：`__init__` 里 `capability_report` 非 None 时走 `apply_capability_report` → `attach_extension_runtime` → `__init__` 末尾 `_bind_extension_context()` 已绑（runner 此刻存在）。新方法是**迟挂场景**（子 agent）的补丁。

## 偏差说明（为何偏离上游）

- 上游 `earendil-works/pi@main` 的 `AgentHarness` 无此方法；pi4 补为**移植偏差**（新增 public 方法，向后兼容，不改任何既有调用路径）。
- 理由：子 agent ephemeral 模型（ADR 0010 F-R28）在 `__init__` 之后才挂 extension，而 `_bind_extension_context` 只在 `__init__` 调一次 → 迟挂的 runner 永远拿不到真实 context_actions。上游 coding-agent 不存在"迟挂 + 依赖 context_actions 的 extension"这一组合，故无此方法；pi4 的 reasonix prefix-cache（ADR 0008 extension）依赖 `getContextUsage`/`compact`，必须补。
- 偏差**最小**：一个 public 包装方法，复用两个既有函数；不改 `Agent` 核心（`set_extension_runner` 的默认绑定保留，作为"未 rebind 时的兜底"，语义不变）。

## 影响

- **pi_agent** 0.81.1 → 0.81.2（patch：新增 public 方法，向后兼容）。
- **contract_version** 0.3.12 **不变**：未改任何冻结决策；F-R28 文字（ephemeral / 不落 JSONL / 1:1）不变；分层/技术栈不变。
- **feature `research-workflow-v1`** v0.2.8 → 0.2.9：`build_ephemeral` 用 `attach_extension_runtime_and_rebind` 挂 Extraction + reasonix（同一 runtime，一次 attach + rebind）；子 agent 单 prompt → 2 轮。
- **契约测试** `tests/packages/agent/contract/test_deps.py` 无 `ADR_SANCTIONED` 机制（与 packages/ai 不同），新增方法不引入禁用框架/域/沙箱导入，无需改该文件。
- **消费方**：`competitive_app/wiring.py` `build_ephemeral`；未来任何"迟挂依赖 context_actions 的 extension"的子 agent 场景同理用此方法。

## B3 偏差：reasonix 不缓存，每子 agent 现场加载

原计划（grill Q6=C + B3）拟在 `ApplicationState` 缓存"只含 reasonix 的 LoadReport"复用。**否决**：

- reasonix 的 `register()` 闭包持 `_State`（`epoch`/`baseline`/`pending_auto`/`consecutive_rewrites`）——**每 session 一份**。
- 缓存 LoadReport 复用其 `extension_result.extensions`，会让**并行子 agent 共享同一个 Extension 对象**（同一 `_State` 闭包）→ `turn_end` 的 `pending_auto`/`epoch` 跨子 agent 交错污染 → compaction 决策错乱。
- 改为：`build_ephemeral` 每次现场 `await load_capability_packages(enabled=["reasonix_prefix_cache"])` —— 每次 `register()` 产新 `_State`、新 Extension，并行安全。代价是一次小目录扫描 + importlib（每 subtask 一次，非热路径）。

## 后果

**正向**：
- 子 agent 迟挂 extension 后 `getContextUsage` 返真实 usage（非 None）、`compact()` 返 `accepted`/`already_pending`（非 `unavailable`）——reasonix compaction 机制在子 agent 真正上线；
- 配合 feature v0.2.9 多轮，compaction 首次能在子 agent **产生 entry**（之前 `compaction_count=0`）。

**负向 / 风险**：
- 每个 ephemeral harness 重 load reasonix（小开销）；若 profiling 证明显著，可改为缓存 reasonix 的 `register` 可调用对象（模块级缓存 import，每 harness 仍 `load_extension_from_factory` 产新 Extension/新 `_State`），但当前不做。
- 新增 public 方法是 pi_agent 对上游的又一偏差点；未来上游若加同款能力需对齐（届时重审，可能撤销本偏差）。

## 验收

- `tests/packages/agent/integration/faux/test_agent_harness_attach_rebind.py`（D1）：
  - `capability_report=None` 时 `extension_runner is None`（bug 前提）；
  - 裸 `attach_extension_runtime` 后 `getContextUsage() is None` + `compact()` 抛 "not available on Agent"（默认值，bug 复现）；
  - `attach_extension_runtime_and_rebind` 后 `getContextUsage()` 返非 None（含 `contextWindow`）、`compact()` 返 `accepted` → `already_pending`（rebind 生效）；
  - 二次 attach+rebind 重绑到新 runner。
- `tests/competitive_app/unit/test_coverage_engine_multiturn.py`（D2）：2 轮触发 / 全满跳过 / 无 intake 单轮 / 轮1 失败不补轮。
- 既有 harness/extension/workflow 套件全绿无回归。
- live（验证手段，非阻塞）：`serve_app.py` 跑 task，临时降 `contextWindow=8k`，确认 reasonix `turn_end` 触发 + `before_compact` `activeTurnEntryIds=轮2`（不再全部）→ fold 轮1 → `compaction_count > 0`。

## 替代方案（否决）

- **A（在 `Agent.set_extension_runner` 里重绑）**：让 Agent 核心在每次 set runner 后绑 context_actions。否决：`Agent` 是上游 isomorphic 核心，改其行为面影响**所有** attach 路径（主 harness / coding tools / 测试夹具），偏差远大于 harness 层包装；且 Agent 无 harness 的 session/compaction 概念，无从绑。
- **B（app 层直接调 private `_bind_extension_context`）**：实验 C 的临时做法。否决：app 层伸手进 `_` 前缀私有方法脆弱，上游重构即断；public 包装方法是稳定 API。
- **C（缓存 reasonix LoadReport 复用）**：见上"B3 偏差"，并行子 agent 共享 `_State` 污染决策，否决。
