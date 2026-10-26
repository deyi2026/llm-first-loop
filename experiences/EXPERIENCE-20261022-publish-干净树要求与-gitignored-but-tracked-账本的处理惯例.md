---
title: publish 干净树要求与 gitignored-but-tracked 账本的处理惯例
scenario: mirror 仓 publish(gen 305) 首次被 DeploymentBindingError tracked_worktree_dirty 硬拒；git add experiences/usage.jsonl 被 gitignore advice 拦截。
root_cause: experiences/ 在 .gitignore 中但账本文件被历史 force-add 跟踪；运行时持续追加使 tracked 树常态脏；git add 对显式 ignored 路径拒绝需 -f。
solution: "发布前快照式提交账本：git add -f experiences/usage.jsonl experiences/.usage_watermark.json && git commit -m \"chore(ledger): 账本快照（…）\"；随后立即 publish（窗口内无新读取则 tracked 树保持干净）；非本人 untracked 文件不处理不删除。"
evidence: 本会话回执：service_control publish 首次拒绝 DeploymentBindingError tracked_worktree_dirty（需操作者处理，程序不 stash）；git add 报 ignored advice；git add -f + chore 提交 cdcd0c3a3 后 publish gen 305 成功（deploy-3e274647…）。
tags: [publish, git, ledger, service_control]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-22T19:45:28.825782+08:00"
updated_at: "2026-10-22T19:45:28.825782+08:00"
---

publish 的 tracked 干净检查会被运行时持续写入的账本文件卡住（experiences/usage.jsonl + .usage_watermark.json）。既定惯例是 chore(ledger) 快照提交（见 mirror PR #5 b5e0f665b）；gitignore 挡 add 时对已跟踪文件用 git add -f。无关 untracked 文件不阻塞（publish 只查 tracked 脏）。