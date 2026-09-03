# ADR 0016 — native sandbox 出网策略：host-side deterministic public-address gate

| 字段 | 值 |
|------|-----|
| **status** | accepted |
| **date** | 2026-09-03 |
| **deciders** | Yuzizhou |
| **contract_version** | 0.3.12 → **0.3.13** |
| **supersedes** | — |
| **relates** | ADR 0013（native-only AgentTool sandbox）、ADR 0014（Linux real gate 可选）、feature [`agent-tool-native-sandbox-v1`](../features/agent_tool_native_sandbox_v1.md) §7/§7.1/§9（v0.2.3 → v0.2.4）、feature [`search-capability-packages-v1`](../features/search_capability_packages_v1.md) |

## 背景

### FACT 1 — production 出网在任何一次提交上都是全 deny

`runner.answer_network_request`（[`native/runner.py:172`](../../../competitive_app/src/competitive_app/adapter/out/sandbox/native/runner.py)）的 `action` 初值是 `"deny"`，**只有** `options.review_domain is not None` 时才会被改写：

```python
action = "deny"
if options.review_domain is not None:
    chosen = await options.review_domain({...})
    action = chosen if chosen in ("allow", "deny") else "deny"
```

而 `build_application_state` 构造 `NativeSandboxProvider` 时从未传 `review_domain`。`git log -S "review_domain" -- competitive_app/src/competitive_app/wiring.py` 为空 —— 该参数从未出现在任何一次提交里。SRT 层同样没有旁路：`policy.create_default_policy` 的 production 默认 `"allowedDomains": []`。

结果：production 里 sandboxed worker 的**每一个**出网连接都被拒绝。五个 search/fetch AgentTool 全部失效，SOCM coverage 恒为 0，且失败被 `worker.py` 归一化成 `tool execution failed`，表现为工具自身报错，不指向沙箱。WSL 实测 `run_sandboxed_command(review_domain=None)` → `exit_code: 1` + `fake broker: network denied`。

### FACT 2 — feature §7 描述的第三形态从未接线

冻结的 feature §7 要求：

> 1. 默认 deny network；未匹配连接提交精确 `hostname:port` approval。
> 5. production 无交互 UI 时不得隐式批准。
>
> G5 …… 不存在 UI 时，只有 deterministic/model reviewer 返回且成功消费 exact one-shot grant 的请求可以放行。

对应实现 `approval.approve_domain_endpoint`（reviewer → grant → `consumeGrant`）确实存在并有单测，但**只有测试在调用它**（`tests/.../test_native_approval.py`）。production 组合根从未把它接进 `answer_network_request`。

也就是说，§7 描述的是一个**从未存在过的状态**：production 既不是"reviewer + one-shot grant 放行"，也不是"有条件 deny"，而是"无条件 deny"。这不是实现落后于契约，是契约描述与任何一次实际提交都不符。

### FACT 3 — 当前 sandbox 出网目标面只有三个 provider endpoint

逐个核对五个 AgentTool 的实际 socket 目标：

| tool | 实际连接 | 备注 |
|------|----------|------|
| `tavily_search` | `TAVILY_API_URL`（默认 `https://api.tavily.com`）`/search` | `follow_redirects=False` |
| `tavily_fetch` | 同上 `/extract` | 目标页 URL 作为 **payload 字段** `{"urls": [url]}`，由 Tavily 服务端抓取 |
| `anysearch_search` | `ANYSEARCH_API_URL`（MCP streamable-HTTP） | `follow_redirects=True` |
| `anysearch_fetch` | 同上，`tools/call` name=`extract` | 目标页 URL 作为 **argument** `{"url": url}` |
| `grok_search` | `GROK_API_URL` + `/chat/completions` | `follow_redirects=True` |

即：**sandbox 从不直接连搜索结果 URL**，正文抓取由 provider 服务端代劳。出网目标面 = 三个由 env 配置的 host。这与"抓取需要任意公网"的直觉相反，是本 ADR 决策的关键事实（也推翻了本仓早期一条口头判断）。

## 决策

在 App 组合根引入 **host-side deterministic egress gate**：`wiring._build_native_review_domain(allowed_domains)`，作为 `review_domain` 回调注入 `NativeSandboxProvider` → `NativeRuntime` → `SandboxCommandOptions`。

判定顺序（全部在 Host 进程内，无 LLM，除 DNS 外无 IO）：

| 条件 | 结果 |
|------|------|
| hostname 缺失/空 | `deny` |
| `SANDBOX_ALLOWED_DOMAINS` 非空且 hostname 精确匹配或是列表项的子域 | `allow` |
| `SANDBOX_ALLOWED_DOMAINS` 非空且不匹配 | `deny`（此分支**不做 DNS**） |
| `SANDBOX_ALLOWED_DOMAINS` 为空（默认）且 `validate_public_hostname(hostname)` 成立 | `allow` |
| 其余（私网/loopback/link-local/CGNAT/fake-ip/混合解析/DNS 失败） | `deny` |

配置面新增一项 `sandbox.allowed_domains`（env `SANDBOX_ALLOWED_DOMAINS`，逗号分隔），归 trusted App composition 所有，Agent/workspace/project-local extension 不可改，符合 §9 既有约束。

**默认值为空（允许全部公网地址）是 fail-usable 的取舍，不是安全上的最优解。** 由 FACT 3，production 部署**应当**显式收紧到三个 provider host，例如：

```bash
SANDBOX_ALLOWED_DOMAINS=api.tavily.com,<anysearch host>,<grok host>
```

之所以不把"从三个 provider env URL 自动推导 allowlist"作为默认（替代方案 E，见下），是因为 `anysearch`/`grok` 客户端启用了 `follow_redirects=True`：provider 把请求 302 到自家 CDN/区域域名时，推导出的清单会静默拒绝，故障表现与本 ADR 要修的 bug 完全相同。留给部署方显式配置，是把这个判断交给知道自己 gateway 拓扑的人。

**broker 侧的两道闸门原样保留、且仍然是权威**：`broker._ask_network` 在**发问前**先 `validate_public_hostname`，Host 返回 allow 之后、代理真正 dial 之前**再解析一次**（反 DNS rebinding）。Host 回调只能收紧，不能放宽 broker 已经拒绝的目标。

## 偏差说明（为何偏离 feature §7）

§7 的 reviewer + one-shot grant 形态本次**不接线**，理由：

1. **判定输入是确定性的。** 由 FACT 3，需要判定的 hostname 集合在部署期就是已知的三个 provider host。这是清单匹配问题，不是需要语义判断的问题；model reviewer 在这里不增加判别力。
2. **成本与延迟按连接数放大。** 一次 research task 的 provider 调用是几十到上百量级；每条连接一次 LLM 调用，成本和 wall-clock 都不可接受，且引入一条与 stage/tool 两层重试相乘的失败面。
3. **确定性优于可解释性。** 出网判定是安全边界，需要可测试、可复现。当前形态有 19 条离线断言覆盖（见验收）；model reviewer 无法做同等强度的契约测试。

因此本 ADR 把 §7 clause 1 的"默认 deny"重新定义为：**broker 默认 deny，Host gate 按确定性策略放行**；clause 5 的"不得隐式批准"由"确定性 reviewer 显式判定 + broker 双重校验"满足 —— 但必须诚实记录两条实质偏差，不是措辞调整：

- 本路径**不消费 one-shot grant**（G5 原文要求）；
- 默认配置下放行面是"全部公网"，而非 §7 clause 1 的"未匹配即提交 approval"。

`approve_domain_endpoint` / `BoundaryApprovalBrokerService` 代码**保留不删**：它是 `pi-auto-review@0.3.2` 的 behavior-equivalent port 产物（D14 同构义务），也是将来接入交互式 UI 审批时的现成接缝。

## 影响

- **contract_version** 0.3.12 → **0.3.13**；§6 技术栈行 "model-backed exact network approval" 改为准确措辞；§8 新增 G14。
- **feature `agent-tool-native-sandbox-v1`** v0.2.3 → **v0.2.4**：§7 clause 1/5 + G5 重写；§9 配置清单补 `sandbox.allowed_domains`；§9 readiness 的 "network default denied" 改为 "network default deny + host gate 显式判定"。
- **代码**：策略本体只在 `competitive_app/wiring.py`（+57）；`native_sandbox_provider` / `native_runtime` 各多一个 `review_domain` 转发参数（`SandboxCommandOptions` 与 `runner.answer_network_request` 的接缝早已存在，本次只是把回调接上）。`packages/ai|agent` 零改动 —— 出网决策 100% 落在 App 组合根，符合 D9/G12（OS sandbox/approval policy 不进 Pi core）。
- **Domain / Pi core**：不受影响。
- **部署**：不设 `SANDBOX_ALLOWED_DOMAINS` 时行为 = 允许公网；收紧只需改 env，无需改码或重新构建。

## 后果

**正向**：
- search/fetch 能力从"结构性不可用"恢复为可用；coverage 不再恒 0。
- SSRF 面仍然关闭：cloud metadata `169.254.169.254`、RFC1918、loopback、CGNAT、fake-ip `198.18.0.0/15` 全部 deny，且 broker 侧 dial 前再验一次，post-approval rebinding 无效。
- 收紧策略是一个 env 变量，且由 FACT 3 已知收紧到三个 host 不会损失能力。

**负向 / 风险**：
- **默认策略是"允许整个公网"，而实际只需要三个 host** —— 默认值明显宽于必要面。这是本 ADR 最大的残余风险，缓解手段是部署期配置而非代码，因此依赖运维纪律。被批准的 worker 代码只有 manifest 里的 approved tool target，但一旦某个 capability package 被投毒，出网限制不再构成第二道防线（`capability_packages/` 本地-only + 人工 review 是 D5/D22 既有的第一道）。
- **无逐连接审计记录**。当前 allow/deny 决策不落 journal，事后无法回答"这个 task 到底连了哪些站"。列为 follow-up。
- **G5 的 one-shot grant 语义在 production 缺席**，与 `pi-auto-review` 父本的行为等价性在这一点上不成立，已在 feature §7 显式标注为 accepted deviation。

**Follow-up（不属本 ADR，另开）**：
1. 把 `review_domain` 的 allow/deny 决策写入 run journal（hostname/port/结果/原因），补上审计面。
2. 评估把默认收紧为"从三个 provider env URL 推导"（替代方案 E），前置条件是先确认 anysearch/grok 的 redirect 落点是否跨域。

## 验收

离线单测 [`tests/competitive_app/unit/test_sandbox_egress_policy.py`](../../../tests/competitive_app/unit/test_sandbox_egress_policy.py)（19 断言，注入 resolver，不打真实 DNS）：

- allowlist 模式：精确匹配 / 子域 allow；`notexample.com`、`example.com.evil.test`、未列出的父域 deny；解析大小写与首尾空格、结尾点规范化；**allowlist 分支不触发 DNS**（注入会 raise 的 resolver 断言）。
- 默认模式：公网地址 allow；loopback / RFC1918 / link-local / metadata / CGNAT / fake-ip deny；**混合解析**（一公一私）deny；DNS 失败 deny。
- 两种模式下 hostname 缺失/空均 deny。

回归：WSL2 Ubuntu 全量离线 `uv run pytest -m "not live" -q` → **11 failed / 1142 passed / 12 skipped / 40 deselected**。HEAD 同环境同为 11 failed，逐条一致（`/bin/bash` vs `/usr/bin/bash` 的 argv 断言 ×2、timeout 路径 IPC `ConnectionResetError` ×2、macOS/proxy 平台断言 ×4、`test_reasonix_search_coload`、`test_refine_sections`、`test_post_task_evolution_failure_does_not_fail_run` 的 fake Store 缺 `get_task`）——全部先于本改动存在，本次新增 19 passed 即上表用例，无新增失败。

## 替代方案（否决）

- **A 路（接线 `approve_domain_endpoint` + `pi_auto_review` reviewer）**：完全落实 §7/G5。否决理由见"偏差说明"1–3：判定输入确定性强，reviewer 无判别力增量，成本/延迟/不确定性按连接数放大。接缝保留，将来若出现交互式审批 UI 可重启。
- **B 路（维持现状不接线）**：零代码零 ADR。否决：等于接受 search/fetch 永久不可用，P4 的核心业务能力（coverage）无法交付。
- **C 路（硬编码三个 provider host 为默认）**：否决：三个 endpoint 全部来自 env（`TAVILY_API_URL`/`ANYSEARCH_API_URL`/`GROK_API_URL`），硬编码会在换 gateway 的部署上失效；且 `TAVILY_API_URL` 有默认值而另两个是必填，形状不一致。
- **D 路（SRT `network.allowedDomains` 层放行）**：不用 Host 回调，改在 policy 里放开。否决：SRT 层放行绕过 broker 的 pre-dial 重解析，反 rebinding 保护失效；且策略从"每连接判定"退化为"启动期静态清单"。
- **E 路（默认从三个 provider env URL 自动推导 allowlist）**：安全性最好。**暂缓**而非否决：`anysearch`/`grok` 客户端 `follow_redirects=True`，跨域重定向会被静默拒绝，故障形态与本 ADR 修的 bug 相同。改为部署期显式配置 + 列入 follow-up 2。
