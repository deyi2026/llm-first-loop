---
method_id: capability-precheck-before-control-verbs-e457317541c2
name: capability-precheck-before-control-verbs
description: 对托管后台任务/资源调用 cancel/kill 等控制动词前，先解析其最新 status 回执中的能力字段（句柄、回收策略、持久化状态）。若回执已声明本操作者无句柄、自动回收关闭且状态已持久化，则该动词已被回执排除：登记孤儿事实（id 与字段值）后直接回到主目标，不做注定失败的一次尝试。仅当存在可用句柄/通道、回执疑似过期、存在按 id 的管理通道、或孤儿占用端口/锁等阻塞主目标的资源时，才升级处理（如按 PID 进程级清理），并用一次 status 复查验证结果。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:1284:1bfe3923337be77621e4
evidence_refs: learning:learn:170c6937a6f2
created_at: 2026-09-18T05:46:13.011077+00:00
updated_at: 2026-09-18T05:46:13.011077+00:00
---
## Trigger
准备对 managed job/background task 调用 cancel/terminate/kill 等控制动词，且该资源的最新状态查询回执中包含句柄/能力类字段（如 local_handle=false、auto_reclaim=false）。

## Discriminator
动作发生前就已可见的回执字段：状态=orphaned、local_handle=false、auto_reclaim=false、state_durable=true——随后的失败原因（本进程无句柄、auto_reclaim=false）是对这些字段的逐字复述，即失败在尝试前已被回执完整预言。

## Short path
- 查询目标 job 的 status；未知量：当前操作者是否持有任何终止通道？
- 解析能力字段：local_handle=false 且无文档化的按 id 取消通道 → 判定该动词在此 API 下不可用，不再发起尝试。
- 评估孤儿是否阻塞主目标（端口/锁/独占资源）；不阻塞且 state_durable=true → 登记 job_id 与关键字段，立即回到主任务。
- 仅当阻塞主目标或用户明确要求清理时升级一级（ps 定位 PID 后进程级处理，或走管理通道），完成后用一次 status 复查关闭该未知量。

## Stop conditions
- 回执显示存在可用句柄或自动回收通道 → 允许一次动词尝试并以 status 验证，不重复尝试。
- 孤儿非阻塞且状态已持久化 → 登记后退出清理分支，不再对其发起任何控制调用。
- 升级处理后复查显示任务消失 / cancel_requested=true / 阻塞资源已释放 → 清理未知量关闭。

## Verification
- 任何清理动作后重新查询 status，以状态转移为准，不单独信任动作回执。
- 若仍尝试了被回执排除的动词，核对失败 reason 是否只是回执字段复述（无新信息）——是则证明该尝试本可跳过。

## Counterexamples
- 回执可能过期：句柄可能已被其他进程/重启回收，下'不可用'结论前应先复查一次 status。
- 系统存在不依赖 local_handle 的按 job_id 持久取消队列或管理 API 时，local_handle=false 不代表不可取消，可按文档尝试一次。
- 用户明确要求清理遗留任务时，一次有界的通道探测是合理的，不应机械跳过。
- 孤儿实际占用端口/锁等阻塞主目标的资源时，'登记后继续'是错的，必须升级到进程级处理。
