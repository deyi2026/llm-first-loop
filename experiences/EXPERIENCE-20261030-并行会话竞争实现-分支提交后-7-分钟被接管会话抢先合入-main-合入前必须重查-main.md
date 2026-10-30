---
title: 并行会话竞争实现：分支提交后 7 分钟被接管会话抢先合入 main；合入前必须重查 main
scenario: 2026-10-30 晚，镜像仓多会话并行修复 §11.6 两个 P2。我按 HANDOFF-20261030-write-scope-git-takeover 只留分支不合入；但分支提交与最终答复之间的窗口里，接管会话抢先在 main 落了等价修复。
root_cause: ""
solution: "跨会话 HANDOFF/并行开发场景：① 分支提交后、声明\"待合入\"前、以及任何合入/推送动作前，重查 main 是否已有等价实现（git log --oneline <基线>..main -- <我改的文件>），有则让位不合入；② 让位时保留分支指针作记录（不删，删除属用户/接管会话决定域）；③ 让位理由要落到模型面/接口面证据（字段词汇实测暴露面），不只看功能等价。"
evidence: "本会话 2026-10-30 21:2x execute_command 回执：git merge-base --is-ancestor 7155c9e7f main → NOT merged；git show --stat 4d7dc24ef → deyi2026 10-30 19:34，3 文件 +93/-14（含 browser_semantic_operation.py/_lift_m1_compact_echoes 扩触发面 diff 原文）；git diff 4d7dc24ef 7155c9e7f --stat → 4 文件 114+/96-（不等价）；docs/design/20261027-m1-review.md:74（compact 回执 reject_reason 实测暴露 A1-A9/T1/L10）。命令回执 evidence ref: evidence://v1/30438248cad9f510ff0b9424529ff17beab31186fcd0535c1497530b8c5ef929"
tags: [git, 并行会话, handoff, 竞争实现, grep验证]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T21:26:56.840065+08:00"
updated_at: "2026-10-30T21:26:56.840065+08:00"
---

时间线：我 19:27 在镜像仓分支提交 7155c9e7f（§11.6 两个 P2 修复，新增 rejection_reason 字段）；接管会话 19:34 在 main 落 4d7dc24ef（等价双修复，方案为扩既有 reject_reason 的触发面到 status=="rejected" 整类+动词白名单兼容）并过合入门禁。若强行合入会让模型面出现 reject_reason/rejection_reason 两个近义字段（m1-review :74 实测模型面稳定暴露的是 reject_reason，接管会话复用旧词的方案在此证据上更优）。第二教训（同轮）：验证文档纠偏是否已被他人应用时，我 grep 的特征短语"子帧落在窗口外"与原文"子帧那个「同名按钮」落在窗口外"不连续而漏检，差点误判"更正已应用"；grep 前应先从已读原文复制精确连续片段，或用多个短词分别验证。