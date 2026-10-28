---
method_id: match-git-add-mode-to-status-change-class-ee1d2bb36f21
name: match-git-add-mode-to-status-change-class
description: 分批提交时，staging 命令的形式应匹配 status 回执里已可见的变更类别：目标组全部是已跟踪文件的修改（porcelain 全为 M/D、无 ??）时，直接 `git add -u <pathspec>`；含未跟踪新文件时才用显式路径 add。目录级 `git add <dir>` 会尝试纳入未跟踪路径，在『目录整体被 .gitignore、内部个别文件仍处已跟踪状态』的常见状态目录（usage/telemetry/experiences 类记录）上必然 exit 1。判别标志在任务第一次 status 时就已具备，无需一次试错性失败来发现。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:78fffae1-3786-4a53-9158-71e2847e5ab7:842:d5cc6d9b51011d1b8a8d
evidence_refs: learning:learn:f72aca8b24e7
created_at: 2026-10-16T20:31:16.306360+08:00
updated_at: 2026-10-16T20:31:16.306360+08:00
---
## Trigger
分批/分组 git 提交任务中，已通过 git status（porcelain）拿到目标组每个路径的变更标志，正要为其中一组执行 staging；尤其当组内路径包含 usage/telemetry/状态记录类目录。

## Discriminator
status 回执显示该组所有条目均为已跟踪变更标志（` M`/`M `），且组内没有任何 `??` 未跟踪条目。这一事实在第一次 status 时即可见：本组的 staging 语义就是『只暂存已跟踪文件的修改』，`git add -u <pathspec>` 是既正确又不会触碰未跟踪/忽略路径的形式；而目录级 `git add <dir>` 会尝试纳入未跟踪文件，在『目录被 ignore 但内部仍有已跟踪文件』的布局上必然失败。

## Short path
- 读第一次 status porcelain，把每组按变更类别二分：全 tracked-modified vs 含 untracked-new
- 全 tracked-modified 的组直接 `git add -u <该组 pathspec>` 并提交，一步到位，不再触发 ignored 目录失败
- 含未跟踪新文件的组用显式文件路径 add（`-u` 会漏掉新文件），再提交
- 提交回执核对文件数与 status 推导条目一一对应、工作区 porcelain 变空即停

## Stop conditions
- 该组 commit 回执的文件清单与 status 推导的条目完全一致（无多余、无遗漏）
- 工作区 porcelain 为空，且没有为绕过 ignore 报错而使用 `git add -f`
- 发现组内确有需要新增的未跟踪文件时，退出本方法，改用显式路径 add

## Verification
- add 之后用 `git diff --cached --name-only`（或提交回执的文件清单）与计划清单逐项比对
- 若出现过 'paths are ignored' 报错，确认最终提交只含已跟踪文件的修改，未强加任何被忽略的新文件

## Counterexamples
- 组内包含必须新增的未跟踪文件（新模块/新测试/新脚本）：`git add -u` 会静默跳过它们，必须显式点名路径
- 目标路径下文件全部是未跟踪且被 ignore（纯本地缓存/临时产物）：add 的 ignore 报错是正确防线，应把该路径移出提交范围，而非换 `-u` 或加 `-f` 绕过
- 尚未拿到 status 回执、变更类别未知时：先跑一次 porcelain 再选命令，不要凭上轮记忆假设分组仍准确
