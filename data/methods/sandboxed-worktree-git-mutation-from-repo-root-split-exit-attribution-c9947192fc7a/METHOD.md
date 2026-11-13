---
method_id: sandboxed-worktree-git-mutation-from-repo-root-split-exit-attribution-c9947192fc7a
name: sandboxed-worktree-git-mutation-from-repo-root-split-exit-attribution
description: 在 OS 级写沙箱（仅授工作区/缓存目录写权）下的 linked worktree 中，git 有状态变更的真实写目标是主仓 .git/worktrees/<id>/index.lock，常落在授权集之外：worktree 内落盘文件成功、git add 却报 Operation not permitted。若再把 add+commit+检查器串进一条 && 链，标签变量会把 git 的 128 短路透传成『检查器退出码』。做法：git 变更单独执行且 workdir 设为主仓根、用 git -C 寻址 worktree；机械检查器独立调用取自身退出码；失败只按 stderr 签名归因（fatal index.lock = git 写授权问题，128 = git fatal），不把链上标签值当检查器证据。
aliases: worktree 里 git commit 报 Operation not permitted 怎么修, 沙箱环境 git add 拿不到 index.lock 写权限, 链式命令失败后退出码该归谁, 检查器退出码是被前面命令短路顶掉的吗, 主仓根目录下用 git -C 操作 worktree, linked worktree 提交被 macOS 沙箱拦
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6440599a-8f63-45ea-9205-23f2ceead498:0:3213790e64d4e65c35ab
evidence_refs: learning:learn:15278b73c2e2
created_at: 2026-11-13T09:22:01.164799+08:00
updated_at: 2026-11-13T09:22:01.164799+08:00
---
## Trigger
在带 OS 级写沙箱（每条命令回执横幅注明『仅允许写工作区与缓存目录』之类）的 shell 执行环境中，于 linked worktree（cwd 形如 <主仓>/.worktrees/<id>）执行有状态 git 变更（add/commit），且任务要求汇报某个机械检查器的真实退出码。

## Discriminator
决策时刻已可见的事实组合：每条回执的沙箱横幅 + cwd 是 linked worktree 路径（其 git 元数据必然在主仓 .git/worktrees/<id>/ 而非 worktree 内）；同一沙箱下 worktree 内 heredoc 建文件成功，而 git add 报 fatal: Unable to create '<主仓>/.git/worktrees/<id>/index.lock': Operation not permitted、退出码 128（git fatal 特征，Python 检查器通常退出 1/2）。这一『文件写成功、git 写失败』的不对称当场判定为写授权范围问题而非检查器问题；链上打印的 checker_exit=128 是 && 短路透传，检查器进程从未启动。

## Short path
- 发命令前从回执横幅+cwd 判定：linked worktree 下且沙箱仅授工作区/缓存写权 → 先 git rev-parse --git-dir 确认真实 git 元数据位置（应指向主仓 .git/worktrees/<id>/）
- git 变更单独成一条命令执行，workdir 设为主仓根并用 git -C <worktree> 寻址，使 index.lock 写入落在授权集内；失败时仅按 stderr 签名归因（fatal index.lock EPERM = git 写授权），不重跑任何检查器
- 提交成功后，机械检查器独立一条命令运行，其退出码即真实退出码；HEAD 前移、porcelain 干净作为提交成功证据
- 其余核验（diff --check / numstat / name-status / status）保持只读，随后或并行执行
- 汇报时逐项绑定『该命令自己』的退出码与输出，明确披露中途失败与恢复路径

## Stop conditions
- git 变更已成功提交（HEAD 前移、git status --porcelain 为空），且检查器以独立调用取得自身真实退出码并全部核验只读完成
- 若在 worktree cwd 下 git add 本就成功（普通 checkout，或沙箱授予整仓写权），跳过换 workdir 步骤，直接独立运行检查器

## Verification
- git rev-parse --git-dir 输出指向主仓 .git/worktrees/<id>/，据此选择 workdir 而非盲试
- 每个被汇报的退出码绑定其所属命令：独立调用，或链内紧邻捕获（cmd; echo x=$?），并与 stderr 签名互证（fatal/128 = git；Python 检查器通常小整数退出）
- 失败后核对 HEAD 未前移、目标文件仍为 ?? 未跟踪，证明提交未发生、链上检查器从未运行

## Counterexamples
- 普通（非 linked）checkout：.git 就在 cwd 下，链式 add+commit+check 可一次通过，换 workdir 纯属多余
- 沙箱策略本身授予整个主仓根写权（与 cwd 无关）时，git add 不会失败，无需变更执行方式
- 链路用分号分隔且每步紧跟独立退出码捕获（或每步单独调用）时，归因无损，无需强制拆分命令
- 只读 git 命令（status/diff/log）永不触发 index.lock 写，拆分它们只有开销
- 若失败签名来自检查器自身（其错误文本与小整数退出码），应归因于检查器内容，而非链路或沙箱
