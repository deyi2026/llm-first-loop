---
method_id: single-pending-writer-ledger-check-then-conditioned-wait-42a348b2b1e0
name: single-pending-writer-ledger-check-then-conditioned-wait
description: 用于'完成了吗'类状态询问：先以权威 append 台账（rows.jsonl/manifest）对照计划行集合求出精确缺失集合，再按 run 身份 ps 确认缺失行是否有活跃 writer（CPU/存活/耗时），对照同任务参考时长判断偏慢是否在正常带内。若剩余唯一未知量是时间可解的'某行何时落盘'而非查询可解，立即停止重复同参数状态查询，注册一次条件化定时续跑（台账落行或进程退出触发），并设卡死阈值。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:2032:2e3771f532f1617af2b9
evidence_refs: learning:learn:7453d2e150bf
created_at: 2026-09-22T16:27:25.354730+00:00
updated_at: 2026-09-22T16:27:25.354730+00:00
---
## Trigger
用户询问长跑批处理/评测任务是否完成；存在权威 append 台账与计划行集合；可能有 worker 仍在运行

## Discriminator
台账 diff 已给出精确缺失行集合，且 ps 显示恰有一个活跃 writer 绑定到缺失行（高 CPU、进程存活）——此时唯一剩余未知量是时间可解而非查询可解，任何重复的同参数状态查询都不产生新信息

## Short path
- 读运行台账并与计划行集合 diff：未知量=哪些行缺失，得到精确缺失集合
- 按 run 身份 ps 过滤活跃 worker：未知量=缺失行属于'运行中/已死未落行/未启动'哪一类
- 对照同任务参考时长带宽：未知量=当前耗时是正常偏慢还是异常卡死
- 向用户报告唯一剩余未知量，注册单个条件化定时续跑（行落台账或 worker 退出即触发），附卡死阈值（超时或 worker 死亡未落行则如实报告并诊断，不擅自重跑）
- 停止一切同参数状态查询，直到定时触发或用户再次询问

## Stop conditions
- 缺失行全部落台账且对应 worker 已退出：转入终判并汇报，不再查询状态
- worker 已死且行未落台账：停止等待，转诊断并如实报告，不擅自重跑
- 已注册条件化续跑：不再发起新的同参数状态查询

## Verification
- 复查台账行数与计划行集合一致，ps 确认无残留 worker 进程
- 确认续跑绑定的是台账落行/进程退出事件条件，而非固定短间隔的重复轮询
- 终判读数（duration/rounds/reward/facts）对照参考基准文档（如 B2_REFERENCE.md）

## Counterexamples
- 台账非 append 权威（结果在结束时整体重写）：行数轮询不是有效判别，应查完成标记或 manifest
- 用户问的是已完成结果的正确性而非完成度：台账+活性检查无法回答，必须读结果内容本身
- 环境没有定时续跑/调度机制：条件化等待不可用，只能按参考时长设定低频间隔轮询
- 多个 worker 并发写多行且行间相互依赖：单变量等待过度简化，需逐实体核验
