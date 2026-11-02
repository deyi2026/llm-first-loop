---
title: edit_file 同一文件多处修改必须串行：每次成功后旧 snapshot 即失效，并行第二发必然版本冲突
scenario: 推广晚班修稿：对 docs/promotion/20261101-lfl-daily-51.md 做两处独立修改，为省轮次在同一消息里并行发两个 edit_file（同一 expected_snapshot_ref）。第二个调用确定性失败：版本冲突；重试又因第一个再次成功而再失败，共浪费 2 轮。
root_cause: ""
solution: 同一文件多处修改一律串行：edit 成功 → 重新 read_file(snapshot=true) → 取新 snapshot_ref → 下一处 edit。不同文件才可并行。修改点多且碎时，改为一次 edit 覆盖整段（old_string 取包含全部修改点的连续块）。
evidence: "本会话 d51 修稿阶段两次「修改失败: 版本冲突: 当前完整文件字节已不同于 expected_snapshot_ref；本次未写入」回执（并行 edit 20261101-lfl-daily-51.md 两处）；随后串行重取 snapshot 后同样修改均成功。"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-01T21:07:50.094763+08:00"
updated_at: "2026-11-01T21:07:50.094763+08:00"
supersedes: [EXPERIENCE-20260917-edit-file]
---

现象：同一轮对同一文件并行发起两个 edit_file（都基于同一 snapshot_ref），第一个成功后文件字节已变，第二个确定性报「版本冲突: 当前完整文件字节已不同于 expected_snapshot_ref」；连续两轮重复发生（d51 修稿阶段 2 次）。恢复成本：每次需重新 read_file(snapshot=true) 取新 snapshot 再 edit，浪费 2 轮。运作规则：对同一文件的 N 处修改必须串行——每次 edit 成功返回后，旧 snapshot 立即失效，下一处修改前重新 read_file 取 snapshot（或改用一次性整段替换覆盖全部修改点）。并行 edit 只适用于不同文件。适用边界：LFL edit_file 工具的 snapshot 前置契约（expected_snapshot_ref 绑定完整文件字节）。