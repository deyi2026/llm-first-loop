---
method_id: isolate-via-linked-worktree-when-dirty-state-disjoint-and-foreign-0b5a33f42326
name: isolate-via-linked-worktree-when-dirty-state-disjoint-and-foreign
description: 共享 git 工作区存在未提交改动，但其文件集与本任务目标提交的文件集不相交且归属不确定时，不要把'消化这些改动'（stash / switch 回切 / restore）纳入任务路径。stash 是有损操作，可能把并行会话的活 WIP 收进 stash 成为唯一副本；switch 回切会覆盖正在进行的写入并直接失败。应改用 git worktree add 从权威基线引用直接建任务分支，cherry-pick、定向测试、提交、开 PR 全部在隔离区完成，共享区零 mutation，事后无需协调待办。适用于拆 PR、验证单个提交等只需要'干净基线 + 已知提交'的任务。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5e09cedf-9412-454e-b7a9-f0247530ef7c:199:5d639989c00201273429
evidence_refs: learning:learn:ade3dcd5fe35
created_at: 2026-09-22T17:39:01.377940+00:00
updated_at: 2026-09-22T17:39:01.377940+00:00
---
## Trigger
要在 git 仓库中从干净基线拆分支 / cherry-pick / 跑定向测试时，git status 显示脏文件，且 git show <目标提交> --stat 的文件集与脏文件集不相交；或分支表显示多个 linked worktrees（多会话共用主工作区的使用模式），脏改动归属不明。

## Discriminator
动手前即可获得的两条事实：(1) 目标提交文件集 ∩ 脏文件集 = ∅——脏状态与本任务无因果关系，任何 stash/switch 对本任务只有风险没有收益；(2) 仓库已有多 worktree 并用迹象或脏文件 mtime 新鲜——归属不确定，可能是并行会话的活 WIP 而非静态遗留。二者合起来把'如何处理脏状态'的多条路线缩成一条：根本不处理，侧向隔离。

## Short path
- 求交集并判归属：对比 git status 脏文件集与目标提交 --stat 文件集；结合 branch -vv 的 linked worktree 标记与脏文件 mtime 新鲜度，判定脏状态是否与本任务相关、是否可能活着（未知量：这些改动是谁的、要不要碰）
- 交集为空且归属不确定 → 不 stash、不 switch，直接 git worktree add <path> -b <task-branch> <权威基线引用>，获得零污染任务环境（未知量：如何拿到干净基线而不触碰共享区）
- 隔离区内 cherry-pick 目标提交，git diff 对照原提交验证无损落地（未知量：移植是否逐字节一致）
- 跑定向测试前确认 pytest rootdir/pythonpath 相对解析（隔离区测的就是隔离区代码），取回执（未知量：新基线上测试是否成立）
- 写报告、只 add 自己的文件、push、开 PR；结束时复查共享区 git status 与进入时一致，全程对共享区零 mutation（未知量：是否留下协调债务——答案应为无）

## Stop conditions
- 目标提交在隔离分支无损落地（diff 为空）+ 定向测试回执与提交声明一致 + PR 打开且 MERGEABLE
- 发现脏文件与任务文件集有交集 → 停止隔离路线，先在原地弄清脏改动的内容与归属
- 隔离区测试环境不等价（依赖共享绝对路径/数据目录）且无法验证 → 改走协调方案，不在隔离区硬跑出不可信回执

## Verification
- git diff <原提交> <cherry-pick 结果> -- <目标文件> 为空，证明移植无损
- 测试命令在隔离区执行且回执路径指向隔离区，而非共享工作区
- 结束时 git status（共享区）显示他人脏文件集合的数量与文件名未被自己改变；若此前已误 stash 他人 WIP，保留 stash 并在交付说明中显式标注，绝不 drop

## Counterexamples
- 脏文件与任务文件集重叠（目标文件本身被改）：隔离会丢弃必要改动或导致 cherry-pick 冲突，必须先在原地理解并收编脏状态
- 单会话独占工作区且确认是自己的静态遗留 WIP：stash + switch 更省事，新建 worktree 属于过度工程
- 测试/构建链依赖共享工作区的绝对路径或共享数据目录，隔离等价性未验证：隔离区结果不可信
- 目标提交依赖实验分支上的兄弟提交，无法在干净基线独立落地：需先解决依赖集，隔离本身不解决问题
