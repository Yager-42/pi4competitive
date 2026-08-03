# ADR 0015 — pi_ai 结构化错误透传（AssistantMessage.error）

| 字段 | 值 |
|------|-----|
| **status** | accepted |
| **date** | 2026-08-03 |
| **deciders** | xj120 |
| **contract_version** | 0.3.11 → **0.3.12** |
| **pi_ai version** | 0.81.2 → **0.81.3**(patch) |
| **supersedes** | — |
| **relates** | ADR 0012（pi_ai 透传先例）、feature [`llm-fallback-observability-v1`](../features/llm_fallback_observability_v1.md) v0.2.0（G2/G2a/B2/B12）、CLAUDE.md 约束 1（isomorphic port） |

## 背景

App 层要引入 Multi-LLM Fallback（feature `llm-fallback-observability-v1` v0.2.0，grill G2 决策）：降级判定需要区分**瞬时错误**（限流/5xx/超时/断连 → 换 provider）与**客户端错误**（400/401/403/404 → 换 provider 也没用，原样透出）。

现状错误模型：

1. pi4 的传输层 `_http_stream.py`（httpx）把一切错误**吞进事件流**——不抛异常：
   - HTTP `status_code >= 400` → `error_message(model, f"HTTP {status}: ...")`（错误只存在于 `errorMessage` **文本**里）；
   - 传输异常（httpx timeout/connection 等）→ `except Exception` → 同路径吞掉，文本 = `str(exc)`。
2. 上游 `earendil-works/pi@main` 的 TS `AssistantMessage`（`packages/ai/src/types.ts`）只有 `errorMessage?: string`（文本），**无**结构化错误字段。pi4 的 isomorphic 移植 `types.py` 忠实镜像，同样只有 `errorMessage` 文本。
3. 结果：fallback 判定只能靠文本匹配（`"HTTP 429"` 前缀 / 异常类名），脆弱且不可测——上游措辞一变，分类即断。

## 决策

给 `AssistantMessage` 加**结构化 error 字段**（向后兼容，NotRequired）：

```python
class ErrorInfo(TypedDict):
    statusCode: NotRequired[int]   # HTTP 状态码；仅 type == "http_error" 时存在
    type: Literal["timeout", "connection", "http_error", "parse", "aborted", "other"]
    message: str                   # 人类可读描述（与 errorMessage 同源，可一致）

class AssistantMessage(TypedDict):
    ...
    errorMessage: NotRequired[str]   # 保留：文本，向后兼容（session SoT 历史数据不受影响）
    error: NotRequired[ErrorInfo]    # ADR 0015：结构化，仅 stopReason == "error" 时存在
```

- 产点：仅 `_http_stream.error_message()`（`api/_http_stream.py`）——所有错误消息的单一构造点，改一处全 provider 生效：
  - HTTP `>= 400` → `error = {"type": "http_error", "statusCode": resp.status_code, "message": f"HTTP {status}: {text[:500]}"}`；
  - httpx 异常 → 按 `isinstance(exc, httpx.TimeoutException)` / `httpx.ConnectError` / `httpx.ReadError` 分类为 `timeout` / `connection` / `other`（`ConnectionError` 内建同映射）；
  - abort → `type == "aborted"`（`error_message(..., aborted=True)` 路径）。
- 事件流侧零改动：`AssistantMessageEventError.error` 本就携带 `AssistantMessage`，复用。
- `parse` 枚举保留为合法值（当前 `_http_stream` JSON 解析失败是跳块不产错，暂无产点；未来结构化抽取若需要可补）。
- **不动** `StreamOptions`/`SimpleStreamOptions`/`ProviderResponse`/其他消息类型。

## 偏差说明（为何偏离上游）

- 上游 TS `AssistantMessage`（main）无 `error` 字段；pi4 补此为**移植偏差**（与 ADR 0012 response_format 同模式）。
- 理由：App 层 Multi-LLM Fallback 的降级判定必须以结构化错误为输入（feature B2 分类规则：`type ∈ {timeout, connection}` 或 `http_error ∈ {429} ∪ [500,600)` → 降级；`{400,401,403,404}` → 不降级）。文本匹配（`"HTTP 429"` 前缀）不可靠：上游/网关措辞变化即断，且不可做类型级契约测试。
- 偏差**最小**：只加一个 NotRequired TypedDict 字段 + 单一产点分类；不改任何成功路径、不改 `errorMessage` 语义、不加新异常抛出（错误仍以消息形态交付，pi 语义保持）。
- 上游已有 `diagnostics`（redacted diagnostics array）机制：不冲突，也不复用——`error` 是**结构化分类**（判定输入），`diagnostics` 是诊断明细（展示），职责不同。

## 影响

- **pi_ai** 0.81.2 → 0.81.3（patch：新增向后兼容错误分类字段）。
- **contract_version** 0.3.11 → 0.3.12（pi_ai 是 P1 底座，加能力属架构层变更，需升契约）。
- **契约测试** `test_deps.py` `ADR_SANCTIONED` 允许集补 `packages/ai` 三文件（`types.py` / `api/_http_stream.py` / `utils/event_stream.py`——若该文件有改动，否则两文件），守"packages/ 冻结，偏差需 ADR + 显式列入"。
- **消费方**（competitive_app `application/model/fallback_stream.py`）：判定读 `msg.get("error")`；`errorMessage` 文本仅作日志/透出展示。
- **session SoT**：历史 JSONL 中 `errorMessage` 文本数据不受影响（NotRequired）；新错误消息同时带文本 + 结构化字段。

## 后果

**正向**：
- fallback 降级判定变类型级：`error["type"]`/`error["statusCode"]` 直接可测、可断言，无文本脆弱性；
- 单一产点（`error_message`）覆盖全部错误路径，各 provider（openai-completions/responses 等共用 `_http_stream`）一致受益；
- 与 ragent 首包探测机制正交：探测期判定也消费同一 `error` 字段（error 事件先行即切）。

**负向 / 风险**：
- packages/ai 从 ADR 0012 的单点透传再增一偏差（结构化 error）。ADR_SANCTIONED 守其范围；
- `type` 枚举是新增契约面：未来上游若自行加 error 字段需对齐（届时重审，可能撤销本偏差）；
- 分类覆盖面以 `_http_stream` 产点为准：非 httpx 传输层（如 websocket transport，本仓未启用）不在此偏差范围，type 缺省由消费方按 `other` 处理。

## 验收

- `packages/ai` 单测：HTTP 400/401/403/404/429/5xx → `error.type == "http_error"` 且 `statusCode` 正确；httpx 超时 → `timeout`；连接错误 → `connection`；abort → `aborted`；成功消息**无** `error` 字段；`errorMessage` 文本仍存在。
- P1（pi_ai）+ competitive_app 全绿无回归。
- feature `llm-fallback-observability-v1` 验收 §6.2（契约测试：字段形状/仅 error 时存在/枚举合法/errorMessage 兼容）。

## 替代方案（否决）

- **A 路（App 层文本匹配）**：`_should_fallback_message` 按 `errorMessage` 文本前缀分类，零 ADR。否决：文本脆弱（上游/网关措辞变化即断）、不可做类型级契约测试；feature grill G2 用户明确选 B。
- **B 路（pi_ai 抛异常）**：`_http_stream` 改为抛结构化异常，App 层 `except` 分类（poirot `_should_fallback(exc)` 同款）。否决：破坏 pi 语义——harness/调用方预期错误以消息交付（`stopReason="error"`），抛异常会改全部调用方行为面，偏差远大于加字段。
- **C 路（只加流内 error 事件字段）**：不动 `AssistantMessage`，只在事件流加结构化 error。否决：`result()` 返回的最终消息无结构化错误，fallback 批式交付（feature B6）判定点在完整消息上，仍需同步改消息形状——绕不开。
