---
method_id: prewrite-recheck-then-block-on-live-concurrent-writer-b4ba8fd4b5e3
name: prewrite-recheck-then-block-on-live-concurrent-writer
description: 独占写授权任务里『开工核查 clean』不等于『写时仍 clean』。首次 edit/commit 前必须重跑 git status 对照任务指定文件清单，并用早前 read 回执的内容身份（version_token/sha、read 与 fresh grep 同区间矛盾）核对磁盘现状；一旦发现目标文件被改且指向活跃并发写者，第一未知量从『我该写什么』切换为『谁在写』：停止一切写（含 stash/reset——会毁掉在途工作），用 action_trace/mtime 定位写者，对其发 block 请求并把裁决选项交还用户。本集据此停笔上报，避免与另一会话 277 行同任务改动交错损坏。
aliases: worktree被别的会话改了, 两个agent写同一个文件, 写前再查一次git status, 读的代码和grep对不上, 唯一代理撞上并发写, 别的会话在改我的worktree
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:931d4383-f8bd-4f91-84bd-5d59d551c8ba:0:563b1cd80ceaaa8580d1
evidence_refs: learning:learn:ab6729f5890e
created_at: 2026-11-13T11:18:33.477544+08:00
updated_at: 2026-11-13T11:18:33.477544+08:00
---
## Trigger
任务书授予独占写授权（如『唯一开发代理』、指定 worktree/branch 与 base/tree），开工状态核查已通过、即将进行首次 edit/commit；或执行中出现『自己刚读过的目标文件区间内容与 fresh grep/重读不一致』的可观察矛盾。

## Discriminator
写入前重跑 git status --porcelain 对照任务文件清单，或用早前 read 回执的 version_token/sha 与当前磁盘核对：早前 verified-clean 的 worktree 现在出现目标文件的未提交修改，或同一文件同一区间两次读取内容矛盾；再以事件流 action_trace 中其他会话的 edit_file 记录 + 文件 mtime，把假设从『我的读取缓存过期/该开始写了』收敛为『存在活跃并发写者』。

## Short path
- 开工照常验证 worktree/branch/base/tree/remote（本集 11:07 已验证 clean）
- 首次 edit/commit 前执行廉价 pre-write gate：git status --porcelain 对照任务指定文件清单，clean 才允许进入写入
- 发现目标文件 dirty 或 read/grep 同区间矛盾时，把第一未知量切换为『谁在写』：查 action_trace 其他会话的 edit_file、文件 mtime，必要时 git show HEAD:<file> 判别改动是否属 base
- 确认另一活跃会话正在写同任务文件面：对目标 worktree 零写（不 stash、不 reset、不 checkout），向对方发 block 类 help_request 并保存本会话任务状态
- 向用户报告冲突事实并给出裁决选项（对方继续我退出 / 终止对方我接管 / 核实对方死活），裁决前不再有任何写动作

## Stop conditions
- pre-write gate clean 且无并发写证据：正常进入实现流程
- 并发写者已确认且已 block + 上报：停止一切写动作，等待用户裁决

## Verification
- 冲突报告中每个断言都有回执支撑：早期 clean 的 status、后期 dirty 的 status/diff --stat、action_trace 编辑记录与 mtime
- 本会话写副作用为零：git status 无本会话产生的新变更、无 commit/push、目标文件 mtime 未因本会话变动

## Counterexamples
- worktree 上的 dirty 是与本任务文件面无关的改动（用户实验代码、构建产物）：记录基线并绕开，不必阻塞整个任务
- 任务一开始就声明 worktree 带在途修改并授权基于现状继续：pre-write gate 只需固化基线快照，不构成冲突
- 内容矛盾最终归因于工具快照缓存（version_token 与 stat 不符）：先按缓存失效重读，不要直接指控并发写者
- 对方会话已证实终止且无人认领其半成品：是否接管/重写仍属用户授权裁决，不因『改动方向正确』而自行续写
