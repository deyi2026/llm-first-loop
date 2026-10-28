---
method_id: hydrate-interrupted-action-receipt-before-rerun-a84e37408d27
name: hydrate-interrupted-action-receipt-before-rerun
description: 会话因基础设施故障（LLM 请求超时/传输中断）打断后收到极简续跑指令时：工具侧回执不随 LLM 侧故障丢失，evidence ledger 最新 receipt 的时间戳恰好夹住中断点。先从错误/事件流判定失败类别并取最后派发的工具调用，再按 source+acquired_at 匹配该调用的已持久化 receipt 并完整 hydrate（读到 complete=true），用其中退出码与输出判定中断动作成败：成功则不重跑、直接进入剩余未知量；无 receipt 才重执行；receipt 显示失败则转入诊断。以一次定向 hydrate 替代源码/文档级再发现与盲目重跑。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72b1f325-1293-4022-9fb8-46f58685873e:382:f69d2babc5644acb254c
evidence_refs: learning:learn:e0bc80ab8ccb
created_at: 2026-10-17T12:20:31.557137+08:00
updated_at: 2026-10-17T12:20:31.557137+08:00
---
## Trigger
任务循环因 infra 故障（LLM 请求超时、连接中断等）中断后需续跑，且中断前最后派发的工具动作结局未知（是否执行、是否成功）

## Discriminator
list_evidence 最新条目的 source 与事件流中最后派发的工具调用一致，且 acquired_at 早于中断时间点（receipt 在故障前已服务端落库）——该动作已被观察并持久化，其退出码/输出即结局，无需重执行或从源码再推导

## Short path
- 读错误/事件流：先判定失败类别（infra 超时 vs 工具/任务失败），并取最后派发的工具调用标识
- list_evidence 取最新条目：按 source 与 acquired_at 匹配中断动作，确认 receipt 存在且时间早于中断点
- 完整 hydrate 该 receipt（分页读到 complete=true）：由退出码与输出判定中断动作已成功/失败/未完成
- 成功→跳过重跑，直接转入中断前尚未解决的剩余未知量；无 receipt→重执行该动作；receipt 显示失败→按任务失败诊断
- 若结论涉及当前共享状态，仅另做一次新鲜度核对后收口

## Stop conditions
- 中断动作结局已由其持久化 receipt 判定，且剩余未知量均由权威观察回答，停止恢复性探索
- 确认中断动作从未被观察（无 receipt 且事件流无回执）后，转正常执行路径而非继续在 ledger 里搜寻

## Verification
- receipt 的 source 标签与事件流最后 dispatch 的工具调用一致；acquired_at≥dispatch 时间且≤中断时间
- 终局断言前区分'中断时刻已成功'与'当前仍成立'：涉及可变状态时补一次新鲜读取（如重查 pending 计数）

## Counterexamples
- 中断动作是异步/后台 job：receipt 只覆盖派发不含完成态，须轮询 job 状态而非信 receipt
- 退出码 0 但命令非幂等且可能中途被杀（部分写入）：需直接核验目标状态，不能只信回执
- 失败是工具侧（exit≠0）而非 infra：hydrate 之后下一步是诊断修复，不是'跳过重跑'
- 无持久化回执机制的裸环境：只能从副作用重新推导，本方法不适用
