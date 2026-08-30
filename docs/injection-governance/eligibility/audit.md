# Prompt Eligibility Audit — resolved is retrievable, not injectable

状态：**AUDIT PASS / IMPLEMENTATION NOT STARTED**
基线：`31df1a3 test(injection): validate R8 shadow soak`
日期：2026-08-30
范围：只审计当前 prompt surface；**本阶段不修改 production `src/` 行为，不启动 behavior canary，不进入 R9**。

## 1. 为什么在 R8.3 之后新增这一门

R1-R8 已经解决了来源标记、预算、去重/指针化、recovery one-shot、identity summary、user truth 尾位和 capability shadow 等问题，但这些机制主要回答：

> “一段程序信息如果要进入 prompt，应该如何标记、压缩、排序、预算和归因？”

本审计回答更前置的问题：

> **“它到底有没有资格进入 prompt？”**

Owner 明确冻结的新原则：

> **已经解决并回答完成的用户任务/问题，退出自动上下文；原问题、答案、工具过程和历史细节只保留在可检索索引/档案中。模型后续确需回看时，通过 ref/index 主动检索并精确 hydrate。**

这一原则的目的不是删历史，而是把“工作上下文”和“历史知识库”分离：

```text
Working Context
  = 当前用户原话
  + 仍未完成的 active task state
  + 当前仍有效的 durable constraints
  + 当前轮无法由程序自行处理的必要 evidence/control

Indexed History
  = resolved Q&A
  + resolved tool chain
  + old reasoning
  + consumed recovery/notice
  + superseded decisions
  + observability/audit data
```

后者默认 **0 字符自动进入 provider prompt**。

## 2. Eligibility 必须位于 Budget 之前

现有链路大体是：

```text
program material
  -> classify REFERENCE / STATUS / PROGRAM_RECOVERY
  -> R2 keep/drop budget
  -> R8 profile（当前仅 shadow）
  -> R6 wire
```

目标顺序应改为：

```text
material
  -> lifecycle / eligibility gate
       RESOLVED      -> archive/index only
       CONSUMED      -> archive/index only
       SUPERSEDED    -> archive/index only
       OBSERVABILITY -> event/tool/UI only
       ACTIVE        -> 再判断 REQUIRED_NOW
  -> representation gate
       可按需检索 -> ref/tool，不给正文
       必须正文   -> eligible inline
  -> model profile
  -> R2 hard budget
  -> R6 exact-user wire
```

**Budget 只能限制“有资格进入”的内容，不能把“不该进入”的内容合法化。**

同样，`ref` 本身也不是自动注入许可证。若模型已经有稳定工具入口，目录/索引默认也应留在 prompt 外。

## 3. 冻结生命周期规则

### E1 — RESOLVED

已经得到最终回答、已完成的任务节点、已消费的工具证据，不再自动回放。

目标：`archive/index -> search/hydrate on demand`。

### E2 — CONSUMED

只对某一次 run/turn 有意义的控制信息，在被消费后立即退出 provider view。例如 recovery、stagnation/overflow/round-exhaustion 控制。

### E3 — SUPERSEDED

被新决定覆盖的旧模型、旧参数、旧方案、旧路径、旧约束正文退出 prompt。只把当前 effective value 留在 active state；历史版本可检索。

### E4 — OBSERVABILITY

cache、budget、profile、architecture、自评、审计、provider 状态等如果程序/UI/工具可以查询，默认不得主动占用模型注意力。

### E5 — ACTIVE + REQUIRED_NOW

只有仍活跃、且本轮缺少它就可能错误完成当前用户任务的信息，才具备 prompt eligibility。

即使 eligible，也优先：

```text
program can handle -> 程序处理，0 prompt
tool can retrieve  -> ref/tool，0 正文
must be inline      -> 进入 profile + R2 budget
```

## 4. 三种审计状态

- **DONE**：当前代码已经把该类内容从未来 provider prompt 排除/退休，且有结构证据。
- **PARTIAL**：已经降密、去重、指针化或局部过滤，但仍存在自动可见路径。
- **OPEN**：当前行为仍与 Eligibility 原则冲突，或生命周期门缺失。

注意：`PARTIAL` **不得**被解释为“已经做过不注入”。例如 R3 把正文缩成两行 ref，只代表降低密度，不代表该 ref 已退出自动 prompt。

本轮机器矩阵共审计 **34 个 prompt surface**：`DONE=6`、`KEEP=1`、`PARTIAL=12`、`OPEN=15`。其中 9 项列为 behavior-canary blocker。具体逐项状态以 `eligibility/matrix.json` 为准，后续实施时直接更新该矩阵而不是另建一份口径。

## 5. P0：behavior canary 前必须解决的 Eligibility 缺口

### P0-1 resolved Q&A / tool chain 没有退休边界

当前普通 `user -> assistant/tool -> final assistant` 仍作为 `sess.messages` 进入后续 history，直到预算/compact 触发。系统没有“该 episode 已 resolved，因此下一独立任务默认不再投影”的 provider-view gate。

这正是本审计的首要根因：**conversation storage 被当成 working context。**

目标不是删除 session 原文，而是在新 human turn 建立 provider view 时：

1. 当前/明确 continuation episode 保持 active；
2. resolved episode 退出默认投影；
3. 如果当前用户显式引用旧问题，再按索引 hydrate 所需片段。

### P0-2 立即退休之前，resolved episode 还缺完整 retrieval coverage

现有 `search_archive` 明确主要检索“被压缩的历史/超长结果”；普通尚未 compact 的 resolved conversation 并不会天然进入 ArchiveStore。`search_records` 的 kind 也没有 raw session-conversation 索引。

因此不能直接“过滤 resolved history”然后声称信息零丢失。实施前必须先闭合：

```text
resolved episode
  -> durable episode index/archive
  -> stable ref
  -> exact/keyword hydration
  -> provider-view retirement
```

这是 **retire-before-delete 的硬前置**。

### P0-3 `model_switch_notice` 会主动复活旧任务

`src/llm_loop/core/loop/interop.py:225-289` 当前会：

- 读取最近 user + assistant；
- 复制为“用户最近指令 / AI 最近进度”；
- 添加“切换不改变任务：继续推进当前会话任务”；
- `persisted_injection=True` 写入 session。

如果上一任务已经 resolved，这会同时复制旧 user truth、旧 assistant state，并由程序重新下达“继续”命令。

目标：model switch 是 routing/runtime 状态，默认 **0 prompt**。若确需恢复 active task，只读取 canonical active-task ref，不复制聊天文本。

### P0-4 `declaration_reminder` 在 final answer 之后持久化，天然只能污染下一轮

`src/llm_loop/core/loop/engine.py:920-947` 在最终回答已生成后检查声明-回执；不一致时 append 一个 `role=user` 的 `declaration_reminder`，随后 `break`。

机械验证：该消息 `role=user`、`persisted=True`，`history._is_injected_system()` 返回 false，因此 `skip_injected_system=True` 无法过滤它。

这条信息来不及修正当前 final answer，只能进入未来 turn。

目标：声明一致性进入 audit/UI，或在**当前回答交付前**纠正；不得生成下一轮 stale prompt message。

### P0-5 `Evidence Recovery Manifest` 是“可检索索引却仍每轮自动注入”，并旁路 R2

当前 `.env` 为 `EVIDENCE_MODE=enforce`。`src/llm_loop/core/loop/build.py:892-905` 每次 build 调用 `evidence_recovery_manifest()`，随后直接：

```text
built.append({"role": "user", "content": manifest})
```

该 manifest 自己已经告诉模型使用 `list_evidence/search_evidence/read_evidence` 精确取回；因此按 Eligibility 原则，**索引本身也不应每轮自动进入 prompt**。

同时该 append 发生在 R2 `_inject_parts` 之外，是统一 injection budget 的旁路。

目标：manifest 留在 evidence ledger/tool surface；只有明确 recovery dependency 时才按 ref hydrate。

### P0-6 Cognitive packet 在未来 applied 时会扫描历史全部 `memory_snapshot`

`src/llm_loop/core/loop/build.py:1151+` 的 `_packet_parts` 会遍历 `sess.messages`，把所有 `injection_kind=memory_snapshot` 加入 packet compiler 输入。

R8 当前 `applied=false`，所以 R8.3 没有行为问题；但如果直接启动 behavior canary，profile 可能把历史 stale memory 再投影出来。

因此：**Eligibility gate 必须同时位于 flat `_inject_parts` 与 Cognitive `_packet_parts` 之前。** 这也是本审计将 behavior canary 继续冻结的主要原因。

### P0-7 local 每轮固定“行为提示”不是用户任务，也不是稳定控制面

`src/llm_loop/core/loop/build.py:979-995` 对 `provider_id == "local"` 每轮追加尾部提示，包括：

- “给具体动作”；
- “改≤3文件自主执行、>3或涉生产先列方案”等程序默认规则；
- “不确定先 search_records/search_archive”。

它没有绑定当前 user task，并且包含 command-shaped 行为规则。若这些规则是真正全局 policy，应属于稳定 system/rules；若只是评测补丁，则不应进入生产 prompt。

目标：从 dynamic tail 删除。任何真正有效的全局规则只允许进入稳定、权威的 system control plane。

### P0-8 未知 program slot 当前 fail-open 为 `STATUS`

`src/llm_loop/core/injection_labels.py` 的未知 slot 会安全降级为 `STATUS`，`build.py` 随后继续让其参与聚合/预算。

这对 R1 的“来源不可伪装”是安全的，但对 Eligibility 是 fail-open：未来模块只要往 `_inject_parts` 塞内容，就可能自动获得 prompt 资格。

目标：**unknown eligibility = deny/not-eligible**。显式 allowlist 的 prompt-capable producer 才能进入后续 profile/budget。

## 6. P1：应退出自动 prompt 或收敛为 active-ephemeral

### 6.1 `memory_snapshot` / `experience_tip`

R3 已完成 K=3、pointerization、seen-set、command neutralization；但 `turn_context.py` / `tool_exec.py` 仍把产物以 `persisted_injection=True` 写入 session。

目标生命周期：

```text
current active turn -> 最多 ref/必要事实
turn/episode resolved -> retrievable_only
```

`turn_ref` 已经提供了天然的生命周期身份，不应继续把“最近 K 轮”当成资格本身。

### 6.2 `session_digest_catalog` / compact archive pointer

R3 已把旧正文回灌退役为 ref/两行状态，这是正确的降密；但在稳定 `search_archive` 工具已经存在后，目录本身仍不一定需要自动出现。

目标：默认 tool-only。只有当前 active task 明确依赖已归档内容且程序无法自动 hydrate 时，才给特定 ref。

### 6.3 hotcard

当前 `pop_hotcard()` 的主要门是“未消费 + 来源 session != 当前 session”。**跨 session 不等于 continuation。**

目标：只有显式 continuation（如“继续上次任务/恢复 X”）或 canonical active goal 绑定成立时 hydrate；普通新 session 不自动看到上一任务存在。

### 6.4 stagnation / empty-search / overflow / fallback / round-exhaustion

这类内容如果仍需要模型参与，只能是**当前 unresolved run 的 ephemeral control**，run 结束后立即 consumed，不得跨下一 human turn。

其中 round-exhaustion 发现一个确定性缺口：

1. `max_iterations_decision_message()` 原文以 `[轮次决策请求]` 开头；
2. R1 后先经 `render_program_appendix()`，实际首行变成 `[程序附录·非用户输入] ...`；
3. run-end consumer 仍检查 `content.startswith("[轮次决策请求]")`；
4. 机械验证结果：`legacy_consumed_predicate=False`，且 `_is_injected_system=False`。

因此现有“run 后 consumed”机制不能按文档假设视为已闭环。

### 6.5 gate note / budget receipt

`GATE_NOTE_CONTENT` 本身写着“你无需处理”；这类 cache/budget 事实天然属于 observability。

目标：event / `architecture_status` / UI，0 prompt。

### 6.6 interop

必须按语义拆分：

- `notify` / job completed：event/UI，默认 0 prompt；
- `coordinate/task`：只有真正成为当前 active task 时才 eligible；
- backlog count：observability，不需要模型每轮知道。

当前代码对首次 `topic=notify` 仍会注入，属于 OPEN。

### 6.7 Task Frontier

当前 active goal 有 task graph 时，每次 build 都可自动渲染 frontier。任务图本身是程序状态，不应因为“存在”就获得 prompt 资格。

目标：只给当前真正需要模型决策的 active node/constraint；全图、blocked/unreachable 详情走 `task_frontier()` 按需查询。completed task 只留历史索引。

### 6.8 tool schemas

Tool schema 虽不叫 injection，但同样占 prompt/attention。

当前 local provider 已做固定核心白名单 + `get_tool_schema` 按需读取，属于 PARTIAL；非 local provider 仍默认全量 schema。

目标：稳定 core tools + task-relevant schemas；其它工具通过 schema discovery 按需展开。

### 6.9 historical reasoning

当前 `.env REASONING_TAIL=-1`：非 tool-call reasoning 在 provider view 省略；云端仍保留所有历史 `assistant(tool_calls)` reasoning 以满足协议。active session storage 中 reasoning-bearing messages 数量远高于最终回答数。

目标：只保留 provider 协议当前仍要求的最小 tool-pair reasoning；resolved episode 的 reasoning 进入 archive/index，不作为工作上下文。local endpoint 已有 `-2` 全省略路径，是正向先例。

## 7. 已经真正 DONE 的“不注入”工作

以下不能重复立项：

1. **R4 legacy/program recovery**：旧 persisted recovery 在 build provider view 过滤；新 recovery 是 per-session one-shot slot，匹配当前 human turn，build 消费即清空。
2. **R5 identity Q&A derived summary**：identity detail 不再进入长期 derived summary；raw archive 保留可检索。
3. **R6 user truth**：程序内容不得追加在 current user truth 之后；exact user text byte-for-byte 尾位。
4. **push-style injected_system observability**：architecture/self-eval/proc-stale/预算预警/轮数预警等带 `injected_system` 的 system message 由 `skip_injected_system=True` 排除 provider view。
5. **cache telemetry line**：legacy assistant cache telemetry 在 build provider view strip，权威数据走 telemetry。
6. **R8 capability shadow telemetry**：`injection.profile.shadow` 是 event，不进入 provider payload，R8.3 证明 `applied=false`。

注意：上述 DONE 只表示特定 surface 已退出 provider prompt，不表示整个 Eligibility 已实现。

## 8. 运行数据只读取证（不是 wire 计数）

对当前 workspace `data/sessions/.../*.json` 做**只读 metadata/长度统计，不输出正文**。

### active sessions

```text
sessions=62
messages=11061
tool messages=4428
reasoning-bearing messages=3840

memory_snapshot=382   (~410243 stored chars)
experience_tip=118    (~47746 stored chars)
model_switch_notice=21
session_digest_catalog=5
declaration_reminder=3
```

### 2026-08-30 更新的 sessions

```text
sessions=15
messages=780
tool messages=250
reasoning-bearing messages=219

memory_snapshot=59
experience_tip=20
model_switch_notice=10
session_digest_catalog=5
declaration_reminder=3
```

这些数字是**持久化 surface 存在性证据**，不是“当前请求一定发送了多少”。history/compact/provider filtering 会改变 wire；后续实施必须新增 provider-view eligibility telemetry 才能精确量化退役收益。

## 9. 建议的统一 Prompt Eligibility Gate

未来实现不应给每个来源继续打独立补丁，而应建立一个中央 gate：

```text
EligibilityDecision
  source_id
  lifecycle = active | resolved | consumed | superseded | observability
  required_now: bool
  retrieval_ref: str | None
  disposition = inline | ref | tool_only | archive_only | drop_from_provider
  reason_code
```

要求：

1. Gate 在 R2 budget 和 R8 profile **之前**执行；
2. flat history、dynamic `_inject_parts`、Cognitive `_packet_parts`、evidence manifest、tool schema surface 使用同一 eligibility 语义；
3. unknown producer 默认 deny；
4. `drop_from_provider` 不删除 storage/audit truth；
5. resolved/consumed retirement 必须先有可验证 retrieval ref；
6. current human truth、assistant/tool protocol pairing、system provider contract 不得被 eligibility 破坏；
7. 每个决定产出只读 telemetry，至少能回答“为什么这一块没有进入 prompt”。

## 10. Behavior Canary 前置门

R8.3 虽已 PASS，但本审计发现 P0 eligibility 缺口，因此 **behavior canary 继续 NOT STARTED**。

至少满足以下条件后才重新讨论 canary：

```text
resolved episode searchable = 100%
resolved episode auto-visible = 0
consumed control next-turn visible = 0
superseded state auto-visible = 0
observability-only prompt chars = 0
unknown injection producer eligible = 0
evidence manifest budget bypass = 0
flat / packet eligibility decision parity = 100%
exact user truth / tool pairing / provider wire regressions = 0
```

## 11. 审计结论

R1-R8 主要解决了“注入怎样更安全”；本轮审计确认下一层根因是：

> **conversation/archive/control-plane 的生命周期没有完全从 provider working context 中分离。**

因此下一实现阶段应围绕 **Prompt Eligibility / Resolved Episode Retirement**，而不是继续单纯降低 budget 或直接启用 minimal/full behavior profile。

权威机器清单：`docs/injection-governance/eligibility/matrix.json`。
