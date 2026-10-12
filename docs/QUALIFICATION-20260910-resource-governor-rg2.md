# Resource Governor RG-2 Qualification — 2026-09-10

> Implementation commit: `924fc89` — `feat(resources): coordinate RG-2 provider calls`
> Parent: `c7da5c5` — RG-1 qualification HEAD
> Branch: `feature/resource-governor-rg2-provider-lease-20260910`
> Ruling: **PASS / CLOSE RG-2 scope**

## 1. Qualification scope

本报告只裁决 RG-2 已声明的窄范围：

- Task provider-call P0 lease；
- SubAgent provider-call P1 lease；
- local loopback MLX runtime 的 live concurrency observation；
- Task / SubAgent / Learning 对同一本地 runtime key 的竞争；
- lease terminal/exception/stream-close release；
- foreground service order 但不伪造 preemption；
- RG-1 Learning foreground barrier 行为不退化。

本报告**不**把以下能力算作通过：

- cloud concurrency；
- RPM / TPM；
- pricing / cost / quota；
- TrustDomain；
- provider cancel / request preemption；
- Linux / llama.cpp / GGUF runtime qualification；
- 多 provider alias 指向同一 physical runtime 的 identity 合并。

这些边界保持在 RG-2 设计声明之外。

## 2. Implementation boundary

相对 parent `c7da5c5`，implementation commit `924fc89` 精确 14 files：

```text
docs/DESIGN-20260910-adaptive-reasoning-learning-architecture.zh.md
docs/DESIGN-20260910-resource-governor-rg2.md
src/llm_loop/core/loop/engine.py
src/llm_loop/core/loop/engine_services/fallback.py
src/llm_loop/core/loop/engine_services/recovery_controller.py
src/llm_loop/factory.py
src/llm_loop/methods/learning_plane.py
src/llm_loop/resources/__init__.py
src/llm_loop/resources/local_runtime.py
src/llm_loop/resources/provider_calls.py
src/llm_loop/subagent/runner.py
tests/unit/test_learning_journal.py
tests/unit/test_provider_call_resources.py
tests/unit/test_resource_governor_contract.py
```

Commit stat：

```text
14 files changed
+1504 / -35
```

明确未修改：

```text
src/llm_loop/core/prompt.py
src/llm_loop/tools/**
src/llm_loop/llm/client.py
src/llm_loop/llm/pool.py
provider registry implementation
```

`ModelClientPool` 仍只负责模型/provider 路由与 client 生命周期，没有获得 resource scheduling 或任务语义裁决权。

## 3. Production call-site coverage

只读 provider-call inventory + 回归测试确认，当前生产真实路径全部进入 RG-2：

### Task primary

```text
LoopEngine chat_stream -> foreground_task_provider_stream -> P0 lease
LoopEngine sync chat   -> foreground_task_provider_chat   -> P0 lease
```

stream wrapper 额外验证：

- first `next()` 前完成 admission；
- provider send marker 在 lease 内发生；
- `StopIteration.value` 原样保留；
- normal terminal release；
- explicit `close()` release；
- exception release。

### Fallback

`FallbackService` 每个真实 fallback candidate 调用独立进入 P0 provider-call lease。

主 attempt 与 fallback 不共享 lease；跨 provider fallback 会重新观察目标 resource。

### ERR1210 retry

当前 production `RecoveryController` 的 changed-wire retry 独立持 P0 lease。真实 call-site 单测在 fake local provider 的 `chat()` 内直接观察到：

```text
ExecutionClass = FOREGROUND_TASK
ServicePriority = P0_FOREGROUND
```

retry terminal 后 active leases = 0。

`injection_span.py::_Err1210Mixin` 已不被 production LoopEngine 继承，保持 resource-unwired；没有为了静态覆盖率重新激活退役实现。

### SubAgent

真实 `SubAgentRunner.run()` call-site 单测在 `self.llm.chat()` 内观察到：

```text
ExecutionClass = SUBAGENT
ServicePriority = P1_ACTIVE_TASK_AUXILIARY
```

terminal 后 active leases = 0。

## 4. Cross-session / cross-execution contention

### 4.1 两个不同 Task Session

测试构造两个独立 Session，指向同一个 qualified local runtime：

```text
max_concurrency = 1
```

第一个 Task 已进入 provider 并持 P0 lease 时：

- 第二个 Task 进入 Governor pending；
- provider fake call count 仍为 1；
- in-flight = 1；
- 第一个 release 后第二个才进入 provider；
- 两者最终都完成；
- active leases = 0。

因此“不同 Session”不会绕过已资格化 local runtime concurrency。

### 4.2 Foreground vs SubAgent waiter

共享 single-slot key 时，已有 blocker release 后：

```text
P0 foreground waiter
before
P1 SubAgent waiter
```

相同 priority 继续使用 RG-1 arrival sequence FIFO。

### 4.3 Learning 使用同一 local runtime key

在 qualified 8901 adapter 下：

```text
Task resource key
== SubAgent resource key
== Learning resource key
== mlx-loopback:8901
```

因此已开始的 Learning 不再依赖独立 `rg1-learning-process:<model>` key 与新 Task 并发击穿同一 single-slot runtime。

对 cloud / 未资格化 runtime，Learning 仍保留 RG-1 fallback lane；RG-2 不伪造 cloud capacity。

## 5. Local runtime adapter qualification

当前 adapter 的事实链：

```text
client loopback URL
-> exact local port
-> lsof LISTEN PID
-> exactly one PID
-> ps command
-> mlx_lm.server
-> matching --port
-> explicit --prompt-concurrency
-> explicit --decode-concurrency
```

单元测试证明：

- remote endpoint 不触发 local probe；
- missing concurrency flags -> unknown；
- invalid values -> unknown；
- ambiguous multiple listener PID -> unknown；
- `--flag value` 与 `--flag=value` 均可解析；
- provider 名称不用于推断 runtime type/capacity；
- coordination limit 使用 `min(prompt_concurrency, decode_concurrency)`。

### 5.1 Live 8901 read-only observation

现有 8901 不重启情况下，adapter 真实观察：

```text
observed        = true
runtime_type    = local
resource_key    = mlx-loopback:8901
max_concurrency = 1
source_ref      = local-listener:8901:pid:<live-pid>
```

PID 仅作为瞬时 provenance，不进入代码/config 常量。

### 5.2 Observation cost

同一 live 8901 连续 20 次只读 observation：

```text
min     ~= 13.8 ms
median  ~= 14.3 ms
p95     ~= 16.0 ms
max     ~= 25.2 ms
```

RG-2 不加 TTL cache。当前开销相对本地大模型请求很小，而无缓存可避免 server restart / PID change / launcher concurrency change 后继续沿用 stale capacity。

## 6. Live 8901 serialization canary

在**同一个已加载 Ornith runtime** 上进行两次极短真实 provider request：

- 不启动第二本地模型；
- 不重启 8901；
- 不改 8901 launcher；
- qualification 请求显式 `reasoning_mode=off`，仅用于压缩测试时间，不改变生产 reasoning policy。

结果：

```text
adapter_observed                 true
adapter_limit                    1
resource_key                     mlx-loopback:8901
pending_seen_while_first_active  true
max_provider_inflight            1
active_leases_after              0
in_flight_after                  0
errors                           []
threads_alive_after              [false, false]
```

两次真实 provider response：

```text
first : prompt_tokens=24, completion_tokens=2, content_chars=2, elapsed~=1.616s
second: prompt_tokens=24, completion_tokens=2, content_chars=2, elapsed~=1.751s
```

这证明 RG-2 在 live single-slot runtime 上不是只“记一个 lease”，而是真正让第二个调用等待第一个 release 后再进入 provider。

## 7. Non-preemption ruling

RG-2 不支持 provider cancel。

因此：

```text
Learning already owns single-slot lease
+ new P0 Task arrives
=> Task waits
=> no fake cancel
=> Learning terminal/release
=> Task admitted next
```

这与 Resource Governor 的 service-order 定义一致：priority 决定**等待者服务顺序**，不改写正在运行的真实请求。

## 8. Prompt / tool / provider-visible invariants

### 8.1 Production source boundary

相对 RG-1：

```text
prompt production files          unchanged
tool implementation/schema files unchanged
LLMClient                         unchanged
ModelClientPool                   unchanged
```

### 8.2 Actual parent/candidate build comparison

用 RG-1 parent `c7da5c5` detached worktree 与 RG-2 candidate 使用同一隔离 Settings 实际 `build_engine`，比较同一序列化表示：

```text
registered provider-parameter surface
  parent    62 tools / 23652 bytes / SHA 8b8fb78b1552e7990fa0ddc5317c34299cce9bd1196ead16360921bd5c7aef37
  candidate 62 tools / 23652 bytes / SHA 8b8fb78b1552e7990fa0ddc5317c34299cce9bd1196ead16360921bd5c7aef37
  identical true

runtime-health projected provider-parameter surface
  parent    60 tools / 22978 bytes / SHA d0eb3cf4faa7a0aa4a0da872ac1f396ee56f9cd4fb3c19545ab33ffeedd42ea8
  candidate 60 tools / 22978 bytes / SHA d0eb3cf4faa7a0aa4a0da872ac1f396ee56f9cd4fb3c19545ab33ffeedd42ea8
  identical true
```

这些绝对 byte 数对应本次 probe 的“provider parameter object”序列化表示；RG-1 旧 qualification 中使用过另一 canonical 表示，因此**不跨表示比较绝对 bytes**。本阶段有效裁决是同一 probe 下 parent/candidate exact identity。

Universal Prompt source：

```text
parent SHA    30c6e3667ca8d4f10aeb0ab0e26667b1988f19a6879379137517070e2316e3d6
candidate SHA 30c6e3667ca8d4f10aeb0ab0e26667b1988f19a6879379137517070e2316e3d6
byte-identical true
```

因此 RG-2 没有通过资源治理向模型暗加 prompt/tool surface。

## 9. Static / regression gates

### Pre-commit staged candidate

```text
implementation files              14
staged security                   PASS
git diff --check                  PASS
Ruff src/tests                    PASS
Pyright                           0 errors / 0 warnings / 0 informations
py_compile changed runtime files  PASS
focused/adjacent suites           PASS
full pytest -m 'not real_llm'     100% / exit 0 / 156s
```

### Clean committed implementation `924fc89`

```text
git status                        clean
parent                            c7da5c5
git show --check                  PASS
focused/adjacent suites           PASS
Ruff src/tests                    PASS
Pyright                           0 errors / 0 warnings / 0 informations
py_compile                        PASS
tracked security                  PASS
full pytest -m 'not real_llm'     100% / exit 0 / 149s
```

测试侧 existing audit warning 仍主要来自 fixture 中公开/invalid provider URL；本次新增假本地模型路径最初触发 security gate 后已直接改为平台中性 fixture，**没有放宽 security allowlist**。

## 10. LLM-First authority audit

`local_runtime.py` 与 `provider_calls.py` 没有 task/prompt semantic payload，也没有：

```text
quality
complexity
importance
relevance
completion
method_applicability
should_run
```

作为 admission 输入。

资源层只读取：

```text
already-selected client/provider/model
endpoint identity
live listener/process facts
explicit concurrency
execution class
service priority
lease ownership
```

因此 RG-2 没有形成“程序替模型决定哪个任务值得运行”的第二决策系统。

## 11. Known limits / not qualified

### 11.1 Multi-process LFL

Governor lease ledger 仍是当前 LFL 进程内；多个 LFL 进程同时调用同一个 8901 尚不是跨进程 provider semaphore。

### 11.2 Multiple provider aliases -> one endpoint

当前 `ResourceKey` identity 含 `provider_id`。若未来把两个 provider alias 都指向同一个物理 8901，不能宣称它们已自动合并成一个 runtime lease；需要先扩展 physical-runtime identity contract 并独立资格化。

### 11.3 Other local runtimes

GGUF / llama.cpp / Linux / remote self-hosted runtime 尚未进入 RG-2 live adapter qualification。不能因为都“是本地模型”就自动套用 MLX 结论。

### 11.4 Cloud

GLM / MiniMax / DeepSeek cloud concurrency、RPM/TPM、quota/cost 仍未接入。remote endpoint 在 RG-2 保持既有调用行为，**不是被宣称 unlimited**。

## 12. Final ruling

RG-2 声明范围 **PASS / CLOSE**。

已经证明：

1. Task / SubAgent 的 production provider calls 已进入共享 Resource Governor；
2. fallback 与当前 production 1210 retry 没有绕过；
3. live 8901 concurrency 来自当前 listener/process explicit facts，不从 provider 名称或静态 registry 猜；
4. 不同 Session / Task / SubAgent / Learning 可在同一 qualified local runtime key 上机械竞争；
5. service priority 对等待者生效，但不伪造 preemption；
6. stream terminal/close/exception 与 sync terminal/exception 都不会泄漏 lease；
7. prompt/tool/provider-visible surface 相对 RG-1 不变；
8. implementation clean committed-state 全量回归通过；
9. 未混入 RG-3/RG-4/RG-5 的 rate/cost/trust/cancel 权力。

下一阶段若继续，应进入 **RG-3 cloud mechanical resource facts**：先只读冻结 GLM / MiniMax / DeepSeek 的 provider/account/project/model concurrency 与 rate-window 事实来源，再决定最小 adapter；不应直接把静态套餐文档数字硬编码进 Governor。
