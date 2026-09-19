---
title: schedule wake 不可作为无人值守窗口的主机制（grant_unavailable 4/4 降级）
scenario: 依赖 schedule(wake=true) 在无人值守窗口（如次日早晨部署窗口）自动续跑会话
root_cause: ""
solution: "永远不把 schedule wake 当主路径。注册唤醒的同时，把任务状态写成自包含恢复指令（已完成事实/确切下一步/可直接粘贴的命令），并明确告知用户\"唤醒可能失败，回一句『执行』即可按 checkpoint 恢复\"。"
evidence: "event_stream(scope=workspace, query=grant_unavailable) evidence://v1/50202e039d2439c85e63d224ecb8f47fadb0545b92b2e850513120902229ef89（4 条 degraded_to_notify，2026-09-17 本会话核验）；演进建议 EVO-20260917-a8c10c58"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-17T16:46:16.133483+08:00"
updated_at: "2026-09-17T16:46:16.133483+08:00"
---

事件流证据：sched-bd65338b(09-10)、sched-c0cff602(09-15)、sched-2a77069d(09-16)、sched-e0f9ad1d(09-17) 四次 wake 全部 reason=grant_unavailable 降级，且 prompt_chars=0（通知不带负载）。09-17 08:00 因此错过 T0 部署窗口。设计定时流程时：主路径=用户次日回复一句话按 checkpoint 恢复；wake 只当尽力而为的加速器。schedule message 必须自包含（状态+下一步+确切命令），因为唤醒失败时它是唯一传给恢复会话的线索。