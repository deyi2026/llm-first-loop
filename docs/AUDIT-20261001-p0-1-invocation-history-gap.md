# P0-1 只读 Gap Audit：Model Invocation History（v1.1 承诺 vs 现有系统）

日期：2026-10-01
上游设计：`docs/DESIGN-20261001-model-invocation-history-replay-safety.md`（v1.1，§11 P0-1 定义本审计）
性质：**只读取证，0 行实现代码变更，0 次 provider/model 调用，0 次 mutation**
取证对象：当前工作区代码（行号为取证时点）+ `data/event_logs/*.jsonl` 全量 540 个 session（263,330 events）+ `data/audit/payload_trace.jsonl`（80,305 bytes，2026-09-08 最后写入）

---

## 0. 审计问题（按 v1.1 §11 P0-1 原文）

> 仅靠现在的历史数据，哪些 prepared record 字段恢复不了？chatgpt-web 路径的 transport observation 覆盖情况？

**执行摘要（两句话答案）**：

1. 现有系统已在 **API-protocol 四条路径**（openai/anthropic/google/lms-chat）上闭合"机械身份"（pcall/pattempt，write-before-send 的 opened + 响应后 settled），但 **submitted request 的可验证表示（payload digest / projected bytes / tool surface）在默认配置下完全不存在**——唯一例外是环境变量 `LLM_PAYLOAD_TRACE=1` 显式开启时的 hash-only 诊断（且不与 pattempt 关联）。
2. **chatgpt-web 与 deepseek-web 两条 Web 路径连 pcall/pattempt 身份都没有**（客户端无 `transport_observer` 属性 → `open_shadow_call_for_client` 静默返回 None）；历史日志中 pattempt 的 provider_id 分布为 `cognilocal:753 / glm:3378 / minimax:107 / deepseek:177`，**chatgpt-web、deepseek-web 均为 0**。

---

## 1. Capture-seam map（六条最终 submit boundary 的现状）

| # | 路径 | 最终 seam（代码位置） | pattempt | request 表示捕获 | 响应侧捕获 |
|---|---|---|---|---|---|
| S1 | openai 协议 | `src/llm_loop/llm/client.py` L1743-1900；payload 装配完成后 L1831 `_trace_payload_fingerprint(payload,…)`（env-gated），实际发送在 `_transport_attempt_scope`（L1858）内 `self._client.stream("POST", …, json=payload)` | ✅ 已有（scope opens before send, settles in finally） | ⚠️ 仅 env-gated hash-only（默认关闭；canonical `_h` + insertion-order `_hw`，自注"非 HTTP bytes 证明" L690-697）；写入独立 JSONL 非 EventStore，**不与 pattempt 关联**（仅 session_id/run_round/stable_prefix_fp） | ⚠️ settled 有 outcome/usage/status/rate-limits；**无 finish_reason、无 normalized response 引用、无 provider-observed model** |
| S2 | anthropic 协议 | client.py L2041-2096（OpenAI→Anthropic 转换后的 payload 在此装配） | ✅ 已有（L2096） | ❌ **连 fingerprint 调用都没有**（`_trace_payload_fingerprint` 全仓唯一调用点 L1831）；转换后 payload 只在内存中瞬时存在 | 同 S1 |
| S3 | google 协议 | client.py L2176-2209 | ✅ 已有（L2209） | ❌ 同 S2 | 同 S1 |
| S4 | lms-chat | client.py L2274-2307 | ✅ 已有（L2307） | ❌ 同 S2 | 同 S1 |
| S5 | chatgpt-web | `src/llm_loop/llm/chatgpt_web.py` `_SurfaceOwnedTransport.exchange`（L285）→ `chatgpt_transport.py` `_render_request`（渲染文本含 `_REQUEST_PREAMBLE`，模型可见、不在 request.messages） | ❌ **无**（`ChatGPTWebModelClient` 无 `transport_observer` 属性；grep 证实全仓仅 client.py 持有该属性） | ❌ 渲染文本不持久化；surface 层 telemetry 是 "bounded, **prompt-free** transport event"（`chatgpt_surface.py` L273-299，存 surface session store，非 EventStore，非 pcall 关联） | ❌ 响应从 DOM/state 提取后即归一化；原始 rendered response 不保留 |
| S6 | deepseek-web | `src/llm_loop/llm/deepseek_transport.py` `DeepSeekWebPageTransport.exchange`（L279）→ `_render_request` + ingress guard | ❌ **无**（同 S5，`transport_observer` 0 命中） | ❌ `last_prefix_diagnostics`（stable_sha256/chars/payload_chars，L277-294）**仅内存 + log 行**，不落 EventStore | ❌ DSML rendered text → LFL JSON 归一化（L379-381 自注 narrow compat path）；原始 rendered bytes 不保留 |

补充事实：

- `client.chat()`（client.py L2734）内部走 `chat_stream` 聚合 → 与 S1-S4 同 seam，无遗漏。
- fallback 换道：`core/loop/engine_services/fallback.py` L285-322 以 `ProviderAttemptKind.FALLBACK` + site_index 包装 `client.chat` → 走同 seam；**历史 attempt_kind 分布全为 `primary`（4,415/4,415）**，fallback/err1210_retry 的 pattempt 在现存日志中零样本。
- `request.attempt` 事件（spec 见 `event_log/model.py` L705-728）历史计数 **0**——异常路径 payload 字段（provider/model/generation_contract/transform）无任何留存实例可供恢复性评估。

---

## 2. 九维审计（按评审建议维度组织）

### D1 Identity（每种调用路径的 pcall/pattempt 覆盖）

打开 pcall 的生产者（`open_shadow_call_for_client` 调用点）：

| 生产者 | 位置 | purpose | 现状 |
|---|---|---|---|
| 主任务循环 | `core/loop/engine.py` L1445 | task | ✅ 历史计数 3,085 |
| SubAgent | `subagent/runner.py` L1978 | subagent | ✅ 576 |
| Learning plane | `methods/learning_plane.py` L368 | learning | ✅ 141 |
| Memory extractor | `memory/extractor.py` L247 | memory_extractor | ✅ 122 |
| Summarizer | `memory/summarize.py` L129 | summarizer | ⚠️ **历史计数 0**；且代码显式降级：coordinator 为 None 或无 session_id 时直接 `llm.chat(...)` 裸调（L117-118），无任何记录 |
| ChatGPT Web / DeepSeek Web | — | — | ❌ **无 pcall**（见 §0 结论 2） |

关键机制事实：`resources/provider_calls.py` `open_shadow_call_for_client` 在客户端不共享 journal/observer 时**静默返回 None**（fail-open，注释明示"异步漂移即静默不记录"）——这正是 Web 路径零身份的原因：不是被拒绝，是根本没进入。

字段级注意：`ProviderCallIdentity` 有 `origin_run_generation` 字段，但历史 `provider.call.opened` 事件 payload 采样**不含该字段**（采样 payload：call_id/idempotency_digest/owner_ref/execution_class/service_priority/purpose/created_at）→ 身份与 run generation 的历史关联缺失。`idempotency_key` 本身按设计永不持久（只落 24-bit digest），符合预期。

### D2 Pre-submit surface（send 前能否取得 exact projected payload）

- **S1-S4**：exact Python request 对象在 send 前已完整存在（seam 处）；问题是**没有默认的持久化钩子**。`request.meta`（engine.py L1586-1641）在 chat_stream 之前写入，含 `provider_structure_fp`（messages+tools 结构一次性 SHA256 短指纹）——但这是**结构指纹不是 payload**，且按 round 而非 attempt 键控。
- **S5/S6**：渲染文本在 `_render_request` 后存在；chatgpt-web 的 preamble 属于"模型可见但不属于 request.messages"，v1.1 §5 要求纳入 submitted_request——当前无任何持久化。
- 判定：六条路径全部 **not provider-boundary exact**（S1 有 opt-in hash，仍非内容、非关联）。

### D3 Durability timing（记录在 send 前还是后；崩溃窗口）

- `provider.transport.opened`：`resources/transport_observation.py` contextmanager **先 open 再 yield 到物理发送** → 身份层已是 write-before-send；settled 在 finally。
- `request.meta`：send 前写入，但 fail-open（engine.py L1642-1643，"快照失败 fail-open"）。
- Journal 整体是 fail-open shadow（settlement 异常不影响 transport；scope 调用点带 suppress）。
- **崩溃窗口**：opened 无 settled（进程死亡）在日志中可能存在且无 reconciliation 标记——对身份 shadow 可容忍，但 v1.1 RI-1 的 strict durability policy（P0-3 决策点）必须显式处理这个窗口，不能默认沿用 fail-open。
- `payload_trace.jsonl`：80,305 bytes，最后写入 2026-09-08 —— 说明 env 开关只在某次诊断窗口开启过，**不能当作常态覆盖**。

### D4 Representation fidelity（各协议能否获得 exact 表示）

| 表示 | 可得性 |
|---|---|
| OpenAI canonical JSON | ✅ 对象存在；`_h`（canonical, sort_keys）与 `_hw`（insertion-order）双 hash 已实现（client.py L686-699），但 env-gated |
| Anthropic 转换后 payload | ⚠️ 内存中存在，无任何 hash/持久化 |
| Google payload | ⚠️ 同上 |
| lms-chat payload | ⚠️ 同上 |
| ChatGPT rendered text（preamble+DSML） | ⚠️ `_render_request` 确定性可重算，但渲染结果本身不落盘；response 侧原始 rendered 不保留 |
| DeepSeek rendered DSML | ⚠️ 同上；且响应归一化是**有损变换**（L379-381 narrow compat），历史无法从归一化结果反推 rendered 原文 |
| HTTP wire bytes | ❌ 全部路径不承诺（`_hw` 自注已诚实声明）；v1.1 措辞"observable request"与此一致 |

### D5 Controls outside payload（改变模型行为但不进 payload 的控制项）

已记录（`runtime/causality.py` L110-123 `effective_generation_contract`）：provider/model/max_tokens/temperature/top_p/top_k/min_p/wire_protocol/send_tool_choice/reasoning_split → 落 `request.meta.generation_contract`（历史覆盖率 4,267/14,712 = 29%）。

已记录（request.meta 独立字段）：reasoning_mode/capable/control/supported/requested/effort（覆盖率 ~39%）、legacy `thinking`。

**未记录**：
- 每次调用的 `timeout_s` 覆盖（client.py L2739 PARAM-01 注释确认可按调用覆盖，无事件承载）；
- API version / base_url 路径 / 非 secret headers（org id 等）；
- Web UI 侧的模型/effort 选择器状态（chatgpt-web 的 preamble 指令是渲染产物的一部分，deepseek-web 同理——**控制项与 payload 在 Web 路径上合流，但因为 payload 不落盘而一起丢失**）；
- `origin_run_generation` 与 attempt 的关联（见 D1）。

### D6 Sensitive-content policy

- 现状：`transport_observation.py` 模块契约明文"Raw headers, response bodies, prompts, credentials, and semantic task data are never retained" → **今天根本没有 payload 留存，RS-5 的 exact/redacted_sensitive 分级完全未建**。
- `payload_trace` 用裸 SHA-256[:16]（含用户消息对象）——v1.1 RS-5 已裁决低熵敏感值禁用裸 SHA-256；若 P0-2 把 hash 提升为常态事实，必须同步换 keyed HMAC 或仅保留不可关联 metadata。
- chatgpt surface telemetry "prompt-free" 契约（chatgpt_surface.py L280）与 v1.1 兼容，可保留。
- transport credential：当前零留存（headers 从不进 journal）——符合 RS-5 第一句，P0-2 不得破坏。

### D7 Response settlement（响应事实与 pattempt 的稳定关联）

| 字段 | 现状 | 关联性 |
|---|---|---|
| outcome/status_code/usage/rate_limits/error_type | ✅ `provider.transport.settled` | ✅ 直接挂 pattempt |
| finish_reason | ❌ 无事件承载（只能从 message.appended 是否含 tool_calls **推断**，且是 round 键控） | ❌ |
| normalized response 内容 | ⚠️ `message.appended` 有完整归一化 assistant 消息（content/tool_calls/reasoning_content/metadata），另有 `llm.partial_checkpoint`（partial tails + partial_sha256 + native_state_sha256） | ❌ **round/index 键控，不与 pattempt 关联** |
| provider-observed model/fingerprint | ❌ 未捕获（各 `_stream_*` 是否读取响应中的 model 回显——**本次审计未验证**，标记为 open item） | ❌ |
| request.usage 的 cache/timing | ✅ 内容丰富（stable_prefix_fp/timing/cache_hit…） | ❌ round 键控，采样无 attempt_id/provider_call_id 字段 |

### D8 Replay isolation（R1 可复用件与禁入依赖）

可直接复用（`scripts/evidence/run_r1_replay.py` 已验证形态）：
- `_deny_network()`：非 AF_UNIX connect 机械拒绝（L36-53）；
- 零 provider/零 source-tool 调用的确定性时序回放；
- 隔离 Evidence store（BlobStore/LedgerStore/OwnerScope/EvidenceRef + capture-once 语义）；
- 冻结 manifest + SHA-256 + machine-readable report 的审计惯例。

L-R 依赖面**禁止**出现：`llm/client.py` 各 transport、`resources/provider_calls.py`（live coordination）、`core/loop/engine.py`、ToolRegistry、scheduler/dispatcher、service-control（对齐 v1.1 RS-2 capability absence）。

### D9 Historical recoverability（旧日志对 v1.1 字段的三分类）

底料规模：540 sessions / 263,330 events；其中 154 sessions 有 pattempt 事件、138 sessions 的 request.meta 含 provider_call_id。

按 v1.1 §5 字段逐一分类（历史 = 现存旧日志，不做任何重新解释）：

#### prepared record 字段

| v1.1 字段 | 历史可恢复性 | 依据 |
|---|---|---|
| logical_call_id (pcall:) | **known-equivalent**（仅 138/540 sessions）→ 其余 unavailable | request.meta.provider_call_id 3,570 条 + provider.call.opened 3,915 条 |
| provider_transport_attempt_id (pattempt:) | known-equivalent（154 sessions）/ unavailable | provider.transport.opened 4,406 条 |
| parent_attempt_id / attempt_kind / site_index / transport_retry_index | known-equivalent（同上子集） | journal payload 含全部四字段 |
| origin_run_generation | **unavailable**（call.opened 事件 payload 未含） | D1 采样 |
| session_id / event_seq | known-equivalent | EventStore 每行自带 |
| provider / requested_model | known-equivalent（transport.opened provider_id/model_id） | 采样证实 |
| wire_protocol | **transformed**（仅能从 request.meta.generation_contract 间接取，29% 覆盖且 round 键控） | D5 |
| adapter_revision | **unavailable**（runtime_snapshot 部分含进程/配置身份，但无 per-attempt 代码 revision） | D5 |
| transport_controls_ref（effort/timeout/API version/Web 控制项） | **transformed**（reasoning_* 与 generation_contract 散落 round 级；timeout/API version/Web 控制项 unavailable） | D5 |
| submitted_request.payload_ref / payload_sha256 / projected_bytes | **unavailable**（唯一近似：payload_trace 的 canonical+wire hash，但 env-gated、未与 pattempt 关联、非内容）→ 判 ambiguous 不可用 | D2/D3 |
| submitted_request.representation | transformed（可按 provider 推断，但无记录值） | D4 |
| input_segments[]（projected_payload_ref/media_type/bytes/transform） | **transformed-with-rule**：message.appended + context.compressed（58,801 条，含 evidence_ref+archive_ref+msg_seq）+ input_budget 可重建**近似**投影，但这是重建不是记录；compaction marker 可定位 | D7/R1 先例 |
| tool_surface.projected_schema_ref / registry_version | **unavailable**（registry 身份仅 runtime_snapshot 粗粒度；投影后 schema 无留存） | D2 |
| canonical_input_digest | **unavailable** | D2 |
| replay_fidelity | n/a（历史一概为 incomplete，须如实标注） | — |

#### settled record 字段

| v1.1 字段 | 历史可恢复性 |
|---|---|
| transport_outcome / usage | known-equivalent（settled 直挂 pattempt） |
| finish_reason | **transformed**（从 message.appended tool_calls 推断，round 键控） |
| normalized_response_ref | **transformed**（message.appended / llm.partial_checkpoint，round/index 键控） |
| provider_observed_model_or_fingerprint | **unavailable**（且当前代码是否读取响应 model 回显未验证） |
| settled_event_seq | known-equivalent（EventStore seq 隐含） |

#### Web 路径（chatgpt-web / deepseek-web）

历史一律 **unavailable**（无身份、无 payload、无响应原文；surface telemetry prompt-free 且不进 EventStore）。

---

## 3. 最小 P0-2 变更集合（只针对上表真实 gap；不写实现，只定范围）

按 v1.1 §11 P0-2 约束"只补齐 Provider Settlement 覆盖面，不另建 identity 系统"：

1. **[GAP-ID-1] Web 路径接入 settlement**：为 `ChatGPTWebModelClient` / DeepSeek Web client 提供 `transport_observer` 兼容入口（或在 page-transport `exchange` seam 内直开 pattempt），使 engine 现有 `open_shadow_call_for_client` 不再静默返回 None。覆盖 S5/S6 的身份层。
2. **[GAP-REQ-1] 六 seam 统一 prepared 事实**：在 S1-S4 现有 `_transport_attempt_scope` 内、S5/S6 的 exchange 内，落 v1.1 §5 最小字段：payload canonical sha256 + projected_bytes + representation 声明 + 非 secret params 快照（复用 `effective_generation_contract` + reasoning_* 合并）。默认 hash-only（RS-5）；full-content blob 仅显式 opt-in。
3. **[GAP-REQ-2] 关联补齐**：`request.usage` 增加 provider_call_id/attempt_id；`request.meta` 在 pattempt 可用时带上 attempt 级 id（现仅 provider_call_id）。这不动 seam，只补键。
4. **[GAP-RESP-1] settled 扩展**：`provider.transport.settled` 增加 finish_reason、normalized response digest（或 ref）、provider 回显 model（若响应携带且代码确实读取——先做 open item 验证）。
5. **[GAP-POL-1] hash 算法合规**：凡常态化的 payload hash 若涉及用户内容，从裸 SHA-256 迁移到 keyed HMAC 或不可关联 metadata（RS-5 裁决）；credential 永不进 journal 的现状保持。
6. **[GAP-SUM-1] Summarizer 零记录路径**：消除 `memory/summarize.py` L117-118 的静默裸调降级（至少留身份事件），否则该 producer 在历史中永久 invisible。
7. **[GAP-DUR-1] strict durability 决策输入**：P0-3 落 prepared 时必须显式裁决 opened-without-settled 窗口与 fail-open 边界（当前 shadow 的容忍策略不可默认继承为 RI-1 承诺）。

**明确不做**（无 gap 依据）：不为理论完整性重构 Session 模型；不建签名基础设施（RI-5 已收敛）；不动 `provider.structure.validated`（结构校验与内容表示职责不同，现状保留）。

---

## 4. Open items（本次审计未能闭合、P0-2 前需验证）

1. 各 `_stream_*` 是否读取响应体中的 `model` 回显字段（决定 GAP-RESP-1 的 provider_observed_model 可得性）——**未验证**。
2. `provider.call.opened` payload 不含 `origin_run_generation` 是设计遗漏还是有意省略——需对照 `provider_settlement.py` 的 `_identity_payload` 实现确认（本审计以历史事件采样为准）。
3. `request.attempt` 与 fallback/err1210 pattempt 的历史零样本：是日志轮转还是路径未触发——影响异常路径字段的风险评估基线。
4. `payload_trace.jsonl` 的 80KB 内容是否覆盖任何仍可关联的 session（run_round ↔ pattempt 对齐可行性）——未逐行核对。

（item 1/2 已于 2026-10-02 闭合，结论与更正见 §6；item 3/4 保持开放。）

## 6. 补充核验与更正（2026-10-02，P0-2 前置）

本节为 P0-1 冻结审计之后的**只读补充核验**（代码 grep + 全量事件日志重扫，0 mutation / 0 provider 调用），闭合 §4 的 open items 1、2，并更正 §2 受影响行。

### 6.1 Open item 1 闭合：`_stream_*` 不读取响应侧 model 回显

对 client.py 四条 API 流式路径与两条 Web 路径逐一核对：

| 路径 | 响应中 model 回显位置 | 代码是否读取 |
|---|---|---|
| openai | SSE chunk `chunk["model"]`（每 chunk 携带） | **否**（只读 `choices[].delta/finish_reason`、`usage`） |
| anthropic | `message_start` 事件 `evt["message"]["model"]` | **否**（handler 只读 `evt["message"]["usage"]`） |
| google | 响应 `modelVersion` | **否**（只读 `finishReason`、`candidates[].content.parts`） |
| lms-chat | SSE chunk `chunk["model"]` | **否**（openai 同型解析） |
| chatgpt-web | 归一化 envelope 允许键 `{protocol, request_id, content, tool_calls, finish_reason}`（chatgpt_web.py L490） | **结构性不存在**（Web 不回显模型身份） |
| deepseek-web | 同上（归一化有损） | **结构性不存在** |

同时确认：`finish_reason` 已被聚合进 `_StreamAcc.finish_reason`（client.py L382）并落到 `LLMResponse.finish_reason`（L565，`_finish_response`），settle 调用点可达。

**对 GAP-RESP-1 的裁决**：finish_reason = 立即可得（无需新采集）；provider_observed_model = API 三协议各有**单点新增读取**（chunk model / message_start.model / modelVersion），Web 路径**不伪造**、显式省略。

### 6.2 Open item 2 闭合：`origin_run_generation` 缺失是时序+语义正确，非设计遗漏

代码事实：

- `provider_settlement.py` `_identity_payload` 为**条件写入**（`if call.origin_run_generation:`），值来自 ContextVar `current_run_generation.get()`；
- 唯一 run 级 set-site：`core/loop/runner.py:_consume` 的 `current_run_generation.set(handle.run_generation)`，覆盖整个 `run_stream`（含模型调用）；由 commit `3a95ed468`（2026-09-14 "fence late results by run generation"）引入；
- `_call_id` 对空 run 身份有显式 "historical/offline call ids" 兼容注释——空值是**设计内可表达状态**。

全量事件重扫（`data/event_logs/*.jsonl`，按日分桶）：

| 时段 | provider.call.opened | 含 origin_run_generation |
|---|---:|---:|
| ≤2026-09-13 | 885 | 0（set-site 尚不存在） |
| ≥2026-09-15 | 3,061 | 2,818 |
| 其中 foreground_task | 2,242 | **2,242（100%）** |
| 其中 subagent | 576 | **576（100%）** |
| 其中 background_learning | 243 | 0（purpose: learning 142 + memory_extractor 101） |

**更正 §2/D9**：`origin_run_generation` 行由 "unavailable" 更正为——run 作用域调用自 **2026-09-15 起 known-equivalent（100%）**；09-14 之前 unavailable；`background_learning` 执行类**按语义正确地缺省**（后台学习/记忆提取不属于任何活跃 run）。是否为后台调用补"派生自哪个 run/session"的归属，是独立语义决策，**不进 P0-2 最小集**（对齐 DEVELOPMENT_REPAIR_SAFETY Q5：程序不做语义归属）。

### 6.3 GAP-SUM-1 根因定位（新增事实）

`factory.py` L1820 构造 `Summarizer` 时**未传** `provider_call_coordinator`（默认 None）→ `_provider_chat` 恒走裸调降级分支 → 该 producer 历史永久零身份事件。对照：`methods/learning_plane.py` L368 对 memory_extractor 传了 coordinator，产生 101 条 background_learning 事件，**机制本身已验证可用**。修复为构造点单参数补齐（见 P0-2 方案文档）。

### 6.4 GAP-SUM-1 复核更正（2026-10-02 实现阶段，§6.3 诊断被证伪）

进入 P0-2 Phase A1 实现前的锚定现状发现 §6.3 **只核对了构造点、漏看了构造后注入**，完整事实链如下：

- `factory.py` 构造后存在 `summarizer.provider_call_coordinator = provider_call_coordinator` 属性注入（RG-3C 注入块，extractor 同样接线），自 commit `4ae925599`（2026-09-10 "feat(resources): settle RG-3C provider calls"）即存在，working tree 干净（HEAD `cc05a1456`）；
- `memory/summarize.py` `_provider_chat` 的 shadow settlement 实现**完整**（open/bind/settle + `purpose=SUMMARIZER`），降级分支只在 coordinator 或 session_id 缺失时触发；
- 历史 `purpose=summarizer` settlement 事件 = 0 的真实根因：**`SUMMARY_MODE=off`**（`config.py` L570 默认值 + 当前 `.env` 生产配置）。off 模式下 `summarize()` 直接走 `_deterministic`，零 provider 调用。
- 对照组（同日全量重扫）：`purpose` 分布 task 3,122 / subagent 576 / learning 143 / memory_extractor 124 / **summarizer 0**——与"接线缺失"不符，与"功能未启用"一致。

**结论**：GAP-SUM-1 不是接线 gap，是 `SUMMARY_MODE=off` 的流量事实（机制可用、使用为零）。§3.6 建议与 P0-2 Phase A1（"factory 补一个参数"）**取消**；`purpose=summarizer` 相关验收断言改为条件式（见 P0-2 方案文档 §4 更正）。方法论教训与 DEVELOPMENT_REPAIR_SAFETY Step 1 一致：构造点缺参 ≠ 未接线，必须核属性注入与消费端。

## 5. 复现命令（audit 自身可重放）

- 事件类型分布 / provider_id 分布 / request.meta 字段覆盖率：`python3` 遍历 `data/event_logs/*.jsonl`（本审计全量 540 文件，非抽样；脚本见会话 evidence）。
- 代码事实：`grep -rn "_transport_attempt_scope|open_transport_attempt|settle_transport_attempt" src/llm_loop --include="*.py"`；`grep -n "transport_attempt|record_usage|transport_observer|settlement" src/llm_loop/llm/{chatgpt_transport,deepseek_transport}.py`（后者 0 命中即 Web gap 证据）。
- 设计字段来源：`docs/DESIGN-20261001-model-invocation-history-replay-safety.md` §5（prepared/settled schema）、§11（P0-1/P0-2 定义）、§13（验收）。

