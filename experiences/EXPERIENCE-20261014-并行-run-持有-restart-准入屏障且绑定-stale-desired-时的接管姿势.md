---
title: 并行 run 持有 restart 准入屏障且绑定 stale desired 时的接管姿势
scenario: service_control restart：另一并行 run 抢先对旧 desired generation（gen260）发起 restart 并持有准入屏障，卡在 waiting_for_idle；本会话已 publish 新 desired（gen261），活操作不可直接打断
root_cause: ""
solution: "①不打断活操作；②核对 restart 实现（build_restart_plan 严格绑定 desired generation），确认其绑定 260≠261 必然 stale 失败；③让其按 idle 超时（900s）自行 failed 自清屏障（14:41:32）；④屏障一释放立即受理新 desired 的 restart；⑤两阶段等待要等 requester 退出 turn 后才落代，挂短周期自动续跑唤醒收口，不在本 turn 内轮询空等。当前性验证：service_control(action=status, target=web) 应得 admission_barriers=[] 且 stable.matches_desired_generation=true，否则重评"
evidence: "2026-10-14 实测：14:41:32 接管受理 svc-a2ced2815d944eb39641bcaed24c9028；status 回执 stable.generation=261 / lag_generations=0 / matches_desired_generation=true / succeeded_at 2026-10-14T14:44:08+08:00 / terminal_action_barrier=null；15:06 唤醒 run 完成 gen261 收敛核对与 queue 面板浏览器实测，GOAL-20261014-dddae6e0 置 complete。"
tags: [service_control, restart, admission-barrier, parallel-run, stale-binding]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T15:11:28.570817+08:00"
updated_at: "2026-10-14T15:11:28.570817+08:00"
---

背景：service_control restart 采用准入屏障互斥。本次一个 12:08 启动的并行 run 在 14:26 抢先对旧 desired（gen260）发起 restart 并持有屏障，卡在 waiting_for_idle；本会话随后 publish 了 gen261，形成"活操作持有屏障 + 其 desired 已 stale"的局面。处置：(1) 不打断活操作（未知副作用）；(2) 依据 restart 实现中 build_restart_plan 的严格 desired 绑定，判定该操作必然以 stale 失败，无需人工取消；(3) 等 900s idle 超时自行 failed（14:41:32），屏障自动释放；(4) 随即受理新 desired 的 restart。另注意两阶段等待必须等 requester 退出当前 turn 后才落代，主动轮询无意义；挂 10 分钟自动续跑唤醒收口即可。本次 14:44:08 即收敛，比最坏情形快。当前性验证：调 service_control(action=status, target=web)，应得 admission_barriers=[] 且 stable.matches_desired_generation=true；若出现新屏障条目或 mismatch，说明屏障/绑定行为已变，本条结论需重评。