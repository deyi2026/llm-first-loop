# CodeArts 上下文窗口管理与 Pi Coding 缓存命中借鉴方案报告

> 日期：2026-08-18
> 范围：CodeArts（GLM-5.2 驱动的代码智能体）运行时上下文/缓存机制剖析 + Pi Coding 系高缓存命中机制剖析 + 借鉴方案
> 方法：真实工具回执（webfetch 抓取 4 个主流仓库 README）+ CodeArts 运行时系统提示/工具集实证分析
> 置信度声明：CodeArts 内部实现为黑盒，本报告基于"运行时可见的系统提示 + 工具契约 + 行为观察"推断，非源码实证；Pi Coding 等机制基于公开 README 实证。每节标注置信度。

---

## 0. 摘要（TL;DR）

| 维度 | CodeArts 现状（推断） | Pi Coding 系（实证） | 借鉴结论 |
|:---|:---|:---|:---|
| 前缀稳定性 | 系统提示+偏好+技能注入相对稳定，但工具结果/截断动态注入易破坏前缀 | 前缀守卫剥离 volatile-scratch，字节级稳定 | **应引入前缀守卫 + 漂移遥测** |
| 缓存命中可观测 | 无面向用户的命中率遥测（运行时不可见） | cacheRead/input/cacheWrite/turns 持久化 + footer + ASCII 趋势图 | **应补命中率遥测与归因** |
| 历史压缩 | 靠"minimize output tokens"+Task 委托+截断写文件，被动 | cache-friendly compaction（temperature:0 确定性摘要 + SHA-256 跨会话复用） | **应改确定性摘要 + 摘要缓存** |
| 增量召回 | 无显式 delta 召回；全量工具结果易回灌 | session-aware recall delta（只带指针 `[N prior memories still apply]`） | **应走 delta 召回** |
| 工作历史尺寸 | 无可见上限配置（依赖模型窗口） | 主流 100K 级窗口命中 90%+ | **有效工作历史收敛 100-200K** |

**核心判断**：CodeArts 的上下文管理偏"被动截断 + 委托降占"，缺"前缀守卫 + 命中遥测 + 确定性摘要复用"三件套；Pi Coding 系正是靠这三件套在几十 K 提交下命中 90%+。借鉴路径明确且可落地。

---

## 1. CodeArts 运行时上下文窗口管理机制

> 置信度：**中**。基于运行时系统提示、工具契约与行为推断，非源码实证。

### 1.1 上下文构成（运行时可见）

CodeArts 每轮提交给模型的上下文由以下部分组成（按前缀→后缀顺序）：

1. **系统提示（稳定前缀主体）**：角色定义、语气风格、工具使用策略、安全规则、环境信息（cwd/platform/date）、可用技能清单、AGENT.MD 优先级规则、用户偏好（PREFERENCE_1..20）、自定义信息。
2. **对话历史（半稳定）**：历史轮次的 user/assistant/tool 调用与结果。
3. **当前轮新增（易变后缀）**：用户消息 + 本轮工具调用 + 工具结果。

### 1.2 管理策略（系统提示实证）

从运行时系统提示可提取的显式策略：

- **输出最小化**："minimize output tokens as much as possible"、"fewer than 4 lines"。
- **并行批量工具调用**：单消息内并行多个独立工具调用（上限 6 个/调用），减少轮次。
- **Task 委托降占**：探索类任务委托 `explore` 子代理，结果以单消息返回，不把中间搜索过程灌入主上下文。
- **大输出截断落盘**：bash/webfetch 输出超阈值时截断并写入文件，用 `Read offset/limit` 或 `Grep` 按需读取（本报告 webfetch 即触发此机制）。
- **语义/结构搜索优先**：`CodeSemanticSearch` / `CodeGraphSearch` 代替 grep/glob 全量遍历。
- **技能加载**：`skill` 工具按需注入领域指令，避免常驻。

### 1.3 缓存命中情况（推断 + 诚实局限）

> 置信度：**低**。CodeArts 未向运行时暴露命中率遥测，以下为机制推断，非测量值。

- **有利命中因素**：
  - 系统提示体量大且跨轮相对稳定（角色+偏好+技能清单+AGENT.MD），构成可缓存前缀。
  - 并行工具调用减少轮次，间接减少前缀变动次数。
- **不利命中因素（推断的缓存破坏点）**：
  - **工具结果动态注入位置**：若工具结果插在前缀区（如 system 内动态拼接），会破坏字节级前缀稳定——这是 Pi Coding 明确攻击的痛点。
  - **截断落盘后按需回读**：回读内容每次可能不同（offset/limit 变化），形成新的易变段。
  - **Task 子代理结果**：单消息返回但内容随任务变化，属后缀新增，对前缀命中中性但对"新增/提交占比"不利（结果可能很大）。
  - **无前缀漂移检测**：系统提示未要求监控前缀哈希漂移，命中下降时无告警。
- **诚实声明**：CodeArts 是否使用 provider 侧 prompt caching（如 GLM/DeepSeek 的 KV cache）、命中率几何，运行时**不可见**，本报告无法给出实测数字。这是 CodeArts 相对 Pi Coding 系的最大可观测性缺口。

---

## 2. Pi Coding 系高缓存命中机制剖析

> 置信度：**高**。基于 4 个仓库 README 公开实证。

### 2.1 pi-deepseek-cache（前缀守卫 + 遥测 + 友好压缩）

**核心原理**：DeepSeek 的 Context Caching on Disk——prompt **前缀字节级精确匹配**才命中（命中价 ~90% 折扣）。长会话中保持字节前缀稳定很难，该扩展三件事：

| 层 | 机制 | 实证细节 |
|:---|:---|:---|
| P1 遥测 | 累积 `cacheRead`/`input`/`cacheWrite`/`turns` | 从 `message_end` 事件累积，持久化到 `stats.json`，footer 实时显示 + `/cache-graph` ASCII 趋势图 + 成本节省估计 |
| P2 前缀守卫 | 过滤 `volatile-scratch` 消息 | 在 `context` hook 剥离易变内容，监控前缀哈希，漂移即告警 |
| P3 压缩 | cache-friendly compaction | `session_before_compact` 时用 `deepseek-v4-flash`（temperature:0 确定性）摘要，**SHA-256 缓存摘要结果跨会话复用** |

**关键洞察**：命中高的根因不是"大历史摊薄新增"，而是"**前缀占提交 90%+ + 新增小 + 摘要确定性可复用**"。

### 2.2 pi-cache-optimizer（稳定前置 + 缓存键 + 代理兼容）

| 机制 | 实证细节 |
|:---|:---|
| 稳定内容前置 | 把唯一可识别的稳定 system-prompt 内容**重排到动态上下文之前**（重复出现则不动，避免误删） |
| skill 压缩 | 压缩 Pi skill 列表 XML + 剥离 session-overview churn |
| 长缓存保留 | 请求 provider 长缓存保留（兼容时） |
| 缓存键 fallback | 为 openai-completions/responses 加 session-id `prompt_cache_key` |
| 代理兼容告警 | 第三方代理跨上游路由会分裂缓存 → 告警 + `sendSessionAffinityHeaders` 修复 |
| TTL 兼容 | Anthropic 5min→1h 断点顺序非法时自动降级，错误后 process-local fallback |
| 自适应 thinking | Claude opus-4.6+/Kimi K3 的 `forceAdaptiveThinking` 兼容检测与 `/fix` 自动修复（预览+确认+备份） |
| footer 统计 | 按 provider/model 累积，total/session/process 三种 scope |

**关键洞察**：缓存命中是**全链路兼容问题**——前缀顺序、缓存键、代理路由、TTL 顺序、thinking 格式任一环出错都归零。pi-cache-optimizer 把每一环都做成可检测+可修复。

### 2.3 icemage（delta 召回 + cache-aware 打包）

| 机制 | 实证细节 |
|:---|:---|
| session-aware recall delta | session TTL 去重时 emit `[N prior memories still apply: #ids]` 而非静默丢弃——**保留指针不重付 token** |
| `pack --cache-aware` | 分类 sections（conventions/rules/graph/files=stable; task/recall/diff=volatile），**stable-first 排序**，只包裹字节稳定前缀（FNV-1a `prefix_hash` 让漂移可见）→ prompt caching 实际命中（-90% cost / -85% latency） |
| contradiction sentinel | `memory-health --contradictions` 检测矛盾记忆节点（Jaccard ≥0.6） |
| adaptive recall depth | `recall --adaptive`：简单=3 结果，未知=7，复杂=12（确定性，无 LLM） |
| token-ledger | 报告 cache-hit ratio + 诚实成本估计（OpenTelemetry GenAI JSON） |
| `pack --effort-hint` | 从任务意图+图扇出推荐 thinking budget |

**关键洞察**：delta 召回 = "关键事实 + 短尾 + 指针引用"，不是全量历史。这正是 LFL 的 020"提取+摘要"方案的同构。

### 2.4 token-optimizer-mcp（零轮拒绝 + 知识图 + 因果验证）

| 机制 | 实证细节 |
|:---|:---|
| 零轮拒绝 | 拒绝携带答案（refusal carries the answer）——无需重规划，turn 成本从 1 降到 0 |
| 重读返回 diff | 重读未改文件只返回 diff——**单项最大收益** |
| 渐进式披露 | 按会话实际问题选 preview（解析输出形状：测试报告/diff/堆栈/日志/JSON），而非前 40 行 |
| 知识图 | per-project 图，节点=files/symbols/tasks/findings，边=derived_from/contains/supersedes/contradicts；**从真实 agent 流量累积**，非批量摄入 |
| prompt-cache economics | 从 transcript 测量，**按行归因定价**（"CLAUDE.md:2 有嵌入时间戳，使其后一切失效，~329K tokens/session 重写"） |
| compaction=consolidation | 按 `cost-to-rederive × irrecoverability × reuse-probability` 排序，dead ends/decisions 设下限 |
| 因果 holdout | 随机对照验证图是否真省钱，证据不足时直言"图尚未回本" |

**关键洞察**：可观测性的最高形态是**按行归因**——不仅报命中率，还指出哪一行破坏了缓存、代价多少 token。

---

## 3. 主流方案横向对比

| 能力 | pi-deepseek-cache | pi-cache-optimizer | icemage | token-optimizer-mcp | CodeArts（推断） |
|:---|:---:|:---:|:---:|:---:|:---:|
| 前缀守卫 | ✅ | ✅（重排） | ✅（cache-aware 打包） | △（靠拒绝降新增） | ❌ |
| 命中率遥测 | ✅ | ✅ | ✅ | ✅（按行归因） | ❌ |
| 确定性摘要复用 | ✅（SHA-256） | △ | ✅ | ✅ | ❌ |
| delta 召回 | ❌ | ❌ | ✅ | ✅（知识图） | ❌ |
| 代理/兼容修复 | △ | ✅ | ❌ | ✅ | ❌ |
| 因果验证 | ❌ | ❌ | ❌ | ✅ | ❌ |
| 工作历史尺寸收敛 | △ | △ | ✅（adaptive） | ✅ | ❌ |

**结论**：CodeArts 在 6 项中 0 项具备，可观测性与前缀稳定性是最大缺口。

---

## 4. 借鉴方案（可执行改进建议）

> 面向 CodeArts 平台侧（华为云码道）与 LFL 项目侧双维度。按优先级 P0/P1/P2 排序。

### P0-1：前缀守卫 + 漂移遥测（借鉴 pi-deepseek-cache P2）

- **问题**：工具结果/动态注入若进入前缀区，字节级前缀漂移，命中归零。
- **借鉴动作**：
  - 划定**稳定前缀区**（系统提示+AGENT.MD+偏好+技能清单），动态内容（时间戳/工具结果/会话概览）一律移到 user 消息区。
  - 计算每轮前缀哈希（FNV-1a，借鉴 icemage `prefix_hash`），漂移即告警。
  - 系统提示中"今日日期"等易变字段移到前缀区末尾或单独 user 段，避免破坏主体前缀。
- **验收**：连续 10 轮前缀哈希稳定率 ≥ 95%。

### P0-2：命中率遥测 + 按行归因（借鉴 pi-deepseek-cache P1 + token-optimizer-mcp）

- **问题**：CodeArts 运行时无命中率可见，命中下降无感。
- **借鉴动作**：
  - 从 provider 响应 usage 提取 `cacheRead`/`input`/`cacheWrite`，累积近 10 轮窗口命中率。
  - 经 `architecture_status` 对外暴露（LFL 已有该机制）。
  - 漂移时归因到具体注入行（借鉴 token-optimizer-mcp"CLAUDE.md:2 时间戳"式按行定位）。
- **验收**：命中率 < 80% 时产出告警 + 归因行号。

### P0-3：有效工作历史收敛 100-200K（借鉴 icemage adaptive + 主流实证）

- **问题**：1M 大历史非必需，断点风险大且摊薄效应不如小提交小新增。
- **借鉴动作**：
  - 有效工作历史默认 100-200K（按模型窗口 8% 自适应，兜底 100K，上限 200K）。
  - 运行时可调范围上限 1M→200K；存量超限配置降级 + 告警，不中断启动。
- **验收**：收敛后断点恢复 2 轮内命中率回升 ≥ 90%；总成本不增。

### P1-1：确定性摘要 + SHA-256 跨会话复用（借鉴 pi-deepseek-cache P3）

- **问题**：被动截断丢失关键事实，且摘要每会话重算。
- **借鉴动作**：
  - 压缩用确定性模型（temperature:0），摘要结果按内容 SHA-256 缓存，跨会话复用。
  - 压缩优先走"关键事实 + 推理结论 + 短尾"delta 召回（借鉴 icemage），提取不到才回退首尾截断。
- **验收**：同会话续压缩复用率 ≥ 70%；压缩后关键事实召回率 ≥ 95%。

### P1-2：delta 召回 + 指针引用（借鉴 icemage session-aware recall delta）

- **问题**：全量工具结果回灌，新增/提交占比高。
- **借鉴动作**：
  - session 内已见记忆去重时，emit `[N prior memories still apply: #ids]` 指针，不重付全文 token。
  - `recall --adaptive`：按任务复杂度调召回深度（简单=3/未知=7/复杂=12）。
- **验收**：同事实二次召回 token 成本降至指针级（< 50 token）。

### P1-3：主动压缩阈值前置（避免撞顶被动断点）

- **问题**：撞顶才压缩，压缩点即断点。
- **借鉴动作**：`compact_ratio` 前置到预算 < 1.0 附近提前整理，锚点对齐工具轮边界（防孤儿回执协议拒绝）。
- **验收**：被动撞顶压缩次数下降 ≥ 80%。

### P2-1：全链路兼容自检与修复（借鉴 pi-cache-optimizer doctor/fix）

- **问题**：前缀顺序/缓存键/代理路由/TTL 顺序任一环出错命中归零。
- **借鉴动作**：提供 `doctor`（诊断活跃模型/provider/兼容）+ `fix`（预览+确认+备份修复兼容位）。
- **验收**：已知兼容缺陷 100% 可检测、可一键修复。

### P2-2：因果 holdout 验证省钱效果（借鉴 token-optimizer-mcp）

- **问题**：优化器自报省钱不可信。
- **借鉴动作**：对 delta 召回/摘要复用做随机对照 holdout，证据不足时直言"尚未回本"。
- **验收**：省钱声明必须有 treated/holdout 证据支撑。

---

## 5. 与 LFL 既有方案的对齐

| LFL 既有 | 对应主流机制 | 对齐状态 |
|:---|:---|:---|
| `cache_guard`（7 类规则 A-G） | pi-deepseek-cache 前缀守卫 + pi-cache-optimizer 稳定前置 | 方向已对齐 ✓，需补漂移遥测 |
| 020"提取+摘要"方案 | icemage delta 召回 + pi-deepseek-cache 确定性摘要 | 同构 ✓，应提升优先级 |
| 静态化 | pi-cache-optimizer system 主体字节静态 | 方向已对齐 ✓ |
| `architecture_status` 指标暴露 | pi-cache-optimizer footer 统计 | 方向已对齐 ✓，需补命中率字段 |

**结论**：LFL 的 `cache_guard` + 020 方案 + 静态化已与主流对齐，**缺的是命中率遥测闭环与尺寸收敛**。本报告 P0-2/P0-3 正补此缺口。

---

## 6. 置信度与局限

| 结论 | 置信度 | 依据 |
|:---|:---|:---|
| Pi Coding 系靠前缀守卫+遥测+友好压缩命中 90%+ | **高** | 4 仓库 README 公开实证 |
| 主流小窗口（100-200K）命中 90%+，1M 非必需 | **中高** | README 数据 + 机制推断 |
| CodeArts 缺前缀守卫/命中率遥测/确定性摘要复用 | **中** | 运行时系统提示/工具契约推断，非源码 |
| CodeArts 当前命中率数值 | **低/未知** | 运行时不暴露，无法实测 |
| 借鉴方案可落地且与 LFL 既有对齐 | **高** | LFL 已有 cache_guard/020/静态化同构机制 |

**核心局限**：CodeArts 内部为黑盒，本报告对其缓存命中的分析基于运行时可见行为推断，**不建议把推断当事实**。落地前应在平台侧确认 CodeArts 是否使用 provider prompt caching 及当前命中率基线。

---

## 7. 建议下一步

1. **平台侧确认**：向 CodeArts 团队确认 provider prompt caching 使用情况与命中率基线（填补本报告"低置信度"项）。
2. **P0 三项优先落地**：前缀守卫 + 命中率遥测 + 尺寸收敛 100-200K（对应已生成 spec `.codeartsdoer/specs/cache_window_converge/spec.md`）。
3. **020 方案优先级提升**：delta 召回与 LFL 020"提取+摘要"同构，应作为压缩主路径。
4. **遥测先行**：先补命中率遥测，用真实命中数据校验后续优化效果，避免无刻度优化。