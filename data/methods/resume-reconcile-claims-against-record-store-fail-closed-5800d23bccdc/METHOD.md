---
method_id: resume-reconcile-claims-against-record-store-fail-closed-5800d23bccdc
name: resume-reconcile-claims-against-record-store-fail-closed
description: 中断或 claim 过期后恢复进行中任务时，上一轮汇总里的正向断言（审查已 PASS、缺陷已修、已收口）不直接采信：先做一次状态对账——任务前沿回执 + 权威记录面按时间 newest-first 枚举（如审查回执目录）+ git log——把断言逐条映射到磁盘记录；记录上找不到对应 PASS 的按 fail-closed 视为未达成，剩余 findings 逐条在当前工作树定点验证修复是否真的在；目录里 kind/文件集不属本任务的并发 lane 记录只标记归属、不动作；拿到权威 PASS 记录后才宣布 done，并在答复中诚实更正被证伪的旧断言。
aliases: 中断后恢复先核磁盘证据别凭记忆, 上轮总结说过了实际没过, 续跑第一步ls最新审查回执, 并发lane留下的审查文件要不要动, 恢复任务先对状态台账
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ea89d59c-50e1-4d8d-a5d5-f378d50d7ff0:674:0f2b3466b6eaaa5eeb85
evidence_refs: learning:learn:408b2f8b12f0
created_at: 2026-11-12T21:38:20.753969+08:00
updated_at: 2026-11-12T21:38:20.753969+08:00
---
## Trigger
会话中断或 claim 过期后恢复一个进行中任务，且同时存在：(a) 持久化权威记录面（审查回执目录/台账/任务前沿状态）可作对账依据；(b) 上一轮汇总含正向结果断言（已 PASS/已修复/已完成）或已修声明，需决定是否接续推进。

## Discriminator
记录目录 ls -t 最新条目的 qualification/verdict 与汇总断言是否一致：最新记录全为 REVISE 且无对应 PASS 条目 → 断言被证伪，按未过处理；新出现但 kind（如 git_push）与 findings 文件集不在本任务范围内的记录 → 属并发其他 lane。该判别在恢复后第一条枚举命令的回执里即可读出，无需先做任何推进动作。

## Short path
- 恢复第一步只做状态对账：任务前沿回执 + 记录目录 ls -t 最新若干条（可合并一条命令），先不发起推进动作
- 把上轮正向断言逐条对记录：有记录且 verdict/指纹一致→采信；无对应记录→fail-closed 视为未达成
- 只读本任务 lane 的 REVISE 报告取剩余 findings，逐条以锚点 grep/定点 span 验证修复确在当前工作树，不凭汇总记忆、不重读全文件
- kind/文件集不匹配的并发 lane 记录：标记归属、不动它，收尾向用户汇报
- 补修经验证的缺口后走审查链；存在权威 PASS 记录才收口，最终答复显式更正被证伪的旧断言

## Stop conditions
- 本任务全部剩余 findings 已在当前树逐条验证修复，或明确列为待办移交
- 本任务审查链存在权威 PASS 记录且指纹与当前产物一致
- 上轮所有断言对账完毕（采信或证伪），无凭记忆推进的残留项

## Verification
- 每条采信的正向断言可指到具体磁盘记录（文件名+verdict+candidate_sha256/指纹）
- 每条『已修』声明有当前工作树定点检索的行号级命中支撑
- 最终答复包含对被证伪旧断言的显式更正

## Counterexamples
- 汇总的 PASS 断言在记录目录有对应条目且指纹一致：直接采信进入下一步，不重跑审查链
- 无持久记录面的一次性任务（无回执/台账可对账）：不适用，凭当前上下文直接续做
- 记录目录为多 lane 共享且条目缺 lane/工件标识：先按 candidate_sha256 与文件集判归属，不能把别人的 REVISE 当本任务阻塞，也不能把别人的 PASS 当自己的
- 对目录只做了 head -N 部分枚举且总数未知时：只能断言『最新 N 条无 PASS』，不得断言全目录无 PASS；fail-closed 方向的行动不受影响，但不得据此下全称否定结论
