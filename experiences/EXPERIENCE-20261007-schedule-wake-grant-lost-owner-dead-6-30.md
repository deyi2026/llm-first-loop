---
title: schedule.wake 授权丢失（grant_lost_owner_dead）确定性失败全链实证：6 次退避约 30 分钟后降级为仅通知
scenario: 用一次性 schedule wake 做跨会话/延迟核对（典型：restart 终态验证、异步动作 succeeded/failed 分支核对）时，发起会话已结束导致唤醒授权归属丢失。2026-10-07 两个 sid 全链复现：deferred_retry reason=grant_lost_owner_dead 按 30/60/120/240/480/480s 退避重试 6 次（约 30 分钟），最终 degraded_to_notify reason=grant_lost_owner_dead_retry_cap，prompt_chars=0（仅通知不续跑，原始唤醒 payload 丢失）。
root_cause: ""
solution: "① 出现 grant_lost_owner_dead 即视为确定性终态：生命周期事件不归属请求会话，不要在会话日志加大窗口重查，直接 event_stream(scope=workspace) 按 sid 查全局 action_trace；② 不原样重挂同一 wake（授权竞争依旧存在），改用不依赖该授权的兜底：用户在场时明示需手动续跑、或程序侧轮询/notify 通道确认；③ 计划 restart 终态核验时预先按\"wake 可能降级为 notify\"设计核验通道，勿把终态结论托付 wake。"
evidence: "event_stream scope=workspace 2026-10-07 共 9 条 action_trace：sid=sched-51bef712（19:55:32 retry_count=6 next_delay_s=480 → 20:03:33 degraded_to_notify reason=grant_lost_owner_dead_retry_cap）；sid=sched-736aa0ab（20:10:03 retry1/30s、20:10:33 retry2/60s、20:11:33 retry3/120s、20:13:34 retry4/240s、20:17:34 retry5/480s、20:25:34 retry6/480s → 20:33:35 degraded_to_notify，notify_chars=437、prompt_chars=0）"
tags: [schedule-wake, grant_lost_owner_dead, deferred-retry, degraded-to-notify, restart-终态核验, 确定性失败不重试]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-07T21:19:37.803987+08:00"
updated_at: "2026-10-07T21:19:37.803987+08:00"
---

本卡将 experience:EXPERIENCE-20260919-restart-schedule-wake-wake（当时 unverified 的"restart 后 wake 一次性续跑失效"）与 EXPERIENCE-20260910/20260906-schedule-wake-restart 的现象验证并细化到原因级：grant_lost_owner_dead + 固定退避重试 + retry_cap 降级。诊断方法与 method:deferred-action-failure-layer-scoped-lifecycle-trace-ae4184904e2b 一致：全局生命周期事件归属判定，不在请求会话日志上重查。