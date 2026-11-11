---
method_id: post-deploy-workdir-drift-silent-schedule-noop-96360d14d335
name: post-deploy-workdir-drift-silent-schedule-noop
description: 周期定时任务静默空跑（无报错、无产物，但 store 里触发时间已推进）且近期部署把执行根切到 release 目录时，不要从家目录/内容搜索做宽枚举：直接读 runtime_root/data 的排程 store 与审计降级事件做三方对撞（store 状态字段、degraded_to_notify 的命名 reason、期望产物目录），再把条目钉死的 wake_workdir 与交付进程的 code_root/workspace_root（开局状态快照已同时给出两条路径）并排比对，路径身份比对失败即根因。与生命周期追踪类方法互补：那张定失败层级，这张定部署换根后的路径身份根因。
aliases: 定时任务没跑是不是发版换目录导致的, 定时发表文章静默失败怎么查, 发版后定时任务空跑排查, schedule 触发了但没执行, wake_workdir 和交付目录对不上, 排程降级 工作目录不一致
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:9eecb62d-2512-4672-8ab8-7d335dfa7967:0:906a70807f5daa69f42a
evidence_refs: learning:learn:e00d4243bb57
created_at: 2026-11-11T11:01:24.815200+08:00
updated_at: 2026-11-11T11:01:24.815200+08:00
---
## Trigger
周期性定时任务被指未执行/无产物，且开局状态快照已显示 code_root 与 runtime_root 分叉（部署切到 .releases/… 之类的执行根），或审计降级 reason 命名『工作目录与授权时不一致』一类路径身份失败

## Discriminator
已取到的部署/服务状态同时给出 code_root（release 目录）与 runtime_root（项目根）两条不同路径，而排程 store 条目把 wake_workdir 钉死其中之一。这两条已见事实在任何文件系统枚举之前就足以把候选从『全盘找证据』缩成『触发了但准入层路径比对失败』：两个路径加一条比对判据

## Short path
- 快照归层：pending_actions=0 且运行时健康 → 失败锁定在触发→run 交接层；下一跳是全局审计流与排程 store，不是文件系统枚举
- 直读 runtime_root/data 下的排程 store（如 schedule.json），逐条看 trigger_at 是否推进、count/delivery/retry——一次读取回答『触没触发』
- 查审计 action_trace 触发时刻的降级事件取命名 reason；reason 指向 workdir/授权不一致时，把条目 wake_workdir 与部署状态里的 code_root/workspace_root 并排比对
- 用期望产物目录做地面真值：最新产物停在部署切换时刻之前，即坐实空跑起点与断点时间
- 根因落定后给用户带取舍的选项：按交付方当前 workspace_root 重签排程（cancel+新建，注意工具只能钉当前会话工作区）/ 改等价判据发版 / 手工补跑，并预告下一次触发仍会失败的时间点

## Stop conditions
- 根因表达为一对具体路径 + 一条拒绝执行的比对判据，且断点时间与部署事件吻合
- 已预告下一次触发时间的成败风险，处置选项已交用户决定

## Verification
- 重签后的排程在下一次触发真实通过准入并产出当日产物——不能凭推断宣布修复，要实测一次
- 或等价判据（release 根≈runtime 根）发布后有单测/实测证据
- 产物目录重新出现当日条目

## Counterexamples
- 排程根本没触发（trigger_at 未推进、审计无降级事件）→ 问题在调度器/唤醒层，路径比对无关
- 部署未改变执行根（code_root==runtime_root）→ 静默空跑更可能是共享授权/槽位竞争，应走生命周期追踪类方法而非本卡
- 任务其实有产物只是用户没看到 → 先核产物位置与通知链，不要按空跑排查
