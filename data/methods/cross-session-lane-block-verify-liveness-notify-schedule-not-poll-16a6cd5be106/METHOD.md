---
method_id: cross-session-lane-block-verify-liveness-notify-schedule-not-poll-16a6cd5be106
name: cross-session-lane-block-verify-liveness-notify-schedule-not-poll
description: fail-closed 闸（内部 commit/知识入库/主写门类）以『他人 live lane/他人会话占用』为由拒绝、并明示释放条件是对方终态时，第一个未知量不是『怎么过闸』而是『阻塞者还活着吗』：先读闸自身源码拿到权威账本路径与 stale 兜底阈值，用账本最新行+coordination/事件日志尾交叉判定活跃度。活跃→不绕不 reap，向对方会话投递 help_request 说明堵住了什么，用零副作用的闸调用本身做终态探测，一两轮后停止 run 内轮询，落盘自包含 runbook 并注册定时续跑。陈旧→走闸自身 stale 回收路径。
aliases: 被别的会话的lane卡住了, 等别的agent收口再重试, 多会话合并闸排队等终态, 别人的活跃lane挡住我的提交, 闸说等对方终态怎么办, 活锁等待转定时续跑
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:df541f4c-2416-4a84-a73b-c1c05feb56d1:132:88d42d7abd945261cda1
evidence_refs: learning:learn:cfaf625de35d
created_at: 2026-11-15T21:52:02.667664+08:00
updated_at: 2026-11-15T21:52:02.667664+08:00
---
## Trigger
闸门拒绝回执点名『他人 live lane / 他人会话占用』并给出『等对方终态后重试』类释放条件；即阻塞条件属于另一 agent 的生命周期，而非本地可修复前置。

## Discriminator
回执是否同时具备三要素：(1) 点名阻塞实体（lane id/会话 id）；(2) 释放条件=对方终态；(3) 自述设计动机（避免合并闸竞争、0 副作用、fail-closed）。三者齐备→绕过即破坏协调协议，等待是设计内路径。且闸脚本源码就在工作区，grep 一次即可拿到权威账本路径、最新行优先规则与 STALE_AFTER 阈值——不要先猜路径/find 全扫去找阻塞者的存放文件。

## Short path
- 对拒绝回执先 grep 闸自身源码/文档：拿权威账本路径、最新行优先规则、stale 阈值、自排除参数（--session-id 语义）
- 读账本中阻塞者最新行：status/owner_session/base/goal，与 coordination 状态、对方事件日志尾（run.end 之后是否又有新 run.opened）交叉判定活跃 vs 陈旧
- 判活跃→不绕不 reap；向对方会话投递 help_request（need=info，写明堵住了哪个下游动作、需要什么答复）
- 用零副作用的重试闸调用本身做终态探测：每轮 wait 后重试一次闸即可（注意 wait 单次上限），无需反复重读账本或扫对方日志
- 两轮仍堵且对方持续开新 run→停止 run 内轮询：写自包含 task-state（已核实事实+闸链+接手步骤），注册间隔大于对方单轮耗时的定时续跑，向用户报告等待是正确路径而非失败

## Stop conditions
- 闸调用放行（对方 lane 终态或按规则 stale 回收）→ 立即接续被闸的下游动作链
- 对方回复 ETA → 按 ETA 调整续跑间隔
- 账本显示对方 lane 已 merged/abandoned/closed 但闸仍拒 → 转为诊断闸自身 stale 判定，而不是继续无限等
- stale 兜底阈值触发在即且无人工通道 → 上报用户决策，不要自行回收他人 lane

## Verification
- 唤醒后先重试闸本身确认放行，再核对账本阻塞行确已终态
- 下游被闸动作（如 review_admission→push）回执 accepted 且终态一致
- 确认全程零副作用：未改写他人 lane 行、未对活跃 worktree 做任何操作

## Counterexamples
- 阻塞条件是当前会话自身（自己的 lane / deferred 动作依赖本 run 结束才生效）→ 属自阻塞场景：结束回合即释放，机制不同，勿套本卡
- 拒绝 reason 是本地可修前置（缺字段、knowledge_flush_pending 本身这类）→ 直接修前置，不要等外部生命周期
- 阻塞者按闸自身规则已 stale（空闲超阈值+worktree 干净）或账本 status=abandoned → 走 stale 回收路径，不注册无限续跑
- 对方临界区是秒级（如一次合并几秒完成）→ 单次有界 wait 后重试即可，定时续跑反而不划算
- 闸不是 fail-closed 的协调保护而是普通排队/可插队语义 → 本卡的『绝不绕过』不适用
