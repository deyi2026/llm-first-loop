# LFL Unified Resource Governor — RG-2 Provider Call Lease 与本地 Runtime Concurrency

> Status: implementation candidate / qualification pending
> Parent: RG-1 `c7da5c5`
> Scope: Task/SubAgent provider-call lease + qualified local MLX runtime concurrency observation + Learning same-runtime contention

## 1. 本阶段裁决

RG-2 的目标不是新增一套“智能调度”，而是把 **真正会消耗 provider/runtime 计算资源的调用** 接到 RG-1 已存在的共享 `ResourceGovernor`。

本阶段只增加三项能力：

1. Task 的真实 provider attempt 在调用期间持有 P0 lease；
2. active-task SubAgent 的真实 provider attempt 在调用期间持有 P1 lease；
3. 对本地 loopback MLX runtime，从**当前监听进程**观察显式并发事实；Task/SubAgent/Learning 使用同一个 runtime key。

RG-2 仍然**不实现**：

- RPM / TPM / rolling rate window；
- token pricing / cost budget / quota；
- TrustDomain enforcement；
- provider request cancel / preemption；
- 根据复杂度、质量、重要性选择模型；
- 根据资源状态修改 prompt、Method、Skill 或任务语义；
- cloud concurrency 推断。

因此本阶段仍遵守：

> **上层先决定要调用哪个模型；Resource Governor 只约束这个已选调用能否占用已被机械证明的资源。**

## 2. 为什么 lease 必须覆盖 provider attempt，而不是整个 Session

Session/run lease 解决的是“同一会话是否允许并发修改”问题；provider lease 解决的是“同一物理/服务资源是否同时被多个执行面占用”问题。

两者不能混为一谈：

```text
Session A Task -----\
Session B Task ------> same local runtime :8901
SubAgent C ----------/
Learning D ----------/
```

即使四者 Session 完全隔离，它们仍可能争用同一个单并发模型服务。

所以 RG-2 的 lease 生命周期必须精确包住：

```text
provider send / stream consume / response terminal
```

而不是从 user message 到整个 Agent run 都占着模型槽。工具执行期间不持 provider lease。

## 3. Production provider-call 覆盖面

RG-2 只接**当前生产真实路径**：

### 3.1 Task primary

`LoopEngine`：

- `chat_stream(...)`：lease 从实际调用前开始，持续到流正常 terminal、异常或 close；
- sync `chat(...)`：lease 包住一次完整调用。

Task 使用：

```text
ExecutionClass.FOREGROUND_TASK
ServicePriority.P0_FOREGROUND
```

### 3.2 Availability fallback

`FallbackService` 的每一个真实 fallback candidate provider call 都单独申请 P0 lease。

主调用失败后，其 lease 已释放；fallback 不继承旧 runtime lease，避免跨 provider/resource 错绑。

### 3.3 ERR1210 changed-wire retry

当前生产 1210 恢复由 `RecoveryController` 承担。若尾部 user wire shape 确实被机械改变并触发唯一 retry，该 retry 也是一个独立 P0 provider attempt，必须独立申请 lease。

`injection_span.py::_Err1210Mixin` 已不被 `LoopEngine` 继承，是退役兼容代码。RG-2 **故意不接该死路径**，避免为了静态 grep 扩大生产修改面。

### 3.4 SubAgent

`SubAgentRunner` 每轮真实 `self.llm.chat(...)` 使用：

```text
ExecutionClass.SUBAGENT
ServicePriority.P1_ACTIVE_TASK_AUXILIARY
```

SubAgent 的工具执行仍不持 provider lease。

## 4. ProviderCallCoordinator

RG-2 增加共享：

```text
engine.provider_call_coordinator: ProviderCallCoordinator
```

它只做：

```text
selected client/provider/model
        |
        v
runtime adapter observation
        |
  qualified local fact?
     /       \
   yes       no
    |         |
build AdmissionRequest   preserve current call behavior
    |
ResourceGovernor.acquire
    |
provider call
    |
finally release
```

Coordinator 不读取：

- task text；
- messages/prompt 内容；
- complexity / importance / quality；
- Method applicability；
- completion state。

## 5. LocalRuntimeConcurrencyAdapter 的事实来源

RG-2 当前正式 adapter 只认**可机械证明的 loopback MLX listener**。

观察链：

```text
LLM client base_url
  -> parse host/port
  -> host must be local/loopback
  -> lsof exact TCP LISTEN PID(s)
  -> exactly one listener PID
  -> ps exact process command
  -> argv contains mlx_lm.server
  -> --port exactly matches endpoint
  -> --prompt-concurrency explicit positive int
  -> --decode-concurrency explicit positive int
```

任一步失败：

```text
observation = unknown
```

不会从：

- provider 名称；
- model 名称；
- 静态 providers registry；
- 历史 launcher 文档；
- “MLX 一般默认多少并发”

猜值。

## 6. `max_concurrency` 的窄语义

对当前 MLX server：

```text
coordination_limit = min(prompt_concurrency, decode_concurrency)
```

这是 **RG-2 完整 provider request 的保守协调上限**，不是声称 MLX 内部 pipeline 在所有阶段只能有这么多工作。

理由：一次完整请求会经过 prompt/decode 两阶段；为了不超过任一明确声明的 live stage limit，RG-2 使用最小值作为跨执行面安全上限。

未来如果 runtime 暴露更精确的 admission API，可以替换 adapter 事实，不需要让任务语义层感知。

## 7. 当前 8901 的 live 事实

RG-2 实现期只读观测到当前 listener：

```text
runtime = mlx_lm.server
port = 8901
prompt_concurrency = 1
decode_concurrency = 1
prompt_cache_size = 8
```

adapter 输出：

```text
runtime_type = local
resource key = runtime / mlx-loopback:8901
max_concurrency = 1
provenance = local-listener:8901:pid:<live-pid>
```

PID 是瞬时 provenance，不写死进代码或配置。

## 8. 不缓存 live process concurrency 的裁决

在当前机器连续 20 次真实只读 observation：

```text
median ~= 14.3 ms
p95 ~= 16.0 ms
```

这个开销远低于当前本地大模型一次真实 prefill/decode，并且每个 provider attempt 只观察一次。

RG-2 因此**暂不增加 TTL cache**：

- 避免 8901 重启后继续使用旧 PID/旧并发事实；
- 避免模型热切换或 launcher 参数改变后出现 stale admission；
- 保持事实链简单可审计。

如果以后本地超短请求使 probe 开销成为可测瓶颈，再引入带 PID/generation invalidation 的机械缓存；不能只按时间猜 freshness。

## 9. Task / SubAgent / Learning 使用同一个 local runtime key

这是 RG-2 最关键的不变量。

若 8901 被证明：

```text
ResourceKey(provider, RUNTIME, "mlx-loopback:8901")
max_concurrency = 1
```

那么：

```text
Task P0       -> same key
SubAgent P1   -> same key
Learning P3   -> same key
```

不能继续让 Learning 使用独立的 `rg1-learning-process:<model>` key，否则会出现：

```text
Learning already started
+ new Task starts
= two requests hit single-slot runtime
```

RG-2 因此让 Learning 在 adapter 成功时迁到真实 runtime key；只有 cloud / 未资格化 runtime 才保留 RG-1 fallback lane。

## 10. Foreground-first 的准确含义

在 `max_concurrency=1` 时：

### 10.1 尚未开始的等待者

同一 key：

```text
P0 Task > P1 SubAgent > P3 Learning
```

相同 priority 按 arrival sequence FIFO。

### 10.2 已经开始的 Learning

RG-2 没有 provider cancel 能力，所以：

```text
Learning owns lease
Task arrives
=> Task waits
=> Learning is NOT fake-preempted
=> Learning terminal/release
=> Task acquires next
```

这仍符合 RG-0/RG-1 的 non-preemption invariant。

“foreground-first”表示**等待队列的服务顺序**，不是伪造中途抢占。

## 11. ForegroundActivityProbe 仍保留

RG-2 接入 provider lease 后，RG-1 的 run-level foreground probe 仍暂时保留给 Learning：

- runner active；
- `_sync_active`；
- cross-process `*.run.lock`。

原因：它阻止 Learning 在一个 foreground Agent 正处于工具阶段、尚未申请下一次 provider lease 时抢先启动长 Reflection。

因此当前有两层不同事实：

```text
run-level foreground barrier  -> background Learning admission
provider-level runtime lease  -> actual model-call concurrency
```

后续是否缩减 run-level bridge，应以真实交互延迟/资源实验为依据，不在 RG-2 提前删除。

## 12. Cloud / unknown local 行为

RG-2 没有云端 concurrency 的权威事实源，因此：

```text
GLM / MiniMax / DeepSeek remote endpoint
=> local adapter does not probe
=> no RG-2 runtime lease
=> current provider call behavior preserved
```

这不表示“cloud unlimited”，只表示：

> **RG-2 没有资格对其实施 concurrency enforcement。**

真正 cloud provider/account/project/model concurrency、429 reconciliation、RPM/TPM 在后续 RG-3 使用官方/运行时事实接入。

对无法被当前 adapter 证明的本地 endpoint，同样不伪造并发值；其资格范围必须明确标成 unknown，而不是宣称已覆盖。

## 13. Failure / close / retry lease invariant

所有已获得 lease 的调用必须：

```text
normal response -> release
stream terminal -> release
stream close / disconnect -> release
provider exception -> release
fallback failure -> release
1210 retry failure -> release
SubAgent failure -> release
```

一个 provider attempt 失败后，下一个 fallback/retry 是新 attempt，重新观察资源并申请新 lease。

禁止把 failed call 的 lease 偷渡到另一 provider/model。

## 14. Prompt / Tool / Model-routing 不变量

RG-2 不新增或修改：

- system/user prompt；
- Universal Prompt；
- tool registry；
- provider-visible tool schema；
- Method / Experience / Rule / Skill 注入；
- model selection / fallback candidate policy；
- reasoning mode policy。

Resource wait 不生成模型可见训诫文本。

## 15. 已知资格边界

### 15.1 Process-local Governor

当前 lease ledger 仍是 LFL 进程内的；跨 LFL 进程共享同一 8901 时，只有 run-lock probe 能看见 foreground Session，而 provider in-flight lease 尚不是跨进程分布式 semaphore。

RG-2 不夸大为“多进程全局 provider scheduler”。

### 15.2 Provider alias 指向同一 endpoint

RG-0 `ResourceKey` 仍把 `provider_id` 作为 key identity 一部分。当前正式配置按一个 provider identity 对应 8901 资格化；若未来允许多个 provider alias 指向同一物理 endpoint，需要先扩展/冻结 physical-runtime identity contract，不能假设两个 alias 自动共享 key。

### 15.3 只有已证明的 MLX loopback runtime

GGUF/llama.cpp、本地远程机、Linux 等真实 runtime adapter 后续按同样 contract 资格化；RG-2 当前实现不根据相似命令行猜支持。

## 16. RG-2 Acceptance Matrix

| Gate | 必须证明 |
|---|---|
| R2-01 | live loopback MLX listener 唯一 PID + explicit concurrency 才产出 fact |
| R2-02 | remote/cloud endpoint 不被 local adapter 探测 |
| R2-03 | missing/invalid/ambiguous live facts 不猜 capacity |
| R2-04 | prompt/decode concurrency 用保守 min 形成 request coordination limit |
| R2-05 | Task sync provider call 持 P0 lease |
| R2-06 | Task stream provider call lease 持续到 terminal/close |
| R2-07 | stream close/异常后 lease/in-flight 归零 |
| R2-08 | 两个不同 Task Session 竞争同一 max=1 runtime 时不并发进入 provider |
| R2-09 | SubAgent provider call 持 P1 lease |
| R2-10 | Task waiter 优先于 SubAgent waiter；同 priority FIFO |
| R2-11 | Learning 在 qualified local runtime 上与 Task/SubAgent 使用同一 key |
| R2-12 | 已开始 Learning 不伪抢占；Task 等待 lease release |
| R2-13 | Fallback provider attempt 独立申请/释放 P0 lease |
| R2-14 | production 1210 retry 独立申请/释放 P0 lease |
| R2-15 | retired `_Err1210Mixin` 不重新接 runtime 资源逻辑 |
| R2-16 | ModelClientPool 不获得资源/语义调度权 |
| R2-17 | cloud/unknown endpoint 在 RG-3 前保持原 provider behavior |
| R2-18 | 无 RPM/TPM/cost/trust/cancel 实现混入 |
| R2-19 | Universal Prompt 与 RG-1 byte-identical |
| R2-20 | provider-visible tool/schema surface 与 RG-1 byte-identical |
| R2-21 | Ruff/Pyright/py_compile/diff/security 全绿 |
| R2-22 | full non-real-LLM 全绿 |
| R2-23 | live 8901 canary 证明 adapter fact、同 key serialization、terminal 后 lease=0，且不启动第二本地模型/不重启8901 |

## 17. RG-3 以后才允许的内容

RG-2 完成后，下一阶段若进入 RG-3，才允许加入：

```text
cloud concurrency scopes
provider/account/project/model quotas
RPM / TPM rate windows
429 / Retry-After observations
pricing / cost accounting
```

TrustDomain 仍单独留给 RG-4；provider cancel/priority capability 留给 RG-5。

## 18. 最终边界句

> **RG-2 把“这个真实 provider call 正在占哪个已被证明的 runtime 槽”纳入共享 Resource Governor；它不决定这个调用值不值得做，也不改变模型要做什么。**
