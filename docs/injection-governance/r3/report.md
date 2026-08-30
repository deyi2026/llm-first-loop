# R3 验收报告：资料按需化 + 指针化 + 会话级去重

> Goal: `53591825-39d9-4259-8eb2-a07b356fdbf1`
> 基线: mirror `768ba03`（R2/L2-1 PASS）
> 结论: **R3 PASS**

## 1. 本阶段边界

R3 只治理自动资料上下文：

1. 前 K 个真实 human turn 或显式任务切换时才允许自动资料目录；
2. 每个自动资料帧最多两行：一句中性事实 + `ref`；
3. 同一 session 同一 stable ref / 规范化内容 hash 的完整正文最多自动出现一次；
4. 后续重复默认省略，显式任务切换时相关 memory/experience 最多重给一行 ref；
5. compact 后 seen 状态仍可重建；
6. `search_records` / `search_archive` / evidence reader / `read_file` 等主动取回能力保持不变。

本阶段**没有**实现 R4 程序恢复单边界、R5 身份问答剥离、R6 用户原话尾位 / provider wire invariant，也没有做 R7 行为 A/B。

## 2. 状态架构：不新增第二份 Session 真相源

R3 没有新增 `Session.seen_injection_set` 顶层状态。

`seen_injection_set` 由已经持久化的 `sess.messages[].metadata` 重建：

- `reference_key`: 单帧稳定身份；
- `reference_keys`: 聚合目录内所有帧身份；
- stable ref 存在时优先使用 `ref:<stable-id>`；
- 无 stable ref 时使用规范化内容 SHA-256 前缀：`hash:<source>:<digest>`；
- 升级前的历史消息还会从可见 `ref=...` 兼容恢复 seen 状态。

因此 compact 只改变 provider 投影视图，不需要同步第二份状态；Session 原始消息和 metadata 仍然是 seen-set 的持久来源，新 session 自然重置。

单一策略实现：`src/llm_loop/core/reference_injection.py`。

## 3. 自动资料窗口

新增候选参数：

`REFERENCE_AUTO_TURNS=3`

规则是确定性的：

- human turn `1..K`: 允许自动资料目录；
- `K+1` 之后：默认不自动检索 / 不自动注入资料正文；
- 显式任务切换词（如“换个话题”“新任务”“switch task”等）临时重新开放一次目录。

`K=3` 仍然只是 R0 冻结后的**候选默认值**，不是生产最优常量；最终值留给 R7/L3 A/B。

R3 不引入 LLM/embedding 来判断“是否任务切换”，避免门控本身变成新的非确定性来源。

## 4. 各资料源迁移

### 4.1 Memory

`memory/retrieve.py` 仍保留原关键词 / semantic mixed 检索能力，但自动投影变成：

```text
[memory:<type>] <一句中性事实>
ref=memory:<entry-id>
```

- 命令形态历史不直接内联；
- stable memory id 是去重主键；
- 已 seen 时普通轮零正文；
- 显式任务切换时，相关旧 ref 最多一行，新 ref 才允许两行事实+ref；
- turn `K+1` 在 gate 关闭时连自动 memory search 都不执行；
- `mark_injected` 只统计真正进入目录的条目，不给被去重的条目虚增使用次数。

### 4.2 Experience / Skill

工具后经验提示也使用同一 front-K / task-switch / seen-set 规则：

```text
[experience:<tool>] <一句事实>
ref=experience:<id>
```

或：

```text
[skill:<name>] <一句说明>
ref=skill:<name>
```

旧的长经验正文和命令式 `skill_load` 建议不再作为自动资料正文回灌。

### 4.3 SessionDigest

旧行为是每轮把所有成功工具摘要全量重新注入。

R3 保留 `SessionDigest.render()` 作为诊断兼容视图，但自动 prompt 改用 `render_reference_frames()`：

```text
[digest:<tool>] <一句工具结论>
ref=digest:<tool_call_id>;archive_tool=<tool>
```

只在允许窗口注入尚未 seen 的 digest block；其 reference metadata 持久化回 Session，因此后续 build 不再全量重放。

### 4.4 Compact / Archive

R3 取消 compact 时自动把旧正文通过以下路径重新灌回 prompt：

- `[压缩关键事实]`
- `[压缩档案目录]`
- 归档消息前 60 字符拼接摘要

当前只保留两行可检索状态：

```text
[上下文压缩] ...旧正文未自动内联。
ref=archive:search_archive
```

归档原文仍完整写入 ArchiveStore，`search_archive` / `search_records(kind=archive)` 路径不变。

### 4.5 Task Hot-Card

Hot-card 的完整 JSON 仍保存在 `data/handoff/task_hotcard.json`，消费 / replay / recovery 语义没有在 R3 改造；这些属于 R4。

R3 只把自动可见表示压成两行，不再内联旧 anchor/objective/checkpoint-next：

```text
[任务热卡] 上一会话任务接力资料已保存；anchor=<0|1>; active_goals=<N>; pending_review=<N>。
ref=file:<data_dir>/handoff/task_hotcard.json
```

需要完整内容时可用 `read_file` 主动读取。

## 5. 去重与可观测性

Memory / Experience 在稳定 ref 被重复命中且正文被抑制时记录：

`injection_duplicate_suppressed`

detail 含 `source/ref/key`，不含被抑制的长正文。

同 turn 因 gate / dedup 得到零消息时，用临时 `turn_ref` checked 标记避免工具循环内重复检索；这不是持久 seen SoT，仅用于同 turn 操作幂等。

## 6. 额外根因发现：旧 anchor 测试是“伪 PASS”

R3 移除 `[压缩关键事实]` 后，一个既有 anchor 测试首次真实变红。

根因不是 R3 删除了用户任务，而是旧 `history.py`：

1. “锚点保护区”把最后真实 user 之后的 program-user 注入也算进必须保护体积；
2. memory/status 噪声足够大时，保护区整体超预算，`_anchor_protect_valid=False`；
3. 真正的用户任务因此被归档；
4. 随后 `[压缩关键事实]` 又把任务文字复述回 prompt，旧测试只搜索字符串，因此误以为锚点被保留。

R3 修复为：

- 保护对象只包含真实对话 atomic groups；
- program-only user 块不能获得用户任务同级保护，也不能使用户保护失效；
- head 预算确定后再计算 anchor zone；
- 极端 fixture 验证 exact original user message 保留，且该原消息未被 archive。

这比恢复关键事实摘要来“让测试变绿”更符合用户真话优先原则。

## 7. 可证伪验收

### 7.1 R3 专项

`tests/unit/test_reference_injection_policy.py` + `tests/unit/test_reference_injection_integration.py` 覆盖：

- stable ref 优先 / 无 ref hash fallback；
- seen-set 从 durable metadata 重建；
- K=3 前置窗口与显式 task switch；
- 首次帧 <=2 行；重复 0 行 / switch 最多 1 行 ref；
- command-shaped 历史中性化；
- compact-style provider projection 不影响 seen-set；
- `REFERENCE_AUTO_TURNS` 默认/override/0 下界；
- memory 第 4 turn gate 关闭后不再执行自动 search；
- task switch：seen memory 只给 ref，新 memory 给事实+ref；
- experience 同样满足 gate + pointer-only replay；
- SessionDigest 两行投影且 seen 后不重放；
- hotcard 两行 file pointer，不内联旧动作句；
- compact 保留 exact human anchor，不依赖摘要 echo。

针对 `09c44093` 的 x18 重复 trap：把 K 临时放宽到 20 隔离 gate 因素，同一个 `memory:m1` 实际 search 18 次，**完整 snapshot 仍只有 1 条，正文只出现 1 次**。

### 7.2 广回归

R1/R2/R3/Cognitive/1210/History/Digest/Retrieval 共 **237 tests PASS**。

主动检索验证包含：

- `tests/unit/test_search_archive_summary.py`
- `tests/unit/test_archive_search.py`

### 7.3 R2 预算非回归

R3 后重新跑 `off/shadow/enforce × 512/700/900/2000/8000` 共 15 点矩阵。

每一点均满足：

`actual program-origin chars <= R2 accounting used_chars <= budget`

例如：

- off/512: used=316, actual=246；
- shadow/2000: used=1745, actual=1596；
- enforce/2000: used=1745, actual=1428；
- enforce/8000: used=2220, actual=1408。

R3 没有绕过 R2 中央 budget assembler。

### 7.4 R0 frozen

R0 analyzer 重放：**PASS**。

`git diff -- docs/injection-governance/r0` = **0 bytes**。

R0 历史数字保持不变，不用新实现倒改基线。

### 7.5 静态质量

- touched production Python `py_compile`: PASS；
- touched production Python `pyright`: **0 errors / 0 warnings / 0 informations**；
- `ruff`: 当前环境未安装，不冒充 PASS；
- pytest 现有 `audit_test_side_effects` 21 条低风险 URL 告警仍为既有告警，不属于 R3。

## 8. 明确未做

R3 没有：

- 改 `auto_continue` / 1210 recovery 的次数、动作或单边界规则（R4）；
- 做 identity Q&A 剥离（R5）；
- 重排 user truth 到物理尾位或新增 provider wire contract（R6）；
- 按模型 minimal/standard/full 分档（R8）；
- 做弱模型行为 A/B 或把 K=3 宣称为最终值（R7）。

因此 R3 PASS 的含义是：**自动资料已经从“每轮全文投喂”进入“受控窗口 + 两行目录 + session 级一次正文 + 主动检索”的结构时代**，而不是整个注入治理专项已经结束。

## 9. Clean-checkout 基线完整性债务 — ✅ CLOSED

R3 提交后 detached clean-worktree 曾在 collection 前失败。根因不是 R3，而是更早的 prefix-layer PoC 提交遗漏文件：

- `engine.py` 自 commit `5e110ae` 起 unconditional import `llm_loop.tools.prefix_layer`；
- `prefix_layer.py` 与专项测试当时存在于工作区，但未被 git 跟踪；
- 因此 `256e9fb` 的纯 git checkout 需要人工 overlay 才能 import `LoopEngine`。

该仓库完整性债务已在独立提交 **`d7ec87c fix(prefix): restore layered prefix integrity`** 关闭，且没有夹进 R3 hardening：

- 只提交 `engine.py`、`prefix_layer.py`、`test_prefix_layered.py` 三个文件；
- 同时修复两个启用态 P1：prefix 动态状态改为 session-scoped，且动态 schema 匹配改用当前 user turn，而非长历史第一条 user；
- detached clean checkout 无任何 untracked overlay 时 `LoopEngine` import PASS；
- prefix 13/13、邻接 40/40 PASS；pyright 0/0；验证后 clean worktree 仍为空。

## 10. Post-R3 adversarial audit — ✅ PASS

R3 机械验收后又做了一轮“构造反例优先”的独立审查。目标不是重复跑原测试，而是验证 R3 的三个核心承诺是否真的闭环：**seen-set 不可被用户污染、ref 必须可主动水合、task-switch 不能轻易误开资料窗口**。

### 10.1 审查前可复现的 P1

1. **human ref poisoning**：真实用户消息只要包含 `ref=memory:m1`，旧 `seen_injection_set()` 就会把它当成“程序已注入过”，从而抑制首次自动事实帧。
2. **memory / experience 假指针**：自动帧虽然显示 `ref=memory:<id>` / `ref=experience:<id>`，但 `search_records` 用该 ref 查询返回空；只能猜内容关键词才能命中。
3. **task-switch 过宽**：`转到第3页看看`、`接下来处理测试失败`、`重新开始这一步` 均被误判成新任务，K+1 后会重新开放自动资料目录。
4. **memory 显式检索 scope 缺口**：`RecordSearcher._search_memory()` 未传当前 session_id，空查询也会枚举 session-scoped memory；这与 memory store 的会话隔离契约不一致。
5. **digest ref 不能按 ref 找回 archive**：`digest:<tool_call_id>;archive_tool=...` 只是一段描述，ArchiveStore 搜索域不含 `tool_call_id/id`，按 ref 查询为空。
6. **semantic memory scope 绕行**：`SemanticRetriever._candidates(scope="memory")` 直接遍历 `memory.all()`，未按 `scope=session/source_session_id` 过滤；自动注入虽在后段再次过滤，但 semantic 候选生成与显式 search 仍不满足单一会话隔离契约。

### 10.2 Hardening

- seen-set 只接受 canonical program/reference metadata，legacy `ref=` 文本回退也仅允许已识别的 program reference 消息；canonical user text 永不写 seen-set。
- task-switch detector 收紧为明确任务切换词（如“新任务/换个话题/接下来换一个任务”）；同任务导航、重试、改方案不再重开 catalog。
- `search_records(kind=memory, query="memory:<id>")` 支持 exact hydration，并强制 global/session scope；keyword/空查询同样带当前 session_id。
- `search_records(kind=experience, query="experience:<id>")` 支持按 ExperienceStore ID 精确水合。
- ArchiveStore 搜索域加入 archive id / tool_call_id，并识别 `archive:<id>` 与 `digest:<tool_call_id>;...`，因此 digest pointer 在原工具结果进入 archive 后可直接按 ref 找回。
- SemanticRetriever 在 memory candidate generation 阶段即按 session scope 过滤；自动注入与 RecordSearcher 均显式传当前 `session_id`，不再依赖结果末端二次过滤兜底。
- memory / experience / skill 同一次 retrieval 的 stable-ref 也做局部去重，防上游重复结果在单个 catalog 内生成两份完整正文。
- hash fallback 继续保持“同 source + 规范化内容”身份：仅折叠空白/大小写；内容变化或 source 不同不会碰撞。

### 10.3 对抗式证据

`test_reference_injection_policy.py` + `test_reference_injection_integration.py` 现在覆盖并通过：

- 真实 human `ref=` poisoning = 0；legacy program ref 仍可迁移去重；
- 真实 `SessionStore.save -> 新 SessionStore.load` 后 seen-set 可从 durable metadata 重建；
- `memory:<id>` / `experience:<id>` exact ref 可导航；session memory 不跨 sid 暴露；
- `digest:<tool_call_id>;...` 在 ArchiveStore 中可按 ref 精确找回；
- `build_history_messages -> ArchiveStore -> RecordSearcher` 可找回 compact 原文；
- 同次 memory / experience 重复 stable ID 均只产生一份完整帧；
- 同任务导航短语不触发 switch，明确换话题/新任务仍触发；
- hash fallback 的 whitespace/case 规范化成立，语义变化和 source 边界不被错误合并。
- semantic memory candidate：其他 session 的 private memory 在候选生成前即被排除；`test_semantic_wiring.py` 同时锁住主循环 semantic 调用携带当前 sid。

专项 policy/integration 共 **26/26 PASS**。

### 10.4 Post-audit 回归门

在原 R3 验收之外，post-audit 扩展集合实际 collect **281 tests**，覆盖 R1/R2/R3、History/Compact、Digest、Archive/Search、CR-R1 mode/state/projection/barrier/invariants、Cognitive compiler/state/integration，结果 **281/281 PASS**。

冻结门：

- R0 analyzer：R0-1~R0-4 全 PASS，`docs/injection-governance/r0` **0-byte diff**；
- R2：`off/shadow/enforce × 512/700/900/2000/8000` 15 点全部满足 `actual <= accounting used <= budget`；
- touched production `py_compile` PASS；
- touched production `pyright` **0 errors / 0 warnings / 0 informations**；
- `git diff --check` PASS；
- `ruff` 仍未安装，不宣称 lint PASS。

该审查仍**没有进入 R4/R5/R6/R7**：未改变 recovery 次数/边界、未做身份问答剥离、未重排 user truth/wire，也未把 K=3 升级为最终值。
