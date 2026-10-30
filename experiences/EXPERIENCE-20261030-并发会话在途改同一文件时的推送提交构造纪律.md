---
title: 并发会话在途改同一文件时的推送提交构造纪律
scenario: 多会话并发改同一仓库（他人有在途 WIP），我要提交自己的产物并推送。
root_cause: ""
solution: 1) 用临时 worktree 基于 origin/main 构造提交，只拷入自己的文件，绝不在他人已 stage 的主工作树里 commit；2) 提交前用 diff 逐文件比对 live 与 worktree 副本，凡不一致即以 live 为准重建——本轮正是靠这一步避免用旧副本覆盖他人对同一文件的新改动；3) push 必须是单一命令，且命令串与工作目录与 review_admission 登记的逐字一致（本轮 `-C` 变体被判 base 不可解析）；4) 准入回执用 review_admission(action=status) 核 qualification=PASS 后再以同一目标重试。当前性验证：跑 `git ls-remote origin refs/heads/main` 应得已推的 HEAD；跑 `diff <worktree>/<file> <live>/<file>` 对每个待提交文件应无差异，有差异即必须重建提交。
evidence: "本轮三次实测：(a) docs/governance/card-lifecycle.md 我的 edit_file 因版本冲突被拒（他人 13:07:56 写入），未覆盖其改动；(b) push 被 compound_protected_shell_requires_split_commands 拦；(c) `git -C /tmp/lfl-r4-push push` 被 push_base_unresolvable_fail_closed 拦，改为 workdir=/tmp/lfl-r4-push + 命令串 `git push origin HEAD:main` 后成功（远端 main=3089e76c7）。"
tags: [git, push, 并发, 准入, RULE-AI-28, 临时worktree]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T13:19:04.806866+08:00"
updated_at: "2026-10-30T13:19:04.806866+08:00"
---