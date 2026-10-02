# P0-2 Provider Settlement 覆盖面补齐 — Seam 实现方案

Date: 2026-10-02
Status: **Phase A2 COMMITTED（2026-10-02 `3c9b0d52e`，RED→GREEN + focused + A.5 staged gate + 全量回归 6337 passed/0 failed；全量回归时预存 env-ratchet 红已由 `9af598d32` 基线补登记修复）**；A1 已证伪取消（§2 GAP-SUM-1）；**B1 COMMITTED（2026-10-02 `d005f275a`，`resources/content_digest.py`，23 单测 + ruff/pyright 0 error，含 env baseline 登记）**；**B2 COMMITTED（2026-10-02，六 seam prepared facts 落 opened 事件，8 单测 + 相邻 focused + targeted ruff/pyright + 全量回归已过，commit `feat(llm): prepared facts on transport attempts`；chatgpt_web 预存 E402/Optional gate 债已由 `bdc320843` 单独清偿）**；**B3 COMMITTED（2026-10-02，`request.usage` += `provider_call_id`/`provider_attempt_id`（空串=无绑定）；meta 先于物理发送的时序事实冻结为不新增 attempt id，见 §2 GAP-REQ-2 裁决；RED→GREEN 4 测试 + focused 140 相邻 + 全量回归已过，commit `feat(engine): attempt ids in request usage/meta`）**；**C1 IMPLEMENTED（2026-10-02，settled += finish_reason / normalized_response_hmac(+key_id) / provider_observed_model（openai 首 chunk `model` / anthropic `message_start` / google `modelVersion`；lms 与 Web 结构性省略）；shadow 路径统一 allow_create=False——观测层绝不副作用建 key，key 预置由 env 注入或既有 key 文件提供；Web `_validate_response` 移入 attempt scope 内，协议错误穿过 `__exit__` 结算为 error；RED→GREEN 10 测试 + focused 相邻 78 + targeted ruff/pyright 0 error + 全量回归 6382 passed/0 failed，commit `feat(llm): settled response facts`）**
上游：`docs/DESIGN-20261001-model-invocation-history-replay-safety.md` v1.1 §5/§11/§13
证据底料：`docs/AUDIT-20261001-p0-1-invocation-history-gap.md`（含 2026-10-02 §6 补充核验）
约束：v1.1 §11 —— 只补齐 Provider Settlement 覆盖面，**不另建 identity 系统**；RS-5 敏感内容分级；DEVELOPMENT_REPAIR_SAFETY 一个职责一个 commit。

---

## 1. 统一 seam 模型（结论：现有 Settlement 机制即正确 seam）

P0-1/§6 已证实三件套完整可用：

| 组件 | 位置 | 职责 |
|---|---|---|
| `ProviderCallSettlementJournal` | `resources/provider_settlement.py` | 逻辑调用（pcall）+ pattempt 生命周期事件 |
| `ShadowTransportRecorder` | `resources/transport_observation.py` L243+ | `transport_attempt()` contextmanager：物理发送前 open、finally settle |
| `open_shadow_call_for_client` | `resources/provider_calls.py` L84+ | 检查 `client.transport_observer.settlement_journal is journal` 后开逻辑调用 |

**判定**：不需要新 identity 系统。Web 路径 gap 的本质是 web client **没有 `transport_observer` 属性**，导致既有机制静默跳过（`getattr(...) → None`）。补齐 = 注入同一 recorder，复用全部现有生命周期。

### 六路径 seam 映射

| Seam | 路径 | 现状 | P0-2 动作 |
|---|---|---|---|
| S1 openai / S4 lms-chat | `_stream_openai` / `_stream_lms_chat` 内 `_transport_attempt_scope`（client.py L1144） | ✅ 身份已闭合 | 加 prepared/settled 事实字段 |
| S2 anthropic / S3 google | `_stream_anthropic` / `_stream_google` 内同 scope | ✅ 同上 | 同上 |
| S5 chatgpt-web | `chatgpt_transport.py` `exchange()` L88（client 无 observer） | ❌ 零身份 | 注入 recorder + exchange 内包 scope |
| S6 deepseek-web | `deepseek_transport.py` `exchange()` L279（同） | ❌ 零身份 | 同上 |

---

## 2. Per-GAP 实现方案

### GAP-ID-1 Web 路径接入 settlement（Phase A2）

- **触点**：`factory.py`（web client 构造处注入 recorder）；`llm/chatgpt_web.py` / deepseek web client 类加 `transport_observer` property；两 transport 的 `exchange()` 方法体。
- **做法**：`exchange()` 内 `with observer.transport_attempt(provider_id=..., model_id=..., transport_retry_index=0):` 包裹渲染-发送-解析全程；settle 携带 `outcome(ok|error)`、`finish_reason`（归一化 envelope 自带，chatgpt_web.py L490 允许键含之）、`representation="rendered_text"`。
- **不伪造规则**：Web 无 HTTP status/usage/model 回显 → 这些字段**省略**（`None` 不落），不得以估算填充。
- 回归：fake page transport 下断言 `provider.call.opened`/`provider.transport.opened`/`settled` 三事件成对出现。

### GAP-REQ-1 六 seam 统一 prepared 事实（Phase B2）

在 `_transport_attempt_scope`（API 四路径共用）与 Web `exchange` scope 内，扩展 attempt 记录（默认 **hash-only**）：

| 字段 | API 路径来源 | Web 路径来源 |
|---|---|---|
| payload_hmac | canonical JSON（复用 `_h` 语义，见 GAP-POL-1） | rendered text bytes（preamble+DSML 全量） |
| projected_bytes | `len(canonical_json.encode())` | `len(rendered.encode())` |
| representation | `openai-json` / `anthropic-converted` / `google-payload` / `lms-chat-json` | `chatgpt-rendered-text` / `deepseek-rendered-dsml` |
| controls | `effective_generation_contract`（causality.py L110+）+ reasoning_* + 每调用 `timeout_s` | Web 控制项（模型/effort 选择器状态，随渲染入 preamble 的事实以 flag 记录） |

- full-content blob 仅显式 opt-in（沿用现有 env-gate 模式），默认关闭。
- **不动**：`provider.structure.validated`、request.meta 现有字段（只加不减）。

### GAP-REQ-2 关联补齐（Phase B3）

- `request.usage` 事件加 `provider_call_id` / `attempt_id`（pattempt 绑定可用时）；
- `request.meta` 在已有 `provider_call_id` 基础上补 attempt 级 id（engine.py L1586-1641 区域）。
- 纯加键，不改 seam；旧日志解析不受影响（additive schema）。

#### B3 实现裁决（2026-10-02，RED→GREEN 后冻结）

- **时序事实**：`request.meta` 在物理发送**之前**发出（engine.py meta 块先于 chat/stream 调用），settlement pattempt id 在该时点结构性不存在；在 additive-only 约束下 meta **不新增** attempt 级 id（不得伪造、不得改事件时序）。meta 的既有 `provider_call_id` 保持唯一 settlement join key。
- **键名**：usage 新增键定为 `provider_call_id` + `provider_attempt_id`——meta 的 `attempt_id` 已被 reachability attempt 概念占用，统一用 `provider_attempt_id` 避免同名异义，两侧 join 语义一致。
- **空值语义**：绑定不可用（无 coordinator / 无 observer / journal 异常）时两键为 `""`（与 meta 既有 `provider_call_id: getattr(..., "call_id", "")` 空串惯例一致），不省略、不丢行、不编造。
- **只读访问器**：journal 新增 `last_attempt_id_for_call(call_id) -> str | None`（RLock 内读 `_last_attempt_id`，缓存逐出返回 None）；coordinator 新增 fail-open 包装 `last_provider_attempt_id(call) -> str`。
- **engine 落位**：join 键计算放模块级 helper `_settlement_join_ids_for_usage(call, coordinator)`（fail-open 返回 `("", "")`），轮循环内仅一次解包调用、**零新增分支复杂度**——`_run_stream_inner` 已在 pyright 复杂度阈值边缘，内联 try/except 会触发 "too complex" 并**掩盖**该函数内 26 个预存 `dict[bytes]` 推断错误（HEAD 基线 pyright exit=1 / 26 errors，B3 不新增诊断，见 commit 门记录）。
- **回归**：`tests/unit/test_request_usage_attempt_ids.py`——绑定场景断言 usage 两键 == settlement store 中 `provider.call.opened.call_id` / `provider.transport.opened.attempt_id` 且 == journal 访问器值；无绑定场景断言两键 `""`；meta 形状冻结测试（无伪造 attempt id）；settlement JSONL 纯 JSON 可解析。

### GAP-RESP-1 settled 扩展（Phase C1）

`provider.transport.settled` 新增：

1. **finish_reason**：API 路径从 `LLMResponse.finish_reason`（`_StreamAcc` L382 → L565 已聚合）在 scope 退出前写入；Web 路径取归一化 envelope。实现形态：attempt scope 暴露 `note(**fields)` 钩子，调用方在流结束、settle 前填充。
2. **normalized_response_hmac**：归一化 assistant 消息（content/tool_calls/reasoning_content）的 keyed HMAC（GAP-POL-1 同一原语），不落内容。
3. **provider_observed_model**（§6.1 裁决的单点新增读取）：
   - openai / lms-chat：首个 SSE chunk `chunk.get("model")`；
   - anthropic：`message_start` → `evt["message"].get("model")`；
   - google：`chunk.get("modelVersion")`；
   - Web 两路径：**显式省略**（结构性不存在，不伪造）。
   - 缺失即省略（本地/兼容后端可能不回显）。

### GAP-POL-1 hash 算法合规（Phase B1，先于所有常态化 hash）

- 凡含用户内容的常态化摘要（payload/rendered/response），从裸 SHA-256 迁移到 **keyed HMAC-SHA256**；key 来源与轮换策略单独 mini-design（env 注入或本地 key 文件）。
- 非内容 metadata（bytes 计数、representation id、controls 快照）不受限。
- credential 永不进 journal（现状保持，transport_observation 模块契约原文）。
- 现存 `payload_trace` 裸 SHA-256[:16] 不提升为常态事实（audit D3/D6 结论）。

#### B1 已落地：key 来源与轮换 mini-design（2026-10-02，`resources/content_digest.py`）

- **原语**：`ContentHmacKey(key_id, secret)` → `digest(bytes|str)` / `digest_json(obj)` / `verify*`；HMAC-SHA256 全长 64-hex；canonical JSON 复用 `_h` 约定（`json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()`）。
- **key 解析顺序**（纯函数，无进程缓存）：显式参数 > env 注入（`LFL_CONTENT_HMAC_SECRET` hex ≥16B + `LFL_CONTENT_HMAC_KEY_ID`，默认 key_id `env`）> 本地 key 文件 `<LFL_DATA_DIR>/keys/content_hmac.json`（`LFL_CONTENT_HMAC_KEY_FILE` 可覆盖路径；缺省自动生成一次：32B secret、`k1-` 前缀 key_id、0600、temp+`os.replace` 原子落位 + fsync——`exists()` ⇒ 内容完整，消除并发读者解析到空文件的窗口）。
- **轮换**：替换 key 文件或更换 env 对后重启进程；消费方（B2 起）在 recorder/journal 构造期持 key 实例。跨 key 摘要预期不等——`key_id` 随事实记录即为此。
- **失败语义**：损坏/缺字段/过短 secret 一律 `ContentHmacKeyError` 大声失败；fail-open 属 settlement shadow 层职责，不在原语内静默兜底。
- **合规**：secret 永不出 repr/日志；4 处字面量 env 直读已登记 env-access baseline（direct/access 137→142）。
- **门**：23 单测（确定性/独立 HMAC oracle/轮换/0600/损坏大声失败/8 线程并发单 key）+ ruff check+format + pyright 0 errors。

### GAP-SUM-1 Summarizer 身份接线（~~Phase A1~~ **已取消 — 2026-10-02 实现阶段证伪**）

- **改判**：原诊断（"factory.py L1820 构造漏传 `provider_call_coordinator`"）只核对了构造点，漏看 `4ae925599`（09-10）以来的构造后属性注入（factory RG-3C 注入块，summarizer/extractor 均接线）；`_provider_chat` 的 shadow settlement 实现完整。
- 历史 `purpose=summarizer` = 0 的真实根因是 **`SUMMARY_MODE=off`**（config 默认 + 当前 `.env`）——机制可用、流量为零，**非 gap**。证据链见 audit §6.4。
- 若未来启用 SUMMARY_MODE≠off，现有接线即产生 settlement 事件，无需代码变更；届时验收断言为：开启后的 producer 调用 100% 产生 opened/settled 对（而非"历史 0 → >0"的绝对计数）。

### GAP-DUR-1 strict durability 决策输入（无代码，P0-3 前置备忘）

- 现状 fail-open shadow（settlement 异常不影响 transport）不可默认继承为 v1.1 RI-1 承诺。
- P0-3 必须 explicit 裁决：opened-without-settled 崩溃窗口的 reconciliation（建议：启动扫描悬挂 pattempt 标记 `orphaned`，不回填 outcome）；prepared 落盘时序（write-before-send 已具备，见 audit D3）。

---

## 3. 提交顺序与门

| Phase | 内容 | commit | focused gates |
|---|---|---|---|
| ~~A1~~ | ~~GAP-SUM-1 接线~~ **已取消**（2026-10-02 证伪，audit §6.4；无代码缺口可修） | — | — |
| A2 | GAP-ID-1 Web 身份 | `feat(web): settle web transports via shadow recorder` | fake-transport 回归 + web 相邻 + journal schema snapshot |
| B1 ✅ | GAP-POL-1 HMAC 原语（2026-10-02 已实现） | `feat(resources): keyed hmac digest primitive` | 原语单测（含 key 轮换）+ ruff/pyright |
| B2 ✅ | GAP-REQ-1 prepared（2026-10-02 已实现：六 seam opened 事件携带 `prepared{payload_hmac, payload_hmac_key_id, projected_bytes, representation, controls}`；RED→GREEN 8 测试 + 旧日志 rehydrate 兼容；honest-absence 分层 fail-open） | `feat(llm): prepared facts on transport attempts` | 六路径参数化回归 + 旧日志解析兼容测试 |
| B3 ✅ | GAP-REQ-2 关联键（2026-10-02 已实现：usage += `provider_call_id`/`provider_attempt_id`，空串=无绑定；meta 时序裁决见 §2；journal/coordinator 只读访问器） | `feat(engine): attempt ids in request usage/meta` | usage/meta 快照测试 |
| C1 | GAP-RESP-1 settled | `feat(llm): settled response facts` | 三协议回显单测 + web 省略断言 |

每 Phase：staged candidate 上跑 final gate（防旧 HEAD 假绿）；不 push，阶段冻结。

## 4. 验收（对齐 v1.1 §13 + rollout 可观测断言）

rollout 后用与 audit §5 同型查询断言：

1. web provider 的 pattempt 数 > 0（历史恒 0）；
2. ~~`purpose=summarizer` 事件数 > 0（历史 0）~~ **条件式**（2026-10-02 更正，audit §6.4）：仅当 `SUMMARY_MODE≠off` 生效后适用——开启后该 producer 调用 100% 产生 opened/settled 对；`off` 期间 0 条属配置正确，非覆盖缺口；
3. settled.finish_reason 覆盖率（API 路径目标 ≥ foreground_task pattempt 的 99%）；provider_observed_model 覆盖率按协议分别统计（Web = 0 属正确）；
4. prepared payload_hmac 覆盖率 ≥ 99%（hash-only 默认开启）；
5. D9 类别迁移：新日志的 prepared/settled 字段从 unavailable → known-equivalent；旧日志分类不变（历史不做重解释）。

## 5. 明确不做（含本次核验新增）

- 不为 background_learning 补 origin run 归属（语义决策，HOLD，audit §6.2）；
- 不为 Web 路径伪造 status/usage/observed_model；
- 不重构 Session 模型、不建签名基础设施、不动 `provider.structure.validated`（audit §3 原三不做）；
- 不把 `payload_trace` 裸 SHA 提升为常态；
- 不在本阶段落 full-content blob（保持 opt-in 关闭）。
