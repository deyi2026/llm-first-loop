---
method_id: authority-rejection-bounds-action-space-operator-menu-preserved-closure-317103054e1b
name: authority-rejection-bounds-action-space-operator-menu-preserved-closure
description: 当本 run 被共享写门上的无主外来资源（如 owner 标识为空的 live lane）阻塞，且自排/重试动作已被回执以命名权限理由拒绝（如『必须未委派真人 ingress』）时，不要继续同姿态重试或被动等待：命名拒绝理由本身就是动作空间边界。先定量阻塞资源成本（ahead 提交数/行数、有无远端副本、owner 身份、空闲时长；不可逆动作前重验现值，不信旧快照），向真人 ingress 提编号决策菜单（等待释放窗口/操作者决定关闭/转交原 owner），每项附成本。简短数字回复按对应菜单项执行并显式说明读法。执行不可逆关闭时保留分支与 worktree，把身份 SHA 与『操作者决定而非证据推断』写入终态理由；阻塞解除后一次性重放被卡链路并在权威远端核验终值。
aliases: 被别人的 lane 卡住 push 怎么办, 无主 lane 挡住入库闸, schedule 被拒无法自排续跑, 委派 run 不能重试时找人拍板, 关别人 lane 前先留 SHA 和分支, 操作者编号菜单 数字短回复怎么读
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:2746:89336b731aa221e367f0
evidence_refs: learning:learn:caeaabaf5920
created_at: 2026-11-11T00:29:44.404938+08:00
updated_at: 2026-11-11T00:29:44.404938+08:00
---
## Trigger
共享写门（推送/入库前置闸）被外来且无主的资源占住，或本 run 的重试/续排动作已被回执以命名权限条件拒绝，且该条件在本 run 能力面内结构上不可满足（委派 run 无法成为未委派真人）。

## Discriminator
拒绝回执里的命名权限条件是否本 run 可自行满足：若否，第二次同姿态重试无信息；再叠加账本事实——阻塞资源 owner_session_id 为空（排除标志不可用）、闸源代码写明的释放条件（转终态或空闲超阈值），动作空间即收缩为『等待窗口』或『真人裁决』两项。

## Short path
- 首次被命名权限理由拒绝后即停止同姿态重试，把理由翻译成动作空间边界（谁能解除阻塞）
- 对阻塞资源做一次成本定量：相对权威 main 的 ahead 提交/文件/行数、远端有无副本、worktree 是否干净、owner 与最后活动时间；不可逆动作前重验现值，不信旧状态快照
- 向真人 ingress 给编号菜单：等释放窗口 / 由操作者决定关闭外来资源 / 转交原 owner，每项附成本与后果
- 简短数字回读作对应菜单项，显式陈述读法与判断归属（操作者决定，非证据推断）
- 执行终态动作时保留可追溯物：不删分支/worktree，身份 SHA 与决策来源写入终态理由
- 阻塞解除后一次性重放被卡链路（原闸重跑至 exit=0 → 审查 → 单步受保护动作），并在权威远端面核验终值

## Stop conditions
- 回执的解决权仍在本 run 能力面内（transient 错误、可自补字段）→ 直接修复，不升级
- 阻塞资源有活跃 owner → 先走 owner 通道或排除标志，不把关闭列入菜单
- 释放窗口临近且等待成本低于打断操作者 → 选等待不出菜单
- 终态动作完成且权威面核验通过 → 停止，不再追加确认

## Verification
- 终态记录包含：资源身份 SHA、保留物路径、决策来源标注
- 原被卡闸以 exit=0 重放成功；最终产物在权威远端核验（如 ls-remote 与本地一致）
- 确认未删除任何可恢复工件（分支、worktree 仍存在，可按 SHA 重开）

## Counterexamples
- 阻塞是 transient（超时/5xx）而非命名权限边界 → 重试仍在动作空间，打断操作者是过早升级
- 阻塞 lane 的 owner_session_id 非空 → 用排除标志或联系 owner，关闭不是首选项
- 资源是本 run 自己名下的 lane → 按自身权限直接收口（配合自有 lane 字节比对/停泊类方法），无需操作者菜单
- 用户已给过明确处置指令 → 不再出菜单，直接执行并留痕
