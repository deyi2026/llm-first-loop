# R6 验收报告：User Truth 物理尾位 + Provider Wire Invariant

状态：**PASS**
基线：`8107ea9 fix(injection): harden R3 reference contracts`

## 1. 目标

R6 只解决最终 provider view 的结构归属，不改 Session / event-log 的事实顺序：

`stable system → history → program appendix → fixed boundary → exact user truth`

硬不变量：

- 本轮真实用户原文 byte-for-byte 保留；
- 初始 human-ingress 请求中，用户原文只作为最终 semantic tail 出现；
- program-origin user 内容不得位于本轮用户原文之后；
- 有 program appendix 时只生成一个 user envelope，禁止 `user(real)+user(program)` 连续 user；
- tool-followup 不重复/搬运用户原文，保持 `assistant(tool_calls) → tool(result)`；
- R6 不改变 R4 recovery 动作策略、R5 identity stripping、R7 A/B、R8 model tiering。

## 2. 根因

R6 前的 build 先让 `build_history_messages()` 输出真实 user，再把 memory/interop/tip/hotcard/gate/Cognitive 等程序附录 append 成尾部 user。Direction-C 虽把部分持久化 program-user 合并到前一条 user，却采用：

`user truth + "\n\n" + program appendix`

所以它只能减少连续 user 数量，不能满足“用户原文最后”。production-shape fixture 实测尾部仍为：

`system → user truth → program user`

## 3. 实现

### 3.1 Provider-view 单 envelope

新增 `src/llm_loop/core/user_truth_wire.py`：

- `current_ingress_user_truth()`：只在人类初始 LLM round 返回 canonical human truth；一旦 current turn 后已有 assistant/tool 或第二条真实 human，则返回 `None`。
- `project_user_truth_tail()`：只改 provider view，不改 Session；吸收当前 user 两侧相邻 program-user，按原序前置，然后追加固定 `USER_TRUTH_SEPARATOR` 与 exact human suffix。
- 无 program 的正常请求是 byte-identical no-op。
- 遇到未知第二条 human user 拒绝吞并，不猜测其为程序消息。

`build.py` 在所有动态 program 组装、R2 budget、Cognitive projection 完成后做 R6 出口投影。因此 R2/R3 仍是上游事实源，R6 只负责 wire ordering。

### 3.2 Tool-followup 不重复用户原文

`_current_turn_ref` 是本轮 canonical human identity。若其后已出现 assistant/tool，R6 不再投影 user truth；后续工具轮保留既有 pairing，避免错误形成：

`assistant(tool_calls) → tool(result) → user(replayed truth)`。

### 3.3 Compact 不得替换 current human truth

R6 对 `build_history_messages()` 增加 `preserve_last_human_exact`，仅 initial human-ingress build 启用。

旧极端路径在单条 current user 自身超过 history budget 时会“原文入 archive + 提交截断/指针 surrogate”。R6 改为：

- 旧历史仍可压缩；
- current human atomic group 不截断、不用 archive surrogate 替换；
- 若 exact human 自身就超预算，提交视图允许显式超 history budget，由 routing/context guard 拒绝，而不是静默改变用户任务。

实测 `truth=5000 chars / history budget=1200`：末条仍为完整 5000 字符 user，view 明确超预算。

### 3.4 1210 恢复保留 exact user

`err1210.py` 新增 `SlotKind.USER_ENVELOPE` 与 `InjectedEntry.user_truth`。

R6 envelope 发生 1210 时：

- strip 只移除 program prefix；
- retry payload 仍保留 `{role:user, content: exact user truth}`；
- one-shot interop/tip 等从 `seg_sources` defer/replay，不从混合 envelope 反推；
- 只有 durable persisted/compact program、无 one-shot source 时 defer 为安全 no-op。

因此异常恢复不再以“删掉整个尾 user”换取 provider 兼容。

### 3.5 Legacy Direction-C 索引修复

R6 initial ingress 不再依赖 Direction-C。tool-followup/legacy direct-build 仍保留它，但修正一个既有隐患：`InjectedEntry` 是 frozen dataclass，旧代码删除 persisted user 后尝试原地修改 `msg_idx`。现在用 `dataclasses.replace()` 重建登记，保证 strip/defer 指向合并后的真实 wire index。

## 4. 验收证据

### 4.1 R6 contract

`tests/unit/test_user_truth_wire.py` 覆盖：

- program 在 current user 前后都能吸收到单 envelope；
- program 原序保持；
- fixed separator 后 exact human byte suffix；
- `tail_user_run == 1`；
- 无 program 请求 byte-identical no-op；
- unknown second human 拒绝吞并；
- production-shape enforce 初始轮单 envelope；
- tool-followup 不重放 truth、pairing 不破坏；
- compact 初始轮 exact truth 仍是 semantic tail；
- oversized current human 不再被 compact surrogate 替换。

### 4.2 1210 / legacy

完整 `test_err1210_recovery.py`、Direction-C 回归通过。R6 专项验证：

- USER_ENVELOPE strip 后 exact user 保留；
- defer 只恢复 program sidecar，不把 human suffix 当程序；
- persisted-only envelope defer 安全 no-op；
- legacy Direction-C 删除 persisted user 后 registered dynamic index 正确重映射。

审查时还发现若干旧测试仍断言 R3 前文案（hotcard 内联正文、`[相关记忆]`、defer 无语义标签）。均在 `8107ea9` detached clean baseline 复现为既有红灯后，才更新为当前 R3/R6 contract；没有把它们冒充 R6 回归。

### 4.3 最终扩展回归

最终集合实际 collect **413 tests**，结果 **413/413 PASS**。覆盖：

- Core Loop / Semantic Wiring
- R1/R2/R3 injection/reference
- History / Append Compression
- R6 user-truth wire
- err1210 / Direction-C
- Archive / Semantic retrieval
- CR-R1 / Cognitive compiler/state/integration
- focus / model-switch / cache-switch

pytest 仍报告 21 条既有 `audit_test_side_effects` provider URL 人工复核告警；非 R6 新增且不阻断。

### 4.4 R2 budget matrix

对 production-shape fixture 显式设置 current turn ref，运行：

`off / shadow / enforce × 512 / 700 / 900 / 2000 / 8000`

共 15 点。程序生成字符统计包含 R6 fixed separator，但排除 exact human truth。全部满足：

`generated_program_chars <= R2 accounting used_chars <= budget`

并且每一点：

`tail_user_run = 1`

示例：

- off/512: generated=267, used=316；
- shadow/2000: generated=1617, used=1745；
- enforce/512: generated=287, used=316；
- enforce/8000: generated=1429, used=2220。

### 4.5 R0 frozen / static

- R0 analyzer：四门 **PASS**；
- `git diff -- docs/injection-governance/r0`：运行前后均 **0 bytes**；
- touched production `pyright`：**0 errors / 0 warnings / 0 informations**；
- touched production `py_compile`：PASS；
- `git diff --check`：PASS；
- `ruff` 当前环境未安装，不声明通过。

## 5. 明确未做

R6 没有：

- 修改 auto_continue / recovery 的次数、具体恢复动作或“单恢复动作”规则（R4）；
- 做 identity Q&A stripping（R5）；
- 调整 `REFERENCE_AUTO_TURNS=3` 或做模型行为 A/B（R7）；
- 做 model capability tiering（R8）。

R6 的 PASS 只表示：**在初始 human-ingress provider payload 中，程序附录已经结构性让位于 exact user truth；异常恢复与 compact 也不能再通过删除/改写用户原文来规避 wire 问题。**
