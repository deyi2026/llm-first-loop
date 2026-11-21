---
method_id: completion-wake-binding-rejected-degrade-to-contract-carrying-reminder-2b6f0e446f24
name: completion-wake-binding-rejected-degrade-to-contract-carrying-reminder
description: 为受管异步子任务绑定完成唤醒时，调度器以『event_predicate requires predicate_ref』类参数约束拒绝，且上下文没有该字段取值来源：不换措辞重试同一形态，也不放弃终态核验。判别依据是准入回执的 waiting_protocol 本身并列了有界 status 轮询与事件绑定两种等待模式、且声明唤醒后仍须 status 核验——终态核验义务由 status 承担，事件绑定只是省空转的优化，绑不上就切换模式。先补一次 status 确认 pending，再注册 immediate 提醒，文本内嵌可独立执行的核验合同（child_id、候选SHA、到点首动作=status、真实终态词表、禁止清单），唤醒后仍以 status 回执为准。
aliases: 绑不上事件唤醒怎么继续等审查结果, 调度器报缺参数改用提醒续跑, 异步审查到点自动核验别只等墙钟, 等待模式降级轮询兜底, 唤醒失败别丢核验义务
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:dc9cbbb4-590e-40e1-b360-158e5ef5619b:846:0d97f8722271a8bce2f4
evidence_refs: learning:learn:e8de95d0970f
created_at: 2026-11-19T19:43:32.857943+08:00
updated_at: 2026-11-19T19:43:32.857943+08:00
---
## Trigger
为受管异步子任务（独立 Reviewer/子代理）绑定完成唤醒（如 review_terminal）时，调度器以参数约束拒绝（回执点名 event_predicate requires predicate_ref），且当前上下文没有该 predicate_ref 的取值来源。

## Discriminator
补救动手前已在场的两条事实：①准入回执的 waiting_protocol 并列『有界 status 轮询』与『completion-wake 事件绑定』两种等待模式，且声明『唤醒后仍须 status 核验资格』——即终态核验义务由 status 承担，事件绑定只是减少空转的优化；②错误回执自述缺失字段是 predicate_ref，而场内不存在可用的 predicate 注册来源。两条合起来把『如何凑齐事件绑定参数』缩成『切换等待模式并保住核验合同』。

## Short path
- 解析拒绝回执：缺失字段=predicate_ref，检索上下文无该字段取值来源 → 判定事件绑定形态本回合不可达，不换措辞重试同一参数
- 先补一次 review_admission(action=status, wait_seconds=30) 确认子任务仍 pending，保证监控义务未因调度失败中断
- 注册 immediate 提醒式 schedule，文本内嵌可独立执行的核验合同：child_id、候选材料 SHA、HEAD、到点首动作=action=status、真实终态词表（PASS/P0/P1/REVISE）、禁止动作清单
- 确认提醒回执含『到点自动续跑当前会话』语义后才收口回报
- 唤醒到达后第一动作仍是 status 核验，wake_reason/计时到达不作为终态证据

## Stop conditions
- 提醒式 schedule 注册成功且回执含到点自动续跑语义
- 等待期间任一次 status 查询返回真实终态（PASS/P0/P1/REVISE）→ 直接按终态处理，不再依赖提醒

## Verification
- 提醒文本不经上下文即可执行：含 child_id 与候选 SHA，首动作指令明确为 action=status 核验
- 唤醒/提醒到达后必须以 review_admission status 回执核验资格，禁止把到达时间当作完成证明
- 对照 waiting_protocol：所选等待模式（轮询+提醒续跑）属于其声明的合法模式集合

## Counterexamples
- 错误是取值非法而非缺字段（如 predicate_ref 传了但格式错），或上下文存在可用 predicate_ref → 按『缺失字段=取值』合同差分修正并重发同一事件绑定，不降级为提醒
- waiting_protocol 只认可事件绑定（终态必须事件推送、无轮询替代）→ 提醒降级不满足合同，先解决 predicate_ref 来源再绑定
- 提醒调度本身也被整体拒绝（调度面不可用）→ 退回纯有界轮询并在本回合继续 status 查询，不得假装已安排唤醒后收口
- 子任务已返回终态（status 直接 PASS/REVISE）→ 无需任何唤醒安排，直接处理终态
