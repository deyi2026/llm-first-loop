---
method_id: memory-gap-audit-stream-verify-and-fix-owner-routing-fa9741a96fc7
name: memory-gap-audit-stream-verify-and-fix-owner-routing
description: 记录库维护/坑审计的可复用纪律：先按主题簇清点既有卡防重复；对疑似缺口用确切失败 reason token 做一次定向探测；search miss 只证明『无卡』，不证明『无现象』，须到主证据流（event_stream/exception_log 原始行）取证确证后再落档；按修复归属分层路由——确定性程序缺陷→演进提案（模型侧只兜底），模型误用→lesson，环境瞬态→experience+workaround；不把当前正失效的机制注册为自身的可靠性保障。用『1 次 token 探测 + 1 次定向证据流窗口』替代换措辞枚举全库，并避免为程序侧确定性缺陷记无效的模型侧经验。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:bc96dbc0-2430-4d50-a3b5-0eb359403708:25:c2189653bb55d42dbb52
evidence_refs: learning:learn:0542757e6c8f
created_at: 2026-10-07T21:58:33.860812+08:00
updated_at: 2026-10-07T21:58:33.860812+08:00
---
## Trigger
记忆/记录库维护类任务：用户要求把踩过的坑及时落档、避免重复、并对既有做法持续优化；或自查发现某失败现象疑似从未建档、需要决定记在哪一层、由谁修。

## Discriminator
当时已可见的三类事实：① search_records 按主题簇命中且带 status/verification_state ⇒ 该现象已有卡，只能标注复用/细化；② 用确切失败 reason token（如 grant_lost_owner_dead）探测 store 返回 miss ⇒ 仅证明无卡，现象真伪未知；③ 主证据流原始行（deferred_retry retry_count=1..6 退避→degraded_to_notify retry_cap、prompt_chars=0、『仅 executing 状态需登记完成』）⇒ 现象确证，且 reason 的确定性程度决定修复归属：确定性程序行为归演进提案，用法错误归 lesson，环境瞬态归 experience。

## Short path
- 按候选坑的主题簇清点 store 既有卡（解决：哪些已记录），命中即标记覆盖，不重复建档
- 对每个未确认现象，用其确切 reason/错误 token 对 store 做一次定向探测（解决：是否已建档）
- miss 时不换措辞再搜，直接拉取该 token 对应的主证据流窗口验证现象并取证（解决：现象是否真实、链路如何）
- 按修复归属分层落卡：确定性程序缺陷→演进提案并附证据链；模型用法错误→lesson；环境瞬态→experience+workaround
- 每个候选要么标注重复、要么带证据落档后停止；若拟用的自动化保障机制本身正是当前失效组件，不注册它，改记人工/机会主义兜底

## Stop conditions
- 所有候选现象均已『标记重复』或『带可回溯证据落档』，无未决缺口
- store miss 已用主证据流核实，不再追加同义变体搜索
- 确认缺陷归属程序侧后，停止模型侧兜底尝试——确定性失败不靠模型反复绕过

## Verification
- 每张新卡引用原始事件凭证（sid、时间戳、retry 计数、回执原文），可独立回溯
- 重复建档数为 0：每个标记覆盖的主题都能指向前次命中的既有卡
- 程序侧提案针对确定性原因提出策略变更（如确定性失败不退避、降级事件保留可再锚定 payload），而非仅复述现象

## Counterexamples
- 事件流中的瞬态故障（超时、429 限流）：非确定性失败，退避/串行+间隔可能是正确缓解，不得按『程序 bug 永不重试』落卡
- store 探测命中且既有卡已覆盖该现象：只标注复用或细化旧卡，禁止另建新卡
- 普通任务中的首次查询 miss：不适用本方法，不得为此做全库清扫；宽枚举仅在用户明确要求审计/查全时进行
