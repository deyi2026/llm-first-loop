---
method_id: pinned-snapshot-reads-resolve-worktree-head-before-source-facts-c0a15a22a54b
name: pinned-snapshot-reads-resolve-worktree-head-before-source-facts
description: 任务材料把权威基线钉死为精确 commit SHA（如 origin/main 快照）并要求对照『真实源码』核验文档声明时，第一次源码内容读取前先解析将要读取的每个 worktree 的 HEAD：与钉住 SHA 不一致，则所有基线事实改走 git show <sha>:<path> / ls-tree 读取，工作树分叉量（如落后 N 提交）本身作为可上报证据记录。防止用身份未定的工作树回答『基线是什么』，也防止把工作树缺文件误当 main 缺文件；工作树读取仅保留给『本地实际执行版本』『未提交内容』这类以工作树为对象的未知量，且两种通道的结果分开标注。
aliases: 检出过期就git show快照, 对着钉住的commit读代码, 别拿工作树当main核验, HEAD和快照SHA对不上先定位再读, 源码核对走快照不走本地检出
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:27812a0e-44de-4c70-bfb4-dd546d86f48e:0:8ac1ee135e87d2794f48
evidence_refs: learning:learn:7447c3ce42f6
created_at: 2026-11-16T23:24:56.691886+08:00
updated_at: 2026-11-16T23:24:56.691886+08:00
---
## Trigger
审查/核验任务给出精确基线身份（commit SHA，或已确认的 origin/main 快照），要求对照真实源码裁决文档/设计声明；仓内存在一个或多个方便读取的 worktree/checkout，但其 HEAD 与该身份的一致性尚未确认。

## Discriminator
任务钉住的基线对象（如 9edfa3481）已被 rev-parse 确认等于 origin/main——权威内容可经 git 直接取得；而即将 ls/sed/grep 的文件系统路径属于身份未定的本地检出。任何输出中打印出的 HEAD ≠ 钉住 SHA，即坐实两者是不同对象，工作树读取回答的是另一个版本的仓库。

## Short path
- 校验被审工件自身身份：对文件系统中的工件直接测精确 SHA256 与行数（工件可能只存在于 worktree，此时文件系统读是正确通道）。
- 校验基线 ref：rev-parse origin/main == 任务钉住的 SHA。
- 读任何『源码事实』前，rev-parse 每个将要读取的 worktree 的 HEAD；未知量：工作树是否就是钉住快照？
- HEAD≠快照 ⇒ 全部基线源码读取改走 git show <sha>:<path> / git ls-tree <sha>；分叉量（behind N）记录为证据而非单纯干扰。
- 逐项把设计声明映射到钉住快照内容裁决；用户点名的焦点项全部闭合、或确认『快照中不存在该实现』即停。

## Stop conditions
- 所有被引用路径在钉住快照中的存在性与内容均已读取并裁决。
- 某声明依赖的实现在快照中不存在（fatal: path does not exist in <sha>）——这本身即是结论：设计引用了基线中不存在的对象，无需再扫工作树佐证。

## Verification
- 回执中每条源码事实标注其读取身份（git show <sha>: 于钉住快照），不与工作树读取结果混引。
- 显式披露工作树 HEAD 与钉住快照的分叉量（如落后 61 提交），并说明该分叉在本结论中扮演的角色（证据 vs 读取通道）。

## Counterexamples
- 钉住 SHA 与工作树 HEAD 相同且树 clean：直接文件系统读取即可，强制 git show 只增加开销无新信息。
- 被审对象本身是未提交的工作树状态（如 worktree 里的新设计稿）：快照中根本不存在该文件，必须文件系统读。
- 未知量恰恰是『本地实际会执行哪个版本的脚本』（执行侧事实）：工作树陈旧正是待测命题，此时快照读与工作树读都需要，且必须分开报告而非二选一。
