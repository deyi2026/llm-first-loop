---
method_id: recover-answer-via-list-evidence-hydration-before-keyword-respray-9fbb60c22bdb
name: recover-answer-via-list-evidence-hydration-before-keyword-respray
description: 事实性问题（常带具体数字/编号）在 evidence/docs 精确词检索 miss 后，不要换词重试或全库 content grep：先 list_evidence 查最近条目；若存在前一会话对主题直接相关权威文档的 read_file 证据（freshness=verified_current），直接按 ref hydration（recovery_handle）取得历史裁定。历史文档通常绑定特定基线 SHA，只能回答『当时是什么』；对『现在是否需要行动』类问题，再改用该台账的官方消费端脚本（守卫/门禁）实测 current 值，用『历史裁定+当前实测』组合作答。与 resume-continuation 互补而非重复：那卡面向续跑指令（停点文档/git delta 重建进度），本卡面向事实问答，沿证据库最近读取记录恢复已知答案。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:18e51b8e-580f-47b5-a867-ad21b62684b1:1055:996c3b2009eadc80e49e
evidence_refs: learning:learn:4f64f9f62636
created_at: 2026-10-08T21:13:27.537194+08:00
updated_at: 2026-10-08T21:13:27.537194+08:00
---
## Trigger
用户就项目状态或既有裁定提出事实性问题（如『某 N 处债务/问题要不要清理』），精确关键词在 search_evidence/search_docs 连续 miss；此时应先查证据库最近条目，而不是换词重试或升级为全库内容搜索。

## Discriminator
list_evidence 回执（如『最近 20/488 条』）中已列出一条可作 recovery_handle 的 read_file 证据，其 label 是与问题主题直接一致的权威文档（本集为项目审计报告，freshness=verified_current，acquired 早于本任务数分钟）——答案的历史部分已在本会话证据库内，剩余未知量只有『当前状态』。

## Short path
- 精确词各查一次 search_evidence/search_docs；miss 即停，不换词连发
- list_evidence 扫最近条目，找主题直接相关、freshness=verified_current 的前会话读取记录
- 按该 evidence ref 做 hydration/recovery，直读目标文档相关小节（本集即 BUG-17 节：口径、67 的构成、既有处置立场）
- 若问题是『现在要不要行动』：识别历史文档绑定的基线 SHA，改跑台账官方消费端脚本/工具实测（historical vs current/new/resolved）
- 以『历史裁定+当前实测』作答并停止

## Stop conditions
- hydration 回执主题一致且 verified_current，历史问题已答
- 『是否行动』类问题已由门禁/台账脚本给出当前实测结论（如 PASS + current 计数）
- list_evidence 无主题相关读取（命中全为无关噪声，如 lock 文件）→ 本方法不适用，转正常探索检索

## Verification
- hydrate 回执的 source.label 与问题主题一致、freshness=verified_current
- 历史文档关键数字能在当前仓库资产复现（台账文件计数 = 文档 historical 计数）
- 当前状态结论来自直接运行官方消费端脚本/工具的回执，而非仅引用历史文档

## Counterexamples
- 证据库最近条目与主题完全无关（本集另一轮 content 搜索只打出 uv.lock 噪声）→ 不硬套，回到正常探索
- search_docs/search miss 回执本身已点名答案文档 → 直接读该文档，无需绕 list_evidence
- 相关读取 freshness=stale/unknown 且对象有已知并发写者 → 只当线索，不得当当前真值
- 续跑类任务（『X 继续』且无活动 goal）→ 套用 resume-continuation（停点文档/git delta），不套本卡
