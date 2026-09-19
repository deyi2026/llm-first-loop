---
method_id: audit-duplicates-via-unfiltered-timeline-and-controlflow-boundary-340f7604d311
name: audit-duplicates-via-unfiltered-timeline-and-controlflow-boundary
description: 审计会话内重复/异常动作时，先一次拉取完整未过滤事件流建时间线，再定位控制流边界事件（定时唤醒/上下文压缩/会话交接）来区分有意轮询与完成后重放；把『返回事件数远小于已知活动量』当作过滤过窄的即时信号，立即去过滤重拉而非微调关键词；最后用权威来源核验副作用终态并清理残留（残留进程、幂等终态），把机制教训存档。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:863879fe-d8f5-48d9-bbdc-6ddc6eaf4b8b:637:acaa4a73e0a9c07345dd
evidence_refs: learning:learn:ed65b0e2edd3
created_at: 2026-09-19T08:44:42.058251+00:00
updated_at: 2026-09-19T08:44:42.058251+00:00
---
## Trigger
用户要求审计工具调用或日志中的重复/异常，且会话涉及后台任务、定时唤醒（schedule/wake）、上下文压缩（compact/fold）或会话交接等控制流事件，根因可能不在当前可见上下文内

## Discriminator
定向查询返回的事件量与会话已知活动量明显不匹配（例：event_stream 只回 1 条，而 tool_history 已列出 ≥8 条同会话动作），且审计目标是因果完整性——此事实在结果返回当场即可判定过滤条件丢事件，应去过滤全量拉取；另一判别事实：tool_history 中相同命令模式聚类可直接给出可疑重复候选，无需先枚举其它来源

## Short path
- 从已给的 tool_history 按相同命令/参数模式聚类，列出候选重复项（未知量：哪些动作可疑、各出现几次）
- 一次性拉取本会话完整 event_stream，不加关键词/时间窗过滤（未知量：每次重复的发生时刻与两次执行之间隔了哪个控制流事件）
- 在时间线上定位『原始完成/汇报』与『重放』之间的边界事件（wake 触发、run.compact 折叠、句柄丢失），把每处重复分类为有意轮询或完成后重放（未知量：机制）
- 影响面核查：ps 查残留进程；用权威来源核验副作用目标终态，字段名以回执列出的可用字段为准（未知量：是否需要处置）
- 幂等处置（kill 残留、确认终态正确），机制教训存档后停止

## Stop conditions
- 每个报告的重复都有带时间戳的事件流条目与明确机制解释，且事件流覆盖到会话最早的因果前因（如 schedule 注册点）
- 副作用目标终态已由权威来源验证、无残留进程、教训已存档
- 体积一致性满足：拉取到的总事件数不少于 tool_history 已知动作数，确认无过滤漏采

## Verification
- 最终清单逐条回对 event_stream 时间戳，次数与机制描述一致
- 拉取结果做体积一致性检查，防止再次窄过滤漏掉前因事件
- 终态核验只使用平台实际支持的字段/接口（先读错误回执中的可用字段列表再重查）
- 残留核查以进程表实际为空为准，而非仅凭句柄状态推断

## Counterexamples
- 问题只针对某个已知动作或单个 job 时，定向过滤查询是正确做法，全量拉取属于过度收集
- 重复全部发生在当前可见上下文、无压缩/唤醒/交接参与时，tool_history 本身已足够定位，完整时间线增益很小
- 事件流过大或按量计费时，应按范围分页并以体积不匹配信号决定扩窗，而不是无脑一次全量
