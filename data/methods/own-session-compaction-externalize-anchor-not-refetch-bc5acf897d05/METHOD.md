---
method_id: own-session-compaction-externalize-anchor-not-refetch-bc5acf897d05
name: own-session-compaction-externalize-anchor-not-refetch
description: 长会话中，回执 metadata 标注本会话模型被 cache 压缩、系统待办里挂着本 session 的压缩/快照门、或同一查询短窗口内第二次返回逐字相同结果时，问题不是证据不足而是上下文正被驱逐：先把已确立结论+证据引用外置成单个 checkpoint（或把压缩快照 manifest 当已归档索引），此后续问从锚点出发、只做有界 delta 取数并回写锚点，交付物由锚点组装。标记在场时继续换措辞重取同一批证据，正是重复调用循环的机制来源（本集 42 次 duplicate、420 轮）。
aliases: 长会话越跑越慢 总在重新取证, 上下文被压缩后像失忆一样重复查, 几百轮会话怎么防重复调用, 先落盘小结再继续 防上下文蒸发, 快照门没过 先固化已知结论
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:6c13edc8-42f8-4bc3-9245-e19a3c891178:1107:bcc2f9544ceca39f83d1
evidence_refs: learning:learn:431a88baed19
created_at: 2026-11-04T10:29:39.211711+08:00
updated_at: 2026-11-04T10:29:39.211711+08:00
---
## Trigger
多轮长会话（数小时/数百轮）任务进行中，出现任一可观测信号：取数回执 metadata 带 cache_compacted_for 指向本会话模型；pending_actions/系统门面出现本 session_id 的压缩快照门（pending/escalated）；同一查询或读取在短窗口内第二次得到逐字相同结果。

## Discriminator
这些信号在『发起下一次取数』之前就已存在于回执/系统面：它们把候选解释『还没查过/证据变了/再确认几个』收敛为唯一假设『上下文被驱逐，缺的是状态连续性而非新证据』。同时可判别归因：门/异常若属于其他 session_id，则本会话不适用，不误触发外置。

## Short path
- 每次准备取数前扫一眼回执 metadata 与系统待办：是否出现指向本会话/本模型的压缩、驱逐、快照未投递标记，或已出现第二次逐字相同结果。
- 命中 → 第一个未知量改为『已确立事实是否已外置』：把已确认结论 + evidence_ref/覆盖指针一次性写入单个 checkpoint 文件，或采用压缩快照 manifest 作为已归档证据的索引。
- 后续一切疑问先查锚点：命中即用；锚点未覆盖的未知量才做一次有界 delta 取数，新结论立即追加回锚点。
- 最终交付（总结/报告）从锚点组装并引用锚点记录的回执 ref，不再从 live 上下文重新推导既有事实。
- 若标记属于其他 session/模型：仅登记归因，正常推进，不付外置开销。

## Stop conditions
- 交付物所需全部事实已由锚点引用的回执覆盖
- 本会话压缩/快照门已解除，且此后一段窗口内不再出现逐字重复结果

## Verification
- 对照本轮前值：duplicate_calls 不再随轮次单调增长
- 锚点内每条结论都能指回一条真实回执 ref；最终答案的事实与锚点一致，无 live 重新推导造成的漂移

## Counterexamples
- 短/新会话且无任何驱逐标记：checkpoint 是纯开销，直接推进。
- 所需事实已有系统原生权威账本（结算回执、STATUS 文档等）：应使用单一数据源，不另建平行锚点文件。
- 压缩门/异常日志属于其他 session_id（如本集 8 条 SSL/503 属别的会话）：正确归因即可，不触发本会话外置。
