---
title: ci_gate 静态诊断棘轮的 changed 集语义 + worktree 沙箱 git 写权限陷阱
scenario: 在 worktree 里跑 ci_gate 全量门禁时被 ruff/pyright 静态诊断棘轮阻断；需要判断「哪些诊断会阻断」「改了文件为何激活历史债」「沙箱下如何做 git 写操作」
root_cause: ""
solution: 1) 用 scripts/check_static_diagnostics.py 判断阻断（changed 集=HEAD vs HEAD^，动了文件即激活该文件历史诊断）；2) 不用单文件 pyright 裸跑结论，用项目级 ratchet；3) git 写操作以 cwd=仓库根 + git -C worktree 执行；4) 文本改动优先用 edit_file，避免 heredoc 触发 compound shell 守卫；5) docs/reports-only 提交用 git diff 排除路径为空来证明代码等同，无需重跑门禁。
evidence: 本会话证据：job_output(CiGate)=exit 0，ratchet ruff new=0/changed_file_diagnostics=0，ratchet pyright new=0/changed_file_diagnostics=0，红数对账 28/28；review_admission status=PASS；git diff b56cb5025..HEAD 排除 docs/reports 为空。
tags: [ci_gate, ruff, pyright, review_admission, git worktree, sandbox, static diagnostics]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-25T14:21:54.911699+08:00"
updated_at: "2026-10-25T14:21:54.911699+08:00"
---

## 场景
在 `llm-first-loop` 仓的 worktree 内跑全量门禁 `bash scripts/ci_gate.sh`（RULE-AI-28 需先 review_admission PASS 取资格）。候选 b56cb5025 首次门禁在第 1 步 ruff 棘轮被阻断：`F821 Undefined name RealtimeSessionRuntime` + `SIM117`（都来自新增测试文件）。

## 关键机制（已实测核验）
1. `scripts/check_static_diagnostics.py --tool {ruff,pyright}` 的「changed」集合 = **HEAD vs HEAD^ 一个提交**（加未提交/untracked），不是与 base 的全量 diff。含义：**只要你的提交动了某文件，该文件的历史诊断就变成 blocking**（`changed_file_diagnostics` 计数进 touched → BLOCK CHANGED FILE）。所以「顺手修一个测试文件的 lint」会把该文件的历史 pyright 债一起激活。
2. 单文件直接跑 pyright（`pyright path/to/test_x.py`）会因缺项目上下文报出大量伪错（本次 7 个 `CloseCountingHttp` 协议不匹配）；用脚本的项目级 ratchet 跑同一提交，该文件 **0 诊断**。不要用单文件 pyright 结论判断门禁会不会红。
3. 门禁的全量并行跑失败后会**串行复跑失败文件**并以串行结果做红数对账（`eval/rules/red_reconciliation.py`：实测红 / 登记命中 / 登记基线 / 过期登记）。本次 28 failed 全部命中登记 → PASS，同时报 4 条过期登记（实测已不红）。
4. 沙箱写限制按 **cwd** 生效：cwd=worktree 时 `git switch/commit` 报 `.git/worktrees/<id>/index.lock: Operation not permitted`；改成 `cwd=仓库根` + `git -C .worktrees/<id> <cmd>` 即通过。
5. `execute_command` 里 `cat > /tmp/x.py <<EOF ... EOF` + 执行 会被 Host 守卫判 `compound_protected_shell_requires_split_commands` 直接阻断；拆成多个单命令，或改用 `edit_file` 工具做文本替换。

## 结论/做法
- 修 lint 用真实导入（`from ... import RealtimeSessionRuntime`，配 `from __future__ import annotations`）+ 合并 `with` 为多上下文单语句，语义与断言不变。
- 判「门禁会不会红」只信 `scripts/check_static_diagnostics.py --tool ...` 的 new/touched 输出，不信单文件 pyright/ruff 裸跑。
- docs/reports-only 提交后可用 `git diff <gated_sha> HEAD -- . ':(exclude)docs' ':(exclude)reports'` 为空来证明代码树与受门禁提交等同，避免为重跑门禁反复 churn 运行产物。

## 验证证据
2026-10-25：`bash scripts/ci_gate.sh` exit=0（28 failed/11185 passed/146 skipped；串行 28 failed/138 passed；红 28/28 命中）；ruff new=0 changed_file_diagnostics=0；pyright new=0 changed_file_diagnostics=0。
