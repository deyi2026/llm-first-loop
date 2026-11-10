---
method_id: pending-edit-claims-in-handoff-state-verify-named-artifact-fields-first-3b1db5c7a336
name: pending-edit-claims-in-handoff-state-verify-named-artifact-fields-first
description: 交接快照/状态账本里『artifact X 的字段 F 需改后重提交/重签』类待办是过去时刻的断言，不是当前事实：X（本例为未跟踪的治理回执 JSON）可能在快照落笔后被自己补写正确。把每条字段类待办当作一次查询即可证伪的假设——文件与字段名已被点名，一次定点 grep/read 就能裁决：现值已对→从管线里划掉编辑步骤只留提交，并对上轮相反说法显式纠正；确为旧值→才执行编辑。终态闭合且已交叉核验的快照仍按消费处理，不重验。
aliases: 快照说要改字段先查现值再动手, 待办可能已经做完先核实再照做, 交接账本待改项先grep裁决, 别把上轮结论当已核事实转述, 照单执行前先证伪待办清单
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:1288:d9ba8ad7c54306da306d
evidence_refs: learning:learn:c29d1a71dcd5
created_at: 2026-11-10T10:14:32.813335+08:00
updated_at: 2026-11-10T10:14:32.813335+08:00
---
## Trigger
多步收口/交接任务中，状态快照或上轮结论携带『artifact X 的字段 F 需修改后重提交/重签/重跑』类待办，且 X 的路径与字段名已被逐字点名、X 位于本地工作区可直接读取

## Discriminator
待办文本本身已点名目标文件与字段（如『改回执 JSON 的 base/head/commits』），且 git status 显示该文件未跟踪或自由可写——意味着快照落笔之后任何写入都可能已兑现该待办；验证成本是一次定点查询，而照单执行的代价是改错已正确的文件并触发多余的重签/重提交循环

## Short path
- 读状态快照，把待办队列拆成两类断言：对外部系统状态的断言 vs 对本地 artifact 字段现值的断言
- 对每条字段断言做一次定点检查：grep 被点名文件中被点名字段（base/head/commit 等）的当前值
- 现值与待办声称的『需改』不符（已一致）→ 把该编辑步骤从管线划掉，只保留提交/重签等后续，并在回复中显式纠正上轮/快照的相反说法
- 现值确为旧值 → 才执行编辑，编辑后按同字段复查一次
- 所有字段类待办均标记为『已核仍需做』或『已失效』后，才据此生成下一步建议

## Stop conditions
- 每条字段类待办都已被 artifact 现值裁决为『需做』或『已失效』
- 建议/执行管线中不再存在未核验的『需改 X 字段』前提

## Verification
- 断言逐条对照 artifact 实际字段现值，引用文件路径+字段值作为证据
- 与上轮或快照相反的结论显式标注为纠正，不复述旧说法、不静默改口

## Counterexamples
- 待办断言的是外部系统状态（CI job 终态、队列受理结果）而非本地文件字段——验证面是 job/队列回执，不是文件 grep
- 快照已终态闭合、事实已交叉核验且本轮被限定只报告——按消费快照处理，不做重验
- 字段值刚在同一轮内由本人写入且写入回执在案——无需再查文件
- 目标 artifact 无结构化字段可定点检查（二进制/无 schema）——退回整体读取或权威账本裁决
