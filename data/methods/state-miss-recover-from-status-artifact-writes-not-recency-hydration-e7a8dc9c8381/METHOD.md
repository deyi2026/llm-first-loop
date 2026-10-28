---
method_id: state-miss-recover-from-status-artifact-writes-not-recency-hydration-e7a8dc9c8381
name: state-miss-recover-from-status-artifact-writes-not-recency-hydration
description: 任务状态 store 查询失败后，不按时间顺序逐条水合最近 evidence：台账回执的 label 已区分类型——计数器型（如 settlement_pending 报 0 项）与准入型（review_admission PASS）快照不回答『停点在哪/后续做什么』；该未知量由最新持久状态工件（dated STATUS/ledger）回答，而写它的 execute_command 快照内嵌确切路径。先水合写文件类命令定位工件、read_file 读全，其状态行与待办/遗留段即完整『后续』清单；读全即停，不再补搜 evidence 关键词。本集可省 2 次无关水合与 1 次事后搜索。
aliases: 找不到任务状态怎么接上一班, 问下一步建议时先看什么, 证据列表跳过结算审核直接找写文件命令, 别按时间一条条翻证据, 接晚班前先核午班状态, 状态查不到去读值班日志
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ab341b43-d714-4d68-a94c-977583d3edbc:233:27d016854ab8221aa23f
evidence_refs: learning:learn:47f512b8c8e9
created_at: 2026-10-27T15:53:29.518261+08:00
updated_at: 2026-10-27T15:53:29.518261+08:00
---
## Trigger
任务状态/停点查询失败（task state not found），或用户问『后续建议/接下来做什么』而当前无活动 goal，需要从 evidence 台账或工作区重建进展时——典型为多班次/多阶段流水线且存在日期命名的 STATUS/ledger 工件约定。

## Discriminator
失败回执本身已声明状态不在会话/workspace store，即停点必在持久工件中；随后 list_evidence 回执每条的 label 已标明 kind：runtime_snapshot 的计数器/准入条目不推进『停点』未知量，只有 execute_command（写文件）条目可能内嵌权威状态文档的确切路径。knowledge-at-time 成立：该区分在水合任何条目之前即可从列表 label 读出。

## Short path
- 状态 store miss 后，把未知量改写为『最新权威停点记录在哪个持久工件』
- list_evidence 一次，按 label kind 筛选：只考虑 execute_command 写文件类条目，跳过计数器/准入类快照
- 水合最新写文件命令，从命令串（cd 目录 && cat > 文件）提取状态工件确切路径
- read_file 该工件至完整，从其状态行与待办/遗留段枚举剩余工作
- 按时效排序输出后续建议；工件读全即停，不再对 evidence 做关键词补搜

## Stop conditions
- 命名约定下日期最新的状态工件已读全，且其待办/遗留段已覆盖用户所问『后续』
- 工件自身状态仍 pending（如『审核中』）时，后续清单第一项=『先核该状态』即可收敛
- 写命令快照未能给出可读工件路径（未落盘/在别处）时，才转向目录或内容搜索

## Verification
- 对照 evidence 时间戳或目录日期，确认所读工件确为最新一期，无更新一期被跳过
- 每条建议可回指工件具体段落（如 §五/§七），与问题无关的水合次数为 0

## Counterexamples
- 用户问的是计费/结算或准入资格（counter/gate 类未知量）时，settlement/admission 快照才是正确来源，状态工件不覆盖
- 状态 store 命中且内容新于工件时，直接用 store 结果，无需读工件
- 项目无日期命名工件约定、台账里也无写文件命令时，本方法不适用，需走目录/内容发现
