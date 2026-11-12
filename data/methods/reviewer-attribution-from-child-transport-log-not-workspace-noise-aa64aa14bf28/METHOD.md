---
method_id: reviewer-attribution-from-child-transport-log-not-workspace-noise-aa64aa14bf28
name: reviewer-attribution-from-child-transport-log-not-workspace-noise
description: 异步审查/准入闸取得终态 PASS 后，若任务点名要回填的执行归属字段（reviewer 实际 model/attempt、P0/P1 计数、材料指纹）不在 start/status 回执 schema 内：不要原样重发 status（终态回执字段固定、零增量），也不要用模型名做工作区级 event_stream/search_records 检索——那只会命中兄弟会话的 cache_monitor/model.switch 路由噪音。唯一权威来源是该 child 自身的执行痕迹：按 child_id 定位 per-child 持久事件日志（provider.transport.opened/settled、subagent.terminal）或 child_state 回执（含子代理回答与结论行），并核对其 candidate_sha256 与 start 回执一致。
aliases: PASS了但回执里查不到审查员型号, 怎么核实子代理真实跑在哪个模型上, 终态了缺字段还能从哪补, 顺着子代理ID找它自己的运行日志, 工作区事件流搜模型名全是缓存告警, reviewer是谁跑的从哪取证
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:7d4eeb31-62b6-4a0d-b484-052b8b5ab066:0:88ef41e60ae3f5c2a936
evidence_refs: learning:learn:af42c34dccc7
created_at: 2026-11-12T09:46:39.280650+08:00
updated_at: 2026-11-12T09:46:39.280650+08:00
---
## Trigger
异步子代理审查/准入闸已回终态（qualification=PASS、artifact_reviewed=true、SHA 与 start 一致），但用户要求的字段（reviewer 实际 model/attempt、findings 计数、材料字节/指纹）未出现在任何闸回执中

## Discriminator
start 回执的 review_budget.models 只是候选列表而非实际执行者；status 回执 schema 在终态后固定，同参重复调用不产生新字段；workspace 级流按模型名检索返回的是跨会话路由/缓存告警，不含本 child 的执行事实。child_id 是把『谁执行了这个 child』join 到其 transport 日志的唯一键

## Short path
- 终态回执到手后先列缺口字段清单，逐一分类：属于闸的判定（qualification/scope/SHA）还是 child 的执行属性（model/attempt/tokens/结论行）
- 闸判定字段已核过即不再重发同参 status；执行属性字段缺口→转向 child 侧痕迹，而非闸轮询
- 按 child_id 解析 per-child 持久事件日志位置（已知命名约定直读，否则一次精确路径检索解析命名方案），读 provider.transport.opened/settled 取 model_id/attempt_kind/retry_index，读 subagent.terminal 取 outcome
- P0/P1 等内容计数取自子代理回答的机器可解析结论行；闸回执未回显时，报告须标注来源为 child 正文而非闸终判
- 核对 child 日志中的 candidate_sha256 与 start/终态回执逐字节一致后，报告全部字段并停止

## Stop conditions
- 闸终态回执已直接包含全部点名字段（含 reviewer model/attempt）→ 报告即停，零补充检索
- child 执行日志不可读或不存在 → 如实报告字段不可得，禁止用 model.switch 事件推断执行者
- child 日志回显 SHA 与 start 回执不一致 → 停止并上报材料不一致，不进入下游被闸动作

## Verification
- provider.transport.settled 的 provider_observed_model 与报告的 reviewer model 一致
- attempt/重试计数取自 transport 事件（attempt_kind、transport_retry_index），而非 review_budget.models 候选列表
- candidate_sha256 在 start 回执、终态回执、child 日志三处一致

## Counterexamples
- 终态回执 schema 本身含 reviewer model/attempt 字段的闸——直接报告，不做任何 child 侧检索
- 用户只要求 PASS 与 SHA、未点名执行者身份——终态回执即充分，不主动深挖
- 回执为 REVISE 或内容未过——属判定归因问题，走判因/重跑方法而非执行痕迹检索
- 该环境 per-child 日志未持久化——回退为『字段不可得』如实上报，不从全局模型切换事件倒推
