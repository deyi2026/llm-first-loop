---
method_id: oversize-git-state-triage-by-provenance-class-7e27731366bd
name: oversize-git-state-triage-by-provenance-class
description: 大小受限的准入/提交门拒绝 'state too large'（或隔夜/并发写者后提交前预检）时，不盲目 stash/checkout 缩小、也不反复重试碰运气：先按 provenance 给 delta 分桶——(1) 有审查回执逐文件 sha256 指纹背书的载荷；(2) diff 仅含易变字段（时间戳/epoch）的可再生运行产物；(3) 归属其他活动 goal 的改动。只无损清掉第(2)桶，第(1)桶逐字节比对回执指纹防审查后漂移，第(3)桶留给属主。重测体积后一次性重试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f3bcb24f-1f02-4da7-aaad-75bb446ffa88:1139:c9feffcf6f92731f23f3
evidence_refs: learning:learn:0312973d5310
created_at: 2026-10-16T09:41:54.159746+08:00
updated_at: 2026-10-16T09:41:54.159746+08:00
---
## Trigger
向有字节上限的准入/审查门提交 git state 被拒 too_large；或在共享工作区（存在并发 goal/会话、隔夜时间间隔）提交前的预检时点

## Discriminator
失败理由是 size 而非内容；且当时可得三条收窄事实：分目录 diff 字节数（哪个桶占大头）、最大桶样本 diff 是否仅时间戳/epoch 类易变字段（可再生）、变更文件是否被某审查回执的逐文件指纹覆盖（已验证载荷）

## Short path
- 预检：存在时间间隔/并发写者时，提交前先量 delta 体积与分目录构成，超上限先分诊再提交
- 对最大字节桶抽样 diff，判定语义改动 vs 仅易变字段的可再生产物
- 对声称已审查的文件，shasum 与回执逐文件指纹比对，确认无审查后漂移
- 仅还原易变字段-only 的可再生 artifact（下轮运行自动重生成，无损）；指纹一致的已审载荷保留；他人 goal 的改动不吞并、归属其属主
- 重测体积低于上限后一次性重试该门

## Stop conditions
- 重测 delta 低于上限且门返回 accepted（非再次 too_large）
- 保留文件与对应回执指纹逐字节一致；被清除文件均为易变-only 可再生
- 仍存在无法归类的改动时，先归属/协调，不靠重试碰运气

## Verification
- shasum -a 256 逐文件 == 审查回执指纹
- 清除前 diff 确认仅时间戳/epoch 类字段变化（本例 18 文件 141+/141- 全为 started_at/wall 变化）
- 门重试回执 accepted，且被清产物在后续全量运行中如预期自动重生成

## Counterexamples
- 超限 delta 全是自己的未审新工作、无回执指纹可验：指纹分诊不适用，应走有回执背书批次的本地提交瘦身（本集前一次 239KB 场景）
- 看似再生的产物 diff 含语义字段（结果数/状态翻转）：还原即丢证据，必须先完整 diff 再决定
- 单写者、delta 全归自己且无并发：直接按需缩减即可，无需分桶
- 拒绝理由是内容/校验失败而非体积：本方法不适用
