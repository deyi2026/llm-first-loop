---
method_id: resolve-coined-nickname-via-session-provenance-then-ground-at-source-5756d1e2fcbb
name: resolve-coined-nickname-via-session-provenance-then-ground-at-source
description: 用户用自造/非正式称呼（带『这个X』式回指）指代某机制并发问评估类问题时，不要把该字面词当作检索键在多索引间反复枚举。字面零命中本身就是关键判别事实：它是称呼，不是正式机制名；指涉物几乎总在当前会话最近的动作与自己上一条交代里已被具体点名（event_stream/action trace 点名的脚本、账本、门禁）。沿这条会话内 provenance 解析『称呼→机制』，再读该机制权威源并重跑检查拿当前回执，回答时显式陈述映射假设与兜底解释供用户纠正。反模式：对同一字面词换措辞多索引枚举；把零命中读成『无此机制』；不声明映射就下结论。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:64924088-0141-4a3a-87ee-81f09678620d:618:87ffdfdc71281112554b
evidence_refs: learning:learn:cc63257add1a
created_at: 2026-10-10T13:37:10.707250+08:00
updated_at: 2026-10-10T13:37:10.707250+08:00
---
## Trigger
用户以非正式/自造简称（常带『这个X』回指，暗示指代先前共同上下文）要求评估或调整某机制；或首轮对该称呼的字面检索零命中。

## Discriminator
回指语气 + 字面词在代码/docs/records 零命中 → 该词是对最近共同上下文中某具体机制的称呼；当前会话 event_stream 与上一条回复当时已点名具体 artifact（脚本/账本/门禁），这是可验证的下一跳，而全库再枚举不是。知识时点：用户消息本身 + 首轮 miss 回执即可得出，无需事后答案。

## Short path
- 从用户消息识别回指；未知量=『这个X』指哪个机制
- 查一次当前会话 event_stream/最近 action trace 与自己上一条交代，列出最近被操作、被点名的具体机制与 artifact；未知量=候选指涉物
- 读该机制的权威源（脚本/配置/账本）并重跑其检查取当前回执；未知量=其现在的严格性设计与通过状态
- 回答时显式写出『称呼→机制』映射假设与至少一个替代解释（兜底），每条论据可指回刚读的源码或回执；停止

## Stop conditions
- 映射已确立，且判断所需事实已由权威源 + 当前运行回执取得
- 会话上下文中不存在任何候选指涉物 → 停止检索，直接向用户要澄清，而不是扩大为全库搜索

## Verification
- 每个结论可回指到刚读的源码行或刚取得的运行回执（如 PASS 行、resolved 计数），而非记忆中的旧事件
- 回答包含映射假设声明与至少一个兜底解释，用户可低成本纠正
- 字面零命中只被用作『非正式称呼』的证据，未被误用作『机制不存在』的结论

## Counterexamples
- 字面或近义检索实际命中某正式机制（称呼恰好接近真实命名）→ 全局检索是正确首步，不应跳去会话上下文
- 新会话、无先前共同上下文，『这个X』无所回指 → 应先要澄清或扩展近义词检索，赌 event_stream 是扩散
- 用户问的是通用概念解释而非本仓库具体机制 → 无需映射到具体文件，直接作答
- 会话历史与当前问题明显无关或 event_stream 巨大时，读会话历史本身就是扩散，应直接要求澄清
