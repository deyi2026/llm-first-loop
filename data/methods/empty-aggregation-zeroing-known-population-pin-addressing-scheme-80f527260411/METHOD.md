---
method_id: empty-aggregation-zeroing-known-population-pin-addressing-scheme-80f527260411
name: empty-aggregation-zeroing-known-population-pin-addressing-scheme
description: 跨源聚合/join（账本 refs × 记录状态）返回空，而上一轮构成统计已给出非零总体和具体 key 样例时，这必是键派生/寻址 bug，不是数据事实。先做一行总体守恒对账：总体归零→修寻址（一次最小目录枚举钉死 store 实际命名方案，如每记录一目录 <slug>-<hash>/ + store 级共享账本文件，别猜平铺路径）；某类别为零但各桶之和等于已知总数→真实缺席，照常采信。重跑后分类总数必须与独立计数对账一致才用于下游结论。本集靠此把『usage 全空』的文档前提纠正为 54 张 candidate 有真实使用。
aliases: join出来是空的但明明有数据, 空聚合先查命名方案再重跑, 账本和卡片状态对不上号, 总数守恒对账检查, 聚合把已知总数吞零了
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cab051cc-c0ca-4a09-b848-6d4a00ec0ffe:1118:d4e91be57f319e4a9d81
evidence_refs: learning:learn:ca7b24e00b1d
created_at: 2026-10-30T08:45:21.659158+08:00
updated_at: 2026-10-30T08:45:21.659158+08:00
---
## Trigger
对目录型持久化 store 做跨源 join/聚合（如 usage 账本 refs × 卡片状态）返回空或零，而手头已有同一总体的独立计数或具体 key 样例（构成 Counter、top-N 输出、可见的 ref 全文）

## Discriminator
总体是否被吞：已知非零总体（如 62 个 distinct refs、top5 样例全文可见）在结果中整体归零 ⇒ 必为键派生/寻址错误，禁止当作事实采信；只是某类别为零而各桶之和等于已知总数（如 0 条 rejected 但 64+11+13=88 守恒）⇒ 真实缺席，照常采信

## Short path
- 对账先行：把空 join 结果与上一轮独立计数比对，判断总体是否被吞（一行判断，不重跑、不换措辞再试）
- 判为寻址错误后，用一次最小目录枚举钉死 store 实际命名/布局（每记录一目录 slug-hash、共享账本在 store 根），从观测样例推导键变换（ref 'method:slug-hash' → 目录名），不猜平铺文件路径
- 按推导出的键变换重跑 join
- 总数对账：各状态桶之和必须等于独立统计的 distinct 数，抽 1 个已知 key（top-N 里的 ref）核对落桶正确，才把结果用于下游结论

## Stop conditions
- 重跑 join 的分类总数与独立计数对账一致（含 no_dir/未解析桶），且已知样例 key 落桶正确
- 或确认从无已知正例（未见过非零计数或具体 key），此时空结果按真实缺席处理，先做存在性探针而非修键

## Verification
- sum(状态桶) == 账本侧独立统计的 distinct key 数
- 抽 top-N 中一条具体 ref，人工确认其被解析到正确状态桶

## Counterexamples
- 构成 Counter 已枚举全部决策且总数守恒时，某类别为零（如 0 条 rejected）是真实事实，不是键错误，不要为凑齐类别去改键
- 无任何已知正例时的空结果可能是真缺席：先用已知存在的 key 做存在性探针，而不是假设寻址错了
- store 布局本会话已钉死时空结果更可能是键规范化问题（前缀如 'method:' 未剥），直接修变换即可，不必再枚举目录
