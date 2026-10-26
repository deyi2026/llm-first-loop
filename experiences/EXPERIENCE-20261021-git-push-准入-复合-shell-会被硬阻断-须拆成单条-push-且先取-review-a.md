---
title: git push 准入：复合 shell 会被硬阻断，须拆成单条 push 且先取 review_admission PASS
scenario: 在 LFL 安装里用 execute_command 执行 git push 触发 RULE-AI-28 Host 准入闸。
root_cause: RULE-AI-28 Host 准入对“受保护动作 + 复合 shell”组合做确定性阻断（compound_protected_shell_requires_split_commands），以保证被审目标与实际执行命令可一一对应绑定。
solution: "顺序固定为：(1) review_admission(action=start, kind=git_push, workdir, command, target_name) 冻结产物 SHA（回执含 push_remote_commit）；(2) review_admission(action=status, child_id) 轮询直到 qualification=PASS；(3) execute_command 只发单条 `git push <remote> <branch>`，不要与 && / ; / 回显混编。执行后用 git ls-remote <remote> refs/heads/<branch> 独立核验远端 SHA。"
evidence: "本机实测回执：execute_command 以 `cd ... && git push lfl main 2>&1; echo ...; git ls-remote ...` 复合形式调用 → [blocked] RULE-AI-28 Host准入阻断，原因 compound_protected_shell_requires_split_commands，动作未执行；改为单条 `git push lfl main` → [success] 退出码 0，stderr \"Everything up-to-date\"；随后 ls-remote 得 lfl/main=5334efcad2bcb5e4a5424c90a58dbcb6cabeb241，与本地 main 一致。审查资格来自 review_admission start（child_id=subagent_01bf88d792b3, push_remote_commit=5334efcad...）→ status PASS。"
tags: [git, push, rule-ai-28, review_admission, execute_command, 硬阻断]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-21T20:14:17.841164+08:00"
updated_at: "2026-10-21T20:14:17.841164+08:00"
supersedes: [EXPERIENCE-20261016-多代理编码-审查-准入-部署-push-流水线的跨-run-调度与五类机械故障处置, EXPERIENCE-20261021-rule28-git-push-准入被拒的三个真实原因-gate-副作用脏-worktree-并行会, EXPERIENCE-20260919-github-push-v2-remote-force]
---