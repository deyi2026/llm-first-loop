---
title: 沙箱内 git worktree 提交/推送与 RULE-AI-28 审查闸的可执行姿势
scenario: 在 LFL 沙箱（macOS sandbox-exec，仅允许写 cwd 工作区+缓存）内的 git worktree 分支上完成 commit + push（受 RULE-AI-28 git_push 独立审查闸管辖）
root_cause: ""
solution: "① worktree 内直接 git add/commit 会因 `.git/worktrees/<name>/index.lock` 沙箱拒写失败——一律从仓库根 cwd 用 `git -C <worktree-path> ...` 执行；② push 前必须 review_admission(kind=git_push)：start 时 command 字符串与 workdir 必须与最终执行**逐字符一致**（目标哈希绑定 command+workdir，`2>&1`/`; echo` 复合段会被拆分保护拦下，push 必须单条裸命令）；③ pre-push 知识闸要求先 `scripts/knowledge_flush.py` 入库未提交方法/经验卡（pathspec 提交，不卷入 dirty entries），再重开审查；④ 审查子代理禁 followup，verdict 非 PASS 令牌（如中文\"通过\"）→ 判 REVISE，重开一次审查（内容未变可用 previous_child_id 窄复审）"
evidence: "execute_command receipts: 11:24 git add EPERM (index.lock)→repo-root 成功; 11:31 push blocked no_pending_qualification; 11:33 compound split 拦截; 11:34 target_mismatch (command/workdir 不一致); 11:32 knowledge 闸+flush 回执; 11:36 REVISE(格式)/11:44 PASS/11:45 push exit 0 (0ce2bd736..6239a2479, git_security_scan 通过)"
tags: [git-worktree, sandbox, RULE-AI-28, review_admission, push, knowledge_flush]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-13T11:46:56.283195+08:00"
updated_at: "2026-11-13T11:46:56.283195+08:00"
---

完整闭环（每步都有工具回执）：1) 在 worktree 内执行 `git add` 报 `fatal: Unable to create .git/worktrees/<name>/index.lock: Operation not permitted`——沙箱可写根=cwd（worktree 子目录），而 worktree 的 index/refs 在主仓共享 .git 下。改用仓库根 cwd + `git -C <worktree> <cmd>` 后 add/commit/push 全部成功。2) push 被 RULE-AI-28 Host闸拦（no_pending_qualification）→ review_admission(start, kind=git_push, command=<与实际执行逐字符一致的命令>, workdir=<实际执行 cwd>)；qualification 目标哈希绑定 command+workdir，`git push origin X`（worktree cwd）与 `git -C .worktrees/... push origin X`（repo 根 cwd）是两个不同目标，资格不通用。3) 复合命令（`push ... 2>&1; echo $?`）被 compound_protected_shell_requires_split_commands 拦——受保护动作必须单条裸命令。4) pre-push 前若报"工作区存在未入库知识资产"，按闸提示跑 scripts/knowledge_flush.py（pathspec 提交，不动 dirty entries），再重开审查。5) 审查子代理禁 agent_followup（会永久失去资格）；verdict 行若用中文"通过"可能被判 review_verdict_incomplete_or_not_pass，重开一次审查即可，内容未变时也可用 previous_child_id 走窄复审。