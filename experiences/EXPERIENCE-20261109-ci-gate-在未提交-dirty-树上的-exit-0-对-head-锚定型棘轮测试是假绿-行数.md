---
title: ci_gate 在未提交 dirty 树上的 exit=0 对 HEAD 锚定型棘轮测试是假绿：行数基线测的是 HEAD 树，提交后才见真红；lane 流程必须提交后重跑全量
scenario: 在共享 main 工作树以 dirty 状态跑 canonical ci_gate（RULE-AI-28 全量），代码未提交即过闸；随后按 lane 流程提交到分支后重跑全量
root_cause: ""
solution: 把「工作树 dirty 状态的全量绿」视为对棘轮类测试（test_arch_guards 函数行数基线，测 HEAD 树）未覆盖的假绿；提交后必须重跑 canonical 全量才能主张分支全量绿。「回退文件到 base」必须用 git checkout <base-sha> -- <path>（分支 HEAD 含本分支提交，checkout HEAD 不是回退）
evidence: "2026-11-09 实测：job-44ea05e8（11-08 23:27 主仓，工作树 dirty 含 EVO 8 文件）ci_gate exit=0；次日 lane 树提交后（job-f04956c3）同代码 2 红（test_function_lines_ratchet_within_baseline：_execute_subagent 567→619 等四函数超登记）。修复链：regen_function_size_baseline.py→guard(r9) 提交 a7590b156→全量绿（job-0808b976/job-9bbf04fa）。另：06d866bef 提交信息声称 manifest 回退但实际 checkout HEAD 指向含错误 pin 的自身提交，真回退需 checkout f0f6fa208（勘误提交 3171f1278，merge-review subagent_731a0fa8bf0f 捕获）"
tags: [ci_gate, ratchet, arch_guards, dirty-worktree, false-green, lane, git-checkout-base]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-09T12:53:29.572512+08:00"
updated_at: "2026-11-09T12:53:29.572512+08:00"
---

1. 走闸前先把分支提交（HEAD=分支头），再在干净分支上跑 canonical ci_gate；若时间线只能先跑（工作树 dirty），把 ratchet 类测试单独在「模拟提交态」复跑（git stash + stash pop 后针对 test_arch_guards 定向跑）或接受一轮已知风险后必补跑。2. 判读 ci_gate exit=0 时核对 ratchet 输出的 changed[uncommitted] 是否非空——非空即存在棘轮盲区，绿不等于全覆盖。3. REVISE 循环里做「回退到 base」类操作时，显式写 base SHA，并立即用 `git diff --name-only <base>..HEAD` 验证回退真实进入累计 diff。