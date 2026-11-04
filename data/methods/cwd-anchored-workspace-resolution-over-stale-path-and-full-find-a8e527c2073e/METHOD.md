---
method_id: cwd-anchored-workspace-resolution-over-stale-path-and-full-find-a8e527c2073e
name: cwd-anchored-workspace-resolution-over-stale-path-and-full-find
description: 任务以隐式指称（『这 5 个文件』『本仓库』）下达且未给绝对路径时，把进程 cwd 当第一锚点：第一条命令直接在原地跑 `git rev-parse --show-toplevel && git status --porcelain`，一次同时解析『工作区在哪』与『哪些文件在变更』两个未知量。凭记忆写出的绝对路径只是待验假设：cd 报 ENOENT 即弃，不换命令在同一路径重试，更不把恢复升级成按记忆名字做全盘 find——pwd 已给出候选仓库，而以被证伪的目录名当搜索键注定落空。记忆路径的用户名段与真实用户不符、仓库名与记忆名不同，都是跨会话/跨机器陈旧记忆的强信号。工作区正确性用内容级验证收口：用户声明的文件清单是否恰好出现在 status 中。
aliases: cd no such file or directory 找不到仓库, 先 pwd 再操作 git, 记错的工作区绝对路径怎么纠正, 不要全盘 find 找项目目录, 当前目录就是项目仓库吗, 跨会话记错的仓库路径
status: candidate
source_model: deepseek/deepseek-flash
source_episode_refs: episode:4aea0dd4-3b3b-4874-8090-870678230df3:1132:36ce58ceb9c5df93bff6
evidence_refs: learning:learn:04385bd17001
created_at: 2026-11-03T15:46:35.866432+08:00
updated_at: 2026-11-03T15:46:35.866432+08:00
---
## Trigger
任务隐式指称某个工作区/仓库（『这些文件』『本仓库』）且未附绝对路径，需立即执行 git/文件操作；或凭记忆/惯例的绝对路径 cd 失败（No such file or directory），需要恢复定位。

## Discriminator
三条当时即可观察的事实把候选空间缩到一两个：(1) cd 的 ENOENT 是确定性失败，同一路径换命令重试必再失败；(2) pwd 回执显示 cwd 本身就是候选项目仓（<真实user>/Project/<repo>），外部搜索多余；(3) 记忆路径的 /Users/<name> 段与真实用户名不一致、且实际仓库名与记忆名完全不同 → 记忆来自别的会话/机器，按记忆名 find / 是在追逐已死假设。

## Short path
- 首个命令在 cwd 原地执行 `git rev-parse --show-toplevel && git status --porcelain`，一次解析『工作区在哪 + 哪些文件在变更』两个未知量
- 把 status 输出与用户声明的文件清单比对：声明的 N 个文件全部出现（本集 5/5）→ 锚定完成且内容级验证通过
- 记忆中的绝对路径仅作待验假设：一次 ENOENT 即弃，不在同一路径上重复命令，也不以该记忆名做文件系统搜索
- 锚定后进入正常流程：精确 add 未暂存文件、逐文件 diff 审查、提交

## Stop conditions
- 声明的文件清单已全部出现在 status → 工作区未知量关闭，停止一切路径搜索与枚举
- git rev-parse 在 cwd 失败（cwd 不是 git 仓）或 status 与声明清单不符 → cwd 锚点证伪，此时才升级为有界发现（先 ~、~/Project 等常见根，而非全盘 find）

## Verification
- toplevel 路径下 `git status --porcelain` 恰含用户声明的全部文件（数量与路径双匹配）
- 记忆路径与真实环境三重比对：用户名段、仓库名、目录存在性——任一不符即判陈旧记忆并整体弃用

## Counterexamples
- cwd 被刻意设在无关 scratch/隔离目录（本集真实存在同族的 workspace、wip-quarantine 目录），cwd 锚点会给出错误仓库：此时必须改用任务文本、回执 runtime_root 等显式 provenance，不能停在 cwd
- 用户消息已显式给出绝对路径 → 直接信任并使用，无需 pwd 先行或另行验证
- 目标仓库确与 cwd 无关且无任何 provenance → 有界目录发现是合法手段，但先限定在 ~、Project 等常见根，而非 maxdepth 6 的全盘 find
