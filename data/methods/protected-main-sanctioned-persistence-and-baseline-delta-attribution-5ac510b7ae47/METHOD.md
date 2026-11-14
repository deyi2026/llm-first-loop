---
method_id: protected-main-sanctioned-persistence-and-baseline-delta-attribution-5ac510b7ae47
name: protected-main-sanctioned-persistence-and-baseline-delta-attribution
description: 在受保护共享主工作树（用户给出 dirty/untracked 基线计数、既有 worktree 全部保护、新增文件含 untracked 也算触碰）里产出报告/文档类产物时，持久化改走既有权威通道（Goal checkpoint + evidence 层存全文与 sha256），不在主树新建文件；若越界写入已发生需纠正：删除前先做基线差额归属——实测 untracked 减用户基线得差额，全量枚举清单逐项归属，只删自己写入的项，他人项如实留档不碰；内容先入 evidence、纠偏 checkpoint 落账后再删除，删完复核计数回到基线减他人项且 HEAD 不变。后续确需入库文档，仅在基于精确 origin/main SHA 新建的干净 worktree 创建。
aliases: main 不让落文件时报告放哪, 误写进工作区怎么补救, 删自己写的文件前先对数, untracked 差额归谁先认领, 产物入账不落盘
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:144:5850855b71b1377e6a0d
evidence_refs: learning:learn:4289fe098344
created_at: 2026-11-13T19:45:59.601933+08:00
updated_at: 2026-11-13T19:45:59.601933+08:00
---
## Trigger
共享仓库主工作树被用户设为写保护区（明确给出 tracked dirty/untracked 基线计数，且新增文件即使 untracked 也算触碰），而任务仍需持久化报告/结论文档；或发现上一轮产物已落入受保护主树、需要纠偏清理。

## Discriminator
实测 porcelain 计数与用户基线的差额 vs 本会话已知写入数：当差额大于自己已知写入数（如 24−21=3 而本会话只写过 1 个文件）时，证明树中存在他人/既有新增项，删除范围必须先由全量 untracked 枚举加逐项归属判定收窄，不能把差额整体当成自己的去清。

## Short path
- 产出报告类产物时先问持久化通道是什么：若存在既有 evidence/checkpoint 权威通道，直接把全文（含 sha256、行数）写入该通道，不在主树落新文件。
- 若疑似已越界：先只读取计数（tracked dirty/untracked/HEAD）与目标文件存在性，确认冲突是否成立及差额大小。
- 差额大于已知写入数时，全量枚举 untracked 清单，按时间戳与来源逐项归属：仅本会话产物进入删除名单。
- 删除前把目标文件全文持久化到 evidence（sha256 与磁盘一致）并落一条纠偏 checkpoint，内容先于破坏性操作。
- 删除后复核：计数回到 用户基线 减 已归属他人的项、HEAD 不变、文件不存在；他人项如实上报、不触碰。
- 后续确需入库文档时，先钉死精确远端基线 SHA，仅在新建的干净隔离 worktree 内创建。

## Stop conditions
- 主树状态回到 用户基线 减 已归属他人的新增项，且每个剩余差额项都有显式归属结论（本会话/他人）。
- 被删内容已在权威通道持久化（evidence sha256 与原文件一致）并有 checkpoint 载明纠偏过程。
- 纠偏记账成功后才执行删除，二者顺序不可颠倒。

## Verification
- 删除前后各取一次 porcelain 计数与 HEAD，确认只减少自己那一项。
- evidence 存档的 sha256 与被删文件原 sha256 字节级一致才允许删除。
- 全量 untracked 清单中每个非基线项都有本会话/他人的显式归属结论，无未归属项。

## Counterexamples
- 任务本身就在专属沙箱或按指令新建的隔离 worktree 中写产物（如为下一阶段 writer 新建的干净树）——该树无保护基线，直接写文件是正确路径，本方法不适用。
- 不存在任何权威持久化通道（无 evidence/checkpoint 系统）时，强推不落文件会丢数据，应先与用户确认通道。
- 差额项归属不明且无时间戳/来源线索时，宁可不删并上报，不能假设多出来的都是自己的或都不是自己的。
- 用户基线本身过期、存在活跃并发写者时计数不会收敛到基线，应报告并发写入信号而非反复清理。
