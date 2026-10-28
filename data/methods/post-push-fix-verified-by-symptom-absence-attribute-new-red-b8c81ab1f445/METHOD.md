---
method_id: post-push-fix-verified-by-symptom-absence-attribute-new-red-b8c81ab1f445
name: post-push-fix-verified-by-symptom-absence-attribute-new-red
description: 为消除某个具名 CI 失败症状而推送修复后，终态仍红时，『修复是否生效』的判据是目标症状是否退出本次 run 的逐项 FAILED 清单，而非整体 conclusion。先与修复前 run 的失败清单对照钉死这一条；再对新增失败做归属四查：diff 是否触及其路径、本地串行/并行能否复现、断言引入是否早于本次、run 时长是否漂移。归因无关后如实上报『已推+修复生效+门禁仍红』并给处置选项，不宣布完成、不擅自放宽阈值。
aliases: 推完 CI 还是红怎么判断修复有没有生效, CI 换了个测试失败是不是我引入的, 目标测试过了但门禁没转绿, 修复推送后 CI 新红的归属排查, 门禁仍红但目标测试已通过
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:20761eb6-10e4-4e71-ae2b-0465510a97d8:1009:af02f64c0102676bed8b
evidence_refs: learning:learn:b3af0e4dcc6f
created_at: 2026-10-27T22:24:22.582502+08:00
updated_at: 2026-10-27T22:24:22.582502+08:00
---
## Trigger
推送了针对某个具名 CI 失败项（特定测试/检查）的修复，远端 CI 终态仍为 failure，需要判断是修复无效还是出现了别的新红

## Discriminator
本次 run 的权威逐项失败清单（log-failed/jobs 明细）中目标症状的成员关系，加上新失败项路径与本次 diff 的相交性——这两条在拉到清单当时即可判定，不依赖任何后续结论

## Short path
- 解剖 push 回执并以 ls-remote 钉死远端真值后，取本次 run 的逐项失败清单；未知量：这次到底哪些项在红？
- 与修复前基线 run 的失败清单对照：目标症状退出 FAILED 列表 ⇒ 修复已生效，整体仍红不推翻此结论；未知量：修复是否生效？
- 对新增失败做归属：diff 是否触及其路径、本地串行+并行各复现数次、断言引入 commit 是否早于本次、run 时长/机器指标是否漂移；未知量：新红归属谁？
- 归属非本次 ⇒ 上报『已推+修复生效+门禁仍红』附证据与选项（放宽阈值/改结构性断言/重跑一次），决策交回用户；终局条件未达成不得宣布完成

## Stop conditions
- 目标症状已从 FAILED 清单消失且新红有≥2 条独立证据归因无关 ⇒ 停止自查，上报证据与选项，不擅自改阈值或宣布完成
- 目标症状仍在失败清单 ⇒ 修复未生效，回到根因诊断，不做归属漂移
- 新失败落在本次 diff 触及的路径 ⇒ 视为自家回归，禁用『无关』结论

## Verification
- 失败清单必须来自本次 run 的权威 log-failed/jobs 明细，不得用本地过时 tracking ref 或上轮记忆替代
- 『修复生效』结论须有修复前 run 的失败清单作对照基线，缺基线时先补拉一次历史 run
- 『无关』结论须至少两条独立证据支撑（如路径不相交+本地不可复现，或断言来历早于改动+runner 变慢的量化对比）

## Counterexamples
- 新失败恰在本次 diff 触及的文件/模块内：症状消失判据仍有效，但『无关』归因失效，必须按自家回归诊断
- 日志只给汇总行（如『1 failed』）而无逐项明细：未见目标测试名不等于它通过，须先取完整失败清单
- CI 红的仍是修复目标本身：不存在新红分流，唯一问题就是修复为何没生效
- 单断言型检查无多失败项可分解：整体结论即症状结论，直接诊断即可
