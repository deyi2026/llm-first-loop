# DESIGN-20260910：Unified Resource Governor RG-0

> 状态：**RG-0 CONTRACT BASELINE**
> 上位 Architecture SoT：`docs/DESIGN-20260910-adaptive-reasoning-learning-architecture.zh.md`
> 本阶段：只冻结权力边界、数据契约和验证矩阵；**不接管 LoopEngine / Learning / SubAgent / ProviderPool，不改变任何 provider 请求行为。**

---

## 1. 目的

LFL 已经存在多种彼此独立的执行面：

- 用户前台 Task；
- SubAgent；
- Deliberation / Reasoning Lab（待实现）；
- Background Learning；
- Qualification；
- Meta-Learning（待实现）。

它们最终都会消耗同一批真实资源：本地 GPU / unified memory / prompt slot / KV cache，或云端 provider 的并发、RPM、TPM、账户/项目 quota 与费用预算。

RG-0 的目标不是实现一个“更聪明的调度器”，而是先冻结一个最小、可验证、provider-agnostic 的机械合同：

> **Resource Governor 只回答“这个已选择的执行请求在当前真实资源边界下能否现在获得资源”；它不回答“这个任务值不值得做、哪个模型更聪明、哪个 Method 更适用、任务是否完成”。**

---

## 2. 2026-09-10 只读审计基线

### 2.1 当前资源控制是碎片化的

现有代码中：

- `ModelClientPool` 负责 provider/model resolve、client cache 与机械 fallback candidate canonicalization；它不是并发/优先级调度器。
- `BackgroundRunner` 对同 Session 做互斥，但不同 Session 可以各自启动 daemon thread，没有 provider/model/account 级统一并发门。
- `SubAgentRunner` 有独立后台线程和 handle 容量，当前 `_max_handles=128` 约束的是本地 handle 资源，不等价于 provider 并发限制。
- `LearningPlane` 已有 foreground-first admission，但它自己检查 foreground busy，并不知道 cloud RPM/TPM、账户 quota 或其他执行面的 provider 占用。
- `LLMClient` 使用 provider HTTP transport；当前没有通用 provider-request `cancel/abort` hook，因此一个已经进入 provider 的请求不能被 Resource Governor 虚构成“可抢占”。

### 2.2 现有 usage 事实可以复用

`request.usage` 已经记录：

```text
model
tokens_in / tokens_out
reasoning_tokens
cache_hit / cache_miss / cache_read_tokens
context_window / output_reserve / headroom
stable_prefix / cache epoch / compaction epoch
runtime_pid
timing
usage_available
```

这些是后续 UsageAccounting 的良好机械基础。

当前缺失：

```text
provider_id
execution_class
resource_scope
admission/queue timestamps
active concurrency
rolling RPM/TPM usage
money cost / pricing provenance
trust-domain admission facts
```

### 2.3 静态声明不能等于 live truth

只读 live audit 已经证明，静态 provider registry 的 runtime metadata 可能落后于真实 serving runtime。当前本地服务真实运行在 MLX，并显式配置单 prompt/decode concurrency 和有限 prompt-cache slots，但 registry 中仍存在旧 runtime identity；输出上限的 registry 声明与 launcher 默认值也存在差异，需要 adapter 进一步解释真实 effective semantics。

因此长期不变量：

> **Declared profile 与 Observed runtime state 必须分离；每条事实必须带 provenance 和 acquisition time，任何一侧都不能静默覆盖另一侧。**

---

## 3. Authority Map

### 3.1 Resource Governor 可以拥有的权力

仅限机械资源事实和不可替代的硬边界：

1. 维护当前已获得的 resource leases；
2. 对同一 provider/resource scope 计算当前 in-flight 数；
3. 按 operator/provider 明确声明的并发硬上限做 admission；
4. 按真实 rate-limit contract 维护 requests/tokens rolling window；
5. 按真实 pricing + operator budget 做金额预算检查；
6. 按 TrustDomainPolicy 的明确 allow relation 阻止未授权数据出域；
7. 根据 provider/runtime 明确证明的 cancel/priority 能力决定是否可以调用对应机制；
8. 记录 admitted / deferred / hard-rejected / released 等事实；
9. 为 usage accounting 提供 execution class、resource scope、queue/admission provenance。

### 3.2 Resource Governor 永远不能拥有的权力

禁止：

```text
根据任务文本判断 complexity / importance / value
根据 Method/Experience 判断任务是否值得占资源
判断哪个模型“更聪明”或“更适合当前语义任务”
因价格高低自动改选另一个模型
因后台任务“看起来不重要”而永久取消
判断 Evidence 是否足够
判断 Deliberation 是否需要发生
判断 Method 是否适用
判断 Task 是否完成
把 service priority 当成 task priority / semantic priority
```

Provider/model 的语义选择继续由用户/模型/既有明确调用关系决定；Governor 对**已选择目标**只做资源 admission。若目标暂时不可用，Governor 返回事实，不自行挑选“更好模型”。

### 3.3 不新增 prompt authority

RG-0 以及未来 Governor 默认都是 prompt-neutral runtime infrastructure。

Resource admission 事实可进入 telemetry / runtime receipt；不得自动注入“建议模型下一步怎么做”的 system/user prose。

---

## 4. ExecutionClass 与 ServicePriority 分离

### 4.1 ExecutionClass

固定六类：

```text
FOREGROUND_TASK
SUBAGENT
DELIBERATION
BACKGROUND_LEARNING
QUALIFICATION
META_LEARNING
```

它回答：

> **这次计算属于哪个执行平面？**

它也是未来 usage 分账的 canonical class。

### 4.2 ServicePriority

固定服务级别：

```text
P0 FOREGROUND
P1 ACTIVE_TASK_AUXILIARY
P2 BACKGROUND_DELIBERATION
P3 BACKGROUND_LEARNING
P4 QUALIFICATION
P5 META_LEARNING
```

它回答：

> **当相同物理资源发生竞争时，谁先获得服务？**

它不表示任务“更重要”或“质量更高”。

### 4.3 为什么 ExecutionClass 和 Priority 不能合并

`DELIBERATION` 有两种机械调用关系：

- 当前用户 Task 主动请求/模型在当前 Task 中调用 → P1；
- 显式安排为后台 Deliberation → P2。

所以不能写成：

```text
if execution_class == DELIBERATION:
    priority = 固定某个语义优先级
```

而应由**调用关系事实**给出 ServicePriority。未来如果 SubAgent 出现真正后台型场景，也使用同一机制，不新造语义分类器。

---

## 5. Resource Scope：一次请求可以同时消耗多个机械资源

云端请求通常不是只受一个限制。例如一次 GLM 请求可能同时消耗：

```text
account RPM
project TPM
model concurrency
```

本地请求可能同时消耗：

```text
runtime prompt slot
model/runtime memory capacity
cache slots
```

因此 `AdmissionRequest` 使用：

```text
resource_keys: tuple[ResourceKey, ...]
```

而不是单一 resource key。

Scope 固定为：

```text
RUNTIME
PROVIDER
ACCOUNT
PROJECT
MODEL
```

要求：

- 一个 AdmissionRequest 的所有 resource keys 属于同一个已经选择的 provider；
- 多 scope admission 最终必须原子化：全部获得 lease，或全部不获得；
- 跨 provider alternative 是另一个 AdmissionRequest，Governor 不自行跨 provider 改写请求；
- `scope_id` 使用稳定、非秘密的 operator alias，不保存 API key、token 或原始秘密账户凭据。

---

## 6. DeclaredResourceProfile 与 ObservedResourceState

### 6.1 DeclaredResourceProfile

来源可以是：

- operator config；
- provider 官方/账户配置经过人工确认后落入本地配置；
- runtime 启动配置的持久声明。

可描述：

```text
runtime_type
max_concurrency
rate_limits[]
cost_budget
trust_domain
supports_cancel
supports_priority
supports_parallelism
```

### 6.2 ObservedResourceState

来源必须是可验证的实时/近期事实，例如：

- runtime capability probe；
- provider response/header；
- LFL usage ledger。

可描述：

```text
runtime_type
runtime_model_id
runtime_max_output_tokens
max_concurrency
in_flight
rate_usage[]
cost_usage + exact window
local_memory_pressure
local_cache_slots_total / used
supports_cancel / priority / parallelism
```

### 6.3 UNKNOWN 的语义

使用显式三态：

```text
YES
NO
UNKNOWN
```

以及 Optional 数值。

必须满足：

```text
UNKNOWN != NO
UNKNOWN != 0
UNKNOWN != unlimited
```

禁止根据 provider 名称推断：

```text
provider_id == "local" -> runtime_type=LOCAL
provider_id == "glm" -> runtime_type=CLOUD
```

这些看起来“显然”的推断也不是机械事实。

### 6.4 冲突处理留给 RG-1 的显式 reconciliation

RG-0 不把 declared 和 observed 合并成一个“真值对象”。

RG-1 只能在：

- scope 相同；
- metric/window 语义相同；
- provenance 明确；
- freshness policy 明确；

的前提下计算 effective hard cap。冲突必须显式暴露，不能静默选一个方便值。

---

## 7. Rate Limit：不把所有厂家强行简化成同一个 TPM

统一 contract 使用：

```text
RateLimitMetric:
  REQUESTS
  INPUT_TOKENS
  OUTPUT_TOKENS
  TOTAL_TOKENS

RateLimitSpec:
  metric
  limit
  window_seconds
```

RPM = `REQUESTS + 60s` 的常见实例；TPM 根据厂家真实口径映射成对应 token metric + 60s。

禁止：

- 不看厂家口径就把所有 token 限制算成 `tokens_in + tokens_out`；
- 从一次 429 反推出永久 RPM/TPM；
- 把历史 429 次数当成当前剩余额度。

429/provider quota response 只能成为新的 provider-response observation；真实限额仍需要有来源的 declared/observed contract。

---

## 8. Pricing 与 Cost Budget

当前 `cost_tier=free/low/mid/high` 只是展示元数据，**不能用于金额计算或 admission**。

RG-0 定义：

```text
TokenPricing        # provider/model target fact，独立于 resource scope profile
MoneyAmount
CostBudget          # scope-level limit + exact window
CostUsage           # observed usage + exact window
```

规则：

- 金额使用 Decimal；
- pricing 可以分别记录 input / cached input / output，并独立绑定 provider/model target；
- 每个价格必须带 provenance；
- 未知价格保持 None；
- 不允许根据 cost_tier 猜价格；
- `estimated_cost` 只能由已知 token estimate + 已知 pricing 机械产生；
- 没有真实 pricing 时，不做伪成本 admission。

后续 Learning/Qualification/Meta-Learning 的 token 与费用必须单独分账，不能混入用户 foreground solved-task 成本。

---

## 9. Trust Domain

RG-0 只定义 `TrustConstraint`：

```text
material_domain
allowed_execution_domains[]
provenance
```

它表达的是：

> 某段材料根据明确 policy 被允许发送到哪些 execution domains。

它不表达内容“敏不敏感”的模型猜测。

来源必须是 operator/policy 的机械事实。未来 RG-4 的 TrustDomainPolicy 负责生成该 allow relation，Resource Governor 只执行它。

如果 policy 要求“必须证明允许才能外发”，而目标 trust-domain 未知，则应 fail-closed；这属于数据出域硬边界，不是语义任务判断。

当前 `cache_guard` 的 secret/privacy leak 检查不能替代 TrustDomainPolicy：前者防止明显秘密泄漏，后者控制“允许哪些任务材料进入哪些 provider domain”。

---

## 10. AdmissionRequest

Canonical 字段：

```text
request_id
owner_ref
execution_class
service_priority
provider_id
model_id
resource_keys[]
submitted_at
estimated_input_tokens?
reserved_output_tokens?
estimated_cost?
trust_constraint?
```

明确不允许包含：

```text
task_text
prompt
messages
quality_score
complexity
relevance
importance
completion
method_applicability
```

`owner_ref` 只用于机械 lineage，例如：

```text
run:<id>
subagent:<id>
learning:<id>
deliberation:<id>
qualification:<id>
meta-learning:<id>
```

Governor 不读取 owner 对象的语义内容。

---

## 11. AdmissionDecision 与 ResourceLease

Outcome：

```text
ADMITTED
DEFERRED
HARD_REJECTED
```

机械 reason codes：

```text
AVAILABLE
CONCURRENCY_FULL
REQUEST_RATE_LIMIT
TOKEN_RATE_LIMIT
COST_BUDGET_EXHAUSTED
TRUST_DOMAIN_FORBIDDEN
RUNTIME_UNAVAILABLE
REQUIRED_FACT_UNKNOWN
FACT_CONFLICT
CANCELLED_BEFORE_START
```

规则：

- ADMITTED 必须携带 ResourceLease；
- 非 ADMITTED 不能携带 lease；
- AVAILABLE 只能用于 ADMITTED；
- defer/reject 可带 blocked resource keys；
- provider 明确提供 Retry-After 或本地 lease 可预测释放时，才能给真实 retry-after；不能猜。

未来 lease 生命周期：

```text
request submitted
    ↓
queued
    ↓
admitted + atomic resource lease
    ↓
provider call
    ↓
usage observation
    ↓
lease release
```

异常路径也必须最终 release；restart 不允许凭旧 PID/线程对象伪造 lease 仍有效。

---

## 12. Cancellation / Preemption

当前通用 `LLMClient` 没有 provider-request cancel hook。

因此默认：

```text
supports_cancel = UNKNOWN / NO
```

除非某个 adapter 真实证明：

- 当前 request 可以被 provider/runtime 定向取消；
- 取消不会造成重复输出/重复 side effect；
- cancellation receipt 可被机械确认。

Foreground-first 在“不支持取消”的 runtime 上意味着：

> **阻止新的后台请求进入资源，而不是假装可以抢占已经发出的后台 provider call。**

这正是当前 Learning P0 的实际能力边界，后续不能用“preemption”一词夸大。

---

## 13. Provider Adapter 边界

未来 adapter 负责“感官”，不是策略。

### 本地 runtime adapter

可观测：

```text
actual serving runtime identity
actual loaded model
configured/effective prompt concurrency
configured/effective decode concurrency
cache slot capacity/occupancy（若 runtime 提供）
memory pressure（若 runtime 提供）
cancel/priority capability（若 runtime 提供）
```

### Cloud adapter

可观测/声明：

```text
provider/account/project/model resource scopes
explicit concurrency contract
rate-limit response facts
RPM/TPM contract
Retry-After
quota/budget state（若 API 明确提供）
pricing provenance
cancel/priority support
trust domain
```

不能从“GLM / MiniMax / DeepSeek”名称硬编码这些事实；厂商规则变化时必须能独立更新 adapter/profile。

---

## 14. 与现有组件的未来接入顺序

### RG-0（当前阶段）

```text
contract module
+ authority design
+ test matrix
```

**零 runtime wiring。**

### RG-1

引入最小 `ResourceGovernor`：

1. 只实现 lease / concurrency / foreground service order；
2. 把 LearningPlane 当前 foreground gate 迁入 Governor；
3. 对当前 local single-slot 行为做 byte/behavior-equivalent qualification；
4. 不接 Cloud rate/cost/trust enforcement；
5. 不改变用户 Task provider 路由。

### RG-2

让：

```text
Task
SubAgent
Learning
未来 Deliberation
```

在真正 provider call 前统一请求 lease。

重点验证不同 Session / SubAgent 不能绕过 provider concurrency。

### RG-3

加入 cloud：

```text
concurrency
rate windows
RPM/TPM
pricing/cost accounting
quota observations
429 reconciliation
```

只使用明确配置/官方事实，不猜值。

### RG-4

接入 `TrustDomainPolicy`，建立跨 provider 数据出域硬边界。

### RG-5

只对真实支持 cancel/priority 的 provider/runtime adapter 启用请求级取消/优先级能力。

---

## 15. RG-0 测试矩阵

| Gate | 要证明的事实 | RG-0 |
|---|---|---|
| C01 | ExecutionClass 恰好六类 | 自动化 |
| C02 | P0-P5 服务顺序固定，priority 不等于 semantic importance | 自动化 + 文档 |
| C03 | Deliberation P1/P2 由 invocation relation 表达，不新造 execution class | 自动化 |
| C04 | runtime type 不从 provider 名称推断 | 自动化 |
| C05 | declared / observed 是两个独立对象 | 自动化 |
| C06 | UNKNOWN 明确保留，不伪装 false/0/unlimited | 自动化 |
| C07 | rate contract 支持 metric + window，不写死厂商 TPM 口径 | 自动化 |
| C08 | pricing 用 Decimal，未知价格不猜 | 自动化 |
| C09 | 一个 request 可绑定同 provider 多 resource scopes | 自动化 |
| C10 | cross-provider resource key / duplicate key fail fast | 自动化 |
| C11 | trust allow relation 带 provenance | 自动化 |
| C12 | ADMITTED 必须有 lease，非 admitted 不得伪 lease | 自动化 |
| C13 | contract dataclass 无 prompt/task semantic payload | 自动化 |
| C14 | contract module 无 LFL runtime plane import | 自动化 |
| C15 | RG-0 不接 Engine/Learning/SubAgent/ProviderPool | 自动化静态 guard |
| C16 | Universal Prompt 字节/SHA 不变 | qualification |
| C17 | provider-visible tool/schema surface 不变 | qualification |
| C18 | full non-real-LLM 无新增回归 | qualification |

---

## 16. RG-1～RG-5 必须预留的验证矩阵

### RG-1 Local concurrency / Learning parity

- max_concurrency=1 时 foreground 已占 lease → Learning DEFERRED；
- foreground release 后 Learning 可获得 lease；
- queue/admission 不修改 Session message；
- 不支持 cancel 时，已开始 Learning 不宣称被抢占；
- 当前 Learning P0 live 时序不退化；
- prompt/cache prefix 不因 Resource Governor 新增自动文本而变化。

### RG-2 Cross-execution contention

- 两个不同 Session 竞争同 runtime key；
- foreground + SubAgent 竞争；
- SubAgent + Learning 竞争；
- 多 resource scopes 必须原子 lease，无 partial acquisition deadlock；
- crash/failure 必须 release 或可机械 reconcile。

### RG-3 Cloud rate/cost

- request window / token window 精确边界；
- provider/account/project 多 scope 同时限流；
- 真实 429/Retry-After observation 更新事实，但不改任务语义；
- pricing unknown 时 estimated cost 保持 unknown；
- foreground / learning / qualification usage 分账；
- GLM / MiniMax / DeepSeek 使用同一 contract，不复制三套 scheduler。

### RG-4 Trust Domain

- local-only material 不能进入 cloud domain；
- cloud-approved material 只能进入 explicit allow domain；
- provider-restricted material 不因另一 provider idle 自动跨域；
- trust-domain unknown 在 required-proof policy 下 fail-closed；
- Trust rejection 不产生模型可见训诫型 prompt 注入。

### RG-5 Cancel/Priority capability

- UNKNOWN/NO provider 不调用 fake cancel；
- YES provider 必须由 adapter qualification 证明；
- cancellation result 有真实 receipt；
- cancel 失败不伪造“已停止”；
- service priority 只影响等待队列，不改变模型/任务语义。

---

## 17. RG-0 Acceptance

RG-0 只有同时满足以下条件才可收口：

1. `contracts.py` 只依赖 Python stdlib；
2. 无 `ResourceGovernor` runtime scheduler 实现；
3. LoopEngine / Factory / LearningPlane / SubAgentRunner / ModelClientPool 均不 import RG-0 package；
4. Universal Prompt 不变；
5. provider-visible tools/schema 不变；
6. RG-0 contract tests 全绿；
7. Ruff / Pyright / py_compile / diff-check 全绿；
8. full non-real-LLM 全绿；
9. security/privacy scan 全绿；
10. 不修改 ignored runtime provider registry，不重启本地/云端服务。

---

## 18. 最终裁决

Resource Governor 的正确抽象不是：

> “程序根据任务价值挑模型、控制模型什么时候值得思考。”

而是：

> **“上层已经决定要执行什么；程序如实告诉它哪些资源现在真实可用、哪些硬边界禁止越过，并用可恢复 lease 确保多个执行面不会相互踩踏。”**

这与 LFL 的核心权力边界一致：

> **模型负责方向；Resource Governor 负责道路容量、收费站、边界线和真实交通状态。**
