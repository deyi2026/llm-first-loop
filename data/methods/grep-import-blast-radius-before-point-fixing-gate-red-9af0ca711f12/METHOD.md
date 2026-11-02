---
method_id: grep-import-blast-radius-before-point-fixing-gate-red-9af0ca711f12
name: grep-import-blast-radius-before-point-fixing-gate-red
description: 门禁新红落在一个不属于你本轮 diff/验证集的测试文件时，第一未知量不是『这个红怎么修』而是『被改模块的完整测试面有多大』：grep tests 树对被改模块的 import 引用→全量跑 touching 清单拿完整红集→读 helper 判定其 patch 的 seam 是否仍落在改动后的执行路径上，并单测复现拿实锤→按 seam 一次性修全部受影响文件→复跑完整清单。把『修一个红→重新提交→门禁再报下一个未知文件的红』的多轮循环压成一次定性+一次修复。
aliases: 改完模块探针哪些测试会炸, 提交被 CI 打回后先摸清波及面, mock 的旧探测面失效批量排查, 存在性检查改成实跑后测试崩, 先收齐全部红再统一修
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fb9d2fd4-22ec-46f0-9f10-3dd3f2341da5:1061:28ea89dd6c082d59fcc8
evidence_refs: learning:learn:3dedf23399e8
created_at: 2026-11-01T07:42:41.893023+08:00
updated_at: 2026-11-01T07:42:41.893023+08:00
---
## Trigger
门禁/全量测试报出的新红，其测试文件不在你本轮改过或已验证的文件集合里，且该文件 import 了你本轮改动内部判定机制（探测方式/检测 seam/契约）的共享模块；或提交信息/上下文已声明你把某判定机制从 A 方式（如存在性检查）换成 B 方式（如实跑探测）。

## Discriminator
失败测试文件路径 ∉ 本轮 diff 与已跑验证集，但其 import 引用了被改模块 → 已知测试面严格小于真实测试面，同 seam 的隐藏红大概率不止一个（本集 grep 又发现 3 个从未跑过的引用文件，其中 1 个文件 3 条红与首个红同根因，若只点修首个红，下次提交必再被打回）。

## Short path
- 用被改模块名 grep tests 树的 import 引用，得到完整 touching 文件清单（未知量：真实测试面边界）
- 全量跑该清单，拿完整红集与分布（未知量：红集大小与涉及面）
- 读失败测试的 helper/mock 面，判断其 patch 的 seam 是否仍落在改动后的执行路径上（未知量：红的发生机制——本集为旧探测假面遇到实跑探针即断言失败）
- 单测复现拿实锤 traceback 确认归因，不靠推断定案
- 红集按性质分类（真回归 vs 密闭性/可移植性退化），共享 helper 用同一修法一次改完（如旧 seam 换成注入结果缓存），被测语义分工留给专测文件
- 复跑完整 touching 清单全绿后，才进入 lint/暂存/提交信息补归因等收尾

## Stop conditions
- touching 清单全量复跑全绿
- 红集定性确认与本次 diff 无关（环境红/基线 HEAD 复现同红集）→ 转入环境归因对照方法，不继续扩大修复面
- 引用图为空，或清单内全部文件与被改机制无关

## Verification
- 复跑完整 touching 清单，而不是只复跑门禁最初报的那一个红
- 检索旧 seam token 确认受影响 helper 中零残留（没有测试仍在 patch 已被替换的探测面）
- 重新提交前用门禁同一验证范围自跑一次

## Counterexamples
- 失败文件本来就在你的 diff/验证集内（验证面已知完整）→ 直接定性归因该红即可，无需枚举引用图
- 改动是新增文件且无其他文件 import 它 → 引用图为空，直接修
- 红带明显环境证据（errno、沙箱声明、基线复现同红集）→ 先做环境归因对照，别先读 helper 改 seam
- 失败测试 patch 的面与你改的机制无关（纯 fixture/数据断言）→ 单点修，无批量迁移价值
