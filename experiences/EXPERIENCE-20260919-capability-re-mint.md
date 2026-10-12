---
title: 进程内一次性 capability 丢失后，重试结构性无效——恢复必须在授权源头 re-mint
scenario: "schedule wake 交付失败治理：grant 为进程内一次性委派能力，owner 进程在注册与触发之间重启后 grant 永久丢失；最初设想的\"claim 后重试等 grant 恢复\"经代码核实结构性无效。同类问题适用于一切\"进程内一次性 capability + 磁盘任务队列\"的组合。"
root_cause: ""
solution: "恢复动作必须发生在授权源头：同会话下一次真人 run 启动时用当前 human ingress 重铸（re-arm）丢失的 grant，并以有界退避窗口（30s→1m→2m→4m→8m，双上限 ≤10 次/首败+30min）保留磁盘条目等待重铸，超窗才降级为通知。配套：启动前先落 wake_started_at 标记，保证 re-arm 永不把已启动过的任务二次启动为自治 run；交付回调引入 WAKE_DEFERRED 哨兵区分\"成功 ack/瞬态 retry/自行 defer\"。"
evidence: 代码事实：src/llm_loop/core/scheduler.py（_WAKE_GRANTS 进程内注册表、claim_due 仅在 owner pid 死亡后放行跨进程 claim、WAKE_RETRY_DELAYS_S/WAKE_MAX_RETRIES/WAKE_RETRY_WINDOW_S、defer_wake_retry、note_wake_started、rearm_wake_grants、WAKE_DEFERRED 哨兵与 _loop 分支）；src/llm_loop/factory.py _deliver_schedule（grant_consumed_stale/grant_lost_owner_dead/runner_disabled/退避降级路径）；src/llm_loop/core/loop/lifecycle.py 真人 ingress re-arm 钩子；src/llm_loop/core/trace_leak/ingress_token.py delegate_ingress 拒绝委派 token 再委派。测试：tests/unit/test_schedule_wake.py 17/17（含 re-arm 重铸/委派拒绝/started 跳过/哨兵不 ack）；tests/unit 全量 pytest exit=0；ruff 全绿。
tags: [wake-grant, re-arm, one-shot-capability, scheduler, bounded-retry, EVO-20260919-f119847d]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-19T17:51:48.309656+08:00"
updated_at: "2026-09-19T17:51:48.309656+08:00"
---

EVO-20260919-f119847d 实现过程确认的机制事实与通用教训：

1. 一次性 capability（wake grant，进程内 _WAKE_GRANTS、不落盘）在 owner 进程死亡后，claimer 拿到的条目上该 capability 结构性不存在。claim_due 只在 owner 死亡后放行跨进程 claim，因此"claim 后重试等 grant 回来"永远不会成功——重试只能覆盖"同一 claim 内瞬态资源忙"（会话忙/守卫占用/runner 暂不可用）。

2. 永久丢失的正确恢复点是授权源头：同会话下一次真人 run 的 human ingress 经 delegate_ingress 重铸（re-arm）。lifecycle.run_stream 在真人 ingress（未委派）启动时触发，factory 注入 engine.rearm_wake_grants 指向共享 schedule store。

3. re-arm 必须配"已启动"标记（wake_started_at，启动 run 前先落盘），否则无法区分"grant 丢失未启动"与"已启动但 ack 落盘失败的 stale 条目"，会把同一 wake 二次启动为自治 run。宁可先落标记后启动（极端窗口丢一次续跑），不可反过来。

4. 交付回调需要第三种结果：成功 ack / 瞬态失败 retry / "已自行 defer 保留条目"。用模块级哨兵 WAKE_DEFERRED 解决，SchedulerThread 收到后既不 mark_triggered 也不 retry_later（否则固定 5s 会覆盖退避节奏或提前消费等待 re-arm 的条目）。

5. 审计教训：降级记录若只写 prompt_chars=0 会掩盖"完整消息其实已作为通知送达"的事实；应并列 notify_chars（真实正文字符数）与 prompt_chars=0。