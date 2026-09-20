---
method_id: verify-at-located-artifact-stop-keyword-discovery-a359455d9a32
name: verify-at-located-artifact-stop-keyword-discovery
description: 当任务从『找来源』转为『核验一个已具名/已定位 artifact 的宣称』时，应切换到取回-核验模式：直接读取该 artifact 本体（README/文档），因为搜索结果摘要对内部事实（端口、配置键、精确数字、功能清单）天然无判别力。本 episode 的摩擦点：在核验 8766/元素表/OpenRouter 这类仓库内部细节时，又发出一个 6 关键词混合宽查询，返回纯噪声（词典、浏览器下载页），零信息贡献；而同轮的精确短语查询 "jev-ultrafast" github 已一发命中规范仓库 URL。附带机械规则：名称已知时用引号精确短语定位；多关键词厨房水槽查询在名称已知场景下偏向噪声。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:a8ca7a5d-9f35-462e-b02e-e13f15ff0023:4:1eb95fad8b3654eebc9e
evidence_refs: learning:learn:8821d0ad0d8e
created_at: 2026-09-20T04:45:37.826322+00:00
updated_at: 2026-09-20T04:45:37.826322+00:00
---
## Trigger
任务是核验某个具名 artifact（仓库/产品/文档）的对外宣称；发现阶段已（或同轮正通过精确名查询）拿到权威来源 URL，剩余未知量是该 artifact 的内部事实，且部分宣称与文章原文存在待裁决的数字冲突。

## Discriminator
两条当时可见的事实：(1) 待核验对象在类型上只能由 artifact 本体裁决——搜索摘要不可能确认 localhost 调试端口、密钥名或精确计时数字，故任何针对这些未知量的关键词搜索判别力为零；(2) 该 artifact 的确切名称（jev-ultrafast）自任务起点已知，精确短语查询被证明一发命中规范来源。两事实共同把『继续发现』从候选空间中排除。

## Short path
- 未知量=仓库位置：用已知确切名称发精确短语查询（"jev-ultrafast" github），取 rank 1 规范 URL，不做多关键词宽查询。
- 未知量=文章宣称真伪：fetch 仓库 README，逐条对照数字/操作清单/端口/密钥；冲突数字（如 9.45→9.09 vs 9.45→7.092）以一手来源裁决。
- 未知量=模型背景与横向比较：这是本体无法自证的外部事实，定向选 1-2 篇第三方深度文章（源码分析、同类工具对比）补齐。
- 每条宣称都映射到一手来源或显式标注为第三方/官方自报后，停止取回与搜索。

## Stop conditions
- 发现阶段在精确名查询命中规范 URL 后即结束，不再对同一未知量发任何发现型搜索
- 每个待核验宣称都有了来源裁决：一手 README 或明确标注的第三方旁证
- 新增搜索/抓取不再对应任何未决未知量（否则即为 post-sufficiency action）

## Verification
- 最终事实表每条可溯源到一手来源，或显式标记『官方自报/第三方』（本 episode 正确做到了后者，如性能数据风险提示）
- 工具 trace 中不存在针对已定位 artifact 内部事实的发现型搜索（违规信号：查询含 >4 个混合关键词且返回结果与查询意图零共享 token）
- 文章与一手来源的数字冲突被显式指出并裁决，而非默认采信任一方

## Counterexamples
- 宣称是外部反响或独立基准（如 HN 热度、有无第三方复现）——artifact 本体不可能自证，此时搜索与聚合文章才是正确来源，只读本体反而不足
- 精确名查询无命中或多义（同名 fork/镜像/重名项目）——权威来源尚未定位，必须先做宽发现再收敛
- README 是营销自报而任务要求独立验证性能数据——读本体不够，须补独立实测来源（本 episode 自身就标注了此风险）
- 目标 artifact 无公开本体（闭源产品、纯传闻）——只能依赖二手来源并降级结论置信度
