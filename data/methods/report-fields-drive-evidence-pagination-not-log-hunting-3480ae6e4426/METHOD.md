---
method_id: report-fields-drive-evidence-pagination-not-log-hunting-3480ae6e4426
name: report-fields-drive-evidence-pagination-not-log-hunting
description: 后台 job 到终态后，报告契约逐项列明所需事实（exit code、各段统计、失败 node id、日志位置），而 job_output 内联视图截断、持久化 evidence 回执自带分页元数据（next_start、complete=false、同一 blob_sha256）时，用『契约字段清单清空』驱动翻页：沿 next_start 把同一 integrity 哈希的 blob 连续读到 complete=true 或所有字段都有行级出处；只有 blob 无法回答的字段（如日志工件落盘与生命周期）才开新轴，且每个来源只读一次、脚本已声明 rm -f 的工件不再做磁盘搜索；报告逐字段标注出处，未实际读到的页不得声称已核对全文。
aliases: 长日志被截断怎么读全, 输出截断继续翻页到complete, 失败node id在没读的页里, 先翻完页再找日志文件, 报告字段没齐别换地方找, CI全量输出分段补读
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8ad7ea3f-6860-49a6-a20b-9c436e6da865:26:d713b5877ca58b10295a
evidence_refs: learning:learn:d83e16e94abb
created_at: 2026-11-10T09:44:16.671932+08:00
updated_at: 2026-11-10T09:44:16.671932+08:00
---
## Trigger
后台 job 到达终态（exit 已定）后需按契约报告一份长日志中的多项具体事实，而 job_output 视图截断、hydration 回执显式给出 next_start 且 complete=false（权威全文已知可达但未读尽）

## Discriminator
回执自带的分页元数据（next_start 衔接、complete=false、同一 blob_sha256）加上契约字段清单：两者在手即可判断『剩余必读内容在已知可达的后续页』，补齐字段无需另开日志路径/磁盘搜索等新轴

## Short path
- 终态回执先定格 exit code 与 job 状态并记账，不再重轮询
- 按 next_start 连续翻页同一 evidence blob，每页提取契约字段并更新『未捕获字段』清单，直到 complete=true 或清单为空
- 仅对 blob 无法回答的字段（如日志工件的落盘位置与生命周期）读一次权威来源的相应段落，同一 span 不做即时重复读
- 来源证明工件已被删除（rm -f/临时目录）→ evidence 引用即日志位置，跳过磁盘搜索；来源声明持久化才做一次有界磁盘直读
- 逐字段带出处成报：数字/node id 指认到具体行段或 evidence sha；未直接读到的字段显式标『未核』，不声称『已分页核对全文』除非真读到 complete=true

## Stop conditions
- 契约字段清单为空且每个字段有行级出处，或 blob 已读至 complete=true
- 权威来源已证明日志工件不存在，且剩余字段均可由已读页回答

## Verification
- 各页 range 连续衔接（next_start 无跳段）且 blob_sha256 全程一致
- 报告中每个统计/node id/日志位置可指认到具体已读行段；『已核对』声明不超出实际翻页范围

## Counterexamples
- 契约只需要 exit code 与总结论（已在终态回执中）：翻完整 blob 属浪费，取到字段即停
- 快照本身只捕获头尾（coverage 标注非 source_complete）：继续翻页徒劳，应转磁盘工件/日志文件轴
- 脚本明确日志持久化在固定路径：一次有界磁盘直读可能比翻巨大 blob 更省，磁盘轴此时正当
