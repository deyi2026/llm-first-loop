# DESIGN-20261001 — Model Invocation History 与 Replay Safety Boundary 设计

> 状态：**v1.1（外部评审意见经代码逐条核验后吸收，见 §15）** | 作者：LFL 会话 | 日期：2026-10-01（v1.1 同日修订）
> 性质声明：本文是**设计级方案**。v1.1 起凡引用当前代码处均已按 2026-10-01 工作区逐条核验（核验表见 §15.2）；其余内容仍为设计承诺而非代码事实。方案落地前须先做只读 invocation-level gap audit（见 §11 P0-1）。
> 关联：`docs/DEVELOPMENT_REPAIR_SAFETY.md`（六问硬门，RULE-AI-24 入口）；`docs/RECOVERABILITY-R1-RESULT-v1.md`（确定性时序 replay 既有先例：零 provider 调用、零 source 工具执行、隔离 store）；`docs/DESIGN-20260925-context-management-role-separation.md`（L1/L2/L3 注入边界与 injection_budget）。

---

## 0. 一页结论

**一句话定位**：

> LFL 不应该首先建设"可重放的 Session"，而应该先建设**"不可篡改、可验证的 Model Invocation History"**。历史认知事实与当前执行权限严格分离；Replay 首先是只读重建，不是重新执行。

| 问题 | 方案答案 |
|---|---|
| 真正要冻结的是什么 | 不是"历史上有哪些组件"，而是**某一次 provider transport attempt 在最终 transport boundary 实际提交的认知表面（observable cognitive surface）** |
| 历史记录能否恢复权限 | 永不能。**Historical authorization is evidence, never authority.** |
| Replay 如何实现 | **惰性数据读取路径**（inert read path），绝不是把历史事件重新灌进 live event bus |
| 历史的身份单位是什么 | **`ProviderTransportAttempt`（`pattempt:`）**；逻辑聚合复用 `ProviderCallIdentity`（`pcall:`）。不新造平行 identity（已存在 `src/llm_loop/resources/provider_settlement.py`） |
| 持久化时序 | **两段式**：send 前落不可变 `provider.invocation.prepared`，响应后追加 `settled`；不采用 request/output 同对象的一体化 manifest |
| 第一闭环做什么 | ① 只读 invocation-level gap audit（P0-1）；② 最小 prepared/settled 记录；③ inert `Replay Safety Boundary` |
| 什么时候扩 Session/Event Schema | 只在 gap audit 证明真实缺口后按需补，不做大一统历史 Schema 重构 |

---

## 1. 问题定义

系统需要能回答四个问题：

1. 某次 invocation，模型**实际收到了什么**（instruction、messages、tool schema、tool result 投影、compaction 影响）；
2. 哪些上下文、工具定义、工具结果**真正进入了认知表面**，顺序如何；
3. 历史记录如何被**安全地**重建（replay / inspection）；
4. 为什么历史事实**不能**恢复当前执行权限。

背景：借鉴外部（DeepSeek V4 式）"可重放会话"方向时，经一轮设计拷问发现该方向的朴素版本存在致命缺陷。本文是**收紧后的修正方案**。

## 2. 拷问暴露的四个致命问题（设计修正依据）

### 2.1 只有原料，仍无法重建"模型当时看到什么"

朴素版本假设：保存 instruction + tool schema + tool result + messages 即可重建。**错误。**

若当时存在 context compaction、截断、budget 裁剪、排序、动态 hydration、tool schema projection，那么未来用**今天的拼装逻辑**把原料重新拼一次，不等于当时模型真正收到的输入。

因此 Replay Invariant 从"所有原料都可恢复"升级为：

> **每次模型 invocation 都必须存在一个可验证的 Input Manifest，描述实际送入 provider 的有序认知表面。**

它至少要能回答：哪些 segment 被包含、顺序是什么、哪些被裁剪/摘要、使用哪个版本的 assembler/provider adapter、每项内容的 digest/ref 是什么。

否则几年后 context builder 演化了，即使历史事件全在，也会"用今天的拼装逻辑重写昨天"。

### 2.2 历史认知事实与当前执行权限必须彻底双轨

历史里记录"当时模型拥有 tool X，schema Y，用户批准了 Z"，只证明**历史事实**，绝不能在 replay 时恢复成当前 capability。否则出现最危险的副作用类别：

- 已撤销权限重新生效；
- 过期授权/token 被恢复；
- 历史 outbound permission 被误认为今天仍有效；
- 过去允许的 mutation 被 replay 再执行一次。

建立两个平面：

- **Historical Cognitive Plane**：模型当时看到了什么、当时被告知拥有什么能力。
- **Current Authority Plane**：今天实际上允许执行什么，由当前安全策略、当前授权、当前 capability 决定。

**前者永远不能提升后者。** 关键不变量直接写入设计：

> **Historical authorization is evidence, never authority.**

### 2.3 Replay 不能通过"重新发布历史事件"实现

副作用风险不只是重新调用 tool。若系统内部存在订阅者、scheduler、wake、outbound dispatcher、service lifecycle listener，把历史事件重新灌进生产 event bus 也可能再次触发动作。

所以 replay 必须是**惰性的数据读取路径**，不能等价于 event re-emission。最低规定：

- replay 事件拥有独立 namespace/run identity；
- 默认不进入 live dispatcher；
- schedule/wake/outbound/service mutation/fs mutation/network mutation 全部 deny/stub；
- 历史 ToolResult 作为 **observation 注入**，而不是通过重新执行 tool 获得。

（既有先例支持：R1 historical replay 已实现该形态——隔离 Evidence store、非 UNIX socket 网络机械拒绝、零 source 工具执行，见 `docs/RECOVERABILITY-R1-RESULT-v1.md` §Replay mechanism。）

### 2.4 "模型看到什么"不能与"模型理解/使用了什么"混为一谈

历史系统可以证明：输入里有什么、输出是什么、调用了哪个工具。但**不能可靠证明**模型内部"理解了哪条 instruction""为什么用了某个 schema"。

因此不设计"恢复模型认知状态"。能可靠恢复的是：

> **observable cognitive conditions**

而不是模型内部 cognition。该术语边界必须坚持，否则后续制造伪精确。

## 3. 设计目标与非目标

### 3.1 目标

1. 每次模型调用存在不可变、可验证的 invocation 记录，可回答"模型当时实际收到什么"；
2. 历史重建是确定性只读操作，零生产副作用；
3. 历史权限事实与当前授权平面机械隔离；
4. 工具调用、retry、并发、streaming 有稳定因果身份；
5. 存储成本可控（content-addressed 去重，不复制一切）；
6. migration 保语义可证，不靠 deserialize 成功冒充语义保持。

### 3.2 非目标（明确不做）

- 恢复模型内部思维状态 / hidden chain-of-thought；
- bit-level deterministic generation replay（模型/provider 版本会下线，服务端实现会漂移）；
- 自动执行历史副作用；
- 大一统 Session/Event Schema 一次性重构；
- 外部世界 snapshot。

## 4. 核心不变量

### 4.1 Replay Invariants（历史认知表面可重建）

**RI-1 两段式存在性与持久化时序**：每次真实 provider transport attempt 在发送前必须落一条不可变 `provider.invocation.prepared`（write-before-send），响应结束后**追加** `provider.invocation.settled` 引用同一 attempt。request 与 output 不放进同一个 immutable 对象——send 前不可能知道 output。rollout 初期允许 shadow/fail-open（与现有 `_transport_attempt_scope` 形态一致：settlement 失败不得阻断 transport）；但正式宣称 RI-1 成立前必须定义 strict durability policy，fail-open 期间不得宣称 RI-1。

**RI-2 有序性**：segment 顺序是 prepared record 的一等字段，重建不依赖任何"当时的默认排序"。

**RI-3 投影真实性与 capture seam**：保存的是**最终 provider adapter / transport submit boundary 实际提交的投影内容**或其 immutable ref，不是"可由此推导的原料"，也不是 `engine.request.meta` 时刻的中间形态（`chat_stream` 内还会发生 provider-replay 投影、孤儿 tool 对清洗、arguments 规范化、cache tagging、内部字段剥离）。工具原始返回 5 MB、模型只收到 4 KB，历史只能声称模型"看到了 4 KB"。承诺措辞限定为 *LFL 在最终 transport boundary 实际提交的 observable request*；远端 gateway/provider 内部再做什么，本地无法证明。ChatGPT Web 的 `_REQUEST_PREAMBLE` 渲染文本（模型可见、不在 `request.messages` 中）属于该 boundary 的一部分。

**RI-4 身份与拼装版本固定**：prepared record 绑定 `provider_transport_attempt_id`（`pattempt:`）与 `logical_call_id`（`pcall:`），并引用 assembler/adapter 的 immutable code/schema revision；重建不得用今天的 assembler 重解释昨天的原料。字段名统一 `provider_transport_attempt_id`，与 Tool Reachability 的 `attempt-N` 自计数严格区分（后者是 request meta 层计数，不是 transport attempt id）。

**RI-5 完整性措辞收敛**：canonical input digest 可重算比对——这提供 *immutable-by-contract + content-integrity verifiable against the recorded digest*。它**不**构成对"manifest 与 blob 一起被离线篡改后重算 hash"的密码学抵抗力（EventStore 是应用语义 append-only JSONL，无 hash chain/signature/外部 anchor）。若未来 threat model 要求，再引入受保护签名或外部 checkpoint，不为本设计新造签名基础设施。

### 4.2 Replay Safety Invariants（历史事实不升权、不触发副作用）

**RS-1 权限不升格**：historical authorization/tool exposure/user approval 只作为 evidence 存在，永远不能恢复为当前 capability（§2.2 双平面）。

**RS-2 惰性读取（capability absence 优先于 deny）**：replay 是 inert read path；禁止 event re-emission 进 live dispatcher/scheduler/wake/outbound。第一道防线是**依赖面上根本不存在能力**：L-R reconstruction library 只 import 只读 Event/Content reader，不 import ToolRegistry、provider client、scheduler、dispatcher、service-control；mutation/network deny 只是第二层 tripwire。安全不依赖调用方记得打开 `replay_mode`，也不依赖调用模型是否"听话"——最弱模型仍安全。

**RS-3 无副作用且第一阶段禁止 stub**：replay 期间 fs mutation、network mutation、service mutation、schedule/wake、outbound 机械拒绝；不伪造 stub 结果——第一阶段 L-R 根本没有产生这些效果的代码路径。

**RS-4 ToolResult 即 observation**：历史工具结果以记录值注入，永不通过重新执行工具获得。

**RS-5 两类敏感物分开**：**transport credential**（Authorization header、API key 等）永不进入历史记录；**model-visible sensitive content**（如用户消息中的敏感值——模型当时确实看到了）受 retention/access policy 管理。policy 禁止保存原文时，必须诚实标注 `replay_fidelity=redacted_sensitive`，不得继续声称 exact（与 RI-1/RI-3 的冲突就此裁决：不保存原值 ≠ exact replay）。需要敏感值 equality proof 时不使用裸 SHA-256（低熵秘密可被字典攻击），改用 keyed HMAC 或只保留不可关联 metadata。

## 5. 数据结构：两条不可变记录（v1.1 重写）

v1.0 的一体化 `ModelInvocationManifest`（request 与 output 同对象）被否决：send 前不可能知道 output，immutable 与 write-before-send 无法同时满足。v1.1 对齐现有 Provider Settlement journal 的 opened/settled 两段形态（`provider.call.opened` / `provider.transport.opened` / `provider.transport.settled` / `provider.call.settled` 事件已存在）：

```json
// provider.invocation.prepared —— 真实 send 前不可变落盘（write-before-send）
{
  "schema_version": "1.0",
  "logical_call_id": "pcall:...",                    // 复用 ProviderCallIdentity
  "provider_transport_attempt_id": "pattempt:...",   // 复用 ProviderTransportAttempt
  "parent_transport_attempt_id": "pattempt:... | null",
  "attempt_kind": "initial|retry|fallback|resend",
  "site_index": 0,
  "transport_retry_index": 0,

  "session_id": "...",
  "origin_run_generation": 3,
  "event_seq": 1204,

  "provider": "openai|anthropic|google|chatgpt-web|...",
  "requested_model": "...",                          // 请求侧模型名，≠ 可证明的远端具体版本
  "wire_protocol": "...",
  "adapter_revision": "<immutable code/schema revision>",  // 不只是可复用字符串
  "transport_controls_ref": "content://...",         // reasoning effort、API version、Web UI control 等非 secret 控制参数

  "submitted_request": {
    "representation": "canonical-json-object|rendered-text",
    "payload_ref": "content://...",
    "payload_sha256": "...",
    "projected_bytes": 84213,
    "input_segments": [
      {
        "seq": 0,
        "kind": "system|developer|user|assistant|tool_result|injection|hydration|compaction_marker",
        "projected_payload_ref": "content://...",    // v1.0 的 content_ref 泛化
        "media_type_or_schema": "text|json|provider-tool-schema|...",
        "projected_bytes": 4096,
        "source_bytes": 5242880,
        "transform": "identity|truncated|summarized|compacted|deduped",
        "transform_meta_ref": "content://..."
      }
    ],
    "tool_surface": {
      "projected_schema_ref": "content://...",       // provider 投影后的 schema 才是"实际暴露"
      "registry_version": "...",                     // 原 registry schema 降级为 provenance
      "tool_count": 12
    },
    "canonical_input_digest": "sha256:..."
  },

  "surface_index_ref": "content://...",              // 派生查询索引，不是第二 authority
  "provenance_ref": "content://...",                 // 含 compaction.hidden_msg_seqs 等诊断信息
  "replay_fidelity": "exact|redacted_sensitive|incomplete"
}

// provider.invocation.settled —— 响应后单独追加，永不回改 prepared
{
  "provider_transport_attempt_id": "pattempt:...",
  "transport_outcome": "ok|error|aborted",
  "normalized_response_ref": "content://...",
  "finish_reason": "stop|tool_calls|...",
  "usage": { "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0 },
  "provider_observed_model_or_fingerprint": "...",   // 若响应带回
  "settled_event_seq": 1299
}
```

设计要点：

- **capture seam = 最终 provider adapter / transport submit boundary**：不是 `engine.request.meta`（早于最终投影），也不是"provider 服务端视角"（不可证明）。ChatGPT Web 的 `_REQUEST_PREAMBLE` 渲染文本（模型可见、不在 `request.messages` 中）必须落入 `submitted_request`；现有 `_trace_payload_fingerprint` 的 `_hw` 自注"非 HTTP body bytes 证明"正是本节要正式解决的 gap；
- **一 attempt 一 prepared record**：同一 logical call 内的 ERR1210 payload 改写重试、fallback 换 provider、断流透明重发各自成 record；相同 payload 仍按 digest 去重；逻辑聚合交给现有 `call_id` 体系；
- **segment 泛化**：`content_ref` → `projected_payload_ref + media_type/schema`；provider-projected 后的 tool schema 才是"实际暴露"事实，registry 原始 schema 只作 provenance；
- **单一真值源**：`tool_result_projection_refs`、`compaction.hidden_msg_seqs` 一律为 derived index / provenance / diagnostic，不作为重建所必需的 authority；
- **大对象 content-addressed**：instruction、schema、blob 按 digest 去重存储；"一等事件"不等于"复制一切"；
- **projected_bytes vs source_bytes 分开**：区分投影完整与源完整（对齐 DEVELOPMENT_REPAIR_SAFETY §2.9）；
- **transform 可追溯**：每个 segment 记录从源到投影经历过的变换类别；
- **digest 是完整性锚**：canonical digest 对 submitted payload 计算，重放时可验证（完整性边界见 RI-5）；
- **requested_model 与 provider_observed_model 分开**：远端 alias 不一定等于可证明的具体模型版本。

## 6. Tool Lifecycle 语义模型（v1.1 重排）

生命周期不只有 available/unavailable。v1.0 把 `authority_allowed` 放在 `model_requested` 之前，但 invocation 级最终授权**依赖模型实际给出的 arguments**（目标路径、URL、是否 mutation、run lease 是否仍有效、用户授权是否绑定本次具体动作；`execute_command` 的 effect-authority fence 在执行时现算并拒绝 UNAUTHORIZED）。因此 authority 评估必须后移到 registry 解析之后：

```
registry_exists → session_discoverable → invocation_exposed
  → model_requested → registry_resolved → authority_evaluated
  → admitted/rejected → attempt_started → terminal → result_projected_back
```

| 状态 | 含义 | 证据载体 |
|---|---|---|
| registry_exists | 工具在注册表中存在 | registry_version |
| session_discoverable | 当前 session 可发现 | session 工具面配置 |
| invocation_exposed | 实际暴露给本次 invocation | prepared record 的 tool_surface |
| model_requested | 模型实际发起调用 | output.tool_calls |
| registry_resolved | registry 解析出本次调用对象与 arguments | 调度记录 |
| authority_evaluated → admitted/rejected | **对解析后的具体调用**现算授权 | 当前授权记录（Current Authority Plane） |
| attempt_started | attempt 开始执行 | attempt 事件 |
| terminal | timeout / error / cancel / success | attempt 终态 |
| result_projected_back | 结果投影回下一次认知表面 | prepared record 的 input_segments |

调用前确实存在的粗粒度 capability policy（如"本 session 根本不可见 mutation 类工具"）单独命名 **`preauthorized_surface`**，不与具体 invocation 的最终授权混为一谈。

**Retry 身份**：必须区分 logical call 与 attempt：

```
logical_tool_call_id   // 一次业务意图调用，跨 retry 稳定
attempt_id             // 一次物理执行尝试
invocation_id          // 发起它的模型调用（= logical_call_id 的 provider 层对应）
caused_by              // 因果父（retry、续跑、子代理委派）
sequence_no            // 单调 session 事件序
```

没有这层身份，"同一次调用重试三次"会在未来审计中被误解成"三次独立业务动作"。provider 层的对应关系：`invocation_id ↔ logical_call_id (pcall:)`，重发/换道对应 transport attempt（`pattempt:`）；见 §5。

**authority_evaluated 的位置**：它属于 Current Authority Plane，在历史记录中出现的只是"当时 authority 的记录值"——按 RS-1，该记录值在 replay 语境下是 evidence，不是 authority。

## 7. 因果结构与并发 / Streaming

**墙钟时间只能辅助，不能作为唯一 ordering truth。** 最小因果结构：

- `invocation_id` / `tool_call_id` / `attempt_id` 三级身份；
- `parent` / `caused_by` 显式因果边（子代理、retry、恢复续跑、多路并行调用）；
- 单调 `session_sequence_no`（每个持久事件一个）。

**Streaming / partial result**：保存的是**真正进入下一次模型上下文的投影**（§4.1 RI-3）。partial 事件只作过程记录，不冒充认知表面事实。

## 8. Replay 分层

| 层 | 承诺 | 允许的操作 |
|---|---|---|
| **L-R Historical Reconstruction** | 确定性 | 只读重建认知表面；digest 校验；inspection/audit |
| **L-D Decision Re-execution** | 尽力复现，**不保证同输出** | 在隔离环境重新请求模型，对比行为差异；须显式新授权 |
| **L-S Side-effect Replay** | 默认**不存在** | 仅独立 sandbox + 显式新授权时才可讨论；不是本设计交付物 |

第一阶段只实现 L-R，且其安全形态是 RS-2 的 **capability absence**（依赖面上根本不存在可调用的 provider client / ToolRegistry / scheduler），deny 规则只是第二层 tripwire。行为重放（L-D/L-S）不进入第一闭环；且任何层都不承诺 bit-for-bit deterministic generation。

## 9. 存储与安全

### 9.1 存储

- manifest 持 ref + digest；content-addressed blob store 复用/扩展 Evidence 层（evidence:// 已具备稳定 ref + SHA 校验先例）；
- 重复 instruction/schema/blob 按 digest 去重；
- retention 单独定义：ToolResult 与 instruction 的敏感级别高于普通 telemetry。

### 9.2 安全分类

- transport credential（Authorization header、API key 等）永不进入历史记录；model-visible sensitive content 按 retention/access policy 管理并如实标注 `replay_fidelity`（RS-5）；
- 派生物（manifest、摘要）权限不高于产生它的上下文（对齐 DEVELOPMENT_REPAIR_SAFETY §2.10）；
- replay 运行环境继承 R1 先例：非 UNIX socket 网络机械拒绝。

## 10. Migration 策略（隐蔽坑的对策）

**原则：旧记录不可原地重新解释；migration 生成 versioned semantic view，并保留 provenance。**

旧字段含义不确定时，**禁止**偷偷映射成新语义。每条迁移结果必须带三分类之一：

- `known-equivalent`（规则证明等价）；
- `transformed-with-rule-X`（按显式规则 X 变换）；
- `ambiguous/unknown`（不确定，保留原样 + 标注）。

**真正有价值的测试不是新 schema 能否 deserialize**，而是固定一批历史 golden fixtures，验证迁移前后这些问题的答案一致：

1. 当时模型实际看到了什么？
2. 哪些工具实际暴露？
3. 哪个 ToolResult 进入了哪次 invocation？
4. causal ordering 是否一致？
5. migration 是否凭空增加了历史 authority/identity/meaning？（第五问必须答"否"）

## 11. 工程路线（v1.1 重排：audit 前置）

v1.0 把 gap audit 排在 P0-3，与本文首行"落地前须先做 gap audit"自相矛盾，也违背"只针对真实 gap 补一等事件"（RULE-AI-24：先取证，再修复）。v1.1 修正为 audit 前置：

### P0-0：固化两组不变量
Replay Invariants（§4.1 v1.1）+ Replay Safety Invariants（§4.2 v1.1）**同时落字**。二者必须同时存在——不能先做 replay 能力、以后再补安全边界。

### P0-1：只读 invocation-level gap audit（先取证，不写实现）
对每个 wire_protocol 列出现有可复用底座与缺失字段：request.meta 结构指纹、Provider Settlement 双层身份、transport observation、OpenAI deep trace final-payload hash（`_hw`）、ChatGPT rendered-request hash——它们**尚未在同一 attempt 上闭合成 authoritative history**。问一个具体问题：**仅靠现在的历史数据，哪些 prepared record 字段恢复不了？** 同时确认 chatgpt-web 路径的 transport observation 覆盖情况（初步检索未见其接入 `_transport_attempt_scope`，待 audit 确认）。

### P0-2：依据 gap 表决定唯一 capture seam 与 identity mapping
只补齐 Provider Settlement 覆盖面（如 Web provider 的 transport observation），**不另建 identity 系统**。

### P0-3：最小 `provider.invocation.prepared`
按 §5 落最小字段集，shadow 落盘 + write-before-send；在此决策点明确 strict durability policy（何时才允许宣称 RI-1）。

### P0-4：inert L-R reconstruction
第一阶段 replay 只允许**历史重建/inspection**：零 provider 调用、零 source 工具执行、零 mutation（可验证形态对齐 R1），不恢复 capability、不把历史事件灌进 live dispatcher。行为重放先不做。

### P1-a：只针对真实 gap 补一等事件
audit 证明什么缺口（如 ToolResult↔invocation 关联丢失、schema revision 无法定位、instruction provenance 不明、producer identity 无法认证），就补什么事件。**不**为理论完整性一次性重构全部 Session 模型。

### P1-b：semantic migration golden tests
按 §10 建立 golden fixtures，测"历史问题的答案没有改变"，不是只测字段转换。

### P2：再决定行为 replay
在 L-R 的重建能力被证明之后，才评估 L-D（Decision Re-execution）是否值得做；L-S 维持默认不存在。

## 12. 可后置问题（不阻塞第一闭环）

- 是否真的需要类似 `headerSeq` 的结构；
- 全量 producer namespace 体系；
- 跨 provider 的完全统一 replay schema；
- 外部世界 snapshot；
- bit-level deterministic generation；
- 所有 Tool Lifecycle 状态全部事件化。

先证明 invocation surface 能不能恢复，再决定这些结构值不值得存在。

## 13. 验收标准

第一闭环（P0-0 ~ P0-4）完成的判据：

1. 两组不变量成文并进入实现约束（代码或守卫可引用）；
2. 新产生的每次 provider transport attempt 都落 prepared/settled 记录：对任一 attempt 可回答"LFL 在最终 transport boundary 实际提交了什么、顺序如何、经何种投影"；
3. inert replay 在隔离环境对任一 `replay_fidelity=exact` 的已记录 attempt 完成重建，canonical input digest 校验通过；其余 attempt 可证明为何不完整（redacted_sensitive / incomplete 的原因可查）；
4. replay 全程零 provider/model 调用、零 source 工具执行、零 mutation（对齐 R1 先例的可验证形态）；
5. gap audit（P0-1）产出具体字段级缺口清单，P1-a 只按清单补；
6. DEVELOPMENT_REPAIR_SAFETY 六问逐条可答（原文在哪 / 回读路径 / provider-view 事实 / runtime qualification / 程序是否越语义 / gate 验证的是候选不是旧 HEAD）。

## 14. 与既有机制的关系

| 既有机制 | 关系 |
|---|---|
| Evidence（evidence:// 稳定 ref + SHA） | content-addressed blob 的载体基础；manifest 复用其 ref/digest 惯例 |
| event_logs（data/event_logs/*.jsonl） | gap audit 的输入底料；P0-1 在其上做字段级可恢复性评估 |
| R1 historical replay（run_r1_replay.py） | inert replay 的既有工程先例：时序回放、隔离 store、零副作用网络拒绝 |
| injection L1/L2/L3 边界（DESIGN-20260925） | manifest 的 input_segments 须能表达三层注入各自的存在与投影 |
| DEVELOPMENT_REPAIR_SAFETY / RULE-AI-24 | 本设计的六问映射见 §13.6；程序保事实与边界、模型保语义的分工在此同样成立 |

---

**最终裁决句**（本设计存在的原因）：

> 先建设 immutable-by-contract、digest 可验证的 Model Invocation History；历史认知事实与当前执行权限严格分离；Replay 首先是只读重建，不是重新执行。

---

## 15. v1.1 修订记录（2026-10-01）

### 15.1 吸收的外部评审意见（9 项全部采纳）

| # | 修订要点 | 落点 |
|---|---|---|
| 1 | 历史身份绑定 `ProviderTransportAttempt`（`pattempt:`），复用 Provider Settlement，不新造平行 identity；字段统一命名 `provider_transport_attempt_id`（与 Tool Reachability `attempt-N` 区分） | RI-4 / §5 / §6 |
| 2 | capture seam 下沉到最终 provider adapter / transport submit boundary；措辞收紧为"LFL 实际提交的 observable request"；ChatGPT Web preamble 纳入 | RI-3 / §5 |
| 3 | request/output 一体化 manifest 否决，改 prepared（write-before-send）+ settled（响应后追加）两段式；strict durability policy 决策点 | RI-1 / §5 / P0-3 |
| 4 | "任何篡改可检测"收敛为 immutable-by-contract + digest verifiable；不为签名新造基础设施 | RI-5 |
| 5 | transport credential 与 model-visible sensitive content 分开；`replay_fidelity=redacted_sensitive`；低熵秘密不用裸 SHA-256 | RS-5 / §13.3 |
| 6 | L-R 安全从 deny/stub 收紧为 capability absence（依赖面无能力）；第一阶段禁止 stub | RS-2 / RS-3 / §8 |
| 7 | `authority_allowed` 后移为 `authority_evaluated`（在 registry_resolved 之后）；粗粒度策略单独命名 `preauthorized_surface` | §6 |
| 8 | `content_ref` → `projected_payload_ref + media_type/schema`；provider-projected tool schema 才是"实际暴露"；`requested_model` 与 `provider_observed_model` 分开 | §5 |
| 9 | gap audit 前置为 P0-1（修复 v1.0 与首行声明的自相矛盾） | §11 |

### 15.2 引用代码事实核验表（2026-10-01 工作区，逐条读过原文）

| 事实 | 位置 | 核验 |
|---|---|---|
| `ProviderCallIdentity` / `ProviderTransportAttempt` 双层身份（call_id / attempt_id / parent_attempt_id / attempt_kind / site_index / transport_retry_index / provider / model） | `src/llm_loop/resources/provider_settlement.py`（dataclass 定义；`open_call` 生成 `pcall:` L130 附近；`open_transport_attempt` 生成 `pattempt:` L369 附近） | ✅ 证实 |
| journal 事件已是 opened/settled 两段式（`provider.call.opened` / `provider.transport.opened` / `provider.transport.settled` / `provider.call.settled`） | 同上（`_JOURNAL_*` 事件名） | ✅ 证实 |
| Tool Reachability 的 `attempt_id` 是自计数 `attempt-N`，非 transport attempt | `src/llm_loop/core/loop/engine_services/tool_reachability.py` `bind_attempt` | ✅ 证实（评审给的路径前缀有误，见 15.3） |
| `chat_stream` 内五类投影：provider-replay 投影、孤儿 tool 对清洗、arguments 规范化、cache tagging、内部字段剥离 | `src/llm_loop/llm/client.py` L1510-1611 | ✅ 证实 |
| OpenAI 最终 payload 构造起点 `_stream_openai` | `src/llm_loop/llm/client.py` L1743 | ✅ 证实 |
| `_transport_attempt_scope` 为 fail-open shadow（settlement 失败不得阻断 transport） | `src/llm_loop/llm/client.py` L1144-1162 | ✅ 证实 |
| `_trace_payload_fingerprint` 的 `_hw` 自注"插入序敏感 JSON hash，非 HTTP bytes 证明" | `src/llm_loop/llm/client.py` L656-699 | ✅ 证实 |
| ChatGPT Web `_REQUEST_PREAMBLE`（模型可见、不在 request.messages）+ `_render_request` 渲染后发送 | `src/llm_loop/llm/chatgpt_transport.py` L26-51、L173-218 | ✅ 证实 |
| EventStore 为应用语义 append-only JSONL（flock + O_APPEND），无 hash chain / signature / 外部 anchor | `src/llm_loop/event_log/store.py` | ✅ 证实 |
| `execute_command` effect-authority fence：执行时现算授权，UNAUTHORIZED 拒绝 | `src/llm_loop/tools/builtin/execute_command.py` L329-342、L410-421 | ✅ 证实（评审路径有误，见 15.3） |
| chatgpt-web 未见接入 `_transport_attempt_scope` | `client.py` 中该符号使用点：L1858（openai）/ L2096（anthropic）/ L2209（google）/ L2307（lms-chat） | ✅ 与评审判断一致（待 P0-1 正式确认） |

### 15.3 对评审的勘误与保留意见

1. 评审两处文件路径与当前工作区不符：`tool_reachability.py` 实际在 `src/llm_loop/core/loop/engine_services/`（非 `src/llm_loop/llm/`）；`execute_command.py` 实际在 `src/llm_loop/tools/builtin/`（非 `core/tools/`）。内容判断本身正确。
2. 评审估算"保留 80-85%"与本次修订一致；但本文件不因评审而引入签名基础设施或新的 identity 系统（对齐 RI-5 与 Q5：程序不做超出 threat model 的机制扩张）。
3. 评审建议的下一步与本文件 §11 一致：**先做 P0-1 只读 gap audit，不写实现**。
