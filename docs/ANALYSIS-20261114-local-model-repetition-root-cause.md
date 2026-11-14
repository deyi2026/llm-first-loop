# 本地大模型「反复重复」根因分析 + 修复优化方案（v0.4 独立审查反馈修订）

- 日期：2026-11-14
- 分析对象：会话 `bc3e7780-af3b-4ea4-97e2-85cec88dbb96`（19:49:46 → 20:17:17，模型 `cognilocal/ornith-ai/Ornith-1.5-35B-A3B-MLX`）
- 证据源：`data/event_logs/bc3e7780-….jsonl`（原始事件）、`data/providers.local.json`、`src/llm_loop/**`（当前代码）
- 状态：**事件、LFL 现有机制与 `$RESEARCH_ROOT` 研究已交叉复核；独立 GLM-5.3 首审有效 HOLD（P0=0/P1=0/P2=4），v0.4 待复审；代码修复未实施**。
- 2026-11-14 复核：调用 LFL 内置 `grill_me`（`depth=3`，五领域，`design_anchored` 8 锚点）；该工具只自动生成首层问题，第 2/3 层由本次证据驱动的人工反例拷问补齐，**不是三轮独立模型审查**。
- **阅读优先级：第 0–7 节为初稿及其证据，含被否决的实现提议；第 8–12 节为 v0.2 拷问记录；第 13–17 节为 v0.3 研究对照；第 18 节为独立 Reviewer 后的 v0.4 纠正。冲突时以最新章节为准。初稿 R1–R7、D1–D4 的原始 P0 和 v0.2 V2-2 自动停机均已废止，严禁直接据此实施。**

---

> **v0.3 核心结论**：LFL 已有 StateBraid、Continuity Kernel、Working State Fold
> S1 consumer、antidrift 与 E1–E5 重复探索优化；本次先查**有效配置与接线**，
> 再修「最新工具回执在预算压缩后没有进入下一轮模型可见工作面」的具体缺口。
> 不新增通用语义断路器、不强制开启 checkpoint producer、不以缓存命中代替任务连续性。

## 0. 结论（一句话）

首个 Run 的前 8 轮有充分证据支持一条**上下文投影导致重复调用的强因果链**：有效历史预算只有
3,698 字符，紧接着的一条工具回执约 3,916 字符；压缩连续归档刚发生的工具交换，
下一轮 `messages_count=2`、`history_chars=3246`、`provider_structure_fp` 均未变化，
`model_catalog({})` 反复出现。**这证明可见结构指纹重复，不等于已经捕获并逐字节比对真实 HTTP 请求体；
也不能从一次样本证明「同输入必然同输出」。**

本次样本中相互叠加的三个重要因素（**不是所有死循环的逻辑必要条件**）：

1. `max_tokens=32768` 把 65536 窗口的**输入额度砍到 32768**；
2. **101 个工具**的 schema 占掉 28,659 tokens（输入额度的 87.5%），只剩 4,109 tokens；
3. 压缩策略在「预算 < 单条回执」时**不报警、不拦截**，而是每轮归档掉最新交换。

---

## 1. 现象与观测时间线（实测事实）

用户第一句是极简问题：`你是什么大模型？`（19:49:46，8 字符）。原稿列出「截至 20:17:17、73 次 provider、100 次工具」，
但**这些数字不属于同一截止快照**：按 `ts <= 2026-11-14T20:17:17` 对原始 JSONL 复核，
实为 **41 次 `provider.call.opened`、56 次 `tool.execution.started`、14 次 `history.compaction`**。
随后日志仍继续写入；在本次只读采样时，完整文件已达 90 次 Provider 开启、115 次工具开始，
因此不得把 20:17:17 写成「会话最终结束」或将不断增长的总数当作冻结事实。
原始事件文件的本次采样 SHA-256 为 `01ca4d749bed93d80640dd53cfbb040bb394fa4e0c77cb3bc1318e286089a556`
（2,509 条、最后 seq=2509；如文件继续写入，须重新取快照并另记 SHA）。

| 时间 | 轮次 | 输入消息数 | history_chars | 预算 | 模型输出 | 工具 |
|---|---|---|---|---|---|---|
| 19:49:46 | 1 | 2 | 3246 | 3698 | 空文本 + 工具调用 | `model_catalog({})` |
| 19:52:12 | 2 | 2 | 3246 | 3698 | 空文本 + 工具调用 | `model_catalog({})` |
| 19:52:21 | 3 | 2 | 3246 | 3698 | 同上 | `model_catalog({})` |
| 19:52:34 | 4 | 2 | 3246 | 3698 | 同上 | `model_catalog({})` |
| 19:53:19 | 5 | 2 | 3246 | 3698 | 同上 | `model_catalog({})` |
| 19:53:33 | 6 | 2 | 3246 | 3698 | 同上 | `model_catalog({})` |
| 19:53:45 | 7 | 2 | 3246 | 3698 | 同上 | `model_catalog({})` |
| 19:53:56 | 8 | 2 | 3246 | 3698 | 同上 | `model_catalog({})` |

关键点：**`messages_count`、`history_chars` 与 `provider_structure_fp=de0a18705a0240c813b0044e`
在前 8 轮相同**；这比单看字符数更强，但仍只足以称为「结构指纹一致」，不能声称传输字节级一致。
`args_sha256=44136fa3…` 即 `{}` 的 sha256，8 次调用参数完全相同；`message.appended` 里 8 条 assistant 消息 `content` 长度全为 `0`。

后两次 run（19:59、20:03 起）死循环换了形态，但没消失：

- `execute_command pwd && ls -1 && git log --oneline -3`（args `1969056b…`）出现 **4 次**（round 1/12/23/26）；
- `execute_command`（`b555973d…`）+ `search_records`（`e77f6f21…`）**成对重复 3 次**（round 6/17/20）；
- 压缩后历史呈锯齿：消息数 `4 → 7 → 10 → 13 → 4 → 7 → 10 → 4 …`，即**每 3~4 轮把已核实的东西归档掉，模型重新探索一遍**。

---

## 2. 根因链（每步都有运行时回执）

### ① 输入额度被 `max_tokens` 腰斩
`request.meta.input_budget`（round 1，19:49:46 实测）：

```json
{"requested_input_tokens":184000, "allowed_input_tokens":32768,
 "tool_schema_reserve_tokens":28659, "tool_schema_reserve_source":"authoritative_tokenizer",
 "effective_history_budget_tokens":4109, "projection_chars_per_token":0.9,
 "pre_tool_history_budget_chars":29491, "tool_schema_reserve_chars":85949,
 "effective_history_budget_chars":3698, "limited_by":"model_window"}
```

- 模型窗口 65536，模型自身 `max_tokens=32768` → `allowed = min(0.9×65536, 65536−32768) = 32768`。
- `data/providers.local.json` 中该模型条目 `max_tokens: 32768`；而本地运行时注册器默认值是 `16000`（`src/llm_loop/web/local_runtime_admin.py:213-214`）——**这条配置明显偏离默认**。

### ② 工具集膨胀吃掉 87.5% 输入额度
- 该轮请求 `tools_count = 101`；工具 schema 共 **85,949 字符 = 28,659 tokens**（权威 tokenizer 计数）。
- 事故时 `tools_count=101` 且 tokenizer 预留 28,659 tokens；**不能仅据当前源码断言事故采用 full schema**。
  当前已有 `TOOL_SCHEMA_LAZY` 与按授权/健康投影的工具面；须核对事故时有效设置和最终 `tools_param`。
  不应为了小窗口在未经资格验证时凭关键词删除可调用工具。
- 剩给「对话+系统提示」的额度：`32768 − 28659 = 4109 tokens`。

### ③ 字符桥把 4109 tokens 变成 3698 字符
`reserve_history_after_tools()`（`src/llm_loop/core/loop/engine_services/token_budget.py:250-286`）：
`effective_history_budget_chars = min(pre_tool_chars, floor(history_tokens × cpt))`。
cpt 取自 provider 配置 `chars_per_token=0.9`（`configured_fallback`，样本数 0）→ `floor(4109×0.9)=3698`。

真实中文/JSON 密度约 2.4 字符/token，所以同一额度后来被自适应抬到 ~10,043（84 条 `message.cache_compacted` 中 `effective_budget` 取值：3698×14、10043×41、10054×13、10041×9、10029×7）。**两个数量级都用错了对象**：字符预算比一条 `architecture_status` 回执（约 3 万字符）小一个数量级。

### ④ 压缩每轮删掉「模型刚刚拿到的那条结果」
`history.compaction`（epoch 1，19:52:12 实测）：

```json
{"trigger":"projected_history_over_compact_limit","pre_chars":7330,"post_chars":3246,
 "effective_budget_chars":3698,"trigger_excess_chars":394,"archived_count":2,
 "compaction_mode":"provider_contiguous_oldest","head_keep_chars":554}
```

配套 `context.compressed` 记录显示被归档的正是 `msg_seq=3`（assistant，`chars=0`）与 `msg_seq=4`（tool，`chars=3916`，`tool_call_id=fGls6Tnd…`）——**最新一轮的完整交换**。
`trigger_excess_chars` 只有 394 字符（超出 394 就触发），但一次压缩回退 4,084 字符，**回退幅度远超触发量**，直接抹掉了刚刚获得的信息。

### ⑤ 结果：高复现性的结构重复，不把相关性写成数学必然
prompt 投影反复回到 `messages=2 / history=3246`，同一结构指纹及 `temperature=0.0`
与连续 `model_catalog({})` 高度一致。若要证明**实际请求字节相同**，仍需在传输前以同一序列化口径
记录请求摘要并核对生成参数、工具 schema、system、运行时注入、模型模板及后端身份。

### ⑥ 动作层没有阻断这次闭环（放大器）
- `_maybe_repeat_guard_hint()`（`src/llm_loop/core/loop/engine_services/tool_cycle.py:258-313`）注释写明：**「每键至多一次；不阻断、不改状态码、不改工具真值」**；阈值 `_REPEAT_GUARD_AT=3`（同 tool+精确参数第 3 次成功）才追加一行文本。
- 更致命：该提示是**追加在工具回执 content 里**的（事故树 `tool_cycle.py:303`）；事件 `seq=85` 的 tool `message.appended` 含 `[repeat_guard]`，随后 `seq=87/88` 归档 assistant→tool 原子组，下一次 `seq=96` 的 `request.meta` 仍是 `messages_count=2`、`history_chars=3246`。**至少这一轮的提示没有进入下一次模型可见决策上下文**；不是仅凭当前 main 猜测。
- `convergence.observation` 同样只观测（`prompt_chars=0`，`tool_cycle.py:1085/1095`）。
- 全库 grep 无 `no_progress` / `loop_breaker` / `identical_call` 之类的硬闸（已核，零命中）。

### ⑦ 次要放大器：assistant 内容恒为空
`request.meta.reasoning_chars=0`（本地模型 8 轮全部为 0），`message.appended` 中 assistant `content` 长度为 0。
即使某轮侥幸拿到新 prompt，历史里也没有「我已经查过什么」的语义痕迹，只有裸 tool_call + 结果。
该模型 `reasoning_control=legacy`、`reasoning_replay=none`（`model_catalog` 实测），思考过程不进历史。

---

## 3. 初稿缺陷清单（**SUPERSEDED：原始 P0/P1 分级不是当前实施阻断项**）

> 本表仅保留事故分析史。D1–D4 的「P0」是初稿判断，已被第 9、15、18 节的反例和现有能力核验取代；不得把这里的分级、阈值或机制直接转成任务清单。

| # | 缺陷 | 位置 | 严重度 | 后果 |
|---|---|---|---|---|
| D1 | 预算可行域无下限校验：`history_tokens ≤ 0` 或预算 < 单条回执时仍照常调模型 | `attempt_executor.py:48-87`、`token_budget.py:250-286` | **P0** | 必然死循环，且对外表现为「模型抽风」 |
| D2 | 压缩无进展判据：允许「归档后状态 == 归档前状态」反复发生 | `src/llm_loop/core/history.py:1504` 附近触发点 | **P0** | 同一状态被压缩 8 次，无人拦 |
| D3 | 动作层重复断路器缺失：重复只提示、不阻断，且提示会被归档 | `tool_cycle.py:258-313` | **P0** | 8/4/3 次重复调用全部放行 |
| D4 | 工具 schema 无窗口感知投影：101 工具全量下发 | `engine.py:1818` | **P0** | 小窗口模型可用上下文趋零 |
| D5 | 配置偏离：模型级 `max_tokens=32768`（注册器默认 16000），`max_input_tokens=184000` 与 65536 窗口矛盾 | `data/providers.local.json` | **P1** | 输入额度直接减半 |
| D6 | 可观测性误导：`model_aware_budget: 1000000→79979` 打印的是**工具预留前**预算，真正下发的是 3698/10029 | `attempt_executor.py:82-87` vs `request.meta.budget` | **P1** | 排障时看不到真值（本次差点被带偏） |
| D7 | 空 assistant 内容 + `reasoning_replay=none` | 协议/历史构建 | **P2** | 历史无状态，重复门槛降低 |

---

## 4. 初稿修复提案（**SUPERSEDED / 不得实施**；第 10、15、18 节已纠正）

设计原则：**程序对「不可能推进的上下文」必须 fail-closed，而不是把决定权交给模型**（RULE-AI-30）。
所有新增判定都只用机械事实（token 计数、ref、状态指纹），不做语义判断、不注入长提示。

### R1（SUPERSEDED，历史 P0）预算可行域硬门：`budget_viability_check`
在 `AttemptExecutor.plan()` 产出 `effective_budget` 之后、真正调用 provider 之前：

```text
inputs: allowed_input_tokens, tool_schema_reserve_tokens, effective_history_budget_chars,
        head_keep_chars/sys_chars, p95_tool_result_chars(本会话实测或全局默认)
判定（任一成立即不可行）:
  A. effective_history_budget_chars - sys_chars < MIN_EXCHANGE_CHARS(建议 6000)
  B. effective_history_budget_chars < MIN_TOOL_RESULT_CHARS(建议 8000)
     且本 run 的工具集中存在 p95 回执 > 该预算的工具（>90% 概率每轮必触发压缩）
行为（fail-closed，明确告知而非静默重试）:
  1) 记录 action `budget.infeasible`（含完整 budget_chain）
  2) 尝试一次性自动收敛：把 max_tokens 降到 min(4096, window×0.12) 后重算（若 operator 未锁定）
  3) 仍不可行 → 该 attempt 不调模型，直接向用户返回结构化诊断：
     「本地模型窗口 65536 / max_tokens 32768 / 工具 schema 28659 tokens ⇒ 对话余额 4109 tokens(3698 字符)，
      小于单条工具回执，无法推进。可选：降 max_tokens 到 4096~8192、开启工具投影、或换窗口更大的模型。」
  4) 绝不允许在不可行域内连续调用模型 ≥2 次
```

验收（RULE-AI-35，必须实测「应拦输入」）：构造 `context=65536, max_tokens=32768` 的注册项 + 101 工具，
发送 `你是什么大模型？` ⇒ 期望 **1 次** `budget.infeasible`、**0 次** `model_catalog` 重复、用户收到诊断文本。

### R2（SUPERSEDED，历史 P0）压缩进展守卫：`compaction_progress_fence`
在 `history.compaction` 决策处（`history.py:1504` 触发点）比较压缩前后状态指纹：

```text
state_fp = (post_chars, len(history_messages), max_archived_msg_seq, head_keep_chars)
if state_fp 与上一轮完全相同（且本轮归档对象是「最新交换」）:
    → 判定 compaction_no_progress
    → 禁用本轮压缩（保留上轮 prompt 原样），改为「回执降级」：
      把该 tool 回执替换为 stub（`result_ref=<evidence|archive ref>` + 首 400 字符 + 「完整内容用 read_evidence 取」），
      stub 大小 < 预算×0.3，且 stub 内显式带 ref，模型可无损取回
    → 第 2 次 no_progress ⇒ 结束 attempt 并上报（reason_code=compaction_no_progress）
```

配套约束（防退化）：`trigger_excess_chars` 很小时不得重压缩到下方一个台阶的一半以下——
建议 `min_post_chars = max(head_keep + MIN_EXCHANGE_CHARS, pre_chars - trigger_excess_chars*2)`，
即**压缩至少保留刚发生的那一次交换**（新证据优先于旧噪声）。

### R3（SUPERSEDED，历史 P0）动作层重复断路器（`repeat_guard` 从 hint 升级为 fence）
复用现成指纹（`_stagnation_fingerprint` + `result_state_sha256`），把计数器从「只提示」改成三级：

```text
level 1: 同 (tool, args) 第 2 次 且 result_sha 相同
         → 不执行，返回控制回执：`duplicate_call_suppressed=true; result_ref=…; 该结果与第 k 轮相同`
         （模型拿到 ref，可 read_evidence 分页取，不需要重跑）
level 2: 第 3 次 → 追加 program_control（走既有 program_control frame，而非塞进回执）
level 3: 第 4 次 → 结束 attempt，reason_code=repeated_exact_call，向用户报告「已 4 次相同调用、结果相同，已停止」
```

要点：
- 提示/控制消息必须走 **program_control**（可存在于 head/system 区，不被压缩归档），不能再塞回执尾部；
- 判定必须在**执行前**（`_execute_allowed_with_wal` 之前的准入点），否则每次都真的跑一遍工具（本会话 100 次执行里 17 次是重跑）；
- 对 `read_evidence` 分页、`wait`、`job_output` 等「同参不同时」的合法轮询，用 `result_sha` 相同作为判据，天然放行；
- 全程 fail-open：任何异常不得改变工具真值。

### R4（SUPERSEDED，历史 P0）窗口感知工具投影：`tool_projection_by_window`
在构建 `tools_param` 处（`engine.py:1818`）加一层确定性投影：

```text
cap = floor(allowed_input_tokens × 0.45)      # schema 硬上限，剩余 55% 留给对话
始终保留: 核心集（约 12-15 个：读/写/搜索/命令/证据/task_state/schedule…）
按需保留: 与本轮用户消息词面重叠的工具名/描述命中项
其余: 不下发，但在 system 里给一行「未下发工具可用 tool_search(name) 发现」
若核心集仍超 cap → 精简描述（去 examples/长字段说明）直至达标；仍超 ⇒ 走 R1 不可行分支
```

预期：101 工具 28,659 tokens → 核心集约 8,000-10,000 tokens，
历史额度从 4,109 tokens 回到 ~20,000+ tokens（按 cpt 2.4 约 5 万字符），死循环域直接消失。

### R5（SUPERSEDED，历史 P1）会话账本 pinned（对抗「历史无状态」）
- 每条工具回执落盘后，程序侧自动追加一行到**运行账本**（不是 assistant 消息）：
  `- [r{round}] {tool}({args_digest}) → {status} / ref={ref} / chars={n}`；
- 账本上限 ~1,500 字符（滚动，最旧可归档），并列入压缩保护（`cache_protected` / head 区）；
- 目标：即使 assistant 内容为空、即使发生压缩，模型也总能看见「本 run 已做过什么、结果在哪」。

### R6（SUPERSEDED，历史 P1）配置与观测校正
- `data/providers.local.json`：ornith 条目 `max_tokens: 32768 → 4096~8192`（本地 35B 模型不需要 32k 输出）；
  并把 `max_input_tokens: 184000` 改为与窗口一致（或删除，让其继承 `context`），避免误导性授权值；
- `attempt_executor.py:82-87`：把 action 文本改成**完整链路**一行：
  `budget_chain: explicit=1000000 → pre_tool=79979 → schema_reserve=28659tok → history=4109tok → delivered=3698chars`；
  并且只在实际下发值上打 `→`（现在打印的 79,979 与实际 3,698 差 21 倍，属于误导性日志）。

### R7（SUPERSEDED，历史 P2）协议侧
- `reasoning_chars=0` 而 `thinking=true`：确认本地服务是否真返回 reasoning 通道；若不返回，就别在请求里声明 `reasoning_effort=max`（白付 token/延迟）；
- 若返回：评估 `reasoning_replay=full`（同注册器的 `qwen3.8-flash-next` 就是 full），至少让「上一轮意图」进入历史。

---

## 5. 初稿实施顺序（**SUPERSEDED：仅留历史，当前顺序见第 15、18 节**）

| 顺序 | 项 | 改动面 | 风险 | 备注 |
|---|---|---|---|---|
| 1 | R6 配置 + 观测一行 | 配置 + 1 处日志 | 极低 | 可立刻止血（`max_tokens=8192` → 额度回到 49,536 tokens） |
| 2 | R1 预算硬门 | `attempt_executor.py` + 拒绝分支 | 中：可能出现「小窗口模型直接被拒」的体验落差 | 用明确诊断文本替代静默重试，符合诚实原则 |
| 3 | R3 重复断路器 | `tool_cycle.py` 准入点 + `repeat_guard` 计数 | 中：误杀合法轮询 | 必须用 `result_sha` 相同作为必要条件，并 fail-open |
| 4 | R2 压缩进展守卫 | `history.py` 压缩决策 + stub 降级 | 中：可能改变既有压缩行为 | 需与 `cache.window`/`prefix_stability` 联合回归 |
| 5 | R4 工具投影 | `engine.py` + 工具元数据 | 中高：漏下发工具会改变能力面 | 必须有「工具发现」兜底，且投影对同模型确定性稳定（缓存前缀不抖） |
| 6 | R5 运行账本 | 历史构建 + 压缩保护 | 低 | 与知识结算解耦 |

**明确不做**：
- 不靠「把全局预算调大」掩盖问题（预算再大也追不上 10 万字符的回执，且会挤压模型注意力）；
- 不在压缩里静默丢弃历史而不给 ref（本次事故的核心教训：**丢弃可以，必须可无损取回**）；
- 不把语义判断塞进程序（「是否在重复」用 sha 指纹判定即可，不猜意图）。

---

## 6. 初稿临时规避设想（历史建议，非本次授权；正式裁决见第 15 节）

1. 会话切到窗口更大的模型（本次已切 `deepseek-v4-flash`，`budget=407,996` 字符，机制性死循环消失）；
2. 若必须用本地模型：把该模型注册项的 `max_tokens` 从 32768 调到 **4096~8192**（额度 32768 → 49536~57344 tokens）；
3. 工具密集的任务不要用 64k 窗口的本地模型（101 个工具 schema 本身就要 ~29k tokens）。

---

## 7. 附：本次未核验/待确认项（不写成结论）

1. 本地 MLX/llama 服务端在 prompt 略超 65536 时是否会静默截断——本会话 `exception_log` 为空、`model_fallback` 不活跃，**没有截断证据，也没有「未截断」证据**；
2. `reasoning_chars=0` 是「服务端没返回」还是「解析器丢弃」，二者都符合观测，需一次探针调用确认；
3. `_projection_density_decision` 的 cpt 自适应从 0.9 抬到 ~2.44 后，`tool_schema_reserve_tokens` 仍走权威 tokenizer（28,659）——两套口径混用是否在其他模型上产生同类偏差，未审计。

---

## 8. v0.2 证据边界与反事实复核（覆盖初稿的过强结论）

本节只使用已读取的事件日志、当前仓库源码与本地模型配置。**当前源码不等于事故时源码**：
事件 `request.meta.runtime_snapshot.git_head=103e9730de04…`，本次工作树 `main=71f95724459f…`；
源码结论只能说明本次复核的实现形态。要归因事故时精确代码，需再核对该运行快照对应的完整 Git SHA、
`source_tree_fp`、`config_hash` 与部署身份，不得把当前源码行号冒充事故时的字节级证明。

| 断言 | 证据/反例 | 裁决 |
|---|---|---|
| 前 8 轮进入重复调用 | `request.meta` 的 `messages_count=2`、`history_chars=3246`、`provider_structure_fp=de0a18705a0240c813b0044e` 均一致；`model_catalog({})` 重复 | **已证实的结构重复** |
| 真实 HTTP 请求体逐字节一致 | 尚无同一序列化口径的逐轮传输前 payload digest；`provider_structure_fp` 是结构摘要 | **未证实，删除「逐字节相同」断言** |
| `max_tokens=32768` 预留使窗口输入上限降为 32768 | 模型 `context=65536`，`max_tokens=32768`；`routing.py` 采用 `min(0.9×context, context−output_tokens)` | **本次合同成立**；不等于模型必然只能输出 32768 或必须永久改为 4096 |
| 101 工具 schema 吃掉 28,659 tokens | 首轮 `request.meta.input_budget` 的 tokenizer 计数；`tool_schema_reserve_source=authoritative_tokenizer` | **已证实的本轮预留**；不是每轮/每模型的常数 |
| 字符桥把剩余 4109 tokens 投影为 3698 chars | `token_budget.reserve_history_after_tools` 和 `projection_chars_per_token=0.9` | **已证实的投影结果**；字符与 token 不能当同一种容量 |
| 压缩后最新工具交换消失 | 首轮 `context.compressed` 的 seq=3/4；`history.compaction` 前 7330、后 3246；后续结构回到首轮 | **已证实**；不能由此推导所有压缩都不安全 |
| 73 次 Provider / 100 次工具属于 20:17:17 快照 | 同一 JSONL 按 `ts` 截断为 41/56；继续写入后达到 90/115 | **初稿统计不成立，必须冻结时间/事件序号/SHA** |
| 需要新 `tool_search` 才能按需发现工具 | 当前仓库没有 `tool_search`；已有 `get_tool_schema`、`registry.schemas(lazy=True)` | **否决初稿 R4 的发现入口** |
| 可以用「本次 result_sha 相同」在执行前拒绝工具 | 执行前尚无本次 result；且副作用工具的同参不等于同效果 | **否决初稿 R3 的前置判据** |
| 缺少任何压缩/重复防护 | 已有 `_breaker_pressure_block`、`project_exact_duplicate_tool_groups`、`_continuity_reuse_result`、`repeat_guard`、`convergence.observation` | **不能写成「完全没有」**；准确缺口是这些机制未阻止本样本的跨轮无进展闭环 |

**快照纪律**：复现时先复制/固定 JSONL，记录 `sha256`、`size`、`last_seq`、截止 `ts`、运行代码/配置 SHA。
如日志仍在追加，只能说「截至某个快照」，不得混合「前 8 轮」与后续 Run 的汇总数字。
本次 2,509 条日志 SHA 见 `1`；它是一次**只读采样**，不是已封存的永久证据文件。

## 9. grill_me 三层拷问：问题、反例与裁决

本次调用 LFL 内置 `grill_me(depth=3, focus_areas=[edge_cases,failure_modes,scale,security,ux])`，
工具返回 `status=success`、`mode=design_anchored`、8 个正文锚点和五领域首层问题。
**工具没有自动完成第二、第三层，也没有输出独立 Reviewer verdict**；以下第二、第三层是针对
首层问题与源码证据继续进行的人工/本助手反例审查，不冒称 GLM-5.3 独立审查。

### 第一层：事实与适用域

1. **问：三个因素是否「缺一不会死循环」？**
   答：否。工具结果可被其他截断/协议错误/权限变化抹掉；即使预算充足，模型也可能重复探索。
   **修订**：本次为三因素叠加的强因果解释，不定义所有重复行为的充要条件。
2. **问：只看 `history_chars` 一样，能证明 prompt 一样吗？**
   答：不能。还需 system、工具数组及顺序、动态注入、模板、生成参数、运行时状态。
   **修订**：记录最终传输前请求的稳定摘要；只保存 digest 与必要归因，不额外落明文敏感 prompt。
3. **问：原文 73/100 是否可重算？**
   答：与标注截止时间不符；20:17:17 为 41/56。**修订**：以冻结快照和事件类型分项计数，
   区分 opened/settled、started/finished、单 Run/多 Run。
4. **问：当前 `TOOL_SCHEMA_LAZY` 已默认开启，为何还要「精简描述」？**
   答：`registry.schemas(lazy=True)` 已提供紧凑 description 和保留机器约束的参数骨架。
   **修订**：先测真实运行设置及每个 schema 的 tokenizer 成本；避免重复实现已有优化。
5. **问：初稿所谓 `tool_search(name)` 在哪里？**
   答：不存在；当前发现工具为 `get_tool_schema`。**修订**：只复用已存在且本轮授权可调用的发现面。

### 第二层：失败、安全与副作用

6. **问：为什么 `MIN_EXCHANGE_CHARS=6000`、`MIN_TOOL_RESULT_CHARS=8000` 是安全下限？**
   答：没有跨模型实测依据；「比单条回执小」也不必然无法回答简单问题或使用精确引用。
   **修订**：不以任意字符常数拒绝所有请求；以真实模型/tokenizer 合同、不可省略的消息/协议
   与实际可恢复性判定。`p95` 仅做风险提示，不能当安全证明。
7. **问：在 `_execute_allowed_with_wal` 之前怎样得到本次 `result_sha`？**
   答：做不到。只可依据已完成的旧回执、不可变来源/版本 token 与现有 WAL 判断能否复用；
   **不能假设未知结果必然相同**。**修订**：重复观测与执行前复用分离。
8. **问：相同 `execute_command` 会不会是用户合法重复执行？**
   答：会，且可能有副作用；不能用同参/旧结果哈希跳过。**修订**：写操作只走现有
   `ToolExecutionJournal`/授权/幂等与副作用核验；状态未知则 HOLD，不静默再执行，也不伪造成功回执。
9. **问：`wait`、`job_output`、文件读取在同参下会不会改变结果？**
   答：会。**修订**：轮询/可变读取必须尊重当前版本和时间语义；仅不可变证据或版本可核的
   `read_file`/`read_evidence` 可复用。源码 `_continuity_reuse_result` 已对压缩 epoch 变化主动放弃 contentless 复用。
10. **问：把工具回执改成「首 400 字符 + ref」一定无损吗？**
    答：不一定；若 ref 不存在、未授权、无法分页或与原来源版本不匹配，就是假无损。
    **修订**：仅在原始回执已持久化、精确 ref 可读、协议配对仍合法时做有界投影；
    否则诚实报不可恢复/容量不足，绝不声称无损。
11. **问：把提示放进 `program_control` 就能保证不丢、且不越权吗？**
    答：不能。它可能改变 system/head 优先级、污染缓存前缀，并与用户/授权语义冲突。
    **修订**：诊断首先保存在程序侧事件与 Web 状态；必要的模型可见事实走既有受治理
    注入槽，带明确来源/长度/失效边界，不新造高优先级命令。

### 第三层：反事实、并发与最小性

12. **问：`max_tokens` 从 32768 降到 8192 就能根治吗？**
    答：只能扩大本样本输入预算；还可能影响长输出任务及 operator 合同。
    **修订**：作为可回滚的单模型配置试验，由配置所有者经现有 CAS/版本校验执行；
    不在一次 attempt 中私自改写请求上限，更不能当全局根治。
13. **问：`min_post_chars = pre−2×excess` 能保证保留最新交换吗？**
    答：本例 `pre=7330`、`excess=394`，该式要求约 6542 字符，**高于 3698 的上限**；
    与物理预算自相矛盾。**修订**：删除此公式；不可容纳时转入精确引用/合法拒绝，而非超限发送。
14. **问：`state_fp=(post_chars,len,max_archived_seq,head_keep)` 能检测活锁吗？**
    答：不能。归档序号会变，实际可见请求却可相同。**修订**：以最终 provider-visible
    请求摘要 + 决策/回执摘要 + 新事实版本判定「同一循环」，而非用压缩计数做代理。
15. **问：按用户词面挑工具会不会破坏 LFL 的 LLM-First 与能力边界？**
    答：会；当前 `_project_tool_schemas_for_round` 明确撤销了 keyword/core/protocol/recovery
    选择权，仅保留授权和运行时健康筛选。**修订**：不能重新引入未经资格验证的关键词裁剪；
    若 101 工具仍不适配小窗口，先使用现有 lazy schema、显式用户可见的能力范围/更大窗口，
    另立工具索引方案须做能力等价与缓存稳定性 A/B。
16. **问：再建一份 pinned 运行账本是否比恢复已有事实更可靠？**
    答：未必，容易形成第二真值源。已有 `task_state`、`longrun_read_cache`、compaction manifest、
    `search_archive`/`read_evidence` 及 WAL。**修订**：优先打通已有事实的 exact-ref 恢复，
    只补最小机械进展摘要，不做自动语义总结或第二份权威执行账本。
17. **问：同一会话并发 Run、重启或授权撤销后，旧指纹还能用吗？**
    答：不能无条件复用。**修订**：指纹必须绑定 session、run_generation、模型/模板/配置、
    最终工具授权面、source_version 与执行账本状态；重启后未知外部效果一律 HOLD，
    不能因为「似曾相识」而重放 Provider 或副作用工具。
18. **问：如果真正原因是 MLX 模板或 reasoning 解析，而非压缩呢？**
    答：本样本压缩链有强证据，但协议差异仍可能并存。2026-10-21 的本地模型合同
    RUNBOOK 已明确 Ornith 的 reasoning replay 尚未通过真实 MLX 资格验证。
    **修订**：协议探针独立验证，不将 Qwen 的 `reasoning_replay=full` 结论直接复制给 Ornith。

## 10. v0.2 最小实施设计（历史候选，须按第 13–17 节研究对照修订）

### V2-0：先冻结事故证据与 RED 复现，不动生产

- 固定原始 JSONL 的 `last_seq`、SHA、模型配置有效值、实际运行 commit/source tree、
  `request.meta`、`history.compaction`、`tool.execution.*`、`provider.call.*` 的对应关系。
- 离线重放至少两个模式：**首 Run 前 8 轮的同结构循环**；**后续 Run 的锯齿压缩/反复探索**。
- 把「相同结构指纹」「相同真实请求」「同参工具」「同结果」「无新事实」分成五个独立布尔事实，
  禁止一个指标替代其他四个。
- 不重新调用真实 Provider、不重放副作用工具、不清理原会话历史或未决债务。

### V2-1：预算链真值与前置可行性（优先级 P0）

- 以现有 `routing.reserve_tool_schema_from_history_budget` 为单一预算来源，
  对账 `context`、`output reserve`、`max_input_tokens`、schema tokenizer 计数、
  历史 token→char 投影、不可裁 system/active ingress、最终 provider 请求。
- **确定的硬拒绝**：真实 tokenizer/最终请求预检证实必需协议与不可裁消息无法容纳；
  或精确引用/合法压缩都无法构成有效请求。拒绝发生在 Provider 发送前，
  返回 `context_capacity_unavailable`，明确 `provider_sent=false`。
- **非硬拒绝**：仅因预计回执很大、`p95` 较高或估算字符预算小于 6000/8000，
  不应阻止一个仍可合法回答的简单请求；可提示预算风险。
- 修正 `model_aware_budget` 展示：`pre_tool` 与 `post_tool` 分列，
  不把 79,979 的前置数字称作实际可下发的 3,698。
- 试验性调低 Ornith 的 `max_tokens` 必须是**独立、经批准的模型配置 CAS 变更**，
  并验证实际生效请求、输出截断和回滚；禁止 attempt 内静默自动改配置。

### V2-2：跨轮「无新事实」检测（优先级 P0）

- 在**最终消息构建/协议修复/工具投影之后、Provider 发送之前**生成安全摘要：
  `request_fp = H(model+template+generation_contract+final_messages+exact_tools+authorization_scope)`。
  采用与真实传输相同的字段/规范化口径，记录算法版本；不存原始敏感 payload。
- 在上一轮回执完成后记录 `decision_fp`（工具名、规范参数、顺序）、
  `observation_fp`（已持久化结果摘要及来源版本）和进展事实。
  `provider_structure_fp` 只能作为先验线索，不能冒充最终 wire hash。
- **SUPERSEDED：不得根据同一 `request_fp` / `decision_fp` / `observation_fp` 或固定重复次数
  自动终止 Run。** 这些指纹只能产生 `same_request_observed` 等诊断事实；
  `exact_no_progress_cycle` 旧名不再作为新门禁。唯一可新增的机械拒绝条件是：
  上一轮已完成的 assistant→tool 原子组确实存在，**最终发送前 Provider 视图**
  经协议配对检查后既没有原始组，也没有已经验证的模型可见 exact-ref；
  同时真实 tokenizer/授权/来源版本核验表明原始组无法容纳、可用 ref 无法合法投影。
  只有此时才 `context_capacity_unavailable`、`provider_sent=false`、`run_incomplete`。
  若 ref 已合法投影、轮询对象状态改变、工具结果可见或指纹不完整，
  不能因「重复」触发该 HOLD。详情以第 15、18 节为准。
- 若来源版本/用户输入/权限/模型/工具 schema 变化，或指纹计算不完整，
  不得声称 exact cycle；走正常授权路径或以「未知」状态停止，而非假造同一性。
- 不以固定「第 4 次工具调用」作全局硬闸；阈值按**已证实的同一闭环**而非单纯次数。

### V2-3：压缩与证据恢复（优先级 P0）

- 复用 `history.py` 的 assistant→tool 原子分组、`_repair_tool_call_pairing`、
  `project_exact_duplicate_tool_groups` 与已有 compaction manifest。
- 发现最新交换将被归档时，先检查**真实剩余容量**与 exact-ref 的存在、可读性、版本和权限；
  可以合法保留就保留；可以精确回读才投影为有界引用；两者都不行则停止/报告容量不足。
- 禁止以 `pre−2×excess`、固定「前 400 字符」、`budget×0.3` 等无法证明可容纳的公式
  替代实际预检；也不允许超限提交、丢失 tool_call_id 配对或虚构 evidence ref。
- 任何压缩优化失败不得删除 durable 原文；若恢复路径失效，向用户标记
  `evidence_unavailable`，不把空回执当作成功。

### V2-4：工具重复与工具面（优先级 P1）

- **只读且版本可核**：优先复用 `_continuity_reuse_result`，确认精确 ref、范围、来源版本、
  compaction epoch；可变读/轮询有变化时照常执行。
- **写操作/命令/外部效果**：绝不因 `tool+args` 重复而跳过、伪造成功或自动重放；
  使用现有 `ToolExecutionJournal`、授权、WAL 和副作用核验，未知效果 HOLD。
- **工具 schema**：先确认 `TOOL_SCHEMA_LAZY` 的运行时有效值及实际 101 工具的成本；
  保留 `get_tool_schema` 现有入口与完整机器约束，不凭关键词隐藏可调用能力，
  不新增不存在的 `tool_search`。如需进一步投影，另做权限等价、工具可达性与缓存稳定性资格测试。
- `repeat_guard` 可继续作为观测，但不再把可能被归档的尾注视为可靠防循环措施；
  不通过未经治理的高优先级 `program_control` 偷渡命令。

### V2-5：复用工作状态与模型合同（优先级 P1/P2）

- 复用 `task_state`/compaction manifest/longrun continuity；只补「已调用工具、
  可核对 ref、当前版本、未决状态」的最小机械事实投影，非语义摘要、非第二权威账本。
- 单独做 Ornith MLX reasoning/template 探针，区分「服务端没返回」「客户端未解析」
  「历史 replay 被省略」；`reasoning_replay=full` 仅在模型实际合同验证后启用。
- 保持 LFL-First/LLM-First：模型决定下一步认知策略，程序只保证容量、授权、
  协议、证据真值和外部副作用安全，不以关键词或任意次数阈值代替模型。

## 11. RED→GREEN 验收矩阵与门禁

| ID | 反例/测试输入 | 必须满足的可核验结果 |
|---|---|---|
| A01 | 固定首 Run 前 8 轮事件离线重放 | 识别相同 `provider_structure_fp` 与反复归档；无超过 2 次的已证实 exact-no-progress 闭环继续发送；不声称已比对 HTTP 字节 |
| A02 | 后续 Run `4→7→10→…→4` 锯齿模式 | 区分新证据与重复探索；恢复失败时返回 incomplete，不凭消息数直接误判 |
| A03 | 65536 窗口、32768 输出预留、101 工具、短用户问题 | 预算链一致；若不可裁请求确实能放入，不因固定 6000/8000 字符阈值误拒 |
| A04 | 不可裁 system+ingress+工具协议真实超限 | Provider 发送前拒绝，`provider_sent=false`，不重试旧请求、不改 operator 配置 |
| A05 | 大工具回执已 durable 且 exact-ref 可读 | 允许合法有界投影/精确回读；原文与 tool_call_id 配对保留 |
| A06 | 回执没有 ref、ref 过期或无权限 | 不生成假 ref、不称「无损」；显式 `evidence_unavailable`/HOLD |
| A07 | `read_file` 相同参数但源版本已变化 | 不复用旧结果，模型得到新版本事实 |
| A08 | `read_evidence` 同一不可变 ref 与相同范围 | 可安全复用；压缩 epoch 改变时不回无内容桩造成二次循环 |
| A09 | `wait`/`job_output` 相同参数但状态变化 | 不被重复断路器误杀 |
| A10 | 同参 `execute_command` 有副作用或结果未知 | 不靠旧 `result_sha` 预判、不伪造成功、不自动重放；走 WAL/人工核验 |
| A11 | 授权撤销、工具健康变化、模型切换或 schema 改变 | 新 `request_fp` 与准入重新核对；不得复用旧授权的执行事实 |
| A12 | 两个并发 Run、崩溃后重启与跨进程续接 | 指纹与状态按 Run 隔离；未知 Provider/Tool 外部效果 HOLD，不自动重发 |
| A13 | 真实 payload 的 system/tools/参数任一变化但字符数不变 | 不能因 `history_chars` 相同误报 exact cycle |
| A14 | 真实 `reasoning_chars=0` 的 Ornith 与已验证的 Qwen 合同 | 分模型探针与回归，不复制另一模型的 replay 配置 |
| A15 | 压缩触发、缓存前缀保护、历史原子分组 | 原有 pairing、cache epoch、精确恢复、事件真值不退化 |
| A16 | 用户取消、预算耗尽、错误诊断 | 及时结束并显示「未完成/已停止原因/是否有副作用未知」，不伪报任务成功 |

验收必须分别报告：**已重放/未重放、Provider 外发次数、工具真实执行次数、
未决副作用数、精确证据 ref、候选 commit SHA、测试 exit code**。
离线/模拟通过不得冒充真实 Ornith 后端资格或生产问题已根治。

实施门禁（按最小批次，不重复做全量测试）：先 RED 复现 → 最小补修 →
定向负向与现有相关回归 → 冻结候选 → **独立 GLM-5.3 Reviewer 有效 PASS、P0/P1=0**
→ **原版完整 R9 exit 0** → 远端 CI/架构/隐私核验 → 再考虑 main 集成与受管部署。
任一变更使 SHA 漂移，相关独立审查资格重新计算。当前文档审查不授权 push、
合并 main、改生产配置、Provider 真实调用或 Mac/Deepin 重启。

## 12. 当前裁决与剩余证据缺口

**v0.2 阶段设计裁决：REVISE（初稿 R1–R7 不可直接实施）。** 根因的「输出预留 + 工具
schema + 字符投影 + 最新回执被归档」链条已获强证据支持；但原稿的统计快照、
字节级同一性、任意阈值、重复工具前置哈希、`tool_search`、自动降配置与第二账本
均须按本次 v0.2 修订。此处 `REVISE` 是本次设计拷问裁决，**不是独立 GLM Reviewer 结果**。

仍待验证：①事故时完整运行代码/配置与本次仓库的差异；
②传输前精确 payload digest 与后端模板/采样身份；
③ Ornith MLX reasoning 实际通道；
④ 101 工具在有效 lazy 模式下各 schema 的真实 token 成本；
⑤ 现有 exact-ref 恢复在「刚归档最新交换」时是否稳定可用；
⑥ 不同模型/任务的最小有效容量与真实合法轮询误报率。
未验证前不得将单次样本的因果解释扩大为「所有本地模型重复的唯一根因」。

---

## 13. v0.3：专项研究对照与现有能力盘点（2026-11-14）

**本节修订动机**：不能把 LFL/StateBraid 已做过的抗漂移、连续性和重复探索优化当成空白，
更不能把「缓存前缀漂移」「任务语义漂移」「工具活锁」混为一个问题。先审已有能力是否**已实现、
已装配、已启用、在事故 Run 内实际命中**，再补唯一缺口。

本次只读对照的仓库身份：

- 研究总仓 `$RESEARCH_ROOT`：`main=78285c8bdebbea30da551b06b693813e727955dd`（干净）；
- 研究内 StateBraid：`main=6cea6f05168ef1d2d70d900f7d4450a38ab65305`（干净）；
- LFL mirror：`main=71f95724459f5d0500a0d19405d9a51d7586d741`（有并行未跟踪文件，且落后远端 3 提交）；
- 事故 `request.meta.runtime_snapshot.git_head=103e9730de049f3b9715b1429d51d0e17d8fee5c`，
  `source_tree_fp=09347b073de607798f521a7624376a41555ae2d80cab18ceb96f987c77525490`。
  **事故时源码、当前 main、研究快照不是同一 SHA；不能用当前实现反推事故时某个守卫必然开启。**

| 已有专项能力及权威材料 | 当前对照结果 | 对本事故的作用与限制 |
|---|---|---|
| **StateBraid compute continuity**：研究 `StateBraid/docs/ARCHITECTURE.md`、`SUPPORTED_SCOPE_V0_1.md`、`analysis/STATEBRAID_LLAMA_MANAGED_CACHE_AB_2026-09-07.md` | 稳定前缀/active successor、exact token/namespace、事务预算与 generation-safe reuse 已设计和测试；v0.1 **仅 MLX 指定 Ornith profile** 为参考资格，llama.cpp M1 `runtime_qualified=false` | 解决**重复 prefill/缓存身份**，不拥有工具选择、任务记忆或是否完成；不能拿缓存命中率证明 Agent 不复读。历史真实 GGUF A/B 不可当作当前 M1 资格 |
| **Working State Fold**：`design/WORKING_STATE_FOLD_PRODUCTION_DESIGN-2026-09-06.md` | 真实 Agent 研究中，选定原始证据后 `cache-recency-verdict` 达到 5/5 一次收口、0 重读；`exact-cache-generation-safety` 达到 4/4、0 重读；而 receipt-only 在该样本中反复重查 | **直接相关**：说明保留原始 tool-role 证据比仅留 assistant 摘要/receipt 更利于连续推理；但这是历史研究结果，不是当前生产自动折叠已通过 |
| **CK1 Continuity Kernel**：LFL `docs/analysis/DESIGN-20260907-continuity-kernel-1.0.md`、`core/episode_history.py`、`prompt_build/stages/ingress_resolution.py` | Session/EventLog、EvidenceRef、原子 tool pairing、current human ingress、working-set receipts 与 S1 checkpoint **consumer/validation** 已有；`build_working_state_checkpoint()` **没有生产 src 调用者**，producer 仍 HOLD | 必须复用现有事实和 selected-raw 豁免，**不得新造第二账本/摘要权威**；producer 不可因这次事故未经资格直接打开 |
| **Run 收敛/防漂移**：LFL `docs/SPEC-20260922-run-convergence-antidrift-v1.md`、`tests/integration/test_antidrift_replay.py` | 已设计/测试 wake `subject_refs`、任务源保护、复活中断事实、用户显式 CAS 插话等；后续治理**撤回自动轮边界插话**；`convergence_decide` 已从 Provider 工具面退役，`convergence.observation` 为纯遥测 | 处理目标被取代、任务源丢失与用户消息饥饿；**不能**把历史 R2 三件套当成当前可调用的 `convergence_decide` 元工具，也不能恢复自动打断 |
| **2026-11-04 重复探索 E1–E5**：LFL `tests/unit/test_evo_305716fa_repeated_exploration.py`、`tool_cycle.py`、`compaction_gate.py`、`token_budget.py` | 已有压缩 epoch 感知 read-cache、reasoning-only assistant 恢复、账本优先入口、密度持久化、交错重复统计；`repeat_guard` 第 3 次同参成功或第 5 次同 ref 读取仅追加**一次提示**，非硬阻断 | 不是缺「重复次数计数器」，而是要验证**提示/真实回执在压缩后是否仍对模型可见**；现有 telemetry 不保证打破输入恒定循环 |
| **Reasoning replay/采样合同**：研究 `analysis/CAPABILITY_PROVENANCE_ADOPTION_AUDIT_2026-09-07.md`、`analysis/P0_CAPABILITY_CONTRACT_PATCHSET_2026-09-07.md`；当前 LFL `llm/providers.py`、`loop/build.py`、`data/providers.local.json` | 研究曾指出历史版本缺模型级合同；**当前已实现** `reasoning_replay=none/tool_calls/full/configured` 与可选采样字段。当前文件中 Ornith 为 `none`、`temperature=0.0`；Qwen3.8 为 `full` | **不得重新立项「新增 reasoning_replay 字段」**。只核对事故实际 routing registry/运行后端/传输字段是否与当前文件一致；`reasoning_chars=0` 仍需独立探针 |
| **Exact duplicate tool fold**：`history.py::project_exact_duplicate_tool_groups`、`config.py` | 代码默认 OFF，但**事故首 8 轮 `request.meta.influence.history.exact_duplicate_tool_projection.enabled=true`，`folded_groups=0`** | 已启用仍零折叠：它折叠 provider-visible 中可用的完整重复组，不能恢复每轮刚被归档、下一轮不可见的工具结果 |
| **Schema lazy / 精确工具授权**：`registry.schemas(lazy=True)`、`_project_tool_schemas_for_round` | 现有 lazy 参数骨架和 `get_tool_schema`，默认配置为 lazy；事故实际 101 个工具仍占 28,659 tokens | 先核验**有效 lazy 设置、每工具 tokenizer 计数及授权工具面**，而非新增 `tool_search` 或按用户关键词删工具 |

**研究证据的有效期**：`analysis/STATEBRAID_LLAMA_MANAGED_CACHE_AB_2026-09-07.md` 和
`analysis/STATEBRAID_LLAMA_MANAGED_MEMORY_PRESSURE_QUALIFICATION_2026-09-07.md`
均有 2026-11-01 状态横幅：所用 real-GGUF 权重已删除，现 M1 候选仅确定性重验；
不准把 9 月历史 PASS 写成 11 月生产资格。`STATEBRAID_LFL_CURRENT_MAIN_REQUALIFICATION_2026-09-07.md`
也明确当时的 current-main real-model ON/OFF A/B **未重跑**。

## 14. 为什么已有优化仍没有阻止这次事故

需要拆开三个互不替代的层面：

1. **Compute/cache 连续性**（StateBraid）：同一真实 token 前缀是否可安全复用、是否减少 prefill；
2. **Evidence/task 连续性**（LFL CK1/Working State Fold/antidrift）：当前任务、原始工具回执、
   来源版本和未决事项是否仍在模型的合法可见工作面；
3. **Run 活性与外部效果**（LFL ToolCycle/WAL）：模型是否在有新事实时继续探索、
   是否重复执行相同工具、未知副作用是否被安全隔离。

**本事故首先命中第 2 层**：`effective_history_budget_chars=3698`，
工具回执约 3916 字符，首 Run 每轮最新 assistant(tool_calls)+tool 组被归档；
`messages_count=2`、`history_chars=3246` 与结构指纹连续 8 轮相同。
**第 3 层** 的 `repeat_guard` 只在回执末尾追加提示、`convergence.observation`
只记录事实；当整组结果下一轮不可见，提示也没有可靠的生存位置。
**第 1 层** 即使完全命中缓存，也只能更快地产生相同错误循环。

事件的 `exact_duplicate_tool_projection.enabled=true, folded_groups=0` 是关键反例：
**「已经启用去重」不等于「已经保住模型必须看到的最新工具事实」**。
本次 JSONL 的事件类型计数未见 `tool.repeat_guard`，但该提示使用 `_record_action`
而非必然写入相同 EventLog 类型，不能据此断言没有触发。
**现已复核事故 Git tree `103e9730de049f3b9715b1429d51d0e17d8fee5c`：
`tool_cycle.py:258–310` 在成功回执尾部追加 hint，`persist_finished` 在
`tool_result_to_message` 之前调用它；EventLog `seq=85` 确有 hint，
`seq=87/88` 归档该交换，`seq=96` 下一次请求回到两条消息。
这是本样本的直接证据，而非对所有 Run 的普遍断言。`request.meta`
也没有足够证据证明 S1 selected-raw producer 曾运行。

旧研究中「reasoning replay 缺失」已由当前代码的显式模型合同部分修复。
因此本事故**不应再次优先改 replay 或 sampling**；先证明运行时实际后端身份，
并独立测 replay 是否引起新的重复。`max_tokens=32768` 与 101 schema 的预算挤占
已有更直接的观测证据。

## 15. v0.3 正式实施顺序：只补已有机制之间的断点

### P0-A｜冻结身份与能力生效矩阵（零业务改动）

- 在**隔离工作树**对齐事故 `git_head/source_tree_fp`、实际 Provider/model/backend、
  `reasoning_replay`、采样参数、`max_tokens`、工具授权集合、lazy schema、
  working-set receipts、exact duplicate fold、checkpoint producer 状态；
  每项记录 `implemented / wired / enabled / exercised / effective` 五列。
- 以事故前 8 轮和后续锯齿模式为 RED fixture；冻结 JSONL `last_seq/SHA`，
  不重放真实 Provider/Tool，不触碰旧会话未决效果。
- 先测本地模型是否真实服务 Ornith MLX，还是仅有逻辑别名；模型身份不符时，
  不把 MLX/StateBraid 的资格结论套用到 llama.cpp 或其他权重。

### P0-B｜修复「最新观察被压缩掉」的可见性断点（**首要代码候选**）

- 在现有 `prompt_build/history` 管线，对即将发送的合法 Provider 视图检查：
  本轮刚完成的 assistant→tool 原子交换是否**至少保留原始结果，或保留可核验、
  可授权、可精确回读的 EvidenceRef/receipt**；tool_call_id pairing 必须完整。
- **优先保留最新原始交换**，与 CK1 current human ingress、已验证的
  cache-protected exact boundary 和 S1 selected-raw 保护取机械并集；
  先算真实 tokenizer/协议容量，再决定能否放入。不得用固定字符阈值或程序
  语义排名裁剪证据。
- 若容量容不下原始交换，则复用现有 durable EvidenceRef、ArchiveStore、
  `read_evidence`/`search_archive` 和 receipt 投影；必须实际验证 ref、版本、
  权限、分页与 tool pairing。**仅有可检索历史，不等于该轮已经向模型交付了恢复指针**。
- 若最新结果既放不下也无法精确恢复，返回
  `context_capacity_unavailable / run_incomplete / provider_sent=false`，
  **以容量/协议失效机械 HOLD**，不发送与上一轮同样缺失观察的请求；
  不伪称任务完成，不自动重试/重放工具，不静默调低 `max_tokens`。
- 预算链以 `routing.reserve_tool_schema_from_history_budget` 和最终请求预检为准，
  并修正 UI 的 `pre_tool/post_tool` 口径；若问题仅由模型配置造成，
  另提**独立、可回滚、需授权**的单模型配置试验。

### P1-C｜让已有抗重复观测准确说明「为什么没进展」

- 保留 `_track_tool_observation`、`repeat_guard`、`SelfEvaluator` 的既有
  **观测而非语义阻断**契约；补一项 `latest_observation_delivered`
  机械事实：前一工具回执的原始/精确引用是否真的进入下一轮 Provider 视图。
- 若重复是**投影丢证据**造成，按 P0-B 的容量/协议 HOLD；
  若回执完整可见而模型仍自主重复（包括合法轮询、参数变化、故障复查），
  只给可核对的次数/来源版本/已核事实，交由模型判断是否继续；
  **不得仅凭 `request_fp` 重复就强制结束 Run**。
- `request_fp` 仅作诊断：以真实最终传输字段生成不含敏感明文的 digest，
  同时记录 `decision_fp`、`observation_fp`、source_version、run_generation；
  它不是替代 `max_iterations` 的第二个通用 loopbreaker。
- 复用已有 `task_state`、`compaction_source`、`longrun_read_cache`、
  `convergence.observation`。`convergence_decide` 已退役，
  **不得为附加 R2 三件套重新注册元工具**；任何机械事实必须在既有事实/回执面供给。

### P1-D｜Working State Fold 只补必要资格，不直接开生产 producer

- 保持 S1 consumer/selected-raw 既有实现；在隔离 shadow/canary 重用研究
  `cache-recency-verdict`、`exact-cache-generation-safety` 任务，
  比较 raw、receipt-only、model-selected raw 三组的最终正确性、原始证据保留、
  post-fold exact rechecks 与一轮收口率。
- 只有在真实压力触发、模型自主选证据、选中组完整、checkpoint 持久、
  scope/model/human anchor 未漂移、预算可容纳时才考虑后续 S2 producer；
  无资格则沿用既有 exact-ref 恢复，不因缓存命中低而强制生产 checkpoint。
- StateBraid 只参与**独立 compute A/B**，记录真实 cached/new-prefill、token LCP、
  generation safety；不得让缓存策略决定证据重要性、工具调用或任务完成。

### P2-E｜分模型合同与用户体验

- 对 Ornith MLX / 当前 Qwen3.8 或实际 GGUF 分别核对 `reasoning_replay`、
  `temperature/top_p/top_k/min_p` 的实际下发与后端默认值；
  **当前已有字段不重复开发**，未知后端身份先不做跨模型等价结论。
- 对重复、容量不足、引用不可用、用户取消、外部效果未知分别显示
  「未完成」「已保留证据」「是否可安全续接」；显式 CAS 插话仍按既有用户动作，
  普通排队不自动升级为打断。

**本轮明确不做**：新 `tool_search`、关键词删工具、第二份任务账本、
语义相似度强阻断、全局降低 `max_tokens`、强制开启 WorkingStateCheckpoint
producer、用 StateBraid 接管 LFL 任务决策、自动重放副作用工具、
恢复已退役 `convergence_decide`、为了「防漂移」每轮增加固定 prompt 自检。

## 16. v0.3 新增验收（叠加第 11 节 A01–A16，不重复建设测试套件）

| ID | 既有测试/研究基线 | 本次必须新增或确认的断言 |
|---|---|---|
| B01 | `test_evo_305716fa_repeated_exploration.py` E1–E5 | 在事故预算 3698 下，`repeat_guard` 提示不能被当作已交付事实；压缩后最新工具观察必须 raw/可核验 ref 可见，或在下一 Provider 前 HOLD |
| B02 | `test_tool_working_set_projection.py` + `test_ingress_exempt_lockdown.py` | 原始 assistant→tool 原子组、当前真人任务锚、source version、selected raw 与真实 cache boundary 的保护并集合法且不超窗口 |
| B03 | `test_antidrift_replay.py` + `test_convergence_boundary.py` | `convergence_decide` 不再暴露，直接工具始终可调用；变体探索/合法轮询不因「相似」而被阻断 |
| B04 | `test_loop_stagnation.py` + `test_evo_305716fa_repeated_exploration.py` | 精确重复、交错 A→B→A→B 计数可见，但不能把同参 `wait`、变化中的文件、命令副作用当作可安全复用 |
| B05 | `test_reasoning_tail.py` + `analysis/P0_CAPABILITY_CONTRACT_PATCHSET_2026-09-07.md` | 当前 Ornith `none` / Qwen `full` 的模型级 replay 资格按实际 Provider 身份隔离；不会重新应用 `localhost => -2` 的旧启发式 |
| B06 | `design/WORKING_STATE_FOLD_PRODUCTION_DESIGN-2026-09-06.md` | S1 consumer 生效且 producer 仍 HOLD；研究两任务的 selected-raw 相对 receipt-only 结果在隔离 canary 复测，未重跑时明确「历史证据」 |
| B07 | `StateBraid/docs/SUPPORTED_SCOPE_V0_1.md` + `LLAMA_CPP_MANAGED_STORAGE_M1.md` | 缓存 ON/OFF 只比较 compute 与行为回归；`runtime_qualified=false` 不升级，历史已删除 GGUF 的结果不冒充现行资格 |
| B08 | 事故 `request.meta.influence.history.exact_duplicate_tool_projection` | 复现 `enabled=true, folded_groups=0`，并证明修复不依赖 duplicate fold 恰好命中 |
| B09 | `docs/SPEC-20260922-run-convergence-antidrift-v1.md` 第 10 节 | 普通队列不自动插话；显式 CAS 插话在合法轮边界进入；wake 对象被替代时仅供机械差量事实 |
| B10 | `test_longrun_continuity.py` + `test_recent_continuity_restart.py` | 崩溃/重启/跨 Run 时 exact-ref、模型身份、授权和 WAL 状态复核；未知 Provider/Tool 效果 HOLD，不自动重发 |

验收报告必须分列三组指标，**不能合成一个「防漂移分」**：

- **Compute**：真实 token LCP、cached tokens、new-prefill、generation safety、runtime/model SHA；
- **Evidence/continuity**：最新工具回执可见率、选中 raw 组完整性、exact-ref 恢复率、
  重读次数、真实任务锚保留、provider pairing；
- **Agent/liveness**：同参及交错重复次数、真实 Provider 外发次数、工具副作用未知数、
  任务完成/未完成、合法轮询误拦率、用户显式插话延迟。

先用现有单测 + A/B 任务做**离线 RED**，仅新增缺失的反例；最小代码补修后
执行定向测试，再按既定独立 GLM-5.3 Reviewer（PASS、P0/P1=0）→ 原版完整
R9 exit 0 → GitHub/CI → 受管发布顺序执行。设计文档修订**不等于**
这些测试、Reviewer 或生产验收已经通过。

## 17. v0.3 历史裁决与执行边界（现由第 18 节更新）

**v0.3 当时的设计方向：建议采纳最小修复路线；独立 Reviewer 后续实际返回 HOLD，见第 18 节。**
优先修**「预算挤压导致最新工具观察不可见」**这一条可重放、可测量的接线断点；
保留既有 StateBraid、CK1、Working State Fold、antidrift、E1–E5 和模型级
reasoning replay，不重复造轮子。若离线 RED 证明问题其实出在事故版本与当前
实现差异，先修接线/配置生效链，不贸然扩展内核。

**仍需独立验证**：事故 SHA 的有效工具/模型合同、真实发送前 payload digest、
最小容量不可行时现有 exact-ref 路径是否满足协议、S1 producer 的实际生产资格、
真实 MLX/GGUF 模型身份与 reasoning 通道、当前远端 main 新增 3 提交是否已包含同族修复。
上述未知项不构成批准生产变更的证据。

v0.3 当次操作只修改这份**原有未跟踪 Markdown**；研究仓、StateBraid、LFL 业务源码、
模型配置、其他并行工作树均不修改；不执行 Provider 调用、main 合并、push 或重启。

---

## 18. v0.4：独立 GLM-5.3 审查、反例处置与剩余门禁

### 18.1 首审是有效 HOLD，不是 PASS

- 审查对象：独立分支 `review/local-model-repetition-v03-20261114`，
  冻结提交 `3d735072e7f7b51727be0eaa332b8140467a34ca`，
  **候选文档 SHA256** `70389a9d2df4f5e368d2694e2b8878b4d8b1a9981e628c07e19ede6bfd8db8fc`。
- 真实 `glm/glm-5.3`，`tools=[]`，1 次 Provider 尝试、无自动重试，
  `finish_reason=stop`、`truncated=false`，约 70 秒，
  输入 34,054 tokens、输出 4,041 tokens；结果 JSON 结构与身份核验无错误。
- **裁决：HOLD，P0=0/P1=0/P2=4**；12 项对抗性验收逐项 PASS，
  但事故树、真实后端和 exact-ref 资格等尚有证据缺口。
  审查回执保存在本隔离工作树的 `data/reviews/local-model-repetition-v03/glm53_review_receipt.json`；
  **首审只绑定 v0.3 冻结 SHA，不自动继承到本 v0.4**。

### 18.2 四项意见与处置

| Reviewer 意见 | 本次处置 | 证据/边界 |
|---|---|---|
| F1：冻结候选身份未写入文档 | **改用外部不可自引用的候选清单**记录 `candidate_commit + document_sha256 + review_receipt_sha256`；不把文档自己的 SHA/提交写进正文，因为写入会改变哈希，造成不可能收敛的自引用 | 首审 `3d735072` / `70389a9d…` 由外部 review receipt 绑定；本次 v0.4 需新清单、新审查 |
| F2：初稿 D1–D4/R1–R7 仍像可执行 P0 | 第 3、4、5 节逐项加 `SUPERSEDED` 标记，历史分级不再是当前门禁 | 正式方案仍以第 15、18 节为准；不复活固定字符阈值、第四次自动停止或关键词裁剪 |
| F3：`exact_no_progress_cycle` 可能误拦 | 在第 10 节将它降为**诊断**；机械 HOLD 必须同时证明「最终 Provider 视图无原始最新交换/合法 exact-ref」和「真实容量/授权/来源版本使两者都无法交付」 | 若 ref 可见、原始组可见、可变轮询有新版本，均不能用指纹相似阻断 |
| F4：重复提示放大器只引当前源码 | **补事故树 + EventLog 直接交叉核验** | 事故 release tree HEAD 精确为 `103e9730de049f3b9715b1429d51d0e17d8fee5c`，tracked clean；`tool_cycle.py:258–310` 尾部追加 hint，`persist_finished` 在构造 tool message 前调用；EventLog `seq=85` tool 回执含 `[repeat_guard]`，`seq=87/88` 归档该交换，`seq=96` 下一轮仍为 2 条消息 |

**特别注意 F1 的纠偏**：Reviewer 提议把候选 SHA 和文档 SHA「写入文档头部」，
但自包含文档不可能同时稳定保存自身字节哈希与提交哈希。
正确做法是外部审查清单和不可变 Git 对象绑定；不能为了迎合审查意见引入循环更新。

### 18.3 新补充的只读事实

1. 事故 `git_head=103e9730…` 对应的本机 `.releases/103e9730…` 工作树存在、
   HEAD 精确匹配且 tracked clean。相关 `tool_cycle.py`、`history.py`、
   `history_projection.py`、`compaction_gate.py`、`routing.py`
   对比当前本地 `main=71f9572…` 的 Git diff 均为零；
   因此至少这些关键路径**没有事故树到当前本地 main 的源码漂移**。
   这不证明 live backend/config 与代码 SHA 一致。
2. 事故 EventLog 冻结只读采样：`last_seq=2509`、
   `sha256=01ca4d749bed93d80640dd53cfbb040bb394fa4e0c77cb3bc1318e286089a556`；
   首 Run 前 8 轮的 `request.meta` 均为 `messages_count=2`、
   `history_chars=3246`、`tools_count=101`、`provider_structure_fp=de0a18705a0240c813b0044e`、
   `tool_schema_reserve_tokens=28659`、`effective_history_budget_chars=3698`，
   `exact_duplicate_tool_projection.enabled=true` 且 `folded_groups=0`。
   这**不是**实际 HTTP 字节级同一性证明。
3. 本地 `origin/main` 追踪引用比本地 main 多 3 提交，
   `git diff --name-only main..origin/main` 显示仅
   `tools_task.py`、两份 task 测试及一份治理材料，
   **未改动本事故所涉 history/compaction/routing/tool_cycle 路径**。
   这是本地追踪引用的只读事实，尚未以新的远端 fetch 证明最新状态。

### 18.4 v0.4 后续严格顺序

1. **候选外部清单**：为本 v0.4 文档冻结新 commit、document SHA、所引用事故/研究证据
   SHA；首审 HOLD 不复用为新 SHA 的 PASS。
2. **剩余 P0-A 只读核验**：确定事故时有效 Provider/模型/后端、配置哈希与真实传输前字段；
   用离线 RED 证明最终 Provider 视图是否确实丢失最新回执，以及已有 exact-ref
   是否可按 scope/version/paging 真正恢复。不能把未复现的 `context_capacity_unavailable`
   方案称为已验证修复。
3. **新候选独立复审**：审查 v0.4 的精确候选 SHA、上述新增事实和剩余未知项；
   要求真实 completed/PASS、P0/P1=0，审查工具与代码变更权限为零。
   在此之前**不进入业务代码补修**。
4. **仅在设计 PASS 后**：独立实施工作树、最小 RED→GREEN 修复、专项回归、
   冻结代码候选、**再次**独立 GLM-5.3 代码审查、原版完整 R9 exit 0。
   main/远端 CI/受管发布与重启仍遵循独立门禁和授权，不由设计 PASS 自动放行。

**本阶段未授权事项**：不得因为 v0.3 的 P0/P1=0 就将 HOLD 解释为 PASS；
不得自动重发事故 Provider/Tool、清理未知副作用、修改模型生产配置、
开启 S1 producer、复活 `convergence_decide` 或跨越现有 M5 Goal。
