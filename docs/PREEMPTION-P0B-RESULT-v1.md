# P0-B 结果文档：Background Learning 真抢占（foreground always wins 完整语义）

> Goal: GOAL-20260918-345cec71 / Task: TASK-345cec71-002
> 状态: 镜像实现+验证完成，待用户审批后 promotion（MIRROR-WORKSPACE-PROTOCOL §2 ③④）
> 日期: 2026-09-18

## 1. 问题（改动前的事实）

- RG-1 governor 为 non-preemptive：后台租约一旦持有，前台 admission 若与之间 key
  重叠则只能 DEFERRED 等待（`higher_priority_active` 明写 no preemption）。
- LearningPlane 的 foreground 检查全部在 provider transport **之前**；reflection
  调用发出后（`method_reflection_timeout_s`，默认 120s）无任何让出机制。
- 净效果：前台 run 可被后台学习调用阻塞最长一个 reflection timeout——违反
  "foreground always wins" 的完整语义。

## 2. 语义定义（本任务固化）

**抢占只绑定"前台类 admission 动作"**，probe 被动翻转或背景请求不触发撤销：
- governor：`service_priority < foreground_barrier_min_priority`（P0/P1）的
  admission 尝试，且外部 foreground probe active 时，先撤销与本请求 resource_keys
  重叠的背景类（≥ barrier）租约——租约与 in_flight 记账立即移除，被抢占者后续
  `release()` 走既有幂等 False 路径。
- plane：reflection 传输段移入 daemon worker；学习线程以 `preempt_poll_s`
  （默认 0.25s）轮询 `foreground_busy()`，mid-call 命中即
  `mark_requeued("preempted_by_foreground")` + 弃置 worker + 释放租约。
- 不变量：
  - 被弃置 worker 自行结算 shadow call（真实机械结果），但弃置后永不写
    journal / MethodStore / governor；
  - straggler 排空前不得启动新学习传输（不叠加并发）；
  - preemption 不是 failure：requeue 不额外消耗 attempt（attempt 已在
    mark_started 计一次，复用既有语义）；crash 中断仍由 reconcile 兜底。

## 3. 改动清单

| 文件 | 变更 |
|---|---|
| src/llm_loop/resources/governor.py | 模块 docstring 语义更新；`higher_priority_active` docstring（观测不抢占）；新增 `_revoke_overlapping_background_locked` / `revoke_overlapping_background`；`_attempt_locked` 前台类触发撤销（在既有 barrier defer 之前） |
| src/llm_loop/methods/learning_plane.py | docstring 声明 mid-call 抢占；`__init__` 新增 `preempt_poll_s=0.25` 与 `_stragglers`；新增 `_track_straggler`/`_straggler_busy`；`_try_execute` 头部 straggler 闸门；去除 admission 后重复的双重 foreground 检查；传输段（open→bind→reflect→settle）重构为 worker + 抢占轮询；worker 异常经 holder 回传学习线程原语义重抛 |
| tests/unit/test_foreground_preemption.py | 新增：governor 5 场景（task/subagent 撤销、probe 翻转不撤销、无重叠不撤销、probe 关不撤销、幂等 release）+ plane mid-call 抢占全链路（requeue 原因/租约释放/straggler 阻塞新传输/排空后恢复/弃置 worker 不写 journal） |

未动：contracts.py（无新增枚举需要）、factory.py（构造点 keyword 参数 + 默认值兼容）。

## 4. 验证

- 定向：`tests/unit/test_foreground_preemption.py + test_learning_journal.py +
  test_resource_governor_runtime.py` → 全部通过（含既有
  `test_active_background_lease_is_not_fake_preempted_when_foreground_appears`
  不变语义保留）。
- 全量：镜像正典命令 `.venv/bin/python + PYTHONPATH=$M/src`，结果见审批回执。
- 兼容性核对：既有测试对 `_try_execute` 异常传播（RuntimeError）与
  attempt==0 语义的约束均保持。

## 5. 影响面与回滚

- 影响面：仅背景学习路径与 governor 前台 admission；前台任务调用零改动；
  部署后学习 reflection 可能被前台打断重跑（attempt 语义不变，最多
  max_attempts 约束下的重试，token 可能多消耗一次调用）。
- 回滚：两个 src 文件 + 一个测试文件的单 commit revert 即可，无数据迁移。
