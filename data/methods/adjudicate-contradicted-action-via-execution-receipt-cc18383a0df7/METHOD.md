---
method_id: adjudicate-contradicted-action-via-execution-receipt-cc18383a0df7
name: adjudicate-contradicted-action-via-execution-receipt
description: 当用户的事实断言与模型先前汇报的动作结果矛盾时（尤其 restart/publish 这类'受理≠执行'的异步动作），未知量是'该动作的执行终态'。唯一裁决层是按 action_id 索引的服务端执行回执/审计记录；会话 evidence 搜索、快照长文分页、event_stream 摘要都是派生层，结构上不含终态回执，先查它们必然绕远。正确顺序：先冻结用户叫停的变更动作→按已知 action_id 直查回执拿 rc/stage_fact/时间戳/接手动作→拉一次当前 status 建立健康基线→基于回执明确收回先前错误说法并汇报时间线。本集该路径约 3-4 次只读调用即可收口，实际为拿到同样事实多花了约 6 次派生层查询（evidence miss、快照分页×2、event_stream×2、误路径探测）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e80a8cde-8a96-4b11-ad03-3f16341a32f5:1831:1b7649ba74fd5124ee61
evidence_refs: learning:learn:bfccbb09ebbf
created_at: 2026-10-09T14:56:51.764547+08:00
updated_at: 2026-10-09T14:56:51.764547+08:00
---
## Trigger
用户断言'你刚才的 X 动作失败了/没生效'，与模型先前仅基于受理类回执（'已受理/等稍后执行'）给出的汇报相矛盾；动作属于 restart/publish 等受理与执行分离的异步操作，action_id 已知或可从自己先前汇报中取回。

## Discriminator
先前结论只来自受理回执、从未读过执行终态，且用户断言与之矛盾——能裁决该矛盾的记录只有执行层回执/审计（含 action_id、rc、stage_fact、时间戳、pid 字段）；evidence 库、快照 payload、event_stream 均为派生层，查不到该终态。

## Short path
- 先遵守用户约束：冻结所有变更动作（不再 restart/publish/override），全程只读核查
- 从自己先前汇报取回争议 action_id；一次性拉当前 status，得到存活/代际基线与卡住动作清单
- 按 action_id 直接 grep 服务端回执/审计日志，拿执行终态（执行时间、rc、stage_fact、接手动作与新 pid/commit）
- 必要时用进程级旁证（退出日志/服务日志的时间窗口）交叉核对时间线
- 基于回执明确收回先前不实说法，汇报已验证时间线+当前状态+遗留未知项，停手等用户决定

## Stop conditions
- 争议动作的执行终态已由权威回执确认（有 action_id、rc/stage_fact、时间戳）
- 当前健康状态/代际已由一次新鲜 status 确认
- 用户叫停的变更类动作全程未被触碰；剩余未知（如 start 失败根因、另一动作来源）已列为待用户决定项而非继续自挖

## Verification
- 回执字段（action_id、rc、stage_fact、pid、时间戳）与进程级旁证交叉一致（如 exit log 中 SIGTERM 时刻、当前存活 pid）
- 汇报中显式收回先前具体不实结论，并注明证据来自权威回执而非推测
- 确认核查全程未发出任何变更类调用

## Counterexamples
- 未知量是'服务现在是否健康/正在跑什么'——回执是历史记录，此时应拉新鲜 status/观察，而非查审计日志
- 先前结论已基于执行终态回执且用户未提矛盾——重复 grep 审计日志是无信息量的过度核验
- 动作没有独立执行回执层（纯计算/查询类工具）——此时会话 evidence/event 流才是正确查询层
- 用户问的是'start 为什么失败'的根因——回执只证明'失败了'，根因需另一轮针对错误日志的定向排查，不应在本方法内自动延展
