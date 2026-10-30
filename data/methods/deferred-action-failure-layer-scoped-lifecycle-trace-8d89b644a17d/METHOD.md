---
method_id: deferred-action-failure-layer-scoped-lifecycle-trace-8d89b644a17d
name: deferred-action-failure-layer-scoped-lifecycle-trace
description: 当定时/延迟动作未按期执行时，先取系统快照（pending_actions、运行时健康、执行侧共享单授权）判定失败层级；若待办为 0 且运行时健康但执行侧单授权，失败锁定在'触发→run 交接'层——按系统/全局范围查调度生命周期事件（delegated_ingress、degraded_to_notify/deferred_retry/goal_stale_noop 降级枚举），detail 含 session= 可缩小范围；不要在会话日志上反复加大窗口。定位为共享授权竞争且降级不重试后，用不依赖该授权的兜底而非原样重挂同一唤醒。（原卡 ae4184904e2b 的 busy_retry/slot 并发/session 归属三锚点与现行代码不符，本卡为机械复核后的修订版）
aliases: 闹钟设了到点却没响, 待办为 0 但执行侧只有单授权, deferred job 未执行, 降级为通知后唤醒没跑
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cab051cc-c0ca-4a09-b848-6d4a00ec0ffe:1543:f816572cac8582fe4c28
evidence_refs: src/llm_loop/core/loop/engine.py:740,src/llm_loop/core/schedule_delivery.py:72,src/llm_loop/core/schedule_delivery.py:85,src/llm_loop/core/schedule_delivery.py:118,src/llm_loop/introspection/status.py:488,src/llm_loop/factory.py:2629
parent_ref: method:deferred-action-failure-layer-scoped-lifecycle-trace-ae4184904e2b
created_at: 2026-10-30T11:09:42.422433+08:00
updated_at: 2026-10-30T11:09:42.422433+08:00
---
## Trigger
用户报告某个已注册的定时/延迟唤醒（schedule/wake/deferred job）没有执行，需要定位原因；环境中存在事件流或调度日志可查

## Discriminator
状态快照在扩散前已给出三个可判别事实：(1) pending_actions 全为 0 → 唤醒确实未生成新 run，症状成立（status.py `_pending_actions` 投影）；(2) 运行时健康、无程序故障 → 排除调度器未触发和运行时崩溃；(3) 执行侧为共享单授权/单实例，任何唤醒要与占用方竞争（此事实从运行时健康快照观测；注意 status.py 无 slot/并发指标，2026-10-30 复核零命中）。成功唤醒以系统级生命周期事件（delegated_ingress）入列且 detail 含 session=，可按 detail 过滤缩小范围。本卡为 method:deferred-action-failure-layer-scoped-lifecycle-trace-ae4184904e2b 的修订版：原卡三处锚点（busy_retry 行、slot/并发指标、session 不归属前提）与现行代码不符，已按 2026-10-30 机械复核修正。

## Short path
- 取系统状态快照，确认：待办=0（未成 run）、运行时健康、无故障、执行侧共享单授权 → 失败层级锁定在触发→run 交接，且授权竞争为首要假设
- 按该层级事件的归因范围（系统/全局 scope 而非当前会话）拉取唤醒注册时刻至今的生命周期事件；若支持按 sid 或时间窗过滤则直接用
- 读事件链：注册成功→准点触发→降级（原因枚举见 schedule_delivery.py：degraded_to_notify / deferred_retry / goal_stale_noop，detail 含 sid/prompt_chars）→通知仅被观测未注入 run → 根因判定；占用方从同一事件流的 detail/降级原因指认（注意：现行 src 无 busy_retry 行，2026-10-30 复核仅 tests/unit/test_schedule_restart_recovery.py:159 测试名残留）
- 缓解：为依赖该授权的延迟动作配置不依赖授权的兜底（后台 watcher 轮询或释放后重试/退避），并确认兜底在授权再次不可用时仍能推进；不要原样重挂同一唤醒

## Stop conditions
- 生命周期事件链三证齐全（触发时间戳+降级原因+通知去向）且与快照中共享单授权事实互相印证，根因有原文可溯，停止诊断
- 若快照显示待办>0、恢复积压或程序故障非空，失败层级不同，立即切换到对应证据源，不再沿授权竞争分支
- 若生命周期事件显示唤醒根本未注册成功或注册参数错误，转向注册参数核对，停止查交接层

## Verification
- 结论中每个环节（注册、触发、降级原因、通知去向）都有事件流原句支撑，时间戳单调合理
- 降级原因与快照中的共享单授权事实一致，占用方可从同一事件流指认
- 兜底机制验证为不依赖被竞争授权即可推进（如由程序侧轮询），且下一次授权被占时仍能续跑

## Counterexamples
- 唤醒实际执行了但结果错误：证据在会话 run 日志（会话 scope），不应跳到系统范围查生命周期事件
- 快照显示多槽并发且授权空闲：授权竞争假设不成立，应查注册参数（时间/目标会话/消息）而非交接层
- 调度系统支持按 sid 精确过滤检索时，直接按 sid 查询即可，无需也不应按 limit 逐步加宽任何 scope
- 快照显示 recovery 积压或 program_faults 非空：失败在恢复/故障层，先查故障记录，本方法不适用

## 核验记录
- 2026-10-30（事实轴复核，round-2）：busy_retry 在 src/ 零命中（仅 tests/unit/test_schedule_restart_recovery.py:159 测试名）；status.py 无 slot/concurren 指标（grep 计数 0）；delegated_ingress=src/llm_loop/core/loop/engine.py:740；降级态枚举=src/llm_loop/core/schedule_delivery.py:72/85/118；pending_actions=src/llm_loop/introspection/status.py:488 与 src/llm_loop/factory.py:2629。原卡核心分层法成立（round-1 独立回执 task_benefit=pass），仅锚点陈旧，故落修订版而非销毁。
