---
title: review_admission 在共享工作区多会话并发时不可闭环：identity 含 head 致资格随每次新提交失效
scenario: "同一仓库有多个 LFL 会话并发提交（实测 3 分钟内 +3 commit）。要 push 30 个本地 commit，走 review_admission(kind=git_push)。审查 start 时计算 candidate_sha256，其中 identity 含 {\"head\": rev-parse HEAD}；审查耗时约 4 分钟，期间任一并发会话新增 commit 即改变 head，审查 PASS 后 push 的 check_shell 重新计算得到不同 sha，_consume 匹配不到而拒绝（\"不存在覆盖当前产物、目标及父会话的有效独立审查资格\"），且该次审查的 reviewer 预算已消耗。"
root_cause: ""
solution: "并发提交场景下不要在单会话内追资格：(1) 先等 HEAD 静默（观察 git log 最近提交时间，稳定 3-5 分钟再 start）；(2) 审查 PASS 后立刻 push，不要插入其他工具调用；(3) 需要多次重试时，push 被拒本身不消耗资格（不匹配即拒），但每次重新 start 都会消耗一份 reviewer 预算，所以宁可等静默也不要盲目重试；(4) 材料超 reviewer cap 时用分批 push（git push origin <sha>:main），把边界切在\"问题 commit 之前\"，让第一段先落远端、第二段范围变小；(5) 注意 push_head != HEAD 时 include_worktree=False，工作区脏不影响材料，但 head 仍必须与 start 时一致。若并发无法停止，应向用户报告并请其暂停其他会话，而不是反复烧审查预算。"
evidence: "实测 2026-11-01：seg1 审查 start 时 head=c24d8cb38，status 返回 PASS，随即 push 119e711dd:main 被拒，查得 HEAD 已变 012f4ea1（期间两个并发 commit 0c3ba0e96、012f4ea1）。另一次 21e780af 审查 REVISE 后同样无法推送。代码依据 src/llm_loop/tools/review_host_admission.py identity 构造与 check_shell/_consume。"
tags: [review_admission, git_push, concurrent-sessions, candidate_sha, worktree]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-01T11:49:55.904470+08:00"
updated_at: "2026-11-01T11:49:55.904470+08:00"
supersedes: [EXPERIENCE-20261030-git-push-审查资格在并发写者下于-pass-之后失效-先查远端是否已含目标提交-再决定是否重]
---