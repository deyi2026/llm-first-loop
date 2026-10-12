---
title: 跨分支移植语义冲突：目标分支当前契约优先于源分支旧 authority
scenario: 跨分支移植功能批次（如 CR-R1 从 origin/main 移植到特性分支）后，同域出现新旧两套语义的测试互相矛盾：新移植的测试（源码巡检型）要求接线上线，目标分支老测试断言该接线不得存在。
root_cause: 跨分支大块移植时源分支的新演进（origin/main EVO-20260814-aab7eb0b P2 硬熔断）与目标分支既有契约（fix/restart-useful-continuity 的 B-G2/P2-A「停滞仅观测、无 breaker authority」）在同一域冲突；移植侧测试固化了源语义。
solution: 契约优先级裁决法：a) 目标分支 HEAD 的既有测试与代码注释是契约权威；b) 用 git stash 基线（注意 staged 新文件会被一并 stash 走，file-not-found 报错即此因）判定失败是否预存；c) 移植非必需的冲突语义整体摘除（不半留）；d) 纯函数保留（自洽可测），e) 把源语义巡检测试改写为目标契约的反向守卫，防回流。
evidence: /tmp/baseline4.log EXIT=1 仅 compact×2+working_set×4；/tmp/verify_fix.log EXIT=0（stagnation_gate+control_plane+loopbreaker+csrf+upload 全绿）
tags: [port-conflict, contract-precedence, stagnation, cross-branch-port, test-guard]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-09T16:25:01.363843+08:00"
updated_at: "2026-09-11T19:55:09.647912+08:00"
last_verified_at: "2026-09-11T19:55:09.647912+08:00"
---

迹象：移植后同域出现成对矛盾失败——老套件断言"无程序终止"（B-G2: tool.repeat_observed 观测 + chars=0 提醒注入，模型保留裁决），新移植套件断言"接线存在"（stagnation.break/terminated + _stagnation_should_break 源码巡检）。判定三重佐证：1) git show HEAD:tool_cycle 注释"P2-A 后无 breaker authority"；2) stash 基线证实老套件在 HEAD 全绿；3) CR-R1 新测试 grep 零依赖 stagnation → 硬终止非移植必需。处置：摘除 engine 接线与 tool_cycle 判定方法；纯函数（stagnation_feedback 含 evidence-validity gate）保留——自含且被直测；矛盾巡检测试改写为反向守卫（断言接线不存在，防回流）。根因：大块移植天然携带 source 分支演进语义，需逐块对照 target 分支契约。

当前适用性说明：该记录的 stagnation.break/_stagnation_should_break 是“应被拒绝的源分支硬熔断”历史案例；当前有效结论是无 breaker authority，只保留事实观测与机械边界。