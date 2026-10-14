---
method_id: session-exit-gated-async-action-register-then-yield-afcd61145622
name: session-exit-gated-async-action-register-then-yield
description: 当异步动作（如 service_control restart 两阶段 detached worker）的受理回执或 schema 显式声明下一阶段以『requester 会话结束』为推进门禁时，本会话内的阻塞等待与状态轮询不可能改变状态，只会推迟回复结束、从而推迟物理执行。正确路径：受理后立即注册带 action_id 与核对项的验证唤醒，随即结束回复放行门禁；唤醒后再查终态并验证效果。省去 wait+status 这条只复读既定事实的回路（本集浪费 90s+2 次调用，且 wait 主动延迟了门禁满足）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d0721026-9d2f-493f-ad09-a5560e92b589:613:ec7bc39f29c50bae3814
evidence_refs: learning:learn:c20f0cafa582
created_at: 2026-10-13T14:49:06.537402+08:00
updated_at: 2026-10-13T14:49:06.537402+08:00
---
## Trigger
已发起受控异步动作并拿到受理回执（action_id/generation），且回执或工具 schema 明确声明 worker 先等 requester 会话结束、再等目标空闲后物理执行——即门禁推进条件是本会话停止回复。

## Discriminator
发起 wait/status 之前回执已出现的门禁声明：『两阶段等待（先等 requester 会话结束，再等目标空闲）』。据此可判定：只要本会话仍活跃，status 必停留在 waiting_for_requester_exit，会话内 wait+轮询是无信息量的既定结果，且 wait 本身把回复结束推迟同等时长。满足 knowledge-at-time。

## Short path
- 发起 restart，取回 action_id/generation
- 读回执门禁声明：下一阶段等待 requester 会话结束 → 判定会话内核对无意义且会延迟执行
- 立即注册验证唤醒：schedule 内自含 action_id、终态核对命令与效果验证项
- 立即结束回复放行门禁，不做会话内 wait/status
- 唤醒后查 status 终态，实测目标效果并如实回报

## Stop conditions
- 已注册含核对项的验证唤醒，并已向用户回执受理信息后结束回复
- 唤醒后 status 为 succeeded/failed 终态且效果验证完成
- status 出现非预期状态（failed、owner 冲突、待 verify_acknowledge）→ 转会话内处置，不再等待

## Verification
- 回执必须显式含『等待 requester 会话结束』类门禁字样，才允许跳过会话内 wait+status
- schedule 必须自含 action_id 与终态核对入口（如 status 含 action_id），避免唤醒后重新检索
- 完成判定只以唤醒后的 status 终态字段为准；受理回执不得当作完成（受理≠完成）

## Counterexamples
- 异步动作未声明依赖会话结束（普通后台构建/发布可并行推进）：会话内等待/轮询合理且必要，不套用本方法
- 受理即报错或被拒（如非终态 owner 冲突拒绝）：必须会话内立即处置，不能 schedule-and-yield
- 无唤醒/排程机制可用，或用户明确要求本回复内确认结果：只能如实说明无法在会话内完成，而非靠结束回复伪装放行
