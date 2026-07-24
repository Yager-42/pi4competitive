# Feature 边界契约：search-capability-packages-v1

| 字段 | 值 |
|------|-----|
| **feature_contract_version** | `0.1.11` |
| **status** | **frozen** |
| **updated** | 2026-07-23 |
| **feature_id** | `search-capability-packages-v1` |
| **roadmap_stage** | P4 业务能力 v1 — 搜索 capability 可按本文实现 |
| **architecture_contract** | [`ARCHITECTURE_CONTRACT.md`](../contracts/ARCHITECTURE_CONTRACT.md) **v0.3.3** |
| **roadmap** | [`ROADMAP.md`](../ROADMAP.md) §4 |
| **plan** | [`P4_search_capability_packages.md`](../plans/P4_search_capability_packages.md) |
| **path** | `docs/features/search_capability_packages_v1.md` |

---

## 0. 效力与状态

1. 本文是 **P4 搜索能力 v1** 的 **frozen** 功能边界；架构、依赖方向和 Pi package 机制仍以架构契约为最高约束。
2. 标为 **locked** 的决定不得由实现者自行改写；变更须重新 grill 并升 `feature_contract_version`。
3. §10 为 **验收标准（locked）**；实现须满足，不得缩水。
4. 变更本 frozen 边界 = 业务范围变更，须同步 `docs/ROADMAP.md`。
5. 本文不改变架构契约；若后续新增 agent 内核、package 类型或改变依赖方向，须先走 ADR + 架构契约升版。

---

## 1. 目标（locked）

以当前 Pi 本地 capability package 机制，为 P4 `competitive_app` 提供三个可插拔搜索供应商能力：

1. Tavily：搜索 + 网页正文提取；
2. AnySearch：搜索 + 网页正文提取；
3. Grok：AI 驱动搜索，单次返回综合答案和信源。

这些能力通过 Python `AgentTool` 注册到唯一的 `earendil_works.pi_agent` Agent，供 P4 Application workflow 调用。

---

## 2. 规范源与角色（locked）

| 来源 | 角色 | 约束 |
|------|------|------|
| `earendil-works/pi` `main` 的 Pi package / extension 定义 | package 组织与 `AgentTool` 运行语义规范源 | 本地 Python host delta 仍按架构契约 D5/D6/D22、ADR 0006 |
| [`xj120/competitive-agent`](https://github.com/xj120/competitive-agent) | Tavily / AnySearch 能力和字段语义参考 | 仅能力参考；不移植旧 agent、MCP/package runtime 或 workflow 类型（D12 / ADR 0007） |
| [`GuDaStudio/GrokSearch`](https://github.com/GuDaStudio/GrokSearch) `grok-with-tavily` | Grok 搜索、答案与 sources 提取行为参考 | 不原样引入其 FastMCP server、Claude 工具控制、进程缓存或 Tavily/Firecrawl fetch 聚合 |

源码与依赖策略见 **§9.1 / F-S17**（对照重写 + httpx；非 open）。

---

## 3. Pi package 边界（locked）

### 3.1 目录与 package

```text
capability_packages/
  search_tavily/
    package.json
    extensions/
      *.py
  search_anysearch/
    package.json
    extensions/
      *.py
  search_grok/
    package.json
    extensions/
      *.py
```

每个 immediate child directory 是一个本地 Pi package。每包通过 `package.json` 的 `pi.extensions` 声明 Python extension：

```json
{
  "name": "search_tavily",
  "version": "0.1.0",
  "keywords": ["pi-package"],
  "pi": {
    "extensions": ["./extensions"]
  }
}
```

### 3.2 加载与注册

```text
LocalPackageManager
  → resolve package.json / extensions
  → Python extension register(api)
  → api.add_tool(AgentTool(...))
  → LoadReport.tools
  → apply_capability_report(agent, report)
  → agent.state.tools
```

约束：

- package 内执行面必须是 Python；
- 工具必须使用 `earendil_works.pi_agent.AgentTool`；
- App 不直接 import provider extension；由 wiring 加载 package 后应用到 Agent；
- capability package 不依赖 `competitive_app.domain`；
- 本 feature 不新增通用 MCP adapter、MCP package 类型、远程 package install 或第二套 package runtime；
- provider 的底层传输实现仍为内部细节，不能改变对 Agent 暴露的 `AgentTool` 契约。

---

## 4. Package 与 Tool 清单（locked）

| Package | AgentTool | 能力 |
|---------|-----------|------|
| `search_tavily` | `tavily_search` | Tavily 搜索 |
| `search_tavily` | `tavily_fetch` | Tavily 网页正文提取 |
| `search_anysearch` | `anysearch_search` | AnySearch 搜索 |
| `search_anysearch` | `anysearch_fetch` | AnySearch 网页正文提取 |
| `search_grok` | `grok_search` | Grok AI 搜索，返回综合答案 + 信源 |

名称策略：

- 工具名必须带 provider 前缀；
- 不注册冲突的通用 `web_search` / `web_fetch`；
- v1 不增加 provider router / 自动选路工具；
- 不注册 `grok_fetch`；GrokSearch 项目的公开 fetch 实际来自 Tavily / Firecrawl，不属于 Grok 原生搜索边界；
- 不注册 `grok_get_sources`（见 §7）。

### 4.1 Tool 输入契约（locked）

所有 Tool schema 必须拒绝未声明字段；不得加入旧仓 workflow ID、budget 或 source classification 参数。

#### `tavily_search`

| 参数 | 类型 | 必填 | 默认 | 约束 |
|------|------|------|------|------|
| `query` | string | 是 | — | 非空搜索查询 |
| `max_results` | integer | 否 | `10` | `1..20` |
| `topic` | string | 否 | `general` | `general` / `news` |
| `search_depth` | string | 否 | `basic` | `basic` / `advanced` |
| `time_range` | string | 否 | `any` | `any` / `day` / `week` / `month` / `year` |
| `include_domains` | string[] | 否 | `[]` | 最多 20 个规范域名 |

#### `anysearch_search`

| 参数 | 类型 | 必填 | 默认 | 约束 |
|------|------|------|------|------|
| `query` | string | 是 | — | 非空搜索查询 |
| `max_results` | integer | 否 | `10` | `1..20` |
| `vertical` | string | 否 | `web` | `web` / `news` |
| `freshness` | string | 否 | `any` | `any` / `day` / `week` / `month` / `year` |
| `country` | string \| null | 否 | `null` | 大写 ISO-3166 alpha-2 |
| `language` | string | 否 | `en` | `zh` / `en` |
| `include_domains` | string[] | 否 | `[]` | 最多 20 个规范域名 |

#### `grok_search`

| 参数 | 类型 | 必填 | 默认 | 约束 |
|------|------|------|------|------|
| `query` | string | 是 | — | 非空、自包含自然语言查询 |
| `platform` | string | 否 | `""` | 可指定 `Twitter`、`GitHub, Reddit` 等平台提示 |

Grok `model` 只通过配置提供；Agent 不得按次切换模型。`extra_sources` 不暴露，避免隐式调用其他 provider。

#### Fetch Tools

`tavily_fetch` 与 `anysearch_fetch` 均只接受一个必填 `url`：完整 HTTP/HTTPS URL。v1 不接受正文长度参数（§8.3）。

### 4.2 Provider 配置（locked）

三个搜索 capability 的 provider 配置全部来自进程环境（可由 gitignored `.env` / secret manager 注入），不在 `config/settings.yaml` 中重复声明：

```dotenv
TAVILY_API_KEY=
TAVILY_API_URL=https://api.tavily.com

ANYSEARCH_API_KEY=
ANYSEARCH_API_URL=

GROK_API_KEY=
GROK_API_URL=
GROK_MODEL=
```

规则：

- `.env.example` 只提供空 secret 占位和非 secret 示例，不含真实密钥；
- `.env` 必须保持 gitignored；生产可由 secret manager 直接注入同名环境变量；
- 不读取 `config/settings.yaml` 中的 Tavily / AnySearch / Grok provider 字段；
- 不读取 GrokSearch 的 `~/.config/grok-search/config.json`；
- 不支持 `GUDA_API_KEY` 派生多个服务；
- 不允许 Agent 通过 Tool 参数切换 Grok model；
- 该决定仅适用于本 feature 的 provider 配置；P4 其他非 provider 配置仍遵循架构契约 D23，package enablement 见 §4.3。

### 4.3 Package 启用（locked）

搜索 provider 的 key / endpoint / model 走环境变量；本地 package 是否参与产品运行由 P4 settings 显式白名单决定：

```yaml
capability_packages:
  enabled:
    - search_tavily
    - search_anysearch
    - search_grok
```

P4 wiring 必须将该列表传给：

```python
load_capability_packages(enabled=settings.capability_packages.enabled)
```

规则：

- 未列入白名单的本地 package 不加载；
- 不根据 API key 是否存在隐式启用 package；
- 不使用 `CAPABILITY_PACKAGES_ENABLED` 环境变量复制同一配置；
- 白名单中的未知或缺失目录必须产生可观测启动诊断；
- 白名单只表达产品能力组合，不得包含 secret 或 provider endpoint。

### 4.4 配置缺失与加载失败（locked；复用 Pi 机制）

本 feature 不新增第二套 availability / failure-isolation 机制：

1. 白名单中的 extension 在调用 `api.add_tool(...)` 前读取并校验该 provider 所需环境变量；
2. 配置缺失或无效时抛出不含 secret 值的注册异常；
3. 现有 Pi `extensions_loader` 将注册异常转换为 package/path 级 `ResourceDiagnostic(level="error")`；
4. 失败 extension 不向 `LoadReport.tools` 贡献任何 Tool；
5. `strict=False`（默认）继续加载其他 package；`strict=True` 使用 Pi 现有 `PackageLoadError` 语义；
6. App / wiring 只消费和呈现 `LoadReport.diagnostics`，不得复制一套 package 失败策略。

最低可运行配置：

| Package | 必需环境变量 |
|---------|--------------|
| `search_tavily` | `TAVILY_API_KEY`（`TAVILY_API_URL` 有官方默认） |
| `search_anysearch` | `ANYSEARCH_API_KEY`、`ANYSEARCH_API_URL` |
| `search_grok` | `GROK_API_KEY`、`GROK_API_URL`、`GROK_MODEL` |

诊断只允许包含缺失的变量名或配置字段名，不得包含 secret 值、请求 headers 或 provider 响应正文。

### 4.5 HTTP client 与重试边界（locked）

- 当前 Pi `AgentTool` runtime 不提供、也不得新增全局 Tool 重试；任意 Tool 可能有副作用，Agent loop 仍只调用一次 `execute(...)`；
- 每次搜索/抓取调用使用 `async with httpx.AsyncClient(...)` 创建并关闭 client，对齐当前 Python Pi HTTP 惯例；不创建没有 teardown hook 的 module-global client；
- Tavily / AnySearch 对齐旧仓 adapter：每次 Tool 调用只发起一次 provider 请求，不在 capability 内自动重试；
- Grok 对齐 GrokSearch：保留其 adapter 内有界重试、`Retry-After` 优先和指数退避；
- Grok 仅重试来源实现认定的瞬时网络错误及 408、429、500、502、503、504；401/403、参数/解析错误不得重试；
- Grok 流式响应一旦收到首个有效 chunk，不得重新发起请求；
- 不直接复用当前 `pi_ai.utils.retry_async`：它会重试所有异常、无 `Retry-After` / predicate / stream 边界，且当前没有实际调用者；
- 五个 Tool 统一使用 GrokSearch 的 `httpx.Timeout(connect=6.0, write=10.0, read=120.0, pool=None)`；timeout 为 adapter 常量，不新增调优 env；
- Grok 最多重试 3 次（初次 + 3 次 = 最多 4 次请求），指数退避 multiplier `1`、普通最大等待 `10s`，429 优先遵守 `Retry-After`；Tavily / AnySearch 仍不重试；
- 所有 Tool 在发请求前检查 Pi `AbortSignal.aborted`；abort 必须取消当前 HTTP 请求或 Grok retry sleep，并以 aborted 语义结束，不得包装成普通 provider error。

---

## 5. Pi `AgentToolResult` 外壳（locked）

所有成功结果同时提供模型可见内容和结构化详情：

```python
{
    "content": [
        {
            "type": "text",
            "text": json.dumps(payload, ensure_ascii=False),
        }
    ],
    "details": payload,
}
```

约束：

- `content` 中的 JSON 是下一轮 LLM 可见结果；
- `details` 保存同一 normalized payload，进入 tool event / `ToolResultMessage` / session；
- provider 原始 payload 不是 v1 公共契约；
- 失败、空结果与部分成功的映射见 §5.1。

### 5.1 Error 与部分成功（locked）

`search_result.v1` 与 `fetch_result.v1` 必须包含 `warnings` 数组；无 warning 时为 `[]`：

```json
{
  "warnings": [
    {
      "code": "invalid_provider_item",
      "message": "Some provider items could not be normalized"
    }
  ]
}
```

映射规则：

| 情况 | Pi 结果 |
|------|---------|
| 合法搜索但零命中 | 成功；`hits=[]`、`warnings=[]` |
| 部分 hit 非法 | 保留合法 hits；warning `invalid_provider_item`；`isError=false` |
| Grok 有 answer、无 sources | 保留 answer；warning `sources_unavailable`；`isError=false` |
| Provider 返回可用结果但响应部分不完整 | 保留可用内容；warning `partial_provider_response`；`isError=false` |
| Fetch 正文非空但可选元数据缺失 | 使用契约 fallback；必要时 warning；`isError=false` |
| Fetch 正文为空 | 抛 sanitized exception；由 Pi 生成 `isError=true` |
| HTTP/timeout/认证/最终 429/完全无法解析 | 抛 sanitized exception；由 Pi 生成 `isError=true` |
| Abort | 传播 aborted；不得包装成普通 provider error |

warning / exception 只允许稳定 code 与脱敏消息；不得包含 API key、请求 headers、provider 原始错误正文或完整响应 payload。

---

## 6. 搜索结果契约（locked）

### 6.1 `search_result.v1`

```json
{
  "schema_version": "search_result.v1",
  "provider": "tavily",
  "query": "AI coding agents 2026",
  "answer": null,
  "hits": [
    {
      "rank": 1,
      "title": "Article title",
      "url": "https://example.com/page?utm_source=x",
      "canonical_url": "https://example.com/page?utm_source=x",
      "snippet": "Search-result excerpt",
      "score": 0.91,
      "published_at": "2026-07-20T08:00:00Z"
    }
  ],
  "warnings": []
}
```

### 6.2 字段规则

| 字段 | 类型 | 规则 |
|------|------|------|
| `schema_version` | string | 固定为 `search_result.v1` |
| `provider` | string | `tavily` / `anysearch` / `grok` |
| `query` | string | 实际执行的原查询 |
| `answer` | string \| null | Grok 综合答案；Tavily / AnySearch 为 `null` |
| `hits` | array | 按 provider 返回顺序排列 |
| `warnings` | array | 部分成功的脱敏 warning；无 warning 时固定 `[]` |
| `hits[].rank` | integer | 从 1 开始 |
| `hits[].title` | string | 缺失时使用 `canonical_url` |
| `hits[].url` | string | provider 返回的 HTTP/HTTPS URL |
| `hits[].canonical_url` | string | v1 恒等于 `url`（§8.5）；不做清洗 |
| `hits[].snippet` | string | 缺失时为空字符串 |
| `hits[].score` | number \| null | provider 有可靠 score 时保留，否则 `null` |
| `hits[].published_at` | string \| null | 有可靠时间时转为 ISO 8601，否则 `null` |

P4 Application 自行生成 `evidence_id`、`query_id`、`source_request_id`、source classification 和 workflow 状态；这些字段不得泄漏进 capability 返回契约。

---

## 7. Grok 行为（locked）

`grok_search` 必须一次返回 `search_result.v1`：

```text
Grok 综合答案 → answer
Grok citations / sources → hits
```

相对 GrokSearch 参考项目的明确 host delta：

- 不返回临时 `session_id`；
- 不使用最大 256 项的进程内 `SourcesCache`；
- 不要求第二次调用 `get_sources`；
- sources 在同一次 `grok_search` 中内联并随 Agent session 持久化；
- 不通过 `extra_sources` 隐式调用 Tavily / Firecrawl；其他 provider 已作为独立 AgentTool 暴露；
- 不暴露 GrokSearch 的 `web_map`、`switch_model`、`toggle_builtin_tools`、planning 等工具。

---

## 8. Fetch 结果与正文策略（locked）

### 8.1 `fetch_result.v1`

```json
{
  "schema_version": "fetch_result.v1",
  "provider": "tavily",
  "url": "https://example.com/page",
  "canonical_url": "https://example.com/page",
  "title": "Page title",
  "content": "# Complete Markdown content",
  "content_type": "markdown",
  "warnings": []
}
```

### 8.2 字段规则

| 字段 | 类型 | 规则 |
|------|------|------|
| `schema_version` | string | 固定为 `fetch_result.v1` |
| `provider` | string | `tavily` / `anysearch` |
| `url` | string | 请求的 HTTP/HTTPS URL |
| `canonical_url` | string | v1 恒等于 `url`（§8.5）；不做清洗 |
| `title` | string | 无法获得时为空字符串 |
| `content` | string | provider 提取的完整网页正文 |
| `content_type` | string | `markdown` 或 `text` |
| `warnings` | array | 部分成功的脱敏 warning；无 warning 时固定 `[]` |

### 8.3 完整正文策略

对齐 GrokSearch 的完整正文取向：

- 不提供 `max_chars` / `max_bytes` 参数；
- 不摘要；
- 不主动截断；
- provider 返回多少正文就保留多少；
- `fetch_result.v1` 不含 `truncated`，因为 capability 无法真实判断上游是否截断；
- 完整 payload 同时进入 `AgentToolResult.content` 和 `details`。

已接受风险：超长网页可能显著增加下一轮模型上下文和 JSONL session 体积；v1 不在 capability 层缓解。

### 8.4 URL 处理（locked；对齐 GrokSearch）

`tavily_fetch` / `anysearch_fetch` 与 GrokSearch `web_fetch` 同形：本进程 **不直连目标网页**，只把 `url` **原样转发** 给第三方 extract。

因此 v1：

- **不做** 本地公共 IP / localhost / metadata / DNS rebinding / 端口白名单校验；
- **不移植** 旧仓 `SafeNetworkClient` / `ValidatedHTTPTransport`；
- 不声称能阻止第三方在其网络内解析或访问何种目标；
- 安全边界 = 对 Tavily / AnySearch 的信任 + 密钥隔离；
- 接受残留风险：坏 URL、内网域名或 URL 内凭证可能进入第三方请求日志；非 URL 输入可能浪费配额。

- search hits 的 `url` 同样不做本地 SSRF 级拒绝；`canonical_url` 规则见 §8.5。

Tool schema 仍要求 `url` 为非空 string；格式合法性交给第三方与错误映射（§5.1）。

### 8.5 `canonical_url`（locked）

v1 **不清洗** URL：

- `canonical_url` **恒等于** 对应的 `url`（search hit 原始 URL，或 fetch 使用的 URL）；
- 不做 host 小写、去 fragment、去 tracking query、去尾 `/` 等规范化；
- 接受重复命中与 search/fetch 字符串对不齐的风险；去重与证据聚合留给 **P4 Application**；
- 字段仍保留在两个 v1 schema 中，避免以后加清洗时改字段名。

---

## 9. 明确非目标（locked）

- 复刻旧仓 `search.core`、collector 编排、budget、route catalog 或 workflow contracts；
- 通用 provider router、统一 `web_search` / `web_fetch` façade；
- Grok fetch、Grok sources 二次查询和 GrokSearch 进程缓存；
- Firecrawl package 或隐式 Firecrawl fallback；
- `web_map` / 站点地图；
- npm/git package install、`~/.pi` 扫描或远程 package 自动发现；
- 把 Tavily / AnySearch / Grok 类型加入 `packages/ai|agent`；
- 在 capability package 内生成 P4 workflow / evidence 标识；
- P4 研究阶段编排、报告和领域 schema（另行 grill / 冻结）。

### 9.1 源码与依赖（locked）

- **对照重写**：三个 package 各自实现薄 HTTP adapter；只参考旧仓 Tavily/AnySearch 与 GrokSearch（`grok-with-tavily`）的请求形状、归一化与 Grok 重试语义；
- **不** git submodule / vendor 整仓 GrokSearch 或旧仓 MCP server；
- **不** `pip install` GrokSearch 或第三方搜索 SDK 作为正式依赖；
- **不**引入 `tenacity`；Grok 有界重试用少量自写逻辑；
- 运行时 HTTP 使用进程内已有 **`httpx`**（`packages/ai` 已依赖）；不在 capability 层新增独立 Python 发行包；
- 参考归属：GrokSearch 为 MIT，在实现 PR / 本 feature 文档中保留来源链接即可；不把上游 commit 当可安装 lock。

---

## 10. 验收标准（locked）

### 10.1 Offline（默认 CI 必绿）

| ID | 要求 |
|----|------|
| O1 | 三包可被 `load_capability_packages(enabled=[...])` 发现；注册 tool 名恰好为 `tavily_search`、`tavily_fetch`、`anysearch_search`、`anysearch_fetch`、`grok_search` |
| O2 | 缺该包必需 env 时：该包 **零** tool 进入 `LoadReport`，且有 `ResourceDiagnostic(level="error")`（无 secret 正文） |
| O3 | Tool JSON Schema 拒绝未声明字段；参数边界（如 `max_results`）校验失败不发起 HTTP |
| O4 | 归一化 fixture：`search_result.v1` / `fetch_result.v1`（含 `warnings`、空 `hits`、`canonical_url == url`） |
| O5 | **httpx mock** 覆盖五工具：成功路径返回可解析 payload；失败路径抛异常 → loop 侧 `isError=true` |
| O6 | **Faux agent 路径**：`apply_capability_report` 后，faux 模型发出 toolCall → agent loop 执行真实 `AgentTool.execute`（mock HTTP）→ `toolResult` 消息 **`isError=false`** 且 `content` 中含归一化 JSON 文本（agent/模型可见） |

测试落点建议：`tests/capability_loader/` 下 `unit` / `contract` / `integration/faux`，与现有 echo 模式对齐。

### 10.2 Live（真实 provider；有密钥时必跑）

| ID | 要求 |
|----|------|
| L1 | 使用真实 env 密钥；`@pytest.mark.live`；**无密钥则 skip**，不得伪绿 |
| L2 | 至少一个已配置 search tool（优先 `tavily_search` 或 `anysearch_search` 或 `grok_search`）被 **Agent/loop** 调用（可用真实小模型或 scripted toolCall + 真 tool，但 execute 必须打真网） |
| L3 | 返回的 `toolResult` **`isError=false`**，且 `content`/`details` 中可见非空业务内容：search 至少 `hits` 非空 **或** Grok `answer` 非空；fetch live 至少一条非空 `content`（若该 provider 已配置） |
| L4 | Live 不进默认无密钥 CI；本地/带 secret 的流水线必须能跑通 L2–L3 |

### 10.3 实现完成定义

- Offline O1–O6 全绿；
- 对每个在白名单且密钥齐全的 provider，Live L2–L3 在带密钥环境通过；
- 未配置的 provider 仅 skip live，不得降低 offline 标准。

---

## 11. 决策记录

| ID | 状态 | 决定 |
|----|------|------|
| F-S1 | locked | 能力按 Pi 本地 `capability_packages/*` + Python `AgentTool` 接入 |
| F-S2 | locked | 三个 provider package；Tavily / AnySearch 含 search+fetch，Grok 仅 search |
| F-S3 | locked | 所有 provider 使用统一 normalized `search_result.v1` / `fetch_result.v1` |
| F-S4 | locked | 五个 provider 前缀 Tool 名；无通用 façade |
| F-S5 | locked | `grok_search` 一次返回 answer + hits；无 session cache / `get_sources` |
| F-S6 | locked | Fetch 返回完整正文，不设主动截断上限 |
| F-S7 | locked | `fetch_result.v1` 删除无法验证的 `truncated` 字段 |
| F-S8 | locked | 精选 provider 输入：Tavily/AnySearch 保留研究过滤参数，Grok 仅 `query` + `platform`，Fetch 仅 `url` |
| F-S9 | locked | 搜索 provider 的 key、API URL、Grok model 全部走环境变量；P4 其他配置策略不变 |
| F-S10 | locked | P4 settings 以显式白名单启用三个搜索 package；provider 配置仍只走环境变量 |
| F-S11 | locked | 配置缺失复用 Pi extension 注册失败诊断与 strict/non-strict 隔离；不注册坏 Tool |
| F-S12 | locked | Pi core 不重试 Tool；Grok 保留来源重试，Tavily/AnySearch 单次请求；每次调用独立关闭 HTTP client |
| F-S13 | locked | 五个 Tool 统一 GrokSearch timeout（6s connect / 10s write / 120s read）；Grok 最多 3 次 retry；全员传播 Pi abort |
| F-S14 | locked | 全失败抛异常走 Pi `isError`；空结果成功；部分结果保留并通过两个 v1 schema 的 `warnings` 显式报告 |
| F-S15 | locked | Fetch/search URL 本地不校验，原样委托第三方 extract；不对齐旧仓 SafeNetworkClient |
| F-S16 | locked | `canonical_url` 恒等于 `url`，v1 不做 URL 清洗；去重留给 P4 |
| F-S17 | locked | 薄 HTTP 对照重写；无 GrokSearch/旧仓 vendor；仅 httpx；自写 Grok 重试 |
| F-S18 | locked | Offline 必绿 + Live（有密钥）必证 Agent 调 tool 且 toolResult 可见真实/归一化内容 |

---

## 12. 冻结记录

| 项 | 值 |
|----|-----|
| 冻结版本 | `0.1.11` |
| 冻结日期 | 2026-07-23 |
| 决策 | F-S1…F-S18 全部 locked |
| 验收 | §10 Offline O1–O6 + Live L1–L4 |
| 架构影响 | 无；不升 `ARCHITECTURE_CONTRACT` |
| Roadmap | 见 `docs/ROADMAP.md`（实现计划 `P4_search_capability_packages`）；本文路径 `docs/features/` |
