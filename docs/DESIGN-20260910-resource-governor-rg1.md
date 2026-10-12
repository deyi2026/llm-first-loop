# LFL Unified Resource Governor — RG-1 最小运行时与 Learning 迁移

> Status: implementation candidate / qualification pending
> Parent contract: `docs/DESIGN-20260910-resource-governor-rg0.md`
> Scope: lease / explicit concurrency / foreground service order / Learning foreground-gate parity only

## 1. 本阶段裁决

RG-1 把 RG-0 的纯数据 contract 落成第一个共享运行时组件，但只获得**机械资源准入权**：

- 对显式 `ResourceKey -> max_concurrency` 维护进程内 in-flight 计数；
- 一个 `AdmissionRequest` 的多个 key 必须原子获得，或全部不获得；
- `ResourceLease` 只有成功 admission 才产生，异常/终态必须 release；
- 等待请求按 `ServicePriority` + arrival sequence 服务，但 priority 只表达资源服务顺序；
- 在 Task 尚未迁入 Governor lease 之前，用机械 `ForegroundActivityProbe` 兼容现有 foreground fact；
- 第一位消费者只有 `LearningPlane`。

RG-1 **不拥有**：

- 任务复杂度、重要性、质量、完成度；
- 模型/Method/Skill 的语义适用性；
- provider/model 自动选择；
- RPM/TPM、费用、quota、TrustDomain enforcement；
- provider request cancel / preemption；
- Task/SubAgent 的 provider-call lease。

因此 RG-1 不是“调度模型思考”的策略系统，而是一个窄的资源所有权协调器。

## 2. Shared Governor，不做 Learning 私有实现

Factory 始终装配一个：

```text
engine.resource_governor: ResourceGovernor
```

即使 `LEARNING_PLANE_ENABLED=0`，Governor 也只是一组空的进程内数据结构：

```text
active_leases = 0
pending = 0
no thread
no network
no prompt mutation
```

Learning 开启时复用同一个实例。这样 RG-2 可让 Task/SubAgent/Deliberation 逐步接入，而无需再从 Learning 私有 scheduler 重构一次。

## 3. ForegroundActivityProbe 是迁移桥，不是最终资源模型

RG-1 必须行为等价保留 Learning P0 已验证的 foreground facts：

1. `engine.runner.has_running()`；
2. `engine._sync_active`，读取时持有 `_sync_guard`；
3. `sessions/**/<sid>.run.lock` 的真实 flock 状态；
4. 任一探测异常视为 uncertainty，Learning yield。

明确禁止：

```text
bool(engine.registry)
```

因为它是 ToolRegistry，不是 workload registry。

`ForegroundActivityProbe` 只是一座 RG-1 迁移桥：Task 还没有 lease 时，Governor 必须能感知既有真实 foreground activity。RG-2 把 Task/SubAgent 真正接入 lease 后，才能逐步减少这类旁路探测。

## 4. RG-1 Learning lease 的真实含义

Learning 在准备 ReflectionRun 前请求：

```text
execution_class = BACKGROUND_LEARNING
service_priority = P3_BACKGROUND_LEARNING
```

并绑定一个 RG-1 process-local Learning coordination key，显式：

```text
max_concurrency = 1
```

**这不是 provider/model 真实并发能力声明。**

它只表达当前 LFL 进程中这条 Learning consumer lane 的已知容量。真正的：

```text
local MLX prompt/decode concurrency
cloud account/project/model concurrency
```

必须等 RG-2/provider adapter 能提供带 provenance 的事实后，使用独立真实 resource keys。RG-1 不从 provider 名称、静态 registry 或历史 launcher 猜容量。

## 5. Admission 顺序

Learning `_try_execute(job)` 保持 P0 时序语义：

```text
foreground barrier check
  -> quiet period
  -> build mechanical resource request
  -> try_acquire lease (non-blocking)
  -> journal admitted
  -> foreground re-check
  -> journal started
  -> foreground final re-check
  -> exact Episode hydration
  -> ReflectionRun
  -> terminal journal state
  -> finally release lease
```

关键性质：

- Learning worker 不在 Governor 内 busy-wait；失败 admission 直接 yield，保留 queued；
- foreground 在 admission/start 间出现时，仍 `requeued(reason=foreground_arrived)`；
- foreground 在最后一个 provider-call 前检查点出现时，仍 yield；
- 一旦 provider call 已经开始，RG-1 不宣称可以抢占；
- reflection/candidate save/episode failure/异常路径都必须释放 lease。

## 6. Unknown 与错误处理

### 6.1 concurrency unknown

没有显式 limit 的 resource key：

```text
DEFERRED / REQUIRED_FACT_UNKNOWN
```

绝不等价为 unlimited。

### 6.2 resource target unresolved

如果当前 Learning job 的 `source_model` 暂时无法机械解析到 provider/model：

- 不猜 provider；
- 不启动 Reflection；
- 不获得 lease；
- 不消耗 Learning attempt；
- 本轮 yield，等待配置/事实恢复。

这避免 `mark_failed` 但 attempt 未递增造成永久 failed-retry 循环。

### 6.3 probe uncertainty

Foreground probe 自身异常时按 foreground active 处理，Learning yield。它只影响低优先级 background admission，不改变 Task 行为。

## 7. Atomic multi-key lease

虽然 RG-1 Learning 当前只消费一个 coordination key，Governor 从第一版就保留 RG-0 的多 scope 原子能力：

```text
request keys = [A, B, C]
```

若 B 满：

```text
A increment = 0
B increment = 0
C increment = 0
result = DEFERRED
```

禁止 partial acquisition，避免 RG-2 接 provider/account/model scope 时再重写并发核心。

## 8. Service order

Blocking `acquire()` 只用于通用 Governor 能力验证，按：

```text
(service_priority, arrival_sequence)
```

对共享 key 排队。

因此：

```text
P0 foreground waiter > earlier P3 learning waiter
```

同 priority FIFO。

Learning RG-1 实际使用 `try_acquire()`，保持原 durable queue + poll 机制，不新增第二套后台等待队列。

## 9. Non-preemption invariant

如果 Learning 已获得 lease 并已经进入 provider call，随后 foreground 到达：

```text
higher_priority_active = true
existing learning lease remains active
```

直到 ReflectionRun 自己返回/失败并 release。

这与当前 transport 能力一致：generic `LLMClient` 没有可验证 request-cancel hook。真正抢占只能进入后续 RG-5，且必须由 adapter 资格证明。

## 10. Prompt / provider surface invariant

RG-1 不新增：

- system/user prompt 文本；
- tool；
- tool schema；
- provider routing hint；
- Method/Experience 自动注入。

资格验证必须证明相对 RG-0 `5e6ca45`：

```text
Universal Prompt byte-identical
registered tool surface byte-identical
projected provider tool surface byte-identical
```

## 11. RG-1 Acceptance Matrix

| Gate | 必须证明 |
|---|---|
| R1-01 | explicit max_concurrency=1 时第二请求 DEFERRED |
| R1-02 | release 后等待/后续请求可获得 lease |
| R1-03 | unknown limit 不当 unlimited |
| R1-04 | multi-key lease 原子，无 partial increment |
| R1-05 | overlapping waiter 按 ServicePriority 服务 |
| R1-06 | active background 不被假抢占 |
| R1-07 | old runner/_sync_active/run.lock foreground facts 行为等价 |
| R1-08 | ToolRegistry truthiness 不影响 foreground |
| R1-09 | foreground 在 admitted/start gap 出现时 Learning requeue |
| R1-10 | Learning concurrency full 时 job 保持 queued/attempt=0 |
| R1-11 | unresolved resource target 不猜 provider、不消耗 attempt |
| R1-12 | Reflection 异常路径 lease 最终归零 |
| R1-13 | Learning OFF 时 shared Governor 存在但无线程/lease副作用 |
| R1-14 | Learning ON 使用 engine 共享 Governor，不另建私有 scheduler |
| R1-15 | Task/SubAgent/ModelClientPool 仍未接 ResourceGovernor |
| R1-16 | SSE done / next turn 不等待 post-task Learning |
| R1-17 | Universal Prompt 与 RG-0 byte-identical |
| R1-18 | provider-visible tool/schema surface 与 RG-0 byte-identical |
| R1-19 | Ruff/Pyright/py_compile/diff/security 全绿 |
| R1-20 | full non-real-LLM 全绿 |
| R1-21 | live existing-runtime canary：held foreground lock -> zero Reflection provider call；释放后恰好一次 provider call 可进入并得到终态，且 lease 归零；Method 输出/schema 质量另行评估 |

## 12. RG-2 明确后移内容

RG-1 完成后，下一阶段才允许：

```text
Task provider call -> lease
SubAgent provider call -> lease
real local runtime concurrency adapter
provider/account/model resource keys
cross-execution contention
```

仍不意味着自动选模型。

RPM/TPM/cost/quota 是 RG-3；TrustDomain 是 RG-4；可验证 cancel/priority 是 RG-5。

## 13. 最终边界句

> **RG-1 只把“谁现在占着哪个已知资源槽”变成共享、可验证的机械事实；它不决定谁的任务更值得做，也不决定模型应该怎么做。**
