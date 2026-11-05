---
method_id: verify-target-ownership-foreign-clones-under-convention-dirs-7d7817587c3d
name: verify-target-ownership-foreign-clones-under-convention-dirs
description: 批量删除按路径惯例命名的目录（.worktrees/.releases 残留等）时，标签隐含的『本仓库派生物』只是假设：先做一跳归属探针（.git 是文件还是目录、remote 指向谁、dirty 与否），把目标分四类各用各的判据——本仓库派生看 ref 可达+干净；外部克隆按宇宙唯一副本处理（对比其 upstream，删前归档 tracked.diff+untracked.tgz+HEAD+status，而不是在本仓库固化为 branch/tag）；bare 镜像对账 refs 在主仓库可达性，dangling 只在 commit 级（WIP 类人类工作）做保留或显式声明真实损失，不做逐对象全量在场枚举；无 .git 普通目录查可再生性与活动 consumer。备份脚本先 dry-run 再执行，删后对账计数并抽验归档可还原。
aliases: 删 worktrees 前先确认是不是本仓库的, worktrees 目录里混着别的项目的克隆, 删目录前先看 remote 指向谁, 外部克隆当 worktree 删会丢未提交代码, 删 bare 镜像前处理 dangling 对象, 按路径惯例清理先验身份
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:dc65c21c-3531-46e5-a85e-a6b3e5e358a7:1043:d3e0ca4eed22fb39732a
evidence_refs: learning:learn:5d8c9dd8dd75
created_at: 2026-11-05T17:21:01.500831+08:00
updated_at: 2026-11-05T17:21:01.500831+08:00
---
## Trigger
用户按本地路径惯例（『未注册 .worktrees 条目』『残留 .releases 目录』等）下达批量删除令，标签隐含目标是本仓库的可再生派生物；清理名单里混着多种条目类型（本仓库 checkout、外部克隆、bare 镜像、无 .git 普通目录）。

## Discriminator
首轮盘点即暴露的归属事实：目标目录的 .git 是完整目录而非 gitfile 指针、git remote -v 指向另一项目、status 带 M/?? 未提交改动、bare 库 fsck 出现 dangling commit（如 WIP on main）。任一事实即宣告本仓库谓词（ref 可达、worktree 注册、status 干净）对该目标不适用，必须换判据：外部克隆的 dirty 内容按全宇宙唯一副本对待。

## Short path
- 一次盘点同时取文件系统清单与权威注册表，并对每个目标做归属探针：.git 文件or目录、remote 指向、dirty 状态。未知量：每个目标落在哪个谓词宇宙。
- 本仓库派生（HEAD 是本仓库 commit、干净、ref 可达）→ 安全删，不追加多余检查。
- 外部克隆 + dirty → 与该项目本地 upstream 对比确认改动未合入；删前归档 tracked.diff + untracked.tgz + HEAD + status，不要试图在本仓库固化为 branch/tag。
- bare 镜像 → 与主仓库做 refs 可达性对账（missing 应为 0）；对 dangling 只在 commit 级决定保留（KB 级 pack 全保）或显式声明损失，不做逐 blob 全量在场枚举；sha 清单只是审计痕迹不是备份。
- 无 .git 普通目录 → 查内容可再生性与活动 consumer（进程/服务）再删。
- 备份脚本先 dry-run、核对 7 目标全在场再 DRY_RUN=0 执行；删后对账目录计数、注册表计数与服务存活，抽验归档可解包。

## Stop conditions
- 每个目标已归入某一谓词类，其独有内容要么已验证备份（归档条目数>0 且可解包还原），要么已向用户显式声明接受真实损失。
- 受保护面（注册 worktree、回滚/恢复所需目录）计数与删前一致，服务/进程不受影响。

## Verification
- tar -t / diff 行数核对备份非空且含预期文件（新增未跟踪源文件确实在 tgz 内）。
- 删后目录计数、registered worktree 数、关键服务存活与删前一致。
- bare 库类：主仓库 refs 对账 missing=0；被保留与被放弃的 dangling 各有清单可审计。

## Counterexamples
- 全部目标都是本仓库注册 worktree 且干净、commit 可达 → 注册表直判安全删，归属探针不增加信息。
- 外部克隆但工作树干净且 HEAD 等于其 upstream 某 ref → 可由 upstream 重建，diff 备份非必需。
- 无 .git 的小目录其实是运行中服务的活跃状态存储 → 『小且无 .git』不等于可再生，必须先查 consumer/进程。
- dangling 全是自动产物 blob 且主仓库已有 → 不需要仪式性逐对象枚举与损失声明。
