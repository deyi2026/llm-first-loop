---
method_id: hoist-sandbox-workdir-to-cover-git-worktree-metadata-writes-3c9c32f723d8
name: hoist-sandbox-workdir-to-cover-git-worktree-metadata-writes
description: 在写受限沙箱（仅允许写 workdir 子树）里对 git linked worktree 执行写操作（merge/checkout/commit）失败，报 cannot lock ref / ORIG_HEAD: Unable to create '<主仓根>/.git/worktrees/<名>/….lock': Operation not permitted。根因是链接 worktree 的 refs/锁元数据写在主仓 .git 下，超出以该 worktree 为 workdir 的写范围。修法：把 workdir 提升到同时覆盖目标 worktree 与主仓 .git 的最小树（通常是仓库根），用 git -C <目标worktree> 保持命令作用对象不变；只读 git 命令无需提升。
aliases: 沙箱里 git 合并报 ORIG_HEAD.lock Operation not permitted, worktree 占用 main 没法 checkout 怎么合并, 链接工作区的锁文件写不进主仓 .git, 从仓库根 git -C 操作 main 专属 worktree, sandbox 写范围盖不住 git 元数据怎么办
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:2ef924ad-22aa-459c-881a-b100534b16c2:379:02ca7d80d2092f1c4d4d
evidence_refs: learning:learn:f0d0546f84ab
created_at: 2026-10-29T14:14:45.203997+08:00
updated_at: 2026-10-29T14:14:45.203997+08:00
---
## Trigger
沙箱 shell 每条回执均声明仅允许写 workdir 子树；对 linked worktree 跑 git 写命令报 Operation not permitted 且失败路径落在主仓 .git/worktrees/ 下的 .lock；或 checkout 报 '<branch>' is already used by worktree at '<path>' 提示仓库存在专属 worktree 布局

## Discriminator
失败回执里被拒创建的锁文件绝对路径本身标出真实写足迹：它位于 repo_root/.git/worktrees/<名>/，在选择为 workdir 的 worktree 子树之外；而此前 git worktree list 已显示主 worktree 在 repo_root（.git 所在地），且每条 shell 回执都印有『仅允许写工作区与缓存目录』。三事实合一即知：workdir 必须提升到覆盖 repo_root/.git，而不是在 worktree 内换姿势重试

## Short path
- checkout 报 branch 被 worktree 占用 → 跑一次只读 git worktree list，确定既有布局：目标 ref 在哪个 worktree、repo_root/.git 在哪里
- 对目标 worktree 做写操作时，若收到指向主仓 .git/worktrees/…/.lock 的 Operation not permitted，从被拒路径推出所需写范围 = 目标 worktree 树 ∪ repo_root/.git
- 把沙箱 workdir 设为覆盖该并集的最小树（一般即仓库根），命令改用 git -C <目标worktree> 原样重发，一次到位
- 用 git -C <目标worktree> rev-parse <目标ref> 与预期 sha 逐字符核对后停止，不迁移主 worktree 的 checkout

## Stop conditions
- 目标 ref 已更新到预期 sha（rev-parse 逐字符一致），合并/提交落定
- 被拒路径所在的主仓 .git 不在沙箱允许写的任何树内 → 停止换 workdir 重试，转申请扩大沙箱范围或换执行面

## Verification
- 原失败命令重跑成功且不再出现 Operation not permitted
- git -C <worktree> rev-parse <ref> 等于预期 sha；git worktree list 显示 ref 按预期移动
- workdir 提升后未引入额外未跟踪文件（写足迹只落在预期 ref/锁与目标树）

## Counterexamples
- 普通 clone / 单 worktree（.git 是树内真实目录）：workdir=该树即可，无需提升；此时同类报错应查文件权限或陈旧锁
- 错误是 '…lock': File exists（崩溃残留的陈旧锁）而非 Operation not permitted：该删锁文件，与 workdir 摆放无关
- 只读命令（status/log/rev-parse/diff）：不取 ref 锁，窄 workdir 直接可用，提升是多余动作
- 沙箱白名单根本不含 repo_root（只放行某个缓存目录）：任何 workdir 选择都无效，重试属浪费，需扩权
