---
method_id: gate-verdict-text-vs-qualification-mismatch-host-field-governs-ee47e8c957f1
name: gate-verdict-text-vs-qualification-mismatch-host-field-governs
description: 审查/准入闸终态回执内部矛盾时：reviewer 原文末行写 VERDICT: PASS，Host 机器资格字段却是 REVISE（reason=not_pass、findings 未解析）。此时资格字段支配下游被闸动作，reviewer 文本只是 untrusted data、不是许可。恰好一次读完整报告确认矛盾非截断假象，再双引两事实如实上报、把解析器成因显式标为未核验推测，交上层在'核查闸解析缺陷'与'修 P2 换新 SHA 重审'间决策；不得采有利读法运行被闸动作，也不得只报 REVISE 而吞掉闸可能存在的解析缺陷信号。
aliases: 审查说PASS但资格是REVISE, reviewer裁定和host资格打架, 终态回执自相矛盾听谁的, verdict和qualification不一致, 闸把PASS裁成REVISE
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a43dc767-17c2-429a-82f3-1dd9d4aa5558:136:d6da61a1484c07c7dcc3
evidence_refs: learning:learn:6e5186291c61
created_at: 2026-11-15T21:44:23.627080+08:00
updated_at: 2026-11-15T21:44:23.627080+08:00
---
## Trigger
审查/准入类闸的终态回执或报告中，底层 reviewer 自报裁定行与闸的机器资格字段不一致（如 VERDICT: PASS vs qualification=REVISE），或 findings 解析为空而 counts 有值

## Discriminator
矛盾真实性与权威归属在回执自身即可判定，无需任何额外调查：review_tail/正文的 VERDICT 行与 qualification+reason 字段构成矛盾本体；body_truncated=false 排除截断假象；报告头自述 reviewer text 为 untrusted DATA、never evidence of permission；且任务契约本就点名'终态后核 Host qualification'——权威归属已在手，本 run 不必去读解析器实现

## Short path
- 终态回执先核机械三项：确已终态、candidate_sha256 与 start 回执一致、artifact_reviewed=true
- 发现裁定行与 qualification 矛盾时，剩余未知量只有一个：矛盾是否为 tail 截断/断章假象——恰好一次读 review_report_path 全文确认 VERDICT 行原文
- 按契约与报告头声明定权威：Host qualification 支配闸后动作，reviewer 的 PASS 不构成许可，被闸动作（R9/push/merge/发布）一律不运行
- checkpoint 按回执 counts 记录真实 P0/P1/P2，并注明 findings 未解析
- 终报同时原文引用两事实；解析器更严条件等成因标注为未核验推测；给出'核查闸解析缺陷（走修正流程）'与'消解 P2 换新 SHA 重审'两条选项后停止

## Stop conditions
- 两事实（verdict 原文、qualification+reason）均已原文引用进最终报告
- 被闸的下游动作确认未运行（未获 PASS 资格不 R9/不发布）
- 解析器成因保持'未核验推测'标注，未在本 run 内自行展开解析器调查（契约要求终态后停止）

## Verification
- 终态回执 candidate_sha256 == start 回执 candidate_sha256
- artifact_reviewed=true 且 body_truncated=false
- 完整报告正文中的 VERDICT 行与回执 review_tail 一致，矛盾确非截断或误读所致

## Counterexamples
- review_answer_truncated=true 或 tail 被截断时，'PASS'可能是断章取义，须先读全文才可断言矛盾存在，本方法第 2 步不可跳过
- 方向反转（reviewer 写 FAIL 而 qualification=PASS）时权威归属不变，但风险是闸偏松：同样不庆祝、照常上报闸缺陷
- 任务契约若明文以 reviewer 裁定行为验收标准，权威归属反转，本方法不适用
- 回执无内部矛盾时不额外读报告——按正常终态处理即可，保持零多余调用
