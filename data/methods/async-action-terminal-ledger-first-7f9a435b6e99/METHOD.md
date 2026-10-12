---
method_id: async-action-terminal-ledger-first-7f9a435b6e99
name: async-action-terminal-ledger-first
description: 异步两阶段动作（restart/publish/deploy 类）的受理回执不等于终态。当被问"上次是否成功/是否被记录/为何没反馈"时，不要从全局健康快照或重新发现入手：沿 action_id -> 专属台账记录读终态与失败原因，再用同一 id 逐一核对各反馈通道（事件流/待办队列/开场注入），得出"已落盘但通道断"的结论。沉淀 verified 经验时必须在同一次写入附 evidence，避免参数被拒后重试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:1373:4b47664562ec1b1150f8
evidence_refs: learning:learn:a028e1d6501e
created_at: 2026-09-24T02:25:27.377990+00:00
updated_at: 2026-09-24T02:25:27.377990+00:00
---
## Trigger
用户询问此前发起的异步动作的最终结局、是否留痕或为何未被反馈；或异步动作已受理回执但尚未确认终态、需要闭环时。

## Discriminator
当时已知：会话内 event_trace/上一轮回复已明确该动作的 action_id、其专属台账文件路径（如 service-control-actions/<id>.json）及 status=failed。该事实可立刻把"所有可能相关信号"缩为"一份权威终态记录 + N 个指定反馈通道"，无需重新 grep 发现路径，也无需先拉全局审计快照。

## Short path
- 用会话内已见的 action_id 直接读其专属台账记录，取得终态 status 与失败原因（未知量：最终结局）
- 若终态 failed，用同一 id 逐个核对指定反馈通道：事件流检索、pending 队列字段、会话开场注入（未知量：哪个通道断了）
- 对照得出"已落盘但无通道主动推送"，并归因（受理回执不含终态、执行发生在发起会话之外）
- 沉淀经验/提交改进时，evidence 引用与结论同一次写入，verified 状态不再被参数校验拒绝
- 终态经权威记录验证、通道核对完毕且留痕被接受后停止

## Stop conditions
- 权威台账中的终态与期望版本/id 一致（succeeded），或失败原因已定位并可复述证据链
- 所有指定反馈通道均用同一 action_id 核对完毕并能解释静默原因
- 经验/改进写入被接受且携带 evidence，无遗留未验证断言

## Verification
- 台账的 status/updated_at 与事件时间线相互印证
- 每个通道的查询使用同一 action_id，结果能回答"为何没反馈"而非泛泛健康信号
- 写入类调用一次成功（含 evidence），未出现 verified-without-evidence 类参数拒绝

## Counterexamples
- 同步动作的回执本身已含终态：读回执即停，不需要再追台账
- 用户问的是"现在什么东西坏了"且无具体 action_id：此时全局健康/审计扫描是正确起点，本方法不适用
- 台账本身疑似过期或损坏：应交叉核对活体进程（PID/版本/运行状态），不能只信台账记录
