---
method_id: anchor-declared-worktree-root-before-commands-695487311c0e
name: anchor-declared-worktree-root-before-commands
description: 在多 worktree 仓库中恢复一个已有冻结计划的会话任务时（PLAN/PROTOCOL 已落盘于特定 worktree）：第一条仓库命令就用 `cd <工作根> && …` 锚定到该 worktree，而不是在默认 cwd 失败后再枚举全部 worktree；且在首次启动复用的 runner/worker 前，用一次存在性检查确认其源码显式引用的 gitignored 运行时资产（如 data/ 下文件）确实存在于当前 checkout——新建 worktree 不会自动带上被 ignore 的文件。把『在哪个 checkout 工作』和『运行前提是否在该 checkout 内齐备』这两个未知量提前各用一条命令解决。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:257:6d33ca9abea60c0bbee0
evidence_refs: learning:learn:457853ba0ca5
created_at: 2026-09-17T23:21:58.351246+00:00
updated_at: 2026-09-17T23:21:58.351246+00:00
---
## Trigger
多 worktree 仓库中恢复/继续会话任务：任务工件（冻结 plan/protocol、前次 commit）位于某个特定 worktree，且接下来要执行 git 命令或复用既有 runner/worker 启动真实运行。

## Discriminator
进入扩散前已可见的事实：失败命令自身的输出显示 cwd 落在主 checkout 的无关分支，而会话内先前的 commit/工件路径已把任务工作根钉在一个具名 worktree；且被复用契约的源码在读取时就显式引用了 repo 根下的运行时资产路径（如 PROVIDERS = REPO/'data'/providers.json）。这三点当时就足以把下一步从『枚举所有 worktree / 直接开跑』缩为『cd 到声明根 + 预检资产存在』。

## Short path
- 从恢复上下文（checkpoint/goal/已落盘 plan 的路径）确定声明的工作根 worktree；未知量：该根下已落地什么、还缺什么。
- 第一条仓库命令即 `cd <工作根> && git log -3 && git status -sb`，一次取得任务分支状态；不在默认 cwd 先试探失败。
- 只读冻结 PLAN/PROTOCOL 点名的复用契约文件（fixture、worker、既有 runner）；未知量：复用什么、改什么。
- 实现后先跑 fixture 自检与无模型 dry-judge 门；全过才允许进入 measured run。
- 启动前一条存在性检查：复用契约引用的 gitignored 运行时资产是否存在于本 checkout；缺失则先补齐或加受控回退，再启动。
- measured run 在正确 checkout 内启动（输出转日志）即停止发现，等待收割。

## Stop conditions
- 任务 worktree 内最新 commit 与冻结 plan 对齐，无未预期脏文件
- 自检与 dry-judge 门全部通过，且运行前提资产已确认存在或有回退
- measured run 已在声明工作根内启动，不再追加环境探查

## Verification
- 每条 git/运行命令的输出分支名与路径均属于任务 worktree，而非主 checkout
- fixture 自检 + dry-judge 在新 checkout 内全 PASS 后才启动 measured run
- 复用契约引用的每个 repo 根运行时资产在当前 checkout 内存在或已有受控回退

## Counterexamples
- 单 checkout 简单仓库，默认 cwd 即任务根：锚定与预检是多余开销，直接执行即可。
- 任务目标本身就是盘点/清理多个 worktree：全量 `git worktree list` 是目标动作而非搜索扩散，本方法不适用。
- 复用契约引用的资产受版本控制或由 runner 自己生成：无需预检存在性，直接运行。
