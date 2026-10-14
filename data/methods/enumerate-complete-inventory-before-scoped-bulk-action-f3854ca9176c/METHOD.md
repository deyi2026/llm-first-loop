---
method_id: enumerate-complete-inventory-before-scoped-bulk-action-f3854ca9176c
name: enumerate-complete-inventory-before-scoped-bulk-action
description: 当要基于一份清单类输出（git status、搜索结果、evidence range 回执）固定某个批量动作的范围（scoped commit、清理、发布前置处置）时，若该输出是截断的——声明总数大于可见条目数、显示行数受限、或 complete=false/next_start>0——先花一次分组枚举拿到完整集合再定范围。不要从部分清单推出『全部都是X』这类集合级断言，也不要等守卫 ABORT 后才补枚举。守卫仍是兜底，但一次分组 tally（按顶层目录计数）通常能用一条命令把『首屏子集决策→被拦→重诊断→扩大范围』压成『先看全集→一次定范围』。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a2f05599-54ef-4df0-83ac-5403f3fbc184:1308:8a009c8caf584cdf674c
evidence_refs: learning:learn:173dbe64b83f
created_at: 2026-10-13T14:58:04.749501+08:00
updated_at: 2026-10-13T14:58:04.749501+08:00
---
## Trigger
计划执行限定范围的批量动作（提交/stage/清理/发布门禁处置），且其范围依据是一份状态或清单输出；输出带截断信号：stated total 与可见条目不一致、显示行数上限、range.complete=false。

## Discriminator
清单声明总数与实际展示条目数不匹配（本集：git 状态输出标明『输出 36 行』且仅见约 20 条 ?? 项，但 dirty_count=81）——在补齐完整清单之前，『全部 81 项都在 data/methods/』这类覆盖全集合的断言没有任何当时证据支撑，而据此起草的窄范围提交注定要被范围守卫推翻。

## Short path
- 读到截断信号后，未知量=候选集合的完整构成；先跑一条分组统计（如 git status --porcelain | grep '^??' 按顶层目录 tally），一次拿到全集构成
- 对每个出现的顶层目录查入库惯例（git ls-files 该目录、.gitignore 例外规则、历史上同形态 chore 提交），分类为台账资产 vs 代码
- 一次性提交/处置全部已分类条目，范围覆盖全集而非首屏子集
- 动作后做范围审计：实际触及路径 ⊆ 声明的资产目录；发布场景再验与代码基线零代码差异

## Stop conditions
- 完整清单已取得且各类已对照仓库惯例分类，即可固定范围执行
- 声明总数==可见条目数（清单本就完整）→ 按现有范围直接执行，不做额外枚举

## Verification
- 执行批量动作前核对 enumerated_count == stated_total
- 动作后范围审计：git show --stat / diff --name-only 的路径全集落在声明目录内
- 发布场景：与代码基线（如 c028134aa）的差异仅限台账/文档路径，代码路径零差异

## Counterexamples
- 清单完整（total==entries、complete:true）且条目集中在单一预期目录：直接做 scoped 动作，额外枚举是浪费
- 动作是点查询（找某个具名文件/路径），截断不影响该结论：按需读取即可，不需要全集
- 全集含处置方式无法从仓库惯例推出的敏感路径：枚举仍有用，但此时应暂停范围等人工/策略确认，而不是把不确定项并入批量提交
