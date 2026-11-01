---
method_id: destructive-background-automation-out-of-tree-checkpoint-recover-before--3a889a47f33d
name: destructive-background-automation-out-of-tree-checkpoint-recover-before-redo
description: 在共享工作区做长实现/多轮验证，且存在会在任务运行中破坏工作树的后台自动化（自动 push 管线/CI 清洁器执行 stash + reset --hard，甚至清除 untracked 文件）时，未提交交付物随时可能被整体移出工作树。首次消失事件（自己无破坏性命令但文件消失、出现非本人 stash、/tmp 出现 prebackup 类目录）即是判别信号：外部破坏者存在且会复发。此后在单元边界把交付集快照到工作树外；再次消失时按 stash list → 自动化备份目录 → 自建快照的顺序恢复，而不是重做；并尽早 commit 使风险归零。
aliases: 工作区被清空怎么找回, 自动push毁掉在途改动, 成果丢失先查谁的备份, 防止后台管线吃掉新文件, untracked文件被删如何恢复
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:156:0057fc6d43867e29651e
evidence_refs: learning:learn:ae1e0a52cbca
created_at: 2026-11-01T10:41:00.538314+08:00
updated_at: 2026-11-01T10:41:00.538314+08:00
---
## Trigger
在共享工作区进行多轮实现/验证任务，工作区存在会在运行中执行 stash + reset --hard（可连带删除 untracked 文件）的后台自动化，且当前携带大量未提交在途交付物

## Discriminator
一次可观察的消失事件回执：自己未执行任何破坏性命令，但既有修改/新增文件从 git status 消失，stash list 出现非本人创建的条目，或 /tmp 下出现 *prebackup* 类备份目录——该回执本身即证明存在会复发的外部破坏性写入者，无需等第二次损失来确认；此后每一份未提交产出都处于风险中

## Short path
- 首次消失事件（或已知该自动化存在）即成立风险判定：立即用一条有界命令把当前交付集快照到工作树外（untracked 新文件 cp + git diff 存补丁），未知量：成果此刻有哪些、是否已有外部副本
- 此后在每个单元边界（新增测试落地/一层实现完成）刷新该快照
- 工作树再次被清空时先恢复后重做：按 git stash list → 自动化备份目录（*prebackup*）→ 自建快照的顺序探测，核对文件数/校验和后恢复
- 恢复完整性用定向测试复跑验证，然后尽快把成果 commit 进 git 使风险归零
- 同时向用户登记该自动化与在途工作的冲突及修复建议（近 N 分钟有写入则延后 + 回执打印恢复命令）

## Stop conditions
- 全部交付物已提交进 git，工作树中不再存在『仅此一份』的成果
- 确认该自动化在本次任务窗口内不会触发（已停用或已排期避开）

## Verification
- 快照目录清单与 git status --porcelain 的在途集合逐项对齐（含 untracked）
- 恢复后重跑本次定向测试全绿，证明恢复零缺失
- 再次消失事件净损失≈0：恢复耗时远小于重做耗时

## Counterexamples
- 单人独占工作区、无任何后台破坏性自动化：常规提交纪律已足够，外树快照纯属开销
- 自动化只 stash 不删除、且回执打印恢复命令：直接按回执恢复即可，无需自建快照体系
- 交付物已全部 commit：reset --hard 无损，不触发本方法
