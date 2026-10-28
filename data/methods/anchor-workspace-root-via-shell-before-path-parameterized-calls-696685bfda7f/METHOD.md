---
method_id: anchor-workspace-root-via-shell-before-path-parameterized-calls-696685bfda7f
name: anchor-workspace-root-via-shell-before-path-parameterized-calls
description: 新会话或检出位置未验证时，发起带绝对 workdir/路径参数的调用前，先跑一条廉价锚定命令（pwd && git rev-parse --show-toplevel）确立真实仓库根。收到确定性的『workdir 不是有效目录』参数错误回执时，把未知量收窄为『真实根是什么』并用 shell 回执解析，而不是猜测路径变体、继续范围不明的其他调用、或用裸 find 全盘枚举；仓库含 .releases/快照、__pycache__ 等目录时，定位文件用 git ls-files pathspec 代替 find，避免被快照副本淹没（本集 find 输出 960 行噪声，真值仅数行）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:78fffae1-3786-4a53-9158-71e2847e5ab7:1254:eb925f0eabf2b8644ae6
evidence_refs: learning:learn:e411fcc549b6
created_at: 2026-10-17T01:18:32.525987+08:00
updated_at: 2026-10-17T01:18:32.525987+08:00
---
## Trigger
会话开始或环境/检出位置未知（新镜像、迁移后），即将发起首个带绝对 workdir/路径参数的工具调用（goal 执行、文件读写、grep），且本会话尚无任何已验证路径事实——无 pwd 输出、无 git toplevel 回执、无带路径校验标记（如 workspace_path_state=current_match）的工具回执。

## Discriminator
工具回执是确定性参数错误（明确指出『workdir 不是有效目录: <路径>』），而非超时/权限类瞬时故障——回执类型本身就把未知量缩成『真实根路径是什么』，而 shell 自身的 pwd / git rev-parse --show-toplevel 一条命令即给出权威答案，无需枚举路径候选。

## Short path
- 首个文件系统动作前（或收到 invalid-directory 回执后立即）跑 pwd && git rev-parse --show-toplevel，确立权威根路径
- 以验证根替换所有后续 workdir/绝对路径参数；不重试路径变体、不在范围不明时继续其他文件类调用
- 仓内定位文件用 git ls-files '<pathspec>'（走 git 索引），不用裸 find；仅在非 git 环境退化为 find -prune 剪掉快照目录
- 路径层未知量闭合后回到原任务（读 SoT 结构、写规则/技能、跑同步测试）
- 以验证根发起的下一个调用返回 success 即确认锚定有效，停止路径层操作

## Stop conditions
- pwd/git toplevel 已给出真实根，且以该根发起的下一个 workdir 调用返回 success
- 工具回执自带路径校验标记（如 workspace_path_state=current_match）确认路径有效
- 失败回执属瞬时故障（超时/限流/网络）而非 invalid-directory 时，走故障重试路径而非重新锚定

## Verification
- 解析出的根包含预期仓库标记：git toplevel 正常返回、目标 SoT 文件（如 docs/ai_rules.md）在该根下存在
- 文件定位结果来自 git 索引（tracked 文件），而非 .releases/__pycache__ 快照副本
- 后续不再出现同类 invalid-directory 参数错误

## Counterexamples
- 会话已有先前 pwd 输出或带路径校验的回执时，无需重复锚定，直接复用已验证路径（重复 pwd 属无信息动作）
- 失败回执是超时/网络/权限类瞬时错误时，锚定无益，应按故障处理规则重试原调用
- 非 git 仓库（普通目录树）中 git ls-files/toplevel 不可用，应退化为 find 并显式 -prune 掉备份/快照目录
- 工具环境为每次调用独立沙箱、shell 概念不成立时，锚点应改用该工具自身的目录列举/路径校验原语，而非 shell 命令
