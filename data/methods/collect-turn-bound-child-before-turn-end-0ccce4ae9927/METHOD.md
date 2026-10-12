---
method_id: collect-turn-bound-child-before-turn-end-0ccce4ae9927
name: collect-turn-bound-child-before-turn-end
description: 当被委派的子代理/异步任务寿命绑定在父模型回合内（运行时证据：事件流 async.obligation cancelled_on_model_final；spawn 回执自称『后台启动，本回执不是任务结算』并点名收取工具），spawn 回执的 running 只是瞬时状态，回合结束即被取消，不能当持久事实汇报或依赖。需要委派产出时必须在同一回合内履行收取义务：优先同步通道（快速失败即降级），否则 spawn 后用收取工具的最大阻塞等待做本回合轮询；超预算时用租约/topology 机械字段区分『活跃未结算』与『卡死』，活跃则 steer 收尾。通用一层：凡执行物寿命绑定当前执行上下文，创建回执的状态字段不构成跨边界存活保证，收取动作必须安排在边界之内。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:fe0e1465-7509-459e-8792-eaaf6d7269f5:1066:93808ae27184f56a92ed
evidence_refs: learning:learn:f4dd9f97840a
created_at: 2026-10-13T03:10:00.054096+08:00
updated_at: 2026-10-13T03:10:00.054096+08:00
---
## Trigger
需要拿到子代理/异步委派任务的产出，且已有机械证据表明其寿命绑定父模型回合：事件流含 cancelled_on_model_final 记录，或 spawn 回执声明『本回执不是任务结算』并点名同一回合内的收取/等待工具（wait_seconds 形参）

## Discriminator
spawn/运行记录中的生命周期信号：『本回执不是任务结算』『后台启动』『cancelled_on_model_final』、收取工具的阻塞等待形参、租约字段 state/expired/settlement_state。任一存在，即把问题从『子代理在不在跑』转为『如何在本回合内结算它』

## Short path
- 先试同步/阻塞通道一次，快速失败即降级，不在失败通道上重试枚举
- spawn 后立刻进入同一回合收取循环：每次调用收取工具取最大阻塞等待值，禁止零等待短探询反复刷回执
- 等待超过任务书预算时：读 lease/topology 机械字段（state=active、expired=false、settlement_state=uncollected）判断是否活跃未结算，对外表述改为引用这些记录而非上一回合的 running 描述
- 确认活跃但超预算：agent_message steer 要求收尾，随后等待并收取最终结算回执
- 结算到手即停：取消已被本次收取替代的旧 wake/obligation，不追加确认动作

## Stop conditions
- 收取调用返回结算态（completed/failed/cancelled）并附带最终产出
- 租约 expired=true 或拓扑 terminal——转入错误处理/重派决策，不继续空等
- 发现同步通道或父会话本身即可完成，委派多余，取消委派

## Verification
- 对『是否在跑/结果如何』的对外断言必须引用 lease、settlement 或事件流的带时间戳记录，不得引用 spawn 时刻的 running 字样
- 成功收取的判据是收到结算回执（child_state≠running），而非又一次 running 心跳
- 若执行了 steer，检查其后回执是否为结算态；仍 running 则升级为取消重派而非继续等待

## Counterexamples
- 平台保证子代理完成会可靠回调/唤醒父会话且有成功投递事件佐证——此时结束回合等回调更省墙钟，不必本回合阻塞
- 寿命独立的后台任务（自带租约的 daemon、经验证可投递的 scheduled wake，如本集 sched-33725a46 那类独立计划任务）不受父回合结束影响，不能套用『回合结束即死』
- 同步通道可用且健康——直接同步调用最短，spawn+轮询是降级路径不是首选
- 秒级即结算的小任务：一次阻塞收取即可，租约检查与 steer 机制不应触发
