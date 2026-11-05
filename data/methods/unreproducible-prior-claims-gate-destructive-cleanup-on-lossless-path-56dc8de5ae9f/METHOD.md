---
method_id: unreproducible-prior-claims-gate-destructive-cleanup-on-lossless-path-56dc8de5ae9f
name: unreproducible-prior-claims-gate-destructive-cleanup-on-lossless-path
description: 把上一轮的清理建议执行成批量删除时，若建议中的具体锚点断言（某树是某编号、N 棵无独有内容、内容已被 main 超越等）无法在当前仓库廉价复现，就不把这些结论当删除依据：改从仓库内已提交的权威清单机械重提目标集，护栏核查 live 依赖后，先逐目标建可达归档 ref、脏内容二进制落盘，再执行不可逆删除并验证可恢复。判定对错都不丢东西——删除的 gate 从『结论正确』换成『无损可恢复』。
aliases: 上轮清单对不上仓库怎么删, 删worktree前先验证上轮结论, 不可复现的结论不能驱动删除, 破坏性清理先做无损兜底, 按上轮建议执行清理前先对锚点
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:dc65c21c-3531-46e5-a85e-a6b3e5e358a7:893:89a02be122598357d648
evidence_refs: learning:learn:472aded1160b
created_at: 2026-11-05T17:01:06.649960+08:00
updated_at: 2026-11-05T17:01:06.649960+08:00
---
## Trigger
用户要求按上一轮/历史会话的清理建议执行批量删除（worktree/快照树/目录），且该建议携带具体清单断言（具名 ID、编号、计数、『无独有内容/已被超越』类裁决）时。

## Discriminator
删除前对先前断言的锚点做一次廉价复现探针：具名目录 ls 是否存在、具名行是否出现在已提交的权威清单文档中、fresh 计数器（cherry/dirty/ahead 数）是否与先前数字吻合。任一 miss 即证明先前结论不是当前仓库真值——该事实在动手前就可得，足以把『沿结论删』降级为『沿清单无损删』。

## Short path
- 从仓库已提交的权威清单文档机械提取目标集并核对计数，不沿用上一轮转述/记忆中的编号清单
- 对上一轮每条具体断言做存在性/成员/计数探针；miss 的断言降级为线索，不作删除依据
- 护栏核查：live 依赖（现役部署 code_root、服务头）与目标集求交必须为空
- 无损化：逐目标建 refs/archive 归档 ref；脏树补 git diff HEAD --binary + untracked 文件落盘并记体量
- 执行删除（只删检出不动分支）+ prune，用前后计数、live pid 不变、从归档 ref 恢复一棵的探针闭环

## Stop conditions
- 目标集计数与权威清单一致、live 交集为空、每个被删对象都有可达恢复路径（ref 或落盘），且回执全绿
- 先前断言全部复现成功时，可回到常规裁决路径，不必强行走『结论无关』分支（归档 ref 仍建议保留）

## Verification
- 删除前后注册 worktree/目录计数与 du 变化符合预期差值
- live 部署根与服务 pid 删除前后逐一相同
- 任选一个归档 ref 执行恢复探针（重建成功后清理），证明可逆性真实存在

## Counterexamples
- 先前结论可廉价逐项复现（如 cherry 分析确证全部无独有内容）且目标为纯机器可再生制品（构建产物、缓存）时，逐棵归档 ref 是过度仪式，直接删即可
- 目标集含 live 现役部署树时，归档不能替代硬排除——必须从目标集中剔除，而不是『删前先存档』
- 单个小范围可逆操作（删一个已知 tmp 目录）不需要引入整套复现探针+归档流程
