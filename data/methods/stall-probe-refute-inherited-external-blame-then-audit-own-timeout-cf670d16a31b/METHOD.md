---
method_id: stall-probe-refute-inherited-external-blame-then-audit-own-timeout-cf670d16a31b
name: stall-probe-refute-inherited-external-blame-then-audit-own-timeout
description: 后台跑批停滞、且上一轮报告已把同类失败归因为外部依赖（限流/上游故障）时，把该归因当待证伪假设处理：先用已落盘回执的单次 latency 估算预期墙钟；超过预期后不再追加 wait-poll 循环，立即对被指控依赖发一次同端点最小探针——秒级健康回执即当场证伪外部归因；再把已有成功回执的单次墙钟与 harness 源码里的超时常量对比，成功调用已达或超过该常量即翻转归因为自身超时预算（per-read vs per-call 语义），最后用有界墙钟重跑器只补缺失项。本集 600s+ 的等待-轮询被压成 3.3s 探针加一次常量对比，'上游限流'结论当场撤回，真实根因是 120s socket 超时 vs 116~280s 的单请求时长。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:31e64fa8-0da2-4a1c-afd1-a74ed4fcd805:3170:a7aaf5226508e7954ad5
evidence_refs: learning:learn:a0387ec85b54
created_at: 2026-10-19T16:13:46.683750+08:00
updated_at: 2026-10-19T16:13:46.683750+08:00
---
## Trigger
长时后台跑批/批量模型调用停滞无进展（已超过按已有回执 latency 估算的预期墙钟），且上下文带入一条现成的外部归因诊断（限流、上游不可用、网络抖动）可作为待证伪假设；典型场景是重跑上一轮已有臂缺失的同一脚本。

## Discriminator
两个当时即可得的事实足以二选一：(1) 同刻最小探针——在停滞发生的同一时刻对被指控依赖发一次与业务同端点的廉价调用，秒级 HTTP 200 即外部归因不成立；(2) 回执-常量对比——已有成功回执里的单次调用 latency（本集 134.5s）已达到或超过 harness 源码中的超时常量（120s per-read），指向自身超时预算而非网络。

## Short path
- 把带入的外部归因（限流）显式列为待证伪假设；用 raw 结果文件里已知单次 latency × 任务数 / 并发数估算预期总墙钟
- 停滞超过估算墙钟后停止追加 wait-poll：立即同刻探针被指控依赖，并 tail 结果文件确认零新增终态行
- 探针秒级健康 → 归因翻转：读 harness 调用函数，确认 timeout 是 per-read 还是 per-call、attempts、并发信号量与 max_tokens
- 用有界墙钟重跑器只补缺失臂：attempts=1、timeout ≥ 观测最大 latency、按需放大 max_tokens，替代开放式等待
- 原停滞臂全部拿到 finish=stop、content 非空的终态行即停止，复核新回执 latency 落在新预算内

## Stop conditions
- 同刻探针自身失败或超时 → 外部归因成立，停止自身代码审计，转等待/换时段/上报依赖故障
- 原停滞臂在有界墙钟内全部取得终态回执且未截断
- 已有回执 latency 远低于超时常量且探针健康 → 停滞另有原因（并发死锁、队列、脚本逻辑），按新未知量另行诊断

## Verification
- 修参重跑后，原停滞臂 finish=stop、content 非空、无 length 截断
- 新回执的单次 latency 小于新超时预算，且多臂补跑结果与'超时而非限流'的归因一致（限流时段应表现为 HTTP 429/重试记录，而非无回执静默挂起）

## Counterexamples
- 任务本就该长时间运行：已有 latency × 任务数 / 并发未超预期时，开头几分钟零输出不是停滞证据，先等估算墙钟再触发探针，否则误报
- 探针与业务调用不同通道/配额（不同 key、不同端点、不同模型）：探针健康不能证伪针对业务通道的限流指控，必须用同参数同端点探针
- 纯本地无外部依赖的停滞（无网络调用）：无可探依赖，本方法不适用，直接查进程状态、日志与锁
