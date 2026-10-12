---
method_id: first-query-must-preserve-partition-discriminator-ff363d2669cc
name: first-query-must-preserve-partition-discriminator
description: 当下一步动作是对一组记录做分区/分组决策（如 staged/unstaged 分组打包提交、按归属分桶、提取失败清单）时，对该来源的第一次查询就必须保留决策所需的判别字段——分区标记加条目标识。先做丢弃判别字段的聚合/投影，再对同一来源换参数重取全量，是一次可预见的重复查询。聚合式查询只有在其输出仍携带判别字段时才合法（如 pytest -q --tb=no -rf：失败名单仍在输出里）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f1523846-ee16-4c78-9f53-7abf782eac2b:1562:5b2f02ad8965052d8be9
evidence_refs: learning:learn:b88a37f774c9
created_at: 2026-09-30T00:51:55.112153+08:00
updated_at: 2026-09-30T00:51:55.112153+08:00
---
## Trigger
计划中存在对某记录来源（git 状态、日志、搜索结果、测试报告、记录库）的成员做分区/分组/归桶决策，需要先查询该来源获取归属信息。

## Discriminator
检查决策所需字段是否会被计划的查询投影丢弃：git status --short 的第一列即暂存区标记，' M' 与 'M ' 经 awk '{print $1}' 投影后同被折叠为 'M'，计数无法回答'哪些文件在哪一区'；对照组：同集内 pytest -q --tb=no -rf 保留了失败名单，属合法聚合。knowledge-at-time：用户目标已明示'staged/未 staged 分组'，status 两列格式语义当时已知，无需后见之明。

## Short path
- 先写下本次分组决策所需的判别字段与条目标识（分区标记 + 路径/ID）
- 一次查询原始 per-item 记录（如 git status --porcelain），保留全部分区列
- 若上游回执已附分区明细（如 ===STAGED===/===UNSTAGED=== 块），先读它，不重查
- 在本地由原始列表推导分组方案，不对同一来源换参数二次查询
- 聚合只用于汇报展示，不作为分组决策的输入

## Stop conditions
- 已取得含判别字段的 per-item 记录并完成分组决策
- 决策仅为总量/存在性，且聚合结果已直接回答该问题

## Verification
- 分组方案中每一条目都能回溯到原始记录上的分区字段值
- 同一来源未出现仅因投影丢字段而触发的第二次查询（本集 git status 同源查询出现 2 次：awk 计数后紧跟 sort|head 全量列表）

## Counterexamples
- 决策只是'有没有遗留/总数是否超阈值'：聚合计数即足够，强制取全量列表反而多余
- 来源查询代价极高且聚合确实保留判别字段（如 -rf 失败名单、带分区标签的汇总）：两段式先聚合再精查合理，不适用本方法
- 条目极少（个位数）或上一次回执已完整展示分区明细：直接读已有回执即可，无需任何新查询，也无需重查
