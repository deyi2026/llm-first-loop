---
method_id: deferred-wakeup-verify-async-action-terminal-states-e9c597e4c1e4
name: deferred-wakeup-verify-async-action-terminal-states
description: 当后台/异步动作回执显式声明『受理≠完成』（未查询到 status=succeeded/failed 不得宣布完成/失败），且动作被设计为等待当前会话结束才执行时，本回合内终态不可观测。此时不要空口承诺『回复后会自动继续』（本集明示此类承诺曾未兑现），也不要把受理回执当完成。正确做法：显式注册一次性定时唤醒，payload 中逐个点名 action_id 的核对入口与 succeeded/failed 分支计划，并把跨回合需保留的后续待办一并打包进唤醒，防止回合边界丢失。汇报只说『已受理』，查到终态才算数。把『等待/承诺』换成一条机械化的延迟核对，省去失败补台与用户追问。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ca02bdc1-1ca9-4389-9732-e3ba796f5550:561:e3c531c65cd7b64c8c4e
evidence_refs: learning:learn:326988d9c6c4
created_at: 2026-10-07T18:44:35.152921+08:00
updated_at: 2026-10-07T18:44:35.152921+08:00
---
## Trigger
对后台/异步动作（如 service_control 重启）收到 accepted 回执；回执显式写明『受理≠完成』并给出终态核对入口；且动作说明其执行先等待 requester 会话结束——即本回合内终态必然不可见。

## Discriminator
当时已可见的两条事实：(1) 回执文本明确『未查询到 status=succeeded/failed 不得当作已完成/已失败宣布』并给出 service_control(action=status, action_id=…) 核对入口；(2) 动作执行依赖本回合结束（web 重启注明『会等我本回合结束后再执行』），口头『自动继续』无机制保障，只有 schedule/wakeup 提供跨回合续跑能力。

## Short path
- 派发各后台动作并记录 action_id（此时唯一已知量：已受理）。
- 读回执判别：若终态异步且执行依赖本回合结束，判定本回合内核对不可行，放弃同回合等待或口头承诺。
- 注册一次性定时唤醒，payload 内嵌核对计划：逐个点名 action_id 的 status 查询入口、succeeded/failed 分支动作，以及需跨回合保留的后续待办（如用户提出的长期建议）。
- 收尾汇报只陈述已受理 + 唤醒时间 + 判定标准，不使用完成语气。
- 唤醒后按计划逐个查终态：全部 succeeded 才执行依赖收尾（如登记完成）；任一 failed 则取失败阶段事实修复后重试。

## Stop conditions
- 每个 action_id 均查到显式 succeeded/failed 终态（failed 转入修复分支）之前，不宣布部署或动作完成。
- 若已有确认可靠的自动回调/事件机制保证续跑，不再叠加额外定时唤醒。

## Verification
- 终态断言前，用回执点名的核对入口逐个查询到非空 status；查询所用 action_id 必须与受理回执一致。
- 最终汇总中不得出现未经该查询支撑的『已生效/已完成』；只能给快照时注明查询时间与来源。

## Counterexamples
- 同步工具回执本身已含终态（status=succeeded/failed）时，回执即事实，无需排程唤醒，直接进入下一步。
- 存在已确认会自动续跑的回调/事件机制时，再挂额外定时器只会造成重复唤醒与重复执行。
- 只读、幂等或无用户可见后果的动作，未核对终态不会产生误导性宣布，不值得为此排程。
