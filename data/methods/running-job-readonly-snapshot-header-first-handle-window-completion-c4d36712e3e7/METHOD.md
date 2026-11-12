---
method_id: running-job-readonly-snapshot-header-first-handle-window-completion-c4d36712e3e7
name: running-job-readonly-snapshot-header-first-handle-window-completion
description: 进行时后台 job 的限次只读进度查询：job_output 回执头部已含权威状态字段（running/cancel 等），直接回答『exit 之问』；日志正文截断时不第二次调用活工具，而是沿 transport 的内容寻址恢复句柄按报告字段分窗补读——尾部窗取最近阶段、stderr 带取错误素材，显示预算再截断就缩窄区间重发。stderr 按严重性 token 分类计数而非数行。各窗同一 blob_sha256 保证在单一不可变快照上聚合，守住用户单次调用/零副作用约束，四项字段各有引证即停。
aliases: 跑着的后台 job 只读查进度, 截断的运行日志怎么补看, 查任务跑到哪一步了, CI 门禁中途看进展, 数报错条数不重跑任务
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5fad8445-5fac-497b-9180-4e6d6c74ad07:14:9aaa714f899faea1c925
evidence_refs: learning:learn:b7a8a617a5ad
created_at: 2026-11-12T14:57:06.647163+08:00
updated_at: 2026-11-12T14:57:06.647163+08:00
---
## Trigger
用户对受管后台 job 下达严格只读、限次（如仅一次 job_output）的进行时进度查询，要状态/最近阶段/stderr 错误摘要/终态才报 exit；回执头部含权威状态但日志正文被截断，transport 块已给出带 range 元数据与 blob_sha256 的恢复句柄。

## Discriminator
回执头部状态字段（running、cancel_requested 等）当时已免费回答『是否有 exit』；range 元数据给出快照总行数与 complete 标志，blob_sha256 标识这是同一不可变快照——缺失事实只集中在两个带：尾部带（最近阶段横幅）与 stderr 标记带（错误计数）。补全走恢复句柄即可，无需也不应重调活工具（运行中日志在增长，重调会拿到漂移的新快照并违反限次约束）。

## Short path
- 只读回执头部：状态=running → exit 一栏直接写『非终态，无』，不为此发任何额外读取；从 range 元数据得知快照行数与 complete 标志。
- 所有补全走 transport 恢复句柄分窗水合，不再第二次调用 job_output：守住限次约束，且各窗 blob_sha256 一致才能在同一快照上聚合。
- 按报告字段选窗：先尾部窗拿最近阶段横幅（运行中 job 最易变的信息在尾部），再 stderr 标记带拿错误素材。
- 若某次水合回执的可见正文在所需行之前被显示预算截断，不换来源，以所需偏移为 start 重发更窄区间，直到目标行落入可见预算。
- stderr 按严重性 token 分类计数（error: / Warning: / audit 复核告警），不以行数冒充错误数，告警单列并注明不阻断。
- 每个请求字段都有引证行即停，显式声明未 restart/merge/push/publish。

## Stop conditions
- 状态、最近阶段、stderr 分类摘要、exit（或其缺席）四项各有回执引证行；
- 不再对已引证过的区间重复发窗，不为『读全日志』继续；
- 快照仍为 running 时不等待、不轮询、不注册唤醒——用户要的是即时只读快照。

## Verification
- 各水合窗 blob_sha256 一致，证明是同一快照的分窗补全而非新观测；
- 状态字段逐字引用回执头部；exit 报缺席仅当头部明确非终态；
- stderr 计数与 stderr 带内的 token 分类可对账，告警与 error 分列；
- 全程除用户指定的单次调用外零副作用动作（无 restart/merge/push/publish）。

## Counterexamples
- job 已达终态：改走终态字段锚定水合路径（exit 采信 wait/终态回执、尾部窗取总判），本卡『exit 无』分支不适用；
- 用户要等结果而非即时快照：应注册一次性延迟唤醒做有界等待，而不是单次快照；
- transport 无恢复句柄且正文截断：如实报告截断与覆盖范围，不为补全而突破限次或改用有副作用途径；
- 用户要完整日志原文：分窗补读是错误工具，应走整份导出/落盘文件路径；
- 回执正文未截断：直接作答，零次水合。
