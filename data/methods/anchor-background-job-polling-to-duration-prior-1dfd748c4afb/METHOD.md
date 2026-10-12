---
method_id: anchor-background-job-polling-to-duration-prior-1dfd748c4afb
name: anchor-background-job-polling-to-duration-prior
description: 等待必须完成后才能继续的长时后台任务（回归门/构建/批量作业）时，把轮询节奏锚定在可观测的 duration prior（同一命令最近一次实测耗时）与剩余独立工作量上：先做完真正独立的等待期工作；工作耗尽且 elapsed<prior 时不发起零信息查询；首次查询定在 ≈prior 时刻，其后递增间隔；怀疑挂起用进程 CPU 时间是否推进来判定，而非重复查状态。本集 prior（248.73s）在启动门之前就已从旧 job 输出读得，但同一 running job 仍被约 19 次零输出 job_output 连查（episode 指标 duplicate_calls=49）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9ceab5d6-9c2f-4cf4-a73d-9ed7ecee9969:1238:941588a088e8e97531b1
evidence_refs: learning:learn:41caefb0ed2c
created_at: 2026-10-02T03:01:14.144380+08:00
updated_at: 2026-10-02T03:01:14.144380+08:00
---
## Trigger
已启动或即将启动一个已知分钟级耗时的后台任务（全量回归门、构建、批量作业），下游动作依赖其完成，且轮询回执在完成前恒为 running/无增量输出。

## Discriminator
两个当时已在手的事实：(1) 同一命令最近一次运行的实测耗时已可见——本集第 1 步旧 job 回执即给出 `... in 248.73s (0:04:08)`，预期完成时刻可算，且模型自己已知并发 ruff/pyright 会更慢；(2) 每次查询回执恒为 `状态=running`、`输出（0 行）`，即 prior 未到时 job_output 是零信息动作。

## Short path
- 启动后台任务前，先读同一命令最近一次的历史 job 结果，取实测耗时为 duration prior（本集第 1 步即得 248.73s）。
- 单次启动门（后台 + pipefail，保证退出码真实），只启动一次。
- 等待期先完成所有真正独立的预检工作（scoped diff 审查、ruff/pyright、测试覆盖核对、tree/index 一致性），并记录每步耗时。
- 独立工作耗尽后：若 elapsed < prior + 合理余量（本集已知 CPU 争抢应放宽），不发起 job_output——停等优于零信息连查。
- 首次查询定在 ≈prior 时刻；回执仍 running 则按递增间隔再查；怀疑挂起时改用一次 `ps` 看 CPU 时间是否推进来判定，而不是连发状态查询。
- 回执变为 done + exit=0 + 通过计数可读即停止轮询，直接进入下游动作（commit）。

## Stop conditions
- job 回执 status=done 且 exit=0、结果计数可读 → 停止轮询。
- 回执显示失败/被取消/进程消失 → 停止轮询，转入错误处理。
- elapsed 显著超过 prior 且最近一次进程级检查显示 CPU 时间无推进 → 停止盲目等待，改做挂起诊断或按取消意图处理。

## Verification
- 对比反事实：本集对同一 running job 的零输出 job_output 查询约 19 次（episode 指标 duplicate_calls=49）；锚定 prior 后应 ≤3–5 次，且每次查询要么已到 prior 时刻、要么状态有变化。
- 最终结果与旧门同格式可对照（本集 6368 vs 6337 passed，exit=0 由 pipefail 保证），确认等待换来的事实真实可用于下游 commit。

## Counterexamples
- 首次运行、无任何 duration prior 且任务无进度输出：轮询是唯一信号源，不能套『prior 未到就不查』，应使用适中的固定间隔。
- 任务本身有增量输出（pytest -v 逐行、进度条、日志流）：每次轮询都带回新信息，频率应跟随进度速率而非 prior。
- 用户明确要求流式观察，或存在需要盯 cancel_requested/硬超时的时限约束。
- 等待期仍有大量真实独立工作可做：穿插查询合理，本方法只约束『独立工作耗尽后』的节奏，不应推广成一律不许中途查询。
