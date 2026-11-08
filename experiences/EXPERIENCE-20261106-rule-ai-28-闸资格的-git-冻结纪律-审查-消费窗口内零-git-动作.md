---
title: RULE-AI-28 闸资格的 git 冻结纪律：审查-消费窗口内零 git 动作
scenario: RULE-AI-28 闸（review_admission）的资格绑定树摘要与 push_base：审查-冻结窗口内任何 git 状态变化（自己的提交、他人合 main、fetch）都会作废已 PASS 的资格；多会话共享仓库时形成「审查-漂移-重审」循环。
root_cause: ""
solution: 审查前清尽可预期红 → 审查期间冻结全部 git 动作（含 fetch）→ PASS 即消费 → 新红修复后重发而非复用旧资格 → 共享 main 用 help_request(block) 显式排队并在收口时 resolve。
evidence: "evidence://v1/39377c1188ebe45752591cced76c1d039a1c18f15c6aea1d0567ba128451ff4d（S0 全过回执）；本 run 审查轮次史：14cd→0523→0e24→ece469→0603（5 轮 full_test）+ d0f0/8412/7c42/56f6（4 次 git_push 闸）的 action_trace"
tags: [review_admission, RULE-AI-28, 资格绑定, git_冻结, 多会话协调, ci_gate]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-06T22:20:27.257342+08:00"
updated_at: "2026-11-06T22:20:27.257342+08:00"
---

现象链（M2 批次实测，6 次 full_test 资格作废 + 3 次 git_push 资格作废）：
1. worktree 内任何 commit（哪怕 style 单行修复）→ 树摘要变 → 在途 full_test 资格作废；
2. 共仓库其他会话向 main 合并 → push_base 变 → worktree full_test 与主仓库 git_push 资格同时作废；
3. git fetch 更新 remote-tracking → 消费侧 push_base 解析变 → 已 PASS 的资格作废；
4. ci_gate 拦下新红（lint/env-gate/R9）→ 修复必然 commit → 回到 1 的循环。

稳定流程（验证有效）：
A. 发起 full_test 审查前：把已知可修的 lint/env 问题先清掉（ruff 全绿 + env 收口 + 函数大小自查 scripts/regen_function_size_baseline.py --check），最大化首轮即终轮的概率；
B. 审查在途期间零 git 动作（不 commit/fetch/rebase；不替别人动 main；跨会话用 help_request(need=block) 冻结共享 main）；
C. PASS 后立即消费（ci_gate），若拦新红：修复+commit 后**必须重发审查**，不要试图消费旧资格；
D. 多会话共享仓库时，合并/push 窗口用协调消息显式排队，谁冻结谁负责解除（help_resolve）；
E. 分支 rebase 后：旧 SHA 引用会失效（审查回执/文档引用注意用 rebase 后的锚点，merge-review 会核对）。