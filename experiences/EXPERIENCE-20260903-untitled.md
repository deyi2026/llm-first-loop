---
title: 并行多写者工作树：状态不符时先做 HEAD/index/worktree 三方对比
scenario: "本会话主线为死循环病灶自实现护栏（partition_stagnation_block + carry + task_store 确认门），同期间用户驱动 spec 线 tool_loop_guard（C-G1~C-G6 子代理批次）在同一 worktree 施工。子代理按 design D9 否决方案 A，将主线实现收编退役（改独立状态、carry 回退、用例改写），主线对此不知情；期间 edit_file 出现\"match 失败/verified-current Evidence 覆盖\"等混合态症状。"
root_cause: 单工作树多写者（主会话 + 演进管线 + spec 子代理）之间无所有权广播与变更通知机制。
solution: "① 每次开工前 `git status --porcelain` 留基线，收工后对照；② edit_file/report 等出现与自记状态不符时，立即做 HEAD/index/worktree 三方对比而非盲目重试；③ 并行线收编主线代码必须在报告中显式声明（如 C-G3 的\"收编残留 grep=0\"），主线以 spec 线任务账本为准、不静默抢回；④ 跨会话恢复时先 search_records/event_stream 对齐最新事实再动手。"
evidence: ""
tags: [并行线, worktree, clobber, 基线留底, spec工作流]
source: {}
status: active
record_kind: lesson
verification_state: unverified
created_at: "2026-09-03T07:50:31.507714+08:00"
updated_at: "2026-09-11T19:55:09.647912+08:00"
---

本仓单工作树多写者包括：主会话模型、演进执行管线（程序自动 apply）、spec 工作流子代理（spawn_subagent/DSH）。任何一方都可能在他方两轮之间修改文件。此经验与 spec/tool_octet_observation 的 motivation 同源：主会话连续 7 次重复 get_tool_schema 调用被 DuplicateGuard 熔断拦截，但"为什么发出"的决策面证据目前无观测——属执行链之前的 projection 层缺口。

当前适用性说明：正文末尾关于 DuplicateGuard 熔断是当时事故背景；当前程序已无该 breaker authority，本记录仅保留多写者/并行覆盖诊断原则。