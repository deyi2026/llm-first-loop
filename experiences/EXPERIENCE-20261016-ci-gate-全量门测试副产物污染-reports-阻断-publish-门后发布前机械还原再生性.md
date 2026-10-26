---
title: ci_gate 全量门测试副产物污染 reports/ 阻断 publish：门后发布前机械还原再生性产物
scenario: 全量门（ci_gate.sh 全量 pytest）运行后立即 service_control publish 部署：门内测试向 tracked 的 reports/ 目录再生产物（json/md 时间戳扰动），导致 publish 的干净树绑定被拒（tracked_worktree_dirty），流程卡在门禁绿→部署黄之间。
root_cause: ""
solution: 全量门 exit=0 后、publish 前，机械检查 git status：脏文件若全部为 reports/ 下测试再生副产物（对称性 ±行数、仅时间戳/ID 变化），用 git checkout -- reports/ 还原后立即重试 publish。commit 46a15a79→3bd871709 序列两次验证：还原后 publish 一次通过（gen 269）。
evidence: "命令回执：checkout 前 18 文件 ±144（execute_command 2026-10-16T06:52:31）；还原后 publish 成功 generation=269（service_control 2026-10-16T06:52:44）"
tags: [ci_gate, deploy, publish, clean-tree, test-side-effects]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-16T06:56:50.275731+08:00"
updated_at: "2026-10-16T06:56:50.275731+08:00"
---

现象：bash scripts/ci_gate.sh 全量跑毕 exit=0 后，git status 出现 reports/ 下 ~18 个 tracked 文件的对称 ±144 行改动（测试再生的报告产物：时间戳/运行 ID 扰动）。service_control publish 的绑定层要求 code_root tracked worktree 干净，publish 以 DeploymentBindingError(tracked_worktree_dirty) 拒绝。处置：git checkout -- reports/ 还原（这些文件由测试再生成，丢弃安全），publish 立即通过（gen 269 绑定 3bd871709）。边界：仅还原确认再生性的测试副产物；不 stash/commit 掩盖未知改动（publish 报错信息本身明确"程序不 stash/commit/checkout"，操作者判断后执行）。适用信号：全量门跑完紧接 deploy 时 publish 报 tracked_worktree_dirty，且脏文件集中在 reports/ 且 diff 对称。