---
title: verify_path_scope 的「越界写入尝试」计数不含被拒写入，不能用它判定是否发生过越界
scenario: 在 gen 345 的 live 运行时代码根内派受限子代理做 3 类越界写实测（绝对越界 / `..` 别名 / `../../` 穿越），4 次全部被写侧拒绝且目标文件均未生成。
root_cause: "写侧拒绝的记录落在 `scope_unverified` 列表（逐条带 not_in_allow_list / outside_scope 归因），但「越界写入尝试」计数与「已写路径集合」在拒绝路径上不增 ⇒ 计数器只反映\"已越界且落盘\"，不反映\"已尝试越界\"。"
solution: "判定\"越界是否被拦\"要用两件事：(1) 每次 execute_command 的原始状态行与错误码；(2) 只读核查目标文件确实不存在。不要用 verify_path_scope 的越界计数当证据。可观测性改进项（未做）：把被拒写入计入越界计数。"
evidence: "evidence://v1/da368abeda91211af37a5b391e7eda96e49e29ec6518494a4361a72218d88550（子代理回执：4 条 write_target_not_in_allow_list / write_target_outside_scope，ls 确认目标未生成；verify_path_scope 显示越界计数 0、已写 0，scope_unverified 0→5→12）"
tags: [write-scope, observability, verification-discipline]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T23:39:21.166661+08:00"
updated_at: "2026-10-30T23:39:21.166661+08:00"
---