# LFL 模型发挥阻碍审计：规则与程序必要性重审

> 日期：2026-08-31  
> 状态：**ANALYSIS ONLY — NO PRODUCTION CODE CHANGES**  
> 审查目标：不是继续给模型增加“更好的提示”，而是逐项证明每条规则、每个程序控制是否真的有必要进入模型工作面。  
> 适用原则：`resolved is retrievable, not injectable` / `available is discoverable, not necessarily injectable` / `program state is observable / retrievable, not self-injecting`。  
> 当前门禁：R8.23 strict census 后 behavior canary 仍 **BLOCKED**，R9 **NOT STARTED**。  
> 本文为当前更强原则下的上位审计；若与 `ANALYSIS-20260831-rules-procedure-review.md`、`context_health_review_2026-08-31.md` 的旧建议冲突，以本文的新必要性判定为后续设计依据，旧报告保留为历史证据，不回写。

---

## 0. 执行摘要

### 0.1 最重要的结论

LFL 当前的核心问题已经不只是“动态注入太多”，而是出现了一个更深的结构性偏差：

> **为了不让程序替 AI 思考，系统逐步把大量本应由 runtime 确定性处理的机械工作，也转嫁给了模型。**

结果是模型除了完成用户任务，还被要求：

- 每轮做自我评估、状态追踪、窗口检查；
- 管缓存命中、压缩、截断恢复；
- 自己判断程序故障、overflow、轮数耗尽；
- 做模型切换前目录查询、切换后验证；
- 写 `[[memory]]`、维护 Goal/checkpoint；
- 处理演进审批/执行/验证闭环；
- 记住 DSH / CodeArts / interop 的操作规则；
- 在工具失败后阅读程序附加的“建议下一步”；
- 在最终回答里说明调用了哪些工具。

这些行为很多曾以“AI 自主”为出发点，但**自主不等于把运行时运维工作都交给模型**。稳定 system prompt / 稳定规则即使不破坏 KV cache，也仍然会改变注意力分布、诱发额外工具调用，并让弱模型把“维护 LFL”误当成当前任务。

### 0.2 建议重新定义 LLM-first

旧表达：

> 程序是感官和手脚，不是大脑；压缩 / 重试 / 摘要 / 模型切换等决策权归 AI。

建议升级为：

> **用户和模型拥有语义决策权；程序负责确定性机械控制。**  
> 程序不得替模型决定“用户真正想要什么、证据意味着什么、结论是什么”；  
> 但程序应该自己处理不需要语义判断的事情：provider 序列化、协议配对、无副作用重试、物理窗口管理、事件/session 对账、cache 观测、输入鉴权、隔离、UI 状态、确定性错误路由。

这能同时避免两个极端：

1. **程序越权做语义判断**；
2. **程序什么都不做，把所有机械故障都变成 prompt 交给模型。**

### 0.3 本轮建议的动作分类

| 分类 | 含义 | 典型项 |
|---|---|---|
| **KEEP-HARD** | 必须由程序硬执行，不依赖模型遵守 | 安全/隐私、provider 协议、真实物理窗口、显式用户授权边界 |
| **KEEP-MINIMAL** | 可留极少量稳定模型规则 | 用户意图优先、不得编造工具结果、失败如实 |
| **MOVE-CONTROL** | 从 prompt/规则移到 runtime/control-plane | retry、overflow、round limit、cache、compression、interruption repair、runtime fault |
| **MOVE-TOOL** | 从全局规则移到具体 tool schema / typed metadata / skill | 参数说明、DSH/CodeArts、evidence URI、截断取回路径 |
| **RETRIEVAL-ONLY** | 保存但默认不进 prompt | memory、experience、Goal、digest、archive catalog、evolution history |
| **DELETE-GLOBAL** | 从全局模型规则删除 | 每轮自查、动作链强制闭环、最终回答报工具名、`[[memory]]` 强制格式、缓存纪律、长输出分段 |
| **REDESIGN** | 机制本身方向不对，不能只换措辞 | current-turn program injection、trace-leak downgrade reinjection、cache miss hard block、Cognitive enforce |

---

## 1. 必要性判定门：以后任何规则/程序先过这 6 问

新增功能不能再以“模型可能用得上”为理由进入上下文。建议以后统一使用以下门槛：

1. **这是外部硬约束吗？** 例如安全、隐私、provider wire 协议、用户明确授权、真实物理窗口。
2. **程序能否确定性处理？** 如果无需理解用户语义即可完成，就不应消耗模型注意力。
3. **它会不会给模型增加用户未要求的元任务？** 如“先自查”“先写 memory”“先看状态”“先提工具名”。
4. **它是否只是某个工具/provider/平台的局部知识？** 是则下沉到对应 schema / adapter / skill。
5. **它能否按需检索？** 能则默认不应常驻。
6. **去掉它是否真的会让当前用户任务无法正确继续？** 如果只是“可能更稳”，先证明收益再进入 prompt。

判定公式：

```text
model_prompt_required =
    exact_user_semantics
    OR unresolved_model_requested_protocol
    OR provider_required_minimum_bytes
    OR explicitly_user_authorized_active_state
```

其余默认：

```text
prompt_eligible = false
runtime_push_allowed = false
```

---

## 2. 目标架构：把“模型工作面”和“程序管理面”彻底分开

### 2.1 模型工作面应该尽量只剩

1. 稳定、极短的 system contract；
2. 当前真实用户输入；
3. 当前尚未消费的 `assistant(tool_calls) -> tool result` 协议链；
4. provider 明确要求的最小历史字段；
5. 用户明确授权恢复/继续时冻结的一小段当前任务身份；
6. 模型自己主动请求得到的事实性工具结果。

### 2.2 Control-plane 自己处理

- 输入来源鉴权；
- stop / cancel / interruption；
- event/session 修复；
- cache 统计；
- 物理 context window 管理；
- archive / compaction；
- provider serialization；
- side-effect-safe 的 bounded retry；
- fallback availability / capability gate；
- round / timeout / cost hard limits；
- runtime faults；
- scheduler / evolution / pending review / health / observability；
- UI/status/event/audit。

这些状态可以**被模型主动查询**，但不能因为“发生了”就自动变成模型的新任务。

### 2.3 Retrieval plane 保存但不广播

- memory；
- experience；
- historical decisions；
- Goal/checkpoint history；
- archive/digest/evidence catalogs；
- completed tool spans；
- old reasoning；
- evolution/self-eval history。

### 2.4 Tool / Skill 局部承载操作知识

- tool 参数；
- failure class；
- ref 如何读取；
- DSH / CodeArts / Feishu / browser 的使用方法；
- 文件/网页/证据取回策略。

模型只有真正调用/发现该能力时才看到，不再由全局规则预加载。

---

## 3. P0：当前方向明确不合适，应优先删除/改造

## P0-1 RUN-INJECTION-00 尚未真正落实：current-turn 仍被当成 prompt 权限

**现状**

`core/prompt_eligibility.py` 仍允许：

- `program_recovery`
- `memory`
- `tip`
- `task_active`

作为动态 producer；`prompt_lifecycle=current_turn` + 匹配 `turn_ref` 仍可直接放行程序消息。

R8.23 已实证重新打开：E07/E08/E12/E15/E16/E17/E18。

**问题**

“同一 human turn”只能证明生命周期，不能证明当前模型需要这段语义。把 current-turn 当授权，会让程序在工具轮之间不断改变模型的问题空间。

**建议**

- `current_turn` 降级为纯生命周期 metadata，不再是 prompt grant；
- 删除 fresh `program_recovery` / `memory` / `tip` 自动权限；
- E15/E16/E17/E18 全部迁移 control-plane；
- `task_active` 也重新审，不因历史上已收窄就默认保留（见 P1-7）。

**结论：REDESIGN。**

证据：`src/llm_loop/core/prompt_eligibility.py:20-26,68-151`；`docs/injection-governance/eligibility/r823-report.md`。

---

## P0-2 工具结果夹带程序建议：允许来源被污染

**现状**

`tool_result_to_message()` 在真实工具结果后自动追加：

- generic `_FAILURE_GUIDANCE`；
- `ToolRecoveryAdvice.render()` 的 `[恢复策略] ... next=...`；
- `guidance_extra` 经验建议。

长结果 `_DISTILL_GUIDANCE` 还要求模型：

- “继续推理前先提炼”；
- 写入推理链或 `[[memory]]`；
- 用 `search_archive` 再取回；
- 不得如何声明。

这与 RUN-INJECTION-00 已定义的边界冲突：**model-requested tool result 是合法新语义，只因为它是工具真实回执；工具回执本身应保持事实性，不夹带程序意见。**

**建议**

模型可见 tool result 仅保留：

```text
status
actual output / actual error
complete=true|false
objective failure_class / retryable（如确为客观属性）
ref（仅在内容不完整且需要恢复时）
```

删除：

- “建议”“可选项”“请先”“推荐 next tool”；
- 强制写 memory；
- 强制重试/换工具；
- 经验性下一步。

typed recovery 分类本身可保留在 metadata/control-plane。若恢复动作完全确定且无副作用，可由 runtime 执行；否则让模型基于事实自行判断。

**结论：MOVE-CONTROL + FACTUALIZE。**

证据：`src/llm_loop/tools/registry.py:874-881,1186-1245`；`src/llm_loop/tools/recovery.py:18-31`。

---

## P0-3 Evidence capsule 已成为显著上下文税

**现状**

Evidence projection 会在 tool result 正文后追加：

```text
[evidence]
ref=...
source=...
coverage=...
projection=...
complete=...
recover=read_evidence
[/evidence]
```

只读 corpus census：

- 1,638 条模型可见 evidence capsule；
- 24 个 session；
- capsule 本体约 **411,575 chars**；
- 平均约 **251 chars / 条**；
- 约占这些含 capsule 工具消息总字符 **16.87%**；
- `complete=false` 104 条。

**问题**

大多数 capsule 是程序元数据，而不是完成当前任务必需的语义。尤其完整结果 `complete=true` 时，模型几乎没有必要知道 source/coverage/projection/recover 全套字段。

**建议**

- `complete=true`：capsule 从 model content 消失，完整 metadata 只落审计；
- `complete=false`：模型正文最多留下一个稳定、短的事实行，例如 `result_truncated=true; ref=evidence://...`；
- recovery path 由 tool schema / `get_tool_schema` / ref resolver 负责，不在每条回执重复教学；
- projection/capture failure 不能再在 tool result 写 “Do not automatically re-run...” 这类程序指令。

**结论：默认 MOVE-METADATA。**

证据：`src/llm_loop/memory/evidence.py:993-1017`；`src/llm_loop/tools/evidence_enforce.py:74-115`。

---

## P0-4 Cache 优化曾直接阻止模型工作：边界错误

**现状**

`cache_guard` Rule F 可在提交字符数 > history budget 95% 时 BLOCK，请求理由不是 provider 物理窗口失败，而是：

> “压缩在即——本次请求注定低命中全价”

只读 `guarded_requests.jsonl` census：

- 9,897 个 request guard 记录；
- ALLOW 9,809；WARN 48；BLOCK 40；
- 其中 **25 次 BLOCK = submit_ratio**；
- 另外 15 次 BLOCK = privacy leak。

`_breaker_pressure_block()` 也会在 compression breaker active 时因内部 history budget 水位直接终止 run，并要求 checkpoint/换会话。

**问题**

缓存命中率/是否全价是**性能与成本优化信息**，不是语义正确性的硬边界。只要请求在真实 provider window、用户成本策略和安全范围内，就不应该因为“缓存可能不好”禁止模型回答。

**建议**

保留硬 BLOCK：

- privacy / secret leakage；
- disaster safety；
- provider wire invalid；
- 真实 context window 超限；
- 用户明确成本/额度硬限。

降级为 observability / optimizer：

- hit rate；
- submit_ratio 相对内部 history budget；
- system stability cache warning；
- compression-storm cache quality。

程序可自动选择更缓存友好的等价表示，但**不能为了 cache quality 阻止语义请求**。

**结论：DELETE PERFORMANCE BLOCK；KEEP SECURITY BLOCK。**

证据：`src/llm_loop/cache_guard/guard.py:36-77,197-251,465-657`；`src/llm_loop/core/loop/build.py:455-507`。

---

## P0-5 agent_trace_leak：检测到泄漏后“换标签继续喂”方向错误

> 注：本项检查的是当前**未提交工作树**中的 agent_trace_leak 实现，不把它当 HEAD 已固定行为。

**现状 A：default observe 不阻断**

`LFL_LEAK_GUARD_MODE` 默认 `observe`：无白名单 ingress token 的 `role=user` 写入仍 ALLOW，只记录 overreach。

机械复现：

```text
mode=observe
guard=allow
metadata={origin_layer:user_instruction, program_origin:false}
finding=observe_event_only
would_drop=False
```

因此 #280/#290 同型“内部 agent 轨迹伪装人类 user”在默认态仍可进入历史。

**现状 B：mislabel 被重新注入**

build α hook 对确定 mislabel：

1. 从 base user history 剔除；
2. 将原文包装为 `REFERENCE` appendix；
3. 在中央 dynamic allowlist 完成过滤**之后**再把 `leak_downgrade` append 回 `_inject_parts`。

等价于：

> “确认这是污染 → 改标签 → 仍然发给模型。”

**建议**

- 可疑/越权内容：quarantine + event + UI，**provider chars=0**；
- 明确 mislabel 的程序内容不能通过 REFERENCE 身份重获语义权限；
- Web/CLI/Feishu/API 等所有真实人类入口完成 token 签发后，default 切 fail-closed；
- `leak_downgrade` 不进入 prompt producer allowlist；
- 如果无法证明是用户输入，宁可拒绝/等待用户确认，也不要把内容“降级注入”。

**结论：REDESIGN，不建议以当前 default observe 版本作为根治 fixed-point。**

证据：`src/llm_loop/core/trace_leak/user_ingress_guard.py:33-157`；当前工作树 `src/llm_loop/core/loop/build.py:664-726,1368-1397`。

---

## P0-6 E12/E15/E16/E17/E18：运行时故障不应成为模型新指令

R8.23 已完整证明：

- E12 err1210 “programmatic user resend”；
- E15 stagnation reminder；
- E16 empty-search reminder；
- E17 overflow feedback + continue；
- E18 round exhaustion decision + extra LLM round。

**建议**

- err1210：runtime 自己 rebuild/retry once（若无副作用且协议安全）；
- stagnation：程序只维护计数与成本边界；不要发提醒；
- exact duplicate suppression：只能用于**可证明确定性/幂等且外部状态未变化**的工具，不能全局“同参第二次必拦”，因为轮询/实时查询可能合法重复；
- empty search：真实空结果本身已经是事实；不加第二层建议；
- overflow：runtime compact/route/end，UI 显示；不让模型读 overflow 教程；
- max rounds：到硬边界就结束/暂停，等待用户继续；不要花第 N+1 轮问模型“是否继续”。

**结论：MOVE-CONTROL。**

证据：`docs/injection-governance/eligibility/r823-report.md`；`src/llm_loop/core/loop/tool_exec.py`、`overflow.py`、`engine.py`。

---

## P0-7 E07 自动 memory：相关 ≠ 必需

R8.23 corpus：**389 memory_snapshot / 417,908 chars / 44 sessions**。

即使 R8.22 已把 decision/convention 改 recall-only，当前 turn 仍会自动检索 fact/procedure 并以 `role=user` 投影。

**建议**

- memory 默认 `RETRIEVABLE_ONLY`；
- 用户显式说“按我之前的 X”“你记得 Y 吗”→ input-side retrieval；
- 模型主动需要历史 → 调 `search_records(kind=memory)`；
- 不再用 current turn/semantic similarity 作为自动 prompt grant；
- 不把 memory 嵌入 Cognitive packet 作为旁路。

**结论：DELETE AUTO MEMORY。**

---

## 4. P1：规则层本身正在限制模型发挥，应大幅瘦身

## P1-1 `docs/ai_rules.lite.md` 不应继续作为“通用模型执行规则”

当前：

- `_BASE_PROMPT` 约 **765 chars**；
- `ai_rules.lite.md` 约 **3,148 chars / 38 行**；
- full `ai_rules.md` 约 **22,018 chars / 444 行**；
- system prompt 又要求“任务开始或规则存疑时 read_file(full=true) 读取 lite”。

因此系统本身虽然已做短前缀，却又用“任务开始必读”把大量元规则按工具调用重新搬回模型工作面。

**建议**

1. 删除“任务开始必读”；
2. `ai_rules.lite` 从“模型执行视图”改成**按需 Agent/维护 playbook**；
3. system prompt 只保留极少稳定原则；
4. 特定 workflow 需要规则时由 skill/tool 注入局部说明，而不是所有任务共用。

**结论：DELETE MANDATORY READ；RECLASSIFY RULE FILE。**

证据：`src/llm_loop/core/prompt.py:1-41`；`docs/ai_rules.lite.md`。

---

## P1-2 RULE-AI-00 需要重写：区分“语义决策”与“机械控制”

当前 RULE-AI-00 把压缩、重试、摘要、模型切换等整体写成“决策权归 AI”。这会逼模型管理很多它不该管理的 runtime 细节。

建议新定义：

### 用户/模型负责

- 用户真正想要什么；
- 证据怎样解释；
- 当前结论；
- 语义策略/研究路径；
- 是否接受一个会改变任务语义的替代方案；
- 需要用户授权的高影响动作。

### 程序负责

- provider wire 适配；
- tool call pairing；
- 无副作用 bounded retry；
- context window 物理适配；
- lossless archive；
- interruption reconcile；
- timeout/round/cost limit；
- input provenance；
- observability；
- 语义等价的 fallback / route（受 capability floor 与用户模型选择约束）。

**关键修正**：程序“不替 AI 思考”，不等于程序“不能做任何决定”。确定性控制如果还要变成 prompt 交给模型，本身就是额外干扰。

---

## P1-3 方法层 ①~⑥ 不应是全局硬规则

`ai_rules.lite` 当前要求：

- 每轮显式状态追踪；
- 动作前自问；
- 假设先行；
- 增量推理；
- 关键结论即时写 memory；
- 工具轮思考链“三句”。

这些可能是有用的**方法建议**，但它们是任务风格，不是系统不变量。不同模型自身已有更适合的推理策略；强制统一思考格式会限制能力，弱模型则可能把格式执行本身当任务。

**建议**

- 从 universal system/runtime rule 删除；
- 长期软件工程/研究任务可放入对应 skill/playbook；
- 不要求模型暴露/格式化 reasoning；
- 只以外部结果衡量：正确性、任务完成率、重复动作率。

**结论：MOVE-SKILL / DELETE-GLOBAL。**

---

## P1-4 Rule 5 强制 `[[memory]]`：删除

**问题**

- 污染用户最终回答；
- 让模型额外判断“什么值得记”；
- 与现有独立 memory extractor 重复；
- R8.22 已证明历史 decision/convention 自动注入本身就是污染源。

**建议**

- 默认答案不含内部 memory 协议；
- 用户显式要求记住时走明确 memory 工具/控制面；
- 自动提取如保留，只作为后台存储候选，不获得未来 prompt 权限。

**结论：DELETE-GLOBAL。**

---

## P1-5 Rule 6/10：自评、演进、pending review 不应占普通用户任务

当前规则要求模型定期/每轮关注：

- self_evaluate；
- executing evolution；
- pending_review；
- context window；
- reasoning state；
- completion registration。

真实事件日志解析到的 tool call 规模（仅说明这些工具确实被使用，不把全部调用归因于规则）：

- `architecture_status`: 333 calls / 82 sessions；
- `submit_evolution`: 59 / 22；
- `evolution_complete`: 32 / 12；
- `checkpoint_goal`: 72 / 18；
- `self_evaluate`: 12 / 6。

**建议**

- 普通 user run 不承担系统维护；
- evolution/self-eval 进入独立 maintenance run / operator UI / explicit command；
- pending review 只 UI/status；
- 不再“每轮自主检查”。

**结论：MOVE-MAINTENANCE。**

---

## P1-6 Rule 8 “动作链完整 + 回答必须提工具名”：删除

这是典型为了评测可观测性反向污染模型行为的规则。

问题：

- 自查发现异常就“默认应立即 adjust_strategy”可能是错误策略；
- 强制回答里说明工具名破坏自然表达；
- tool trace / audit 已经能证明用了什么工具，不需要用户回答重复一遍；
- 容易诱发“为了闭环而行动”，而非“为了用户目标而行动”。

**建议**

- 将 `tool_used / chain_complete` 留在 offline evaluation；
- 不把 evaluator rubric 当 production prompt；
- 用户回答只说明真正影响结果的动作。

**结论：DELETE-GLOBAL，保留 OFFLINE METRIC。**

---

## P1-7 `task_active`：从自动 active-state 再收紧为“用户授权继续”

R8.16 已把 full task frontier 缩成唯一 in_progress 的 `goal_id + task_id + title`，这是正确减法，但在最新原则下仍需再问：

> 一个 Goal 恰好有唯一 in_progress，是否就有资格改变用户新一轮输入的上下文？

答案应为：**否。**

建议：

- 用户明确“继续/接着/恢复上次任务”时，由 input-side resolver 授权一次；
- 本 run 内冻结该 task identity，不动态变化；
- 普通新问题不自动读取 Goal；
- Goal 只作为 retrievable state；
- ambiguous state 继续零注入。

**结论：从 ACTIVE_STATE 改 USER_AUTHORIZED_STATE。**

---

## P1-8 Rule 9 模型切换操作手册：下沉 runtime/tool

当前要求：

- switch 前必须 `model_catalog`；
- 必须 reason；
- switch 后必须 `architecture_status` 验证。

这些步骤在很多场景只是程序可验证的机械事务。

**建议**

- `switch_model` 自己做目标存在性/能力/状态验证并返回事实；
- user 显式选定的模型失败继续保持 strict；
- default fallback 可程序自动处理，但必须有 capability floor；
- 不要求模型额外查询一次目录和再验证一次状态；
- fallback 结果走 UI/status/audit，不生成下一轮 prompt notice。

**结论：MOVE-TOOL/CONTROL。**

---

## P1-9 Rule 11 截断 SOP：大部分下沉工具层

当前模型需背：

- 三种截断来源；
- 三套路径；
- search_archive 长短 query 策略；
- `head/tail/grep -m` 禁令；
- 未命中后的 SOP。

**问题**

这是实现细节，不是语义规则。尤其“查询不要用 head/tail”不是普遍真理：用户明确只要日志尾部时 `tail -n` 完全合理。

**建议**

工具回执事实化：

```text
complete=false
omitted=true
recovery_ref=<exact handle>
```

ref resolver 负责正确路由，不要求模型先分类“这是哪一种截断”。

**结论：MOVE-TOOL；删除 blanket 禁令。**

---

## P1-10 Rule 13/14/15/17/18/19/20/21：不应是全局常驻知识

### Rule 13 DSH / Rule 15 CodeArts

是 tool/skill 使用说明，移到 schema/skill。

### Rule 14 interop

旧“自动注入”语义已被 R8.13 取消；规则文本已陈旧，应删除/重写为 explicit user accept/retrieval。

### Rule 17 长内容分段

这是 transport/UI 的职责。模型不应每篇长文都机械 `1/N + 继续/跳过/总结`。

### Rule 18 经验前置注入

与 R8.15 “experience on-demand” 正面冲突。特别是“调工具前先查经验”和“程序自动检索经验再末尾注入”应删除。

### Rule 19 中断恢复

R8.19 已改为 program-side reconcile，模型不应再读 event log 恢复自己。

### Rule 20 Goal/checkpoint

Goal 机制本身有价值，但它属于 agent/harness workflow，不是所有 LLM 用户请求的通用思考规则。checkpoint 纪律应由 orchestration 层/skill 管理。

### Rule 21 程序反馈语义

这是“告诉模型忽略程序垃圾”的过渡补丁。目标态应是程序垃圾根本不进 provider history；完成迁移后删除该规则。

**结论：MOVE / DELETE-GLOBAL。**

---

## 5. P1：程序机制需要重审，不应因为历史投入而保留

## P1-11 Cognitive Runtime enforce：当前设计不适合推广

当前 Cognitive path 可以：

- 从 GoalStore 重建 SemanticTaskState；
- 投影 objective/checkpoint/hard_constraints；
- 将 memory snapshot 加进 packet；
- enforce 下生成 decision packet/header；
- session allowlist 可将 shadow 提升到 enforce。

这本质上是一条 program-owned semantic channel。

**建议**

- 当前阶段只保留 `off/shadow` 做测量；
- 禁止 allowlist 自动 promote 到 model-visible enforce；
- 如果未来恢复：必须有显式 user-authorized continuation；
- 不允许 current memory 自动进入 packet；
- 不允许 quiet/header-only 注入；
- 只允许一条 canonical current-task channel，不和 `task_active` / compact anchor 并存。

**结论：FREEZE ENFORCE，重新设计授权模型。**

证据：`src/llm_loop/core/loop/build.py:1428-1775`。

---

## P1-12 Compression：保留“物理管理”，删除“让模型管理压缩”的规则

压缩本身不是坏事。真正错误的是两种极端：

1. 程序静默丢信息；
2. 程序把“什么时候压缩、缓存怎么样、接下来怎么办”都变成自然语言问模型。

建议：

- 保留 lossless archive；
- 程序按真实 provider window 与用户 cost policy 做确定性 compaction；
- 当前 unresolved protocol/active user evidence 不得被裁断；
- compact occurrence 只 telemetry；
- 模型需要旧内容时主动 retrieval；
- 不再要求模型日常关注 history_budget/cache window。

`context.compressed` 当前 corpus 有 55,672 条事件，但代码确认是**每个被归档 message 一条事件**，不能误解为 55,672 次压缩轮。这个数字只说明 archive/event 量很大，不单独作为“压缩风暴次数”证据。

**结论：KEEP MECHANICS，REMOVE META WORK。**

---

## P1-13 固定 history budget 不应成为智能硬上限

当前 provider 配置中可见：

- local / cognilocal 约 30K chars；
- deepseek / glm 约 300K；
- minimax 约 400K。

预算对性能有意义，但在 resolved/tool-span/memory/catalog 清理后，不应再靠过度裁剪解决结构污染。

建议：

- budget = optimizer，不是 semantic correctness boundary；
- 当前 unresolved evidence 放不下时允许按实际 provider window 自适应扩展；
- 真正硬限只来自 provider window、用户成本政策、安全/产品限额；
- 先消除无资格内容，再谈预算收紧。

---

## P1-14 Fallback：可以程序自动，但不能牺牲能力等级

R8.21 已修好跨 provider fallback 重新 build request，这是必要的协议修复。

还需增加：

- capability floor；
- task compatibility；
- user explicit model override strict；
- side-effect / tool capability compatibility；
- 不因“有一个可用小模型”就继续复杂长任务。

自动 fallback 是 availability control，不必再通过 prompt 让模型管理；但程序的选择必须保证**语义能力不降到任务无法完成的等级**。

---

## 6. P2：可以保留，但需要 A/B 证明必要性

## P2-1 CORE9 仍可能偏大，但不要盲删

R8.7 已从 61 tools / 22,699 lazy chars 收到 CORE9 / 3,425 raw chars，这是明显改善。

当前 CORE：

```text
edit_file
execute_command
get_tool_schema
read_file
search_files
search_records
skill_list
skill_load
web_search
```

进一步可实验：

- universal core 是否只需 `get_tool_schema` + 最少 I/O；
- edit/web/skill/search 是否按 user task intent 加载；
- 缩减后 capability discovery 成功率是否下降。

不能只看 token 下降，必须 A/B：任务完成率、错误工具率、发现工具耗时、重复 schema lookup。

**结论：EXPERIMENT，不立刻删除。**

证据：`src/llm_loop/tools/eligibility.py:17-27`；R8.7 report。

---

## P2-2 `PROGRAM_FINAL_PROTOCOL_BOUNDARY` 应只保留协议形状，不保留语义标签

当前历史 program final 会被替换为：

```text
[程序终止边界·无模型回答]
```

这是为避免 `user -> program-assistant -> user` 删除后造成 provider role shape 问题，机制目的合理。

建议：

- 保留 role-shape 兼容；
- 如果 provider 允许，使用最小 neutral placeholder / provider-specific serialization；
- 不让模型从中文标签推断新的任务含义；
- 分类为 `PROTOCOL_ONLY`，不能成为语义规则。

**结论：KEEP SHAPE，MINIMIZE CONTENT。**

证据：`src/llm_loop/core/loop/build.py:742-772`。

---

## P2-3 `TOOL_ROUND_ZERO_HISTORY` 只应是实验性性能模式

该模式会把 local 工具轮缩到：

```text
current user + latest assistant(tool_calls) + tool receipts
```

它可以极大降低 prefill，但也可能让模型失去当前任务中尚未结构化的中间事实。

建议：

- 默认 off；
- 不因 cache/latency 指标自动开启；
- 只有 task-quality A/B 证明不降低 objective fidelity / tool-repeat / completion 才能推广；
- 不用 program task-anchor prose 补偿被删语义。

**结论：KEEP EXPERIMENTAL ONLY。**

证据：`src/llm_loop/core/loop/build.py:204-244`；`core/loop/engine.py` TOOL_ROUND_ZERO_HISTORY 接线。

---

## P2-4 `SYSTEM_PROMPT_EXTRA` 是潜在绕过通道

当前可以通过 env 任意给 stable system prompt 追加文本。它不是 run-time push，但会：

- 绕过 rule SoT；
- 引入不可见行为差异；
- 改变缓存前缀；
- 让线上实例难以比较。

建议二选一：

1. 删除通用 free-text escape hatch；或
2. 只接受 operator-owned、版本化、带 provenance/hash/大小上限的静态 policy bundle。

当前检查环境未发现已设置 `SYSTEM_PROMPT_EXTRA`，所以是治理 hardening，不是 fresh blocker。

---

## 7. 现有规则逐项建议表

| 规则 | 当前主题 | 建议 | 去向 |
|---|---|---|---|
| 方法层①~⑥ | 思考方式/记忆/CoT格式 | **移出全局** | long-task/research skill |
| 1 | 诚实自查 | **保留最小原则** | base system |
| 2 | 工具参数 | **删除全局** | schema/validator |
| 3 | 停滞调整 | **删除提醒；机械防护重写** | control-plane |
| 4 | 程序故障 | **删除** | UI/status/event |
| 5 | `[[memory]]` | **删除** | explicit memory/control |
| 6 | 演进/自评 | **移出普通run** | maintenance mode/UI |
| 7 | 工具优先 | **保留一句“不编造不可见事实”** | base system |
| 8 | 动作链/提工具名 | **删除** | offline eval only |
| 9 | 模型切换 | **下沉** | switch_model/runtime |
| 10 | 每轮自查 | **删除** | maintenance/orchestrator |
| 11 | 截断/轮次SOP | **大部分删除** | tool/control-plane |
| 12 | 身份声明 | **按问题触发** | task-routed model_catalog |
| 13 | DSH | **删除全局** | tool schema/skill |
| 14 | interop | **删除旧自动注入语义** | UI/retrieval/user accept |
| 15 | CodeArts | **删除全局** | tool schema/skill |
| 16 | cache | **删除** | runtime telemetry |
| 17 | 长内容分段 | **删除** | transport/UI |
| 18 | 经验前置 | **删除自动/强制部分** | on-demand retrieval |
| 19 | 中断恢复 | **删除模型职责** | runtime reconcile |
| 20 | Goal/checkpoint | **移出 universal LLM rule** | agent harness/skill |
| 21 | 程序反馈语义 | **过渡期保留说明，目标删除** | provider filter/protocol |

---

## 8. 应明确保留的硬边界：不要矫枉过正

这轮目标是释放模型，不是取消所有程序约束。

### 8.1 KEEP-HARD

1. **灾难性安全**：破坏性生产动作、危险命令、审批。
2. **隐私/凭据防泄漏**：cache/prompt guard 的 privacy block。
3. **provider 协议**：tool_call_id、tool declaration/receipt pairing、provider-required reasoning serialization。
4. **真实物理限制**：provider context window、最大输出、用户明确的成本/时限策略。
5. **输入来源真实性**：人类 user provenance / ingress authorization。
6. **显式用户模型选择**：不能静默背离。
7. **数据持久性**：不能静默丢数据；但“永远不得删除/修改”应改成授权/事务/备份边界，允许用户明确要求的合法数据操作。

### 8.2 KEEP-MINIMAL MODEL CONTRACT

模型真正需要长期知道的内容建议压到几条：

```text
1. 当前用户输入是当前任务的最高语义来源。
2. 不编造你无法直接知道的文件/工具/实时事实；需要时取真实工具结果。
3. 工具/程序失败如实说明，不把失败当成功。
4. 不越过安全/授权边界。
```

provider-specific wire 规则不再让模型“记住”，由 adapter 保证。

---

## 9. system prompt 建议目标态

当前 `_BASE_PROMPT` 已经很短，这是应该保留的方向；要删除的是其中不属于模型语义职责的部分以及“任务开始必读规则”。

建议目标不是继续加规则，而是保持一个**不需要二次读文档才能工作**的自足最小 contract。

### 应删/迁移

- “任务开始 read ai_rules.lite”；
- provider-specific reasoning_content 约束 → provider adapter；
- blanket “数据不删除不修改” → authorization/storage layer；
- universal “失败调整后重试一次” → typed deterministic recovery；
- `[[memory]]` 信息通道提示；
- cache/Goal/evolution/DSH 等任何维护型规则。

### 应保留

- user-first；
- truthful tool evidence；
- no fabrication；
- safety/authorization；
- archive/search capability可以仅在工具 discovery 中体现，不必每个任务教育一遍。

---

## 10. 程序控制的新边界：何时程序应该“替模型做”

为了避免旧 RULE-AI-00 的误解，建议建立一个明确机械判定：

### 程序可直接做，且不需要 prompt 通知

- 同 provider request 的安全序列化；
- event/session 确定性 repair；
- 无副作用、明确 transient 的有限 retry；
- 已知虚拟 ref 的 deterministic resolver；
- lossless archive / physical compaction；
- cache warm/cold telemetry；
- quota/timeout/round hard stop；
- fallback 到**等价能力等级且不背离用户选择**的 provider；
- UI/status/event 的运行时反馈。

### 程序不能替模型/用户做

- 改变用户目标；
- 选择一个语义不同的替代任务；
- 根据历史猜“用户现在肯定要继续上次任务”；
- 根据旧 decision/convention 覆盖当前用户输入；
- 自动接受外部 coordinate/task；
- 对高影响 side-effect 自动重试；
- 降级到明显不足以完成任务的模型；
- 把 program advice 伪装成 user/reference/tool truth。

---

## 11. 旧报告建议中需要明确撤销/修订的部分

### 11.1 “硬熔断后给三要素建议” → 修订

旧建议认为阻断时应附“原因 + 正确工具 + 示例”。新原则下：

- 原因/错误码是事实，可保留；
- “正确工具/下一步”若能确定，应 runtime 自动路由；
- 若不能确定，不应写程序建议让模型服从。

### 11.2 “程序已知指标直接注入给模型” → 撤销

程序指标属于 observability。用户问健康状态时，模型可以主动调用 `architecture_status`；普通任务不应自动获得指标表。

### 11.3 “停滞提醒升级更强提示” → 撤销

更强自然语言仍是干扰。正确做法是：

- 精确机械边界；
- 事实性 tool result；
- 必要时 stop；
- 不再劝模型。

### 11.4 “Rule 20/21 必须长期保留” → 修订

- Goal discipline 保留在 agent harness，不是 universal system rule；
- program-feedback semantic rule 只是 migration protection，目标应删除。

---

## 12. 建议实施顺序（本轮只设计，不执行）

### R8.24-A — Model Contract Slimming

目标：先把模型规则从“系统运维手册”降回“最小语义契约”。

- 新版 minimal system contract；
- 去 task-start mandatory rule read；
- ai_rules.lite 改 playbook/on-demand；
- 删除每轮自查 / action-chain / tool-name / memory / cache / transport / platform manuals。

### R8.24-B — Runtime Control Plane Closure

- E12/E15/E16/E17/E18 zero prompt；
- current_turn 不再 grant；
- overflow/round/retry/repair deterministic；
- E32 repair-before-lifecycle；
- E19 runtime notices 不进 sess.messages。

### R8.24-C — Tool Result Factualization

- generic failure guidance 退出 content；
- typed recovery 只 metadata/control；
- distill guidance 退出；
- evidence capsule metadata-only；
- truncated result 只留 minimal complete/ref fact。

### R8.24-D — Provenance / Cache / Fallback Hardening

- agent_trace guard 全 ingress 闭环后 fail-closed；
- suspect content quarantine，不 downgrade-reinject；
- cache performance BLOCK 退出；
- fallback capability floor；
- privacy/safety BLOCK 保留。

### R8.24-E — Latent Semantic Channels

- E07 auto memory 退出；
- E08 TIP replay 退出；
- E35 compact anchor 退出；
- Cognitive enforce 冻结/重设计；
- task_active 改 user-authorized；
- CORE9 做 A/B 再决定是否继续缩。

完成上述 fixed-point 前：

- behavior canary 继续 BLOCKED；
- R9 不启动。

---

## 13. 验收标准：不能只测“少了多少 token”

### 13.1 结构硬门

- run 开始后 program-authored natural-language prompt chars = 0；
- automatic memory / experience / digest / recovery / runtime status chars = 0；
- tool result advisory-prose chars = 0；
- evidence full-result capsule chars = 0；
- suspect provenance content provider chars = 0；
- cache hit/performance alone BLOCK count = 0；
- Goal/Cognitive state无 user authorization 时 prompt chars = 0；
- legacy TIP/compact anchor resurrection = 0。

### 13.2 能力不退化硬门

- 任务完成率不得下降；
- tool protocol error 不增加；
- factual hallucination 不增加；
- provider 400/1210 不增加；
- tool discovery 成功率不下降；
- 当前 unresolved tool follow-up 可正常继续；
- explicit user restore/continue 可恢复正确 task。

### 13.3 应改善的指标

- 平均模型可见 program chars；
- 工具轮额外元调用数；
- duplicate tool call rate；
- architecture/status/self-eval 非用户请求调用率；
- memory/evidence 元数据占比；
- cache prefix morphology 稳定性；
- 弱模型答非所问率；
- 用户任务→最终回答路径长度。

---

## 14. 当前优先级总表

| 优先级 | 项 | 当前判定 | 建议 |
|---|---|---|---|
| P0 | E12/E15/E16/E17/E18 | 直接运行中自注入 | MOVE-CONTROL |
| P0 | E07 memory snapshot | 自动历史语义 | RETRIEVAL-ONLY |
| P0 | tool failure/recovery guidance | 工具事实中夹程序意见 | FACTUALIZE |
| P0 | evidence capsule | 元数据常驻工具回执 | MOVE-METADATA |
| P0 | cache submit_ratio BLOCK | 性能优化阻止模型 | DELETE BLOCK |
| P0 | trace-leak observe + downgrade reinject | 污染仍可进 prompt | FAIL-CLOSED + QUARANTINE |
| P1 | mandatory ai_rules read | 每任务元工具负担 | DELETE |
| P1 | every-round self-check | 元任务 | DELETE-GLOBAL |
| P1 | action-chain/tool-name | 评测反向驱动行为 | DELETE-GLOBAL |
| P1 | `[[memory]]` | 污染用户答案 | DELETE-GLOBAL |
| P1 | model switch checklist | 可程序验证 | MOVE-TOOL |
| P1 | cache rule | runtime concern | DELETE-GLOBAL |
| P1 | long output segmentation | transport concern | MOVE-UI |
| P1 | experience pre-search | 额外调用/与R8.15冲突 | DELETE AUTO |
| P1 | interruption recovery rule | runtime已可repair | DELETE MODEL DUTY |
| P1 | Goal/checkpoint universal rule | agent workflow | MOVE-SKILL/HARNESS |
| P1 | Cognitive enforce | program semantic channel | FREEZE/REDESIGN |
| P1 | task_active | active≠authorized | USER-AUTHORIZED ONLY |
| P1 | fallback without capability floor | 可能降智 | ADD CAPABILITY FLOOR |
| P2 | CORE9 | 仍有进一步缩小空间 | A/B FIRST |
| P2 | PROGRAM_FINAL boundary prose | protocol shape有必要 | MINIMIZE CONTENT |
| P2 | TOOL_ROUND_ZERO_HISTORY | 性能换语义风险 | EXPERIMENT ONLY |
| P2 | SYSTEM_PROMPT_EXTRA | 隐式规则绕过 | REMOVE/GOVERN |

---

## 15. 最终判断

LFL 下一阶段不应该继续问：

> “还能给模型什么提示，让它更懂系统？”

而应该问：

> **“这个信息/规则/控制为什么必须让模型知道？如果程序能确定性处理，为什么还要让模型花注意力？”**

真正的 LLM-first，不是程序什么都不做，而是：

> **程序把机械复杂度吸收掉，把语义空间让给模型。**

因此后续治理的首要目标应从“注入更少”升级为：

1. 模型不做运行时运维；
2. 模型不背平台操作手册；
3. 模型不被程序建议重写问题空间；
4. 模型只看当前用户问题和自己主动取得的证据；
5. 安全/协议/物理边界由程序可靠执行；
6. 历史、状态、经验全部“可取而不常驻”。

这比继续优化 current-turn injection、提示措辞或预算优先级更接近根因。

---

## 16. 证据索引

- RUN-INJECTION-00：`docs/injection-governance/design.md:206-276`
- Strict census：`docs/injection-governance/eligibility/r823-report.md`
- Prompt baseline：`src/llm_loop/core/prompt.py:1-41`
- Model rule view：`docs/ai_rules.lite.md`
- Full rule SoT：`docs/ai_rules.md`
- Dynamic eligibility：`src/llm_loop/core/prompt_eligibility.py:20-151`
- Tool-result guidance：`src/llm_loop/tools/registry.py:874-881,1186-1245`
- Typed recovery：`src/llm_loop/tools/recovery.py:18-129`
- Evidence capsule：`src/llm_loop/memory/evidence.py:993-1017`
- Evidence enforce：`src/llm_loop/tools/evidence_enforce.py:43-121`
- Cache guard：`src/llm_loop/cache_guard/guard.py`
- Breaker pressure：`src/llm_loop/core/loop/build.py:455-507`
- Tool eligibility CORE9：`src/llm_loop/tools/eligibility.py:17-258`
- Program-final protocol boundary：`src/llm_loop/core/loop/build.py:742-772`
- Cognitive packet/enforce：当前工作树 `src/llm_loop/core/loop/build.py:1428-1775`
- Agent trace ingress guard：当前工作树 `src/llm_loop/core/trace_leak/user_ingress_guard.py`
- Agent trace build hooks：当前工作树 `src/llm_loop/core/loop/build.py:664-726,1368-1397`

### 本轮只读 census

- base system prompt：约 765 chars；
- ai_rules.lite：约 3,148 chars / 38 lines；
- ai_rules full：约 22,018 chars / 444 lines；
- actual assistant tool calls：9,164；
- architecture_status：333 / 82 sessions；
- search_records：258 / 71；
- checkpoint_goal：72 / 18；
- submit_evolution：59 / 22；
- save_experience：57 / 31；
- model_catalog：36 / 31；
- model-visible evidence capsules：1,638；capsule chars ≈411,575；
- cache guard request rows：9,897；submit_ratio-only BLOCK=25；privacy BLOCK=15；
- context.compressed events：55,672（**per archived message event，不等于55,672 compression rounds**）。

本轮没有修改 `src/`、配置或运行行为；只新增本文档。
