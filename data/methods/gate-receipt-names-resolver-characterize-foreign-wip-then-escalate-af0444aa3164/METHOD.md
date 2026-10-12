---
method_id: gate-receipt-names-resolver-characterize-foreign-wip-then-escalate-af0444aa3164
name: gate-receipt-names-resolver-characterize-foreign-wip-then-escalate
description: 生命周期控制面动作（restart/publish/update）在绑定期被物理门禁挡下（如 tracked_worktree_dirty）时，失败回执的 problem_kind/next_step 已同时给出两个决定性事实：阻断的不变量、解决权归属。当回执把裁决交给操作者（『程序不 stash/commit/checkout』），且 git 只读检查显示脏改动是并行会话的成体系在途工作（已暂存源码重构+配套测试修改）而非本会话自产垃圾时，动作空间收缩为：只读定性＋快速健康探针＋并行证据＋按所有者裁决分支上报选项；绝不自行 stash/commit/revert，也不对物理门禁 override。failed 动作无 lease 残留，可被新动作接管。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:1115:2e355aee02ea932f484e
evidence_refs: learning:learn:44ac0dd56c86
created_at: 2026-09-24T14:42:21.842633+00:00
updated_at: 2026-09-24T14:42:21.842633+00:00
---
## Trigger
restart/publish/update 等控制面动作受理后终态为 failed，回执带 problem_kind（如 tracked_worktree_dirty）与 next_step，且 next_step 声明解决者是操作者而非程序/模型；目标 checkout 疑似被并行会话共享

## Discriminator
失败回执 next_step 明确写着『需先由操作者提交或还原 tracked 改动；程序不 stash/commit/checkout』——解决权不在模型侧；配合 git status 只读结果：脏改动是成体系在途开发（已暂存重构+配套测试），非本会话运行时产物。这两个当时可得事实把『重试/override/自行 stash/commit/revert/上报』六个候选缩成『只读定性后上报』一个

## Short path
- 本会话首次调用该控制面先读一次 schema，确认 action 与参数的绑定（restart 走 target，restart_target 只属于 update），用一次 schema 读取替代参数猜测重试
- 按 desired generation 发起目标 restart；受理不等于完成，必须查到 succeeded/failed 终态
- 终态 failed 时先读回执 problem_kind/next_step：确认门禁类型（物理不变量 vs 可举证推进的非物理门禁）与解决权归属
- 解决权在操作者 -> git status+diff 只读定性，三分支：并行会话系统性 WIP / 本会话自产垃圾 / 自己的改动，各分支动作不同
- foreign WIP 分支：快速健康探针（import/相关测试）只为让上报可决策，非为自行处置；有 event_stream 等并行证据源就查一条佐证非本会话所写
- 上报：阻断事实+改动定性+健康度+按所有者裁决的分支选项（还原->同代重发 restart；提交->update 发新代），全程对 tracked 树零写操作

## Stop conditions
- 操作者给出明确裁决或授权，按对应分支执行
- 脏改动被证明是本会话自产的可丢弃产物 -> 自行清理重试，无需升级
- 门禁确认为非物理类型且契约提供 override 出口、我方持有证据 -> 走 override 举证推进而非停止

## Verification
- 本会话对 tracked 树零写操作（无 stash/commit/checkout/revert 记录）
- 所有后台动作终态均经 status/action_id 查询确认，failed 未被误报为成功或未完成
- 上报包含 problem_kind、改动定性、健康探针结果、分支化选项，并确认 failed 动作无 lease 残留、可被新 restart 接管

## Counterexamples
- 脏文件是本会话自己生成的日志/缓存/临时产物 -> 直接清理重试，上报反而拖慢收敛
- 单所有者 worktree 且改动就是本任务产物 -> 按任务目标自行提交或还原，不必升级
- 只有未跟踪文件且不影响绑定校验 -> 无需任何清理，直接重试
- 门禁是非物理类型、契约有 override 出口且证据在手 -> 举证推进而不是停止
