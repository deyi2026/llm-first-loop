---
title: 重启自身宿主服务会让 schedule wake 的 grant owner 死亡，唤醒永不送达
scenario: 在 web 服务所在进程内注册 schedule(wake=true) 后，用 service_control restart 重启 web（或 all）——重启会杀死唤醒 grant 的 owner 进程
root_cause: ""
solution: 重启目标包含自身宿主进程时，不依赖 schedule wake 跨重启续跑：重启前把待查状态（action_id 等）写入持久位置并明确告知用户「下一轮需人工消息触发」；或先完成状态确认再重启宿主。观察到 grant_lost_owner_dead 退避重试时应直接放弃等待，改为用户触发或旁路检查。
evidence: "event_stream(scope=workspace,query=schedule)：sched-b5cb3351 注册于 2026-09-20T11:07:41Z；deferred_retry×4 reason=grant_lost_owner_dead 11:08:45→11:12:15Z；architecture_status action_trace rehydrated=true；service_control status：web svc-44b89dc9 succeeded 11:08:09Z pid 48884"
tags: [service-control, schedule-wake, self-restart, gen-57]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-20T19:19:37.375682+08:00"
updated_at: "2026-09-20T19:19:37.375682+08:00"
supersedes: [EXPERIENCE-20260917-schedule-wake-grant-unavailable-4-4, EXPERIENCE-20260920-wake-grant-run-timer]
---

2026-09-20 gen 57 发布验证中复现：19:07:41 注册 sched-b5cb3351(after=60s) 等待 web 重启终态；19:07:58 web 重启成功但杀死了唤醒 grant 的 owner 进程。event_stream 证据：19:08:45 起 schedule.wake deferred_retry reason=grant_lost_owner_dead 连续 4 次（30/60/120/240s 退避），唤醒从未送达 rehydrate 后的新进程（rehydrated=true），最终靠用户 19:14 人工消息续跑。教训：凡 target 含 web/all 的 service_control restart，本轮末尾注册的 schedule wake 必然失效；要么把等待检查放到不依赖本进程存活的位置（后台 execute_command 落盘标记+下轮读），要么明确告知用户需人工触发下一轮。web 重启本身 11 秒即 succeeded，等待它的自动唤醒才是卡点。