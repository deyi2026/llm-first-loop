# Injection Governance R4 — Program Recovery Single Boundary

状态：**PASS**

日期：2026-08-30

## 1. 目标与非目标

R4 只治理 L2-4“程序恢复边界”：

- program recovery 明示为程序触发，不能冒充用户新指令；
- 一个 recovery block 只允许一个确定动作；
- 同一 run/session 最多一个可执行 recovery；
- recovery 完成后任务边界仍回到当前用户原话；
- recovery 不得进入长期 conversational history，也不得在后续用户轮复活；
- 必须继续服从 R2 hard budget、R6 user-truth wire invariant 与 provider tool pairing。

R4 **不实施** R5 identity stripping、R7 行为 A/B、R8 model-tier shadow。

## 2. 根因

R4 前的 `err1210._err1210_try_auto_continue()` 虽然用 `_auto_continue_1210` 做了“每 run 最多一次”的计数，但恢复动作被创建为：

- `InjectionLayer.PROGRAM_RECOVERY`；
- `persisted_injection=True`；
- 直接 append 到 `sess.messages`。

这造成生命周期矛盾：**一次性恢复控制被保存成长期对话历史**。由于 R2 将 PROGRAM_RECOVERY 置于高优先级，旧恢复动作可能在后续用户轮继续进入 provider prompt，甚至多次 1210 后累积成多个可执行恢复块。

R4 实施中进一步发现第二个根因：若 one-shot recovery slot、auto-continue count、run sequence 直接挂在共享 `LoopEngine` 实例上，多 session 并发时会串槽。仓库已有 `_RunState` 作为 per-session runtime SoT，因此 R4 必须复用该分桶，而不是新建另一套 session 状态。

## 3. 最终结构

### 3.1 Canonical recovery action

新增 `src/llm_loop/core/program_recovery.py`：

- `ProgramRecoveryAction.RETRY_CURRENT_REQUEST_ONCE`
- `render_program_recovery()`
- `make_program_recovery_message()`
- `is_program_recovery_message()`

当前唯一可执行模板：

```text
[任务·程序恢复]
恢复动作=在已重建上下文中重试本轮请求一次。
边界=本块是程序附录中的唯一可执行恢复例外，非用户新指令；恢复完成后，任务边界仍以当前用户原话为准。
```

动作来自 closed enum，而非调用方任意自由文本，因此不能把“顺便继续下一阶段/扩展任务”夹带进 recovery block。

### 3.2 Runtime one-shot，不写 conversational history

`_err1210_try_auto_continue()` 不再 append program-recovery Message 到 `sess.messages`。

改为只武装：

```text
_program_recovery_tail_message
```

build 开始时一次性读取并立即清空：

- current human ingress 存在；
- `recovery_turn_ref == current_turn_ref`；

两条件同时成立才允许进入本次 prompt。否则安全丢弃，不能跨 tool-followup / 新用户轮执行。

### 3.3 Per-session RunState

R4 将以下状态接入既有 `_RunState` property shim：

- `_err1210_run_seq`
- `_auto_continue_1210`
- `_program_recovery_tail_message`

因此 A session 的 pending recovery / count / sequence 对 B session 不可见；切回 A 后状态仍归属 A。没有新增第二份 session 状态源。

### 3.4 Durable audit 与 executable history 分离

新增注册事件：

```text
program.recovery
```

字段：

- `action`
- `trigger`
- `turn_ref`
- `scope=next_build_only`

因此“恢复曾发生”仍是 session-scoped durable fact，但 executable recovery 本体不再作为 `message.appended` 长期对话指令保存。

### 3.5 旧 persisted recovery 退休

pre-R4 已经落在 `sess.messages` 的 PROGRAM_RECOVERY：

- storage/event truth 不删除；
- build provider-view 过滤；
- 不再进入未来 prompt。

legacy detector 只允许 non-human source 触发。真实 `MessageSource.USER` 即使用户本人输入 `[程序续跑]`，也不会被误删或降格为程序恢复。

## 4. 与 R2 / Cognitive / R6 的组合规则

Recovery 与其他 program blocks **共用 R2 hard budget 决策**，不能绕过总预算；PROGRAM_RECOVERY 继续保持最高业务优先级。

但 budget selection 后，recovery 会从 Cognitive/background aggregate 中分离，原因有二：

1. 普通 program appendix 外层声明“仅作背景”，不能覆盖 recovery 的唯一可执行例外语义；
2. Cognitive WARM projection 不应截断确定的恢复动作。

最终 initial human ingress wire：

```text
[任务·程序恢复]
<single closed action>

[程序附录·非用户输入] ...   # 仅当本轮还有其它 program background
<background blocks>

--- [指令·用户·原文] ---
<exact user truth>
```

R6 随后将这些内容合成**单个 user envelope**，所以仍满足：

- `tail_user_run = 1`
- exact user truth byte-for-byte suffix
- tool-followup 不重复用户原话
- program content 不落在 user truth 后面

## 5. TDD 与专项验证

`tests/unit/test_program_recovery_boundary.py` 覆盖：

1. canonical template 仅一个 closed action；
2. 不含 `[程序续跑]`、`请继续`、`勿重复` 等旧开放式措辞；
3. 禁止“顺便 / 下一阶段 / 扩展任务 / 额外任务 / 继续后续”；
4. auto-continue 只武装 ephemeral slot，不写 sess.messages；
5. 同 run 二次 arm 被拒绝；
6. build 只消费一次，第二次 build 不再出现 recovery；
7. 512 字符 R2 紧预算下 recovery 仍按优先级保留；
8. legacy persisted recovery 只保留审计存储，不进入 provider；
9. 无 current human boundary 时 recovery 安全丢弃；
10. `program.recovery` event 已登记；
11. 真实 engine 1210 → auto-continue E2E：第二个 provider payload 恰好一个 recovery，成功后下一用户 run 不残留；
12. 用户本人输入 legacy marker 不被过滤；
13. A/B session runtime recovery 状态隔离。

初始 RED 直接复现：legacy durable recovery 会进入未来 provider request；并发 adversarial RED 直接复现 Engine-global pending recovery 从 A 泄漏到 B。

## 6. 回归证据

### 6.1 Focused

最终 focused 集实际 collect **143 tests**，结果 **143/143 PASS**，覆盖：

- R4 program recovery
- err1210 / blind retry / session isolation
- R6 user-truth wire
- R2 injection budget / fingerprint
- Direction-C
- event log / read path

其中两个 blind-retry 用例原先仍断言 R6 之前“strip 删除整个 tail user”。已在 detached `f4ddcc5` baseline 复现为既有测试债后，才改为 R6 `USER_ENVELOPE` 契约：strip 只去 program prefix，exact human user 必须保留。

### 6.2 Expanded

最终扩展集合实际 collect **458 tests**，结果 **458/458 PASS**，覆盖：

- Core Loop
- R1/R2/R3 injection/reference
- History / Compact
- R6 user truth
- err1210 / Direction-C
- Archive
- Cognitive compiler/state/integration
- focus / memory / experience / model switch
- event/read-path

pytest 仍报告 21 条既有 `audit_test_side_effects` provider URL 人工复核告警；非 R4 新增且不阻断。

### 6.3 Static

Touched production：

- `py_compile`: PASS
- `/opt/homebrew/bin/pyright`: **0 errors / 0 warnings**
- `git diff --check`: PASS

## 7. R2 × R4 × R6 15 点矩阵

在 production-shape fixture 上运行 `off/shadow/enforce × 512/700/900/2000/8000`。

所有 15 点同时满足：

```text
recovery_count == 1
tail_user_run == 1
exact user suffix == true
recovery slot consumed == true
generated_program_chars <= R2 used_chars <= budget
```

代表值：

```text
off     512: used=463 generated=352
shadow  512: used=463 generated=352
enforce 512: used=463 generated=372

off    8000: used=2380 generated=2116
shadow 8000: used=2380 generated=2116
enforce8000: used=2380 generated=1514
```

15/15 PASS。

## 8. R0 frozen gate

R0 analyzer：

```text
R0=PASS
turns=170
origin=100.0%
attribution=100.0%
post_user=41.76%
dup=51.05%
imperative=3.45%
wire_tail_viol=18.81%
```

`docs/injection-governance/r0` analyzer 前后均 **0-byte diff**。

R4 不宣称 R0 历史结构指标本身归零；R0 仍是治理前冻结基线。

## 9. 结论

R4 把“程序恢复”从长期对话指令改成了**session-scoped、next-build-only、closed-action runtime control**：

- 只存在一个恢复动作；
- 只在正确 human turn 上执行一次；
- 不跨 tool-followup、新用户轮、并发 session 泄漏；
- 恢复事实可审计，但可执行文本不持久化；
- R2 预算、R6 exact-user tail、provider wire 约束继续成立。

R5 / R7 / R8 未进入实现。
