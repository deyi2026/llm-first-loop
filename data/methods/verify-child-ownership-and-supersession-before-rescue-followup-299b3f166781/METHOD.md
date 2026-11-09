---
method_id: verify-child-ownership-and-supersession-before-rescue-followup-299b3f166781
name: verify-child-ownership-and-supersession-before-rescue-followup
description: 用户要求抢救/续话某子代理时，先读 topology/lease 回执核两件事：①所有权——parent_session_id≠当前会话且本会话 active_children=none 时，本会话对该 child 的一切 child 域操作必被运行时拒绝，合法路径只有向 owner 会话发 help_request；②时效——替代/同级 child 若已 settled completed 且 owner 已写出终态回执，抢救目标已被取代，应报告取代事实而非执行注定失败或已无必要的指令。outcome=completed 不等于结论可用，必须读回执内容中的 verdict。
aliases: 跨会话给子代理发续话被拒, 被截断的子代理还要不要抢救, 别的会话的子代理怎么收敛结论, followup 子代理前先查归属, 子代理不是本会话的 child 能续话吗
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:376f20bb-9dc9-4200-8780-a7b8dfab31db:0:d5ffc5ce58f17be40d13
evidence_refs: learning:learn:0540a9322c69
created_at: 2026-11-08T21:42:23.376568+08:00
updated_at: 2026-11-08T21:42:23.376568+08:00
---
## Trigger
用户或任务书点名对某个子代理执行收敛/续话/抢救指令（如'让它直接给结论、别再调工具'），但该 child id 来自用户报告或事件流转述，并非本会话直接 spawn；或距其截断/失败报文已过去数分钟的异步场景。

## Discriminator
动手前已可得的回执字段：subagent_topology/lease 回执的 parent_session_id、outcome、settlement_state；coordination_status 的 self= 或 event_stream scope 标签给出的当前会话 id；owner 会话近期事件流中的回执落盘/lane_close 动作。parent_session_id 与 self 一比即可预判 child 域操作是否会被拒；同级 child 的 settlement outcome 可预判抢救是否已无必要。

## Short path
- search_records/event_stream 定位目标 child_id 与 spawn 回执，确认失败类别（truncated/failed/cancelled）
- subagent_topology(child) 读 parent_session_id，与当前会话 id（coordination_status 的 self=）比对，解决『本会话能否直接操作』这一未知量
- parent≠self ⇒ 不发起 agent_followup；改查替代/同级 child 的 lease+topology outcome 与 owner 会话近期 event_stream（回执落盘、lane_close），解决『抢救是否已被取代』
- 已被取代 ⇒ 读终态回执内容取 verdict（不只看 outcome=completed），向用户报告取代事实；残余选项只有经 owner 会话交叉核验（help_request），等用户确认再动
- 未被取代且确需抢救 ⇒ 通过 help_request/命名通道请 owner 执行 followup，本会话不代执任何 child 域操作

## Stop conditions
- owner 会话终态回执已落盘、verdict 内容已读取，用户目标（如审查结论）已由该回执满足
- 所有权与取代状态均已判定，剩余动作只剩用户确认是否发起交叉核验请求

## Verification
- 给用户的 verdict 引自已落盘回执内容（含 P0/P1 计数等字段），而非仅凭 outcome=completed 推断
- 对 parent_session_id≠self 的 child 全程零次 child 域操作尝试，此类被拒调用为 0
- 所有权与取代判定各引用一条具体回执字段（parent_session_id、active_children、settlement outcome）

## Counterexamples
- parent_session_id 等于当前会话：followup 合法，应直接执行用户的收敛指令，不需要 help_request 绕行
- 替代 child 的回执内容为 FAIL 或 coverage 不足：outcome=completed 不构成取代，被截断 child 已掌握的事实仍值得经 owner 抢救
- 单会话环境所有 child 均由本会话 spawn：所有权检查退化为空操作，按常规 followup 流程执行
- topology/lease 回执不可得且用户指令紧急：可让运行时裁决一次，但要预期拒绝并预置 help_request 备选路径
