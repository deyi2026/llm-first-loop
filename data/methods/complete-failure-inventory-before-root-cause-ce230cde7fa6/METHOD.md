---
method_id: complete-failure-inventory-before-root-cause-ce230cde7fa6
name: complete-failure-inventory-before-root-cause
description: 从截断的 CI 失败日志切片直接得出"共 N 个失败"并开始归因，会漏掉未被看到的第 N+1 个失败，导致第一轮修复推送后才重新开诊断循环。应把"失败全集"当作待解未知量：先从权威完整来源（如 short test summary 段、对全量日志 grep FAILED/ERROR）钉死清单与数量，再本地批量复现、对触发提交做 diff 归因。本集第 5 个失败与已修同根因纯属侥幸，通常需整轮重推重验。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:2339:1185ef4f2e9df601677a
evidence_refs: learning:learn:c968737a5902
created_at: 2026-09-22T16:39:33.658542+00:00
updated_at: 2026-09-22T16:39:33.658542+00:00
---
## Trigger
CI/门禁失败后，通过带截断迹象的渠道读取失败日志（行数上限、输出在记录中途结束、未见 runner 的完整汇总段），并准备宣布失败数量、进入根因诊断时。

## Discriminator
工具回执可见截断事实：输出被行数上限截断、内容在 traceback 中途戛然而止、且未出现 pytest 'short test summary info' 等权威失败清单段——此刻即知失败全集尚未被任何完整来源钉死，不能从可见切片外推失败数量。

## Short path
- 从失败 check 取权威失败全集：对完整 --log-failed 做 grep（FAILED|ERROR）或定位 short test summary 段；解未知量：确切失败集合与数量 N
- 按失败测试所属模块分组，diff 触发提交在这些模块上的改动，建立失败→改动映射；解未知量：每组根因落点
- 修复前在本地一次性批量复现全部 N 个失败，确认清单无遗漏
- 按根因修实现（而非放松测试），本地失败集全绿后推送
- 以重新查询的 statusCheckRollup 全 SUCCESS 确认 CI，再进入合并→checkout→restart→receipt 部署链

## Stop conditions
- 失败全集已由完整权威来源钉死，且每个失败都已本地复现或明确归因到具体改动
- 推送后重新查询 statusCheckRollup 无 FAILURE，原失败 check 全绿，才进入合并/部署步骤

## Verification
- 已诊断并修复的失败数 == 权威汇总段列出的失败数（无"日志截断漏看"缺口）
- 合并决策基于推送后重新查询的 check 状态，而非推送前或截断日志的推断

## Counterexamples
- 日志渠道已给出完整汇总段（无截断、失败清单可见）时，全集步骤冗余，直接归因
- 单一确定性失败且带明确 file:line（如 lint 错误）时，失败集平凡，无需全集步骤
- 失败疑似 flaky/网络瞬态时，应先重跑收敛再清点，穷尽归因每个失败反而扩大搜索空间
