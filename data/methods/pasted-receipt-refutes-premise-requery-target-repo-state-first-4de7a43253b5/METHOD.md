---
method_id: pasted-receipt-refutes-premise-requery-target-repo-state-first-4de7a43253b5
name: pasted-receipt-refutes-premise-requery-target-repo-state-first
description: 用户贴回的终端回执是目标仓库当前状态的权威证据。当回执逐字推翻你先前建议的前提（No local changes to save 推翻『有脏文件需 stash』；fatal: Not possible to fast-forward 推翻『可 ff-only』），立即承认并按回执重建前提，绝不重发基于死前提的命令。仓库状态按 checkout 隔离：自己沙箱或另一 worktree 的脏状态不能当作目标仓的证据；对目标仓做一次有界拓扑查询（HEAD、分支 sha、ancestor、单侧独有提交清单）。分叉合并的安全性改用构造性证明：单侧独有提交触及路径 ∩ 分支改动路径 = ∅、且分支已跟踪路径 ∩ 目标未跟踪路径 = ∅ → 必然无冲突，可替代可能被沙箱挡掉的 merge-tree 预演；用 --no-ff + 完整 SHA 保持被审查 SHA 在历史中可追溯。
aliases: 用户贴回报错打脸了我之前的判断, ff 合并失败说分叉了怎么安全合, 沙箱脏状态误当用户仓库状态, 合并前用文件交集证明不冲突, 多出来的提交只改文档能不能直接合
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:36553398-1c59-4c05-927f-23e13f8396e6:1854:477004d5af2da426e201
evidence_refs: learning:learn:edbde9d34203
created_at: 2026-10-28T09:04:39.994340+08:00
updated_at: 2026-10-28T09:04:39.994340+08:00
---
## Trigger
已给出的 git 操作计划（stash / ff-only merge / rebase）被用户贴回的终端输出部分证伪；或准备对一个非自己直接操作的 checkout 断言其状态（脏文件数、HEAD 位置、分支祖先关系）

## Discriminator
回执里逐字的状态判定行本身就是判别事实：『No local changes to save』→ 目标仓 tracked-clean=0；『diverging branches…fatal: Not possible to fast-forward』→ 祖先前提为假。再加上回执归属事实（提示符 cd 路径指向哪个 checkout）：自己沙箱的脏状态不是目标仓证据。前提一旦被证伪，旧计划的对应分支全部作废。

## Short path
- 逐行读贴回回执，列出现行计划的全部前提，标记哪些被证实/证伪；被证伪前提对应的命令不再重发
- 在目标仓内做一次有界拓扑查询补齐事实：HEAD、分支 sha、ancestor 判定、单侧独有提交清单（本集为 1 个 docs-only 提交）
- 按触及路径给单侧独有提交分类：纯 docs/Markdown 与代码目录分开
- 计算两个交集：单侧独有提交触及路径 ∩ 分支改动路径；分支已跟踪路径 ∩ 目标未跟踪路径；双空 → 构造性必然无冲突
- 发修正命令（--no-ff + 完整 SHA），并在回复中显式列出被更正的前提与对应回执行，再进入后续部署门禁

## Stop conditions
- 目标仓自身回执/查询已重建全部前提，且合并安全性已由路径交集代数或真实 dry-run 证明
- 修正后的命令连同被更正前提清单已交付，不再对已死前提做任何补救动作（如多余的 stash/retry）

## Verification
- 每个状态断言都能指向目标仓自身的一条回执行或查询结果，而非其他 checkout 的记忆或自身沙箱状态
- 交集类证明必须以空清单回执为准（grep 命中 0 / exit 1），不得写成『估计不会冲突』
- 合并后用 diff --name-only <被审查SHA> <mergeSHA> 限定代码路径输出为空清单，证明部署代码与被审查代码逐字节一致

## Counterexamples
- 用户贴的回执来自另一个目录/仓库（提示符路径与目标仓不同）→ 回执不能直接当目标仓状态，先确认归属
- 回执是旧时间点的输出、其后仓库又被动过 → 非当前状态证据，必须重查
- 两侧触及路径交集非空（对方提交也改了代码/同文件）→ 构造性证明不成立，退回真实 merge-tree dry-run 或冲突解决
- 目标仓就是助手直接操作的同一 checkout → 无跨 checkout 状态移植风险，直接查询即可，不需要 receipt 对账层
