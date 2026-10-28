---
method_id: census-authoritative-store-before-citing-registry-stats-cc832842dcbc
name: census-authoritative-store-before-citing-registry-stats
description: 撰写交付文档需引用注册表/数据存的现势统计（卡片数、status 分布、日志行数）时，先对本轮证据已点名的权威路径做一次机械普查（最小布局确认＋单记录 schema 读取＋幂等计数），再落笔。上一轮自报数字与臆测的存储路径一律视为未验证主张；对假设路径的普查返回 0/空即判定路径错误，立即改查权威路径，而不是在错误路径上换参重试或带着旧数写作；与旧数冲突以显式勘误登记。本集先写入未普查的旧数字与错误路径，随后 0 结果触发多步探针与替换修补，前置普查可整段省去。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:31e64fa8-0da2-4a1c-afd1-a74ed4fcd805:48:6e18da98456f646a1574
evidence_refs: learning:learn:7b6ce5489ae1
created_at: 2026-10-19T00:55:19.063638+08:00
updated_at: 2026-10-19T00:55:19.063638+08:00
---
## Trigger
撰写或更新交付文档，且正文需引用仓库内注册表/数据存的现势统计（如条目总数、状态分布、usage/log 行数），而当前手中的数字或存储位置来自上一轮自报、记忆或未经本轮验证的假设路径。

## Discriminator
两个当时已可见的事实：①本轮已读的权威 artifact（如审计文档）是否已显式点名权威存储/索引路径（例如『usage.jsonl 为 authoritative registry』字样）；②待引数字是否存在本轮工具回执。二者任一缺失即必须先普查；且普查脚本对假设路径返回 total=0 时，证明的是路径错误而非存储为空。

## Short path
- 从本轮已读的权威 artifact 中抽取其显式点名的存储路径与索引文件，作为唯一普查目标（未知量：权威存储在哪）
- 做一次最小布局确认：列出一个记录目录并读单条记录的头部/frontmatter（未知量：计数所依赖的 schema，如 status 字段位置）
- 跑一次幂等机械普查：按 schema 分类计数、统计行数，重跑一次确认数值稳定（未知量：真实现势计数）
- 仅以普查背书的数字撰写文档；与上一轮自报数字或旧路径冲突时，以显式勘误登记并一次性统一替换，同时清理旧路径引用
- 终检：在文档内 grep 旧数字与旧路径 token，除有意保留的勘误条目外为零即停止

## Stop conditions
- 普查脚本两次运行结果一致，且文档中每个引用的统计数字都等于普查输出
- 文档引用的存储路径与权威证据点名的路径同源；旧数字/旧路径仅存在于显式勘误条目中

## Verification
- 重跑普查脚本并 diff 计数，确认幂等
- grep 交付文档中的旧数字与旧路径 token，确认无意外残留
- 将普查目标路径与本轮已读权威 artifact 点名的路径比对，确认同源

## Counterexamples
- 统计数字已由本轮刚产生的工具回执直接给出时，直接引用即可，再普查属冗余
- 文档有意引用带日期的历史快照（如审计中的『截至某日共 N 张』）时，不得用现势普查覆盖快照，两者应并存并标注时点
- 注册表在远端、最终一致或规模过大不宜全量扫描时，应使用其自身 manifest/index 而非全量普查
- 交付物不含任何关于仓库现势状态的定量主张时，无需普查
