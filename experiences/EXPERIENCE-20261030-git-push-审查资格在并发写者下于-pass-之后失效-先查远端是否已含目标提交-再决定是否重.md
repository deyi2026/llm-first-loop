---
title: git_push 审查资格在并发写者下于 PASS 之后失效：先查远端是否已含目标提交，再决定是否重跑审查
scenario: 同一仓库有另一活跃会话持续改同一批文件（本案是 src/llm_loop/tools/review_host_admission.py 与其测试）时，RULE-AI-28 的 git_push 独立审查资格绑定的是**审查启动时的产物快照**（candidate_sha256），不是提交。对方若在审查 PASS 之后写入工作树，push 即被拒：「不存在覆盖当前产物、目标及父会话的有效独立审查资格」——不是命令写错、不是授权缺失，而是资格与当前产物脱钩，且拒绝信息不提示原因。
root_cause: 准入资格与产物快照绑定而非与提交绑定；并发写者的后续写入使快照失配，且拒绝文案不区分「资格过期」与「未获资格」。
solution: 处置顺序：① **先查目标提交是否其实已被推送**：`git branch -r --contains <sha>` 与 `git rev-parse HEAD origin/main`（本案：第 3 轮 PASS 后 push 被拒；第 4 轮 start 回执 push_remote_commit 已从 566e5b09f 前进到 594db8ddb——对方把含我提交的分支推了，HEAD==origin/main，**根本无需再推**）。② 确有待推提交时，按《并发写者会话下用隔离 worktree + upstream 绑定跑 RULE-AI-28 门禁与推送》走隔离 worktree，避免把对方未提交 WIP 冻结进审查材料。③ 审查 PASS 后**立即推送**，中间不做任何读操作——多一次读都可能因对方写入而使资格失效。④ 推前复查 `git log --oneline -2`：对方可能在你审查期间又提交，HEAD 前进会使资格覆盖不到新 HEAD。
evidence: "第 3 轮 git_push 审查 child subagent_1e0648b50c52 于 16:06:30 PASS（候选 9dad25aa…，src commit 594db8ddb）；并发会话 cbda67c5 于 16:06:58 / 16:07:10 写入 review_host_admission.py 与 tests/unit/test_review_host_admission.py；16:07:40 执行 `git push origin main` 被拒「不存在覆盖当前产物、目标及父会话的有效独立审查资格」；第 4 轮 start 回执 push_remote_commit=594db8ddb；`git rev-parse HEAD origin/main` 两者相等；`git branch -r --contains 90fad9ab6` 与 `contains 05847bfed` 均命中 origin/main。"
tags: [并发写者, RULE-AI-28, git_push, 准入资格, 候选快照]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T16:09:38.175131+08:00"
updated_at: "2026-10-30T16:09:38.175131+08:00"
supersedes: [EXPERIENCE-20261030-并发写者会话下用隔离-worktree-upstream-绑定跑-rule-ai-28-门禁与推送, EXPERIENCE-20261028-rule-ai-28-推送材料超限时按-commit-边界拆批并逐批审查]
---