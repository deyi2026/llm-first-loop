---
method_id: itemized-residual-fix-when-directive-overlaps-own-drifting-commits-fa2e61b759ee
name: itemized-residual-fix-when-directive-overlaps-own-drifting-commits
description: 清单式修正指令（多字段回执/账单修复）到达时，若首个 git log 显示 HEAD 已有同 scope、时间戳紧邻指令时刻的自有 commit（压缩/中断边界的在途工作），不要整份重执行：把指令拆成字段级 checklist，用固定 ref 逐项标 已落地/部分/缺失，只写残差项。账本可能继续漂移（两次读数不一致、commit 时 parent≠起始 HEAD）：先 rev-parse 复核，用带时间戳的 git log+git show 归因中间 commit；属自己在途工作则按当前指令裁决旧自注冲突并在答复中披露重叠时间线；外来 writer 则停手上报。与『整处置已被先前会话完成→verify 模式』互补：本卡处理部分完成与 run 内账本漂移。
aliases: 回执修复和自己刚落的commit撞车, HEAD已有半个修复只补剩下的, 跑着跑着冒出中间提交怎么归因, commit时parent不是开始看的HEAD, 压缩前后自己提交重叠怎么披露
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:3572:23ec106f8d1f173706c3
evidence_refs: learning:learn:d044215dc579
created_at: 2026-11-14T09:39:24.092000+08:00
updated_at: 2026-11-14T09:39:24.092000+08:00
---
## Trigger
多项修正指令到达，git log 显示 HEAD 已有同 scope、时间早于或紧邻父侧消息的自有提交（在途工作重叠）；或执行过程中同一字段两次读取取值不一致、commit 回执的 parent 不是起始观察的 HEAD——修正可能正被自己的重叠会话边跑边落地。

## Discriminator
两个当时即可见的事实收窄搜索空间：(1) HEAD 提交 subject 与指令 scope 部分重合且时间紧邻指令——它至多覆盖部分指令项，必须逐项求残差，而非按『签名匹配→verify』或整份重写二选一；(2) 两次读取间字段值变化（如计数 7→8）且无编辑解释——不是脚本误报，是 run 内账本漂移，需用 ref 复核与归因，而不是重新枚举字段。

## Short path
- git log --format 含时间戳建立账本基线：起始 HEAD、指令引用的 commit、相邻同 scope 自有提交各是什么
- 把指令显式拆成逐项 checklist（字段级：顶层 manifest/note/final_state、计数更正、口径分离、历史标注、审计、扫描、clean、单文件 diff）
- 用固定 ref 定点读（git show HEAD:path 的目标字段）为每项标 已落地/部分/缺失；每次写前后 rev-parse 复核 HEAD 未再移动，移动则重新求残差
- 只写残差项，一次 edit+读回；对 manifest 声称的 commit/tree 逐文件 sha256/bytes 机械审计
- commit 后若 parent≠预期：立即带时间戳 git log+git show 该中间提交归因；属自己在途工作则按当前指令优先裁决旧自注冲突（父侧明示>早期自注），外来 writer 则停止叠加并上报
- 最终答复披露重叠时间线：哪个提交覆盖哪些项、冲突如何裁决、机械核验结果与边界遵守

## Stop conditions
- checklist 全部项对最终 HEAD 验证通过：字段读回一致、逐文件审计 0 mismatch、原版安全扫描 PASS、git clean、diff --stat 仅目标 artifact
- 中间提交归因为外来/未知 writer：停止在其上叠加，转并发写冲突上报
- 指令与 HEAD 完全无同 scope 重叠：退出本方法，直接执行指令

## Verification
- 逐文件 sha256+bytes 对 manifest 声称的 commit/tree 审计（含确认被判 mismatch 的文档是否本就是最终交付版本）
- git rev-parse/porcelain 前后一致，或差异已被 git show 逐行归因
- JSON 解析有效、batch/条目计数与索引读回一致
- 最终 diff --stat 证明 receipt-only（单文件、零 runtime/基线/测试改动）

## Counterexamples
- 指令引用的 commit 即当前 HEAD 且无相邻同 scope 提交（干净续跑）：逐项求残差是纯开销，直接执行或按『commit 签名匹配→verify 模式』处理即可
- 中间提交非自有 scope（外来/对抗 writer 写同一 artifact）：不得静默叠加或按指令优先覆盖，应停手上报并发冲突
- 单项原子指令、无 checklist 可拆：commit 级签名匹配已足够
- 无 git 账本的普通文件目标：漂移检测锚改为版本 token/mtime，机制不同
