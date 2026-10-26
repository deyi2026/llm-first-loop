---
title: 共享 checkout 上 RULE-AI-28 冻结 SHA 必漂移，全量门要用 pinned worktree
scenario: "在多人/多会话共享的 git checkout 上跑 RULE-AI-28 全量门：start 拿到 PASS，重试执行时被 Host 以\"无覆盖资格\"拒绝。"
root_cause: RULE-AI-28 的 candidate_sha256 覆盖 merge_base..HEAD 的全部提交 + 工作树差异；共享 checkout 上其他会话继续提交/改文件，冻结值与重算值必然漂移。
solution: 门禁前把待审改动落到一个固定提交的独立 worktree（`git worktree add -b gate/<name> /tmp/<name> <base>` + apply patch + commit），admission 与 execute_command 的 workdir 都指向该 worktree；ci_gate.sh 本身会回落到主工作树 .venv 并把 PYTHONPATH 指回本 worktree src，因此无需在 worktree 内重建虚拟环境。不要在有并行写入的 checkout 上直接跑门禁。
evidence: "review_admission start 于 11:23:29 冻结 sha=f94947e1（main worktree, HEAD=31e8662b4）；11:32 重算 `_source_snapshot` 得 50ccaf87，deny 原因\"不存在覆盖当前产物…的资格\"。期间 git log 出现 375776286/50ccaf87e/567153f62/01e612802 等并行会话提交。改用 `git worktree add -b gate/... /tmp/lfl-gate-heldout HEAD` 固定提交后，两次 admission 均正常绑定（sha f72fa715 / 376fe285）。"
tags: [rule-ai-28, full-test, worktree, concurrency, admission]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-25T11:57:55.279483+08:00"
updated_at: "2026-10-25T11:57:55.279483+08:00"
---