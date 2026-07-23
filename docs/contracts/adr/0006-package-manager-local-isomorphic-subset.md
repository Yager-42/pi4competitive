# ADR 0006: P3 采用 coding-agent package-manager **本地同构子集**

- **status:** accepted
- **date:** 2026-07-23
- **contract_version_before:** 0.3.1
- **contract_version_after:** 0.3.2
- **supersedes (partial):** ADR 0004 中「阶段③仅为非同构薄 loader、不对齐 package-manager 发现/注册流程」的**实现策略**表述  
- **does not supersede:** ADR 0004 的 **本地-only** 边界（禁止 npm/git 下载、禁止 `~/.pi` 默认发现、禁止 `pi install` 产品路径）

## Context

P1/P2 已同构移植 `packages/ai` 与 `packages/agent`。阶段③需要把「能力包」挂到 Agent 上。

曾在 ADR 0004 / 契约 v0.2.7–0.3.1 将阶段③定为：

- **仅本地** `capability_packages/`；
- **不**做 coding-agent package-manager **全文**同构（install/远程/商店）。

实现策略上原默认「薄自研 loader」。产品侧现要求 **方案 A**：

> 以 upstream `packages/coding-agent` 的 package-manager / resource-loader / extension-loader **为规范源**，**删除**不需要的能力后，对**剩余本地发现与资源解析**做 TS→Python **同构移植**。

上游参考（main `@ c55ae2fa…`）：

| 上游 | 体量（参考） | 角色 |
|------|----------------|------|
| `coding-agent/src/core/package-manager.ts` | ~2650 行 | 源解析、安装、资源路径 resolve |
| `coding-agent/src/core/resource-loader.ts` | ~1040 行 | 加载 extensions/skills/prompts/themes |
| `coding-agent/src/core/extensions/loader.ts` | ~721 行 | 扩展运行时加载 |
| `coding-agent/src/core/skills.ts` 等 | 资源语义 | skills/prompts 文件语义 |
| `coding-agent/docs/packages.md` | 产品文档 | 约定目录与 `package.json#pi` |

其中 **npm/git/install/update/CLI/user-home** 占大量表面；**本地路径 + 约定目录 + pi manifest + resolve → 资源列表** 是可同构子集。

## Decision

### D-PM1 — 同构对象

阶段③（P3）**规范源**改为：

`earendil-works/pi` **`main`** → `packages/coding-agent` 中与 **package 发现 / 资源解析 / 本地加载** 相关的模块，做 **TS→Python 同构子集**。

**不是**移植整棵 coding-agent（TUI、交互、RPC、完整 settings UX）。

### D-PM2 — 必须移植的子集（Port）

对照 upstream，行为与模块边界应对齐的能力：

1. **Local package roots**  
   - 仓库根 **`capability_packages/<pkg>/`** 作为默认「已实现本地包」集合（对应 upstream **local path** 包，但**固定根**，不扫 home）。  
2. **Package layout**（`docs/packages.md` 的本地部分）  
   - 可选 `package.json` → `pi` manifest（extensions/skills/prompts；**themes 可 host-delta 省略**）；  
   - 无 manifest 时的约定目录：`extensions/`、`skills/`、`prompts/`（themes 可选 omit）。  
3. **Resolve resources**  
   - 对齐 `PackageManager.resolve` / 本地收集：列出 enabled 资源路径 + metadata（source/origin/baseDir）。  
   - 过滤语义：glob / `!` 排除 / 精确 `+` `-`（若 upstream 子集可测则 port）。  
4. **Load into runtime**  
   - 对齐 resource-loader **本地加载**意图：  
     - extensions → **Python**：注册 `AgentTool`（及可选 hooks 表面，以 P2 Agent 已有 API 为限）；  
     - skills / prompts → 对齐 P2 harness `Skill` / `PromptTemplate` 语义（可复用已 port 的 harness 加载器，但**发现路径**走本子集）。  
5. **Observability**  
   - 包级失败可观测；单包失败默认不拖垮进程（strict 可选）。

Python 落点（可微调，须写入 `P3_module_map.md`）：

```text
packages/agent/src/earendil_works/pi_agent/package_manager/   # 或 capability_loader/ 下按 upstream 文件名拆分
  package_manager.py      # ← package-manager.ts 本地子集
  resource_loader.py      # ← resource-loader.ts 本地子集
  extensions_loader.py    # ← extensions/loader.ts 的 Python 加载
  # skills/prompts：复用 harness 或薄封装
```

Import：仍属 `earendil_works.pi_agent` 扩展面（保持 G3 单内核）；**禁止**新开第二 agent 内核包。

### D-PM3 — 明确删除 / 永不实现（Omit）

下列 upstream 表面 **禁止** port 为默认路径（调用应不存在或 `NotImplementedError` + 契约测试扫描）：

| Upstream 能力 | 处理 |
|---------------|------|
| `install` / `installAndPersist`（npm/git） | **omit** |
| `remove` / `update` / `checkForAvailableUpdates` | **omit** |
| `npm:` / `git:` / URL 源解析安装 | **omit** |
| `~/.pi`、user global agentDir 默认发现 | **omit** |
| `package-manager-cli.ts` / `pi install` CLI | **omit** |
| temporary `-e` 安装缓存目录 | **omit** |
| 扩展商店 / gallery 元数据消费 | **omit** |
| settings 双 scope 安装持久化（user/project npm 树） | **omit**；P3 可用「enabled 白名单」代替 |

**MissingSourceAction** 中的 `"install"`：**不实现**；缺失本地路径 → `"skip"` 或 `"error"` 仅。

### D-PM4 — 与 ADR 0004 的关系

| ADR 0004 | 仍有效 |
|----------|--------|
| 能力包根 `capability_packages/` | **是** |
| 禁止远程下载 / 禁止 home 默认发现 | **是** |
| 取消「全文 package-manager 为必达」 | **是**（全文仍非必达） |

| ADR 0004 原实现暗示 | 被 0006 替换 |
|---------------------|--------------|
| 阶段③仅「非同构薄自研 loader」 | 改为 **coding-agent 本地子集同构** |

### D-PM5 — Host deltas（允许）

| Upstream | Python |
|----------|--------|
| `.ts` / jiti 扩展 | Python 模块 + `register` / factory → `AgentTool` |
| Node `fs` / `path` | pathlib / 现有 `LocalFileSystem` Result API |
| Themes / TUI | **可 omit** |
| SettingsManager 全局文件 | 最小 config：root + enabled 列表（P4 再接 yaml） |
| `AgentTool` 运行 | **必须**走已移植 `packages/agent`（P2），不复制第二 loop |

### D-PM6 — 上游 pin

- 对照 SHA 写入 `docs/plans/UPSTREAM_SHA.txt`（可与 ai/agent 同 SHA）。  
- vendor sparse 须包含 `packages/coding-agent` 中上述源文件（gitignored vendor 允许）。  

## Consequences

1. P3 计划与测试以 **upstream 模块 map** 为验收，而不是「任意 discover 脚本」。  
2. 实现体量大于薄 loader，但边界清晰：port resolve/load，不 port install。  
3. 契约升至 **0.3.2**；`D16` 阶段③表述更新。  
4. 合同测试须 **禁止** 引入 npm/git clone 安装代码路径。  

## Alternatives rejected

| 方案 | 原因 |
|------|------|
| 全文 coding-agent package-manager 同构 | 产品非 coding TUI；与 D5/D22 冲突 |
| 仅自研薄 loader、不对照 upstream 文件边界 | 与选型 A 不符；长期难对齐 manifest/过滤语义 |
| 把 loader 做成独立第二内核包 | 违反 G3 |

## Implementation pointer

- 计划：`docs/plans/P3_capability_loader.md`（v0.2+，方案 A）  
- 模块表：`docs/plans/P3_module_map.md`（实现时生成）
