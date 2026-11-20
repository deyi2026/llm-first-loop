---
method_id: checklist-keyword-linemap-clustered-span-review-under-budget-6353ab18a0ed
name: checklist-keyword-linemap-clustered-span-review-under-budget
description: 只读复审任务书自带逐项清单（如上一轮 P0/P1 修复点）与硬性调用预算、且声明全量测试已由发起方复跑时：先 rev-parse 冻结 HEAD；对每个权威文件做一次『清单词族 alternation』grep 生成行号地图（并经 import 边确认真正权威实现、跳过 thin wrapper）；只读锚点聚簇后的 span，每段一次核多个清单项的接受谓词（匹配是否精确、比对覆盖哪几侧、是否 fail-closed）；负测/锁实现用一次合并定点 grep 确认存在与断言方向；输出 item→file:line 证据表，清单外观察降级为 P2 残余风险，运行时不可核验事实写免责声明而非 PASS 依据；不重跑已跑过的测试，不逐项重复搜索、不通读全文件。
aliases: 复审清单在预算内怎么核完, 一次grep建行号图再分段读, 只读抽查不重跑测试, 审查工具调用预算分配
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:2838215a-0c23-4432-aac7-b98b13ea7863:0:1b50520c07b3464d5301
evidence_refs: learning:learn:3cbfb5eb5629
created_at: 2026-11-17T01:02:58.748999+08:00
updated_at: 2026-11-17T01:02:58.748999+08:00
---
## Trigger
只读复审任务给出明确逐项核验清单（上一轮 P0/P1、安全/门禁修复点）+ 硬性工具调用/时间预算 + 声明发起方已复跑全量测试、要求只抽查并输出 PASS/REVISE 与 file:line 证据。

## Discriminator
清单各项共享一小族可 grep 词汇（filter/check_run/workflow_id/blob/ed25519/flock/parent/unique…）且首轮 diff/任务书已点名权威文件 ⇒ 每文件一次词族 grep 即可把全部清单项映射为行号锚点；『发起方已复跑测试』使重跑零信息；import 边已指明权威实现 ⇒ 通读、跨文件宽枚举或重跑测试都无增量。

## Short path
- rev-parse HEAD + status + diff --stat vs base：唯一先决未知量是 worktree 是否精确等于候选 SHA
- 对每个权威文件做一次全清单词族 alternation grep，产出所有清单项的行号锚点图；从 import 边确认权威实现，跳过 thin wrapper
- 把锚点聚成最少 span 逐段 read_file，每段同时核 2-4 项的接受谓词：匹配精确性、比对覆盖的侧（main/candidate、ref/blob）、失败方向是否 closed
- 对清单点名的负测/锁实现做一次合并定点 grep（含测试名词根），确认存在且断言 HOLD/唯一/去重
- 逐项输出 item→file:line→观察到的谓词；清单外发现降级 P2；运行时不可核验事实写入免责声明；如实报告调用计数后停止

## Stop conditions
- 每个清单项都有 file:line 与实际读到的判定谓词支撑，不再展开 wrapper 或任务无关文件
- 不重跑发起方已复跑过的测试套件
- 运行时/部署事实（如生产 branch protection 404、issuer 未部署）已标注为不可核验残余风险，而非被采信为 PASS 依据

## Verification
- 报告中每条 file:line 都落在实际读取过的 span 内，可被第三方独立复核
- 自报工具调用次数与实际一致且未超任务预算
- PASS/REVISE 结论能由逐项谓词表逐行推出

## Counterexamples
- 清单词汇在代码中不以字面出现（常量、间接层、混淆命名）→ 词族 grep 建不出地图，应改走符号/定义面裁决
- 清单仅 1-2 项 → 建全图是纯开销，直接定点 grep+单段读
- 发起方未复跑测试，或清单含『实际拦截行为』类运行时断言 → 只读抽查不足，先跑确定性守卫与篡改负测复现
- 目标文件本身很小（百行级）→ 直接整读，无需地图与聚簇
