---
method_id: concede-to-commit-gate-named-live-lane-restore-verify-merge-fafcf484c6cf
name: concede-to-commit-gate-named-live-lane-restore-verify-merge
description: 多会话共享 main、commit/push 有审查闸的仓库里执行一个交接来的修复，到 commit 时被闸拦下并点名另一会话的 live lane 提交：先用『范围覆盖 + 时间戳≥本次开工 + 我的改动未提交』三事实判定自己是重复方；是则 git restore 撤掉自己的未提交 diff，改在对方 lane 自己的树上实测全量门禁验证，再走标准合并审查（BLOCK 按其声明的解除条件补证据，不绕闸）后 ff 合并。开工前的账本/远端检查发现不了中途冒出的并发等价工作——commit 闸就是它的探测点。部分重叠时不整体让位，patch-id/scoped diff 裁决后叠加剩余。
aliases: 提交被闸拦说别的会话已修好同一问题, 修到一半撞上别人的lane, 跑完全量门禁才发现白修了, 双会话同题修复撞车, commit时被告知有等价在途修复
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:3114:2bafb4eeef61a7d6f682
evidence_refs: learning:learn:34ae990c2767
created_at: 2026-11-11T09:00:31.486186+08:00
updated_at: 2026-11-11T09:00:31.486186+08:00
---
## Trigger
多会话共享 main 且 commit/push 带审查闸的仓库；正在执行一个（常为上一会话建议/交接驱动的）修复，开工时的 git log 与 ls-remote 里没有等价工作，到 commit/push 被闸拦下、消息点名另一会话的 live lane/提交覆盖同一修复。

## Discriminator
闸消息内三件可核事实同时成立：①对方提交 subject/改动面覆盖我方未提交 diff 的范围（常附带专门回归测试或更广加固）；②对方时间戳 ≥ 我方本次开工时间（并发产生，开工前检查不可能发现——本集 ls-remote 输出中即无该分支）；③我方改动尚未提交、可无损 restore。三条齐备 → 我方是重复方，让位成本最低。

## Short path
- 被闸拦下点名 live lane 后，第一动作读对方被点名提交的 subject+stat+diff，与我方未提交 diff 逐文件比范围；未知量：对方是否已覆盖本修复
- 范围被覆盖 → git restore 撤净自己的未提交改动，不开第二个竞争性 merge lane，不因沉没成本（已跑过全量门禁）护盘
- 在对方 lane 自己的树上跑 canonical 全量门禁实测（exit=0 才算数），不因对方实现更稳而免验
- 走标准合并审查；被 BLOCK 时按其自述解除条件补齐（如把跨会话证据导出为工作区文件）后复审，不绕闸
- ff/clean 合并后如实汇报本地-远端差与待推送提交集，push 决策交还用户/闸

## Stop conditions
- 对方提交在其自身树全量门禁 exit=0 且合并审查 PASS、ff 合并完成
- 或裁决为部分重叠：等价部分让位，剩余工作已重放在对方提交之上并单独过闸

## Verification
- 对方提交 scope_files ⊇ 我方拟改文件集（逐文件核对，不凭 subject 语义推断）
- 对方树全量门禁 exit=0 是本会话实测回执，非转述他人结论
- 合并后历史上不存在两个等价修复并存；本地/远端差与待推送集已如实汇报

## Counterexamples
- 对方提交只覆盖我方修复的一部分（如只修 PATH 未修并发不稳）→ 整体让位会丢工作，应 patch-id/scoped diff 裁决后叠加剩余
- 单会话、无并发写入风险的仓库里闸报 live lane → 更可能是陈旧元数据，先核实 lane 活性再让位
- 我方修复已提交甚至已推送后才收到 lane 消息 → restore 不再可能，走对账与合并而非撤销
- 点名的 lane 属于自己早前会话 → 不是重复方，按自家收口流程处理
