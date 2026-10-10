---
method_id: registry-first-lookup-for-named-artifact-verification-74024ca56ef7
name: registry-first-lookup-for-named-artifact-verification
description: 核实一批带精确名称的外部平台 artifact（GitHub 仓库/包/论文等）时，不要先走通用搜索引擎：平台自身的 search/registry API 一次就能返回存在性+结构化元数据（star/license/更新时间/描述），而通用搜索对'精确专名'类 query 常返回词典/导航站噪声。同时：回执声明整个通道'所有源均 0 条结果'是通道级事实而非 query 级事实，1-2 次后应换 source class，而不是在同一通道内换措辞继续枚举；单端点 403 是端点级限流，优先换同平台兄弟端点而非退回宽搜索。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:0051f593-fc2b-4570-b0f6-2afe09af0b5e:5:c53d7a368bc6a663aaab
evidence_refs: learning:learn:a7d5881fe844
created_at: 2026-10-10T07:57:12.215772+08:00
updated_at: 2026-10-10T07:57:12.215772+08:00
---
## Trigger
需要核实/盘点一批拥有精确唯一名称的外部平台 artifact（如 GitHub 仓库），信息源自二手转述（文章/清单），所需事实是该平台的结构化元数据；或已观察到同一搜索通道连续返回整通道 0 结果。

## Discriminator
任务起点即可见：(1) 每个目标都带来自原文的精确标识符；(2) 所需字段恰为平台 search/registry API 的结构化返回字段；(3) 通用搜索引擎对这类 query 的结果类别与本任务目标错配。摩擦进行中可见：首个通道回执写明'所有源均 0 条结果'——这是通道为空的证据，不是关键词需要再变的证据。

## Short path
- 对第一个精确名称直接调平台 search API（exact-name query），校验返回的 full_name/description 与转述一致
- 批量复用同一 endpoint 与参数模板处理其余名称，一次取得 star/license/pushed_at
- 仅当某名称 search miss 时，才用 general web 搜索解析别名/迁移/新地址
- search 端点限流（403）时先试同平台其他端点，而非重试同端点或退回搜索引擎

## Stop conditions
- 每个名称都有 first-party 结构化记录且所需字段齐全，或已确认该名称不存在/已迁移
- 平台无可用替代端点时，记录缺口并显式降级到 web 搜索，不做无信息重试

## Verification
- 返回记录的 full_name/描述与转述名称语义一致（非仅词面匹配）
- 所需元数据字段在同一响应内取得，无需为同一事实二次抓取或交叉多源

## Counterexamples
- 目标只有描述性短语而非精确名称（'一个做 X 的工具'）——必须先 general 搜索确定规范名，registry-first 无从下手
- 平台无公开 search API、被整体封锁且无替代端点——此路不通时才走 web 搜索
- 需要的是社区评价/讨论/教程等主观信息而非平台结构化元数据——web 搜索/社区站更合适
- 首次宽搜索即命中含全部所需信息的权威聚合页——直接采用，不必强行走 API
