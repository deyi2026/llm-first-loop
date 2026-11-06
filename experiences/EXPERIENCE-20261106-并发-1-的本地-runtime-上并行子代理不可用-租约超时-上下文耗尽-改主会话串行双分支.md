---
title: 并发=1 的本地 runtime 上并行子代理不可用：租约超时+上下文耗尽，改主会话串行双分支
scenario: 本地 runtime（prompt_concurrency=1、子代理上下文受限）需要并行推进多文件修复任务时，考虑用 spawn_subagent 双 lane 并行提效。
root_cause: ""
solution: 先查 architecture_status 的 prompt_concurrency 与子代理上下文能力：并发=1 或子代理上下文明显小于任务读取量时，不要派并行执行体——改为主会话串行实施 + 双 worktree/分支结构 + lane 账本与合并审查，交付结构与治理完全等价。远程模型子代理（审查类、读少量文件）仍可用。
evidence: "architecture_status prompt_concurrency=1；subagent_87baf950a3f4 续话 refused（fleet lease 权威失效）；subagent_797d84adbb7a failed（上下文预检拒绝静默截断）；agent_message 队列回执\"在下个 step boundary 交付\"后子代理终止。"
tags: [subagent, parallel, runtime-limit, lease, orchestration]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-06T14:06:00.150241+08:00"
updated_at: "2026-11-06T14:06:00.150241+08:00"
---

现象：本机 LFL runtime 的本地模型 prompt_concurrency=1，父会话+两个并行修复子代理共用模型队列，导致：子代理 A 完成勘察后闲置、租约（约 17 分钟 TTL）到期触发 effect fence、续话 refused；子代理 B 24 轮读文件后上下文窗口耗尽 failed（1.68M tokens in，零落盘）。处置：主会话亲自串行实施，双分支（.worktrees/m1-desktop / m1-browser）结构保留，合并走 lane 账本 + RULE-AI-34 审查——执行者换成主会话不影响交付结构。教训：在此类 runtime 上派并行执行体前先看 architecture_status 的 prompt_concurrency；本地小上下文模型不适合"读大库改多处"的子代理任务，除非单缺陷+指定行区间。远程模型子代理（glm-5.3 审查代理）表现正常。另：向运行中子代理发"进度检查"消息会诱导其"回报即终止"（本例实测），监控应只轮询 subagent_result/lease，不发消息。