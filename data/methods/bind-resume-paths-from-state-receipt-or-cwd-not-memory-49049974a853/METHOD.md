---
method_id: bind-resume-paths-from-state-receipt-or-cwd-not-memory-49049974a853
name: bind-resume-paths-from-state-receipt-or-cwd-not-memory
description: 续跑/多目标会话中，workdir/仓库根/worktree 等路径参数不由记忆拼出：协调与任务状态回执自带权威 workspace 字段，shell cwd 可零成本实测。本集首个带路径调用填了记忆里的 ~/Desktop/lfl-agent（旧机用户目录）被拒『workdir 不是有效目录』（尽管同回合刚自宣『先恢复状态、不凭记忆推进』），随后用 Desktop 列表+全 home 的 find 宽枚举重定位；而 task-state 回执的 workspace 字段与一行 pwd 已唯一确定工作区。方法：把路径当运行时未知量，先从状态回执或 cwd 解出再绑定；invalid-path 参数错误只做一次有界重定位，不扫全盘。
aliases: workdir 不是有效目录 怎么办, 续跑别凭记忆填路径, workspace 字段拿工作区, 恢复会话找错仓库目录, 记忆路径被工具拒了先读状态
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:2489:2611097cb52f1ddf9951
evidence_refs: learning:learn:415221cef5ff
created_at: 2026-11-08T21:33:59.888884+08:00
updated_at: 2026-11-08T21:33:59.888884+08:00
---
## Trigger
会话续跑或恢复执行（如『按你的建议执行』类极简指令）后，需要发起带 workdir/绝对路径参数的工具调用，而路径未由用户本轮指令显式给出

## Discriminator
协调/任务状态回执携带权威 workspace 字段（本集 task-state 明示 workspace=<repo 绝对路径>），且当前 shell cwd 可零成本实测；被拒回执『[参数错误] workdir 不是有效目录』是纯参数事实错误，不含权限或内容语义

## Short path
- 免路径的状态读取（goal/task state）恢复目标清单与 workspace 字段；未知量：权威工作区与在途任务
- 后续所有调用的 workdir 绑定该字段或实测 pwd；worktree 路径取自 checkpoint/brief，并用 git status 验证其存在
- git status 锚定 HEAD/lane 后直接进入任务上下文检索（brief/design grep）
- 若路径仍被拒 invalid-path：一次有界重定位（pwd、git rev-parse --show-toplevel、ls 回执提及的父目录），命中即停，不做全 home 枚举

## Stop conditions
- 所有带路径调用均绑定回执 workspace 或实测 cwd，且首个此类调用成功
- git status 显示的分支/worktree 与 checkpoint/brief 一致后，立即停止路径发现

## Verification
- 首个 workdir 绑定调用成功，且其输出 cwd 头与 task-state 的 workspace 字段一致
- invalid-path 恢复过程未产生 ls ~ 或全 home find 类宽枚举

## Counterexamples
- 回执 workspace 已过期（仓库被移动/重命名）时，回执值同样报 invalid-path，此时有界 pwd/git rev-parse 发现才正当
- 用户本轮指令显式给出路径时以用户路径为准，无需回读状态
- 目标是远程主机（如 deepin）上的路径，本地会话回执不覆盖
- 全新会话无任何状态回执时，pwd/git 发现本身就是第一步，不存在『记忆 vs 回执』之争
