# DESIGN-20260910：Resource Governor RG-3A Cloud Resource Facts Contract

> 状态：**contract-only implementation candidate**
> 统一基线：`integration/rg3-unified-20260910@608ec12`
> 前置：Learning P0 + RG-0/RG-1/RG-2 已资格化；b6 的 restart/CI 独立更新已并入统一基线。
> 本阶段不接 cloud enforcement、不改 provider routing、不改 TrustDomain/cancel、不修改 8901。

## 0. 裁决

RG-3A 不把 GLM / MiniMax / DeepSeek 压成一组静态 RPM/TPM/价格常量，也不从 provider 名、
base URL、模型名或 `cost_tier` 猜账号资源。它只冻结**机械事实词汇表**，让后续 RG-3B~E
能够从显式 operator/provider 事实出发，而不是把“未知”误当成“无限”。

本阶段新增五类合同：

1. `ResourceProductIdentity`：显式 product/account/api-family/region/project alias；
2. `ProviderUsageFacts` / `ProviderErrorFacts`：provider 响应的安全、可空、可追溯事实；
3. `QuotaSpec` / `QuotaUsage`：token/request/provider-defined quota；
4. `PricingSchedule` / `PricingRule`：动态时间、输入长度、service tier、provider unit、订阅周期；
5. `ResourceRequirement(key, dimension)`：同一 scope 的 concurrency/rate/quota/cost **互不蕴含**。

## 1. 为什么不能沿用 RG-2 的单一 concurrency 语义

RG-2 的 `ResourceKey` 已能表达 provider/account/project/model/runtime scope，但当前 Governor
把传入的每个 key 都理解为“必须存在 max_concurrency 才能 admission”。这对本地 8901 的
单 slot runtime 是正确的，对 cloud rate-only / quota-only / cost-only scope 则不成立。

RG-3A 因此新增：

```text
ResourceRequirement {
  key: ResourceKey
  dimension: concurrency | rate | quota | cost
}
```

**一个 account key 可以只有 quota/cost，没有已知 concurrency。** RG-3A 只表达这个事实；
Governor 如何分别执行四个维度留到 RG-3E，避免本阶段为了“接上”而伪造 concurrency=1/∞。

## 2. Product identity：禁止按 provider 猜套餐

```text
ResourceProductIdentity {
  provider_id
  product_id
  account_alias      # 非 secret 本地别名，不是账号号/Key
  api_family?
  region?
  project_alias?
  provenance
}
```

同一 provider 可以同时存在不同产品、账号、区域、endpoint family；这些对象的 quota/rate/
pricing 语义可能不同。运行时必须通过显式事实绑定，不能写：

```python
if provider == "...":
    assume_rpm = ...
```

RG-3A 的 contract 模块也通过测试禁止出现具体 vendor 名，保证数据模型 provider-agnostic。

## 3. Usage：`None` 与 `0` 必须分离

既有 `LLMResponse.prompt_tokens/completion_tokens` 用 `0` 同时承担“provider 未给 usage”和
“真实值为 0”两种含义，适合历史 UI/telemetry 兼容，但不能作为 cloud Resource Governor
的 source of truth。

新合同：

```text
ProviderUsageFacts {
  provider_id / model_id / product?
  input_tokens?: int
  output_tokens?: int
  cached_input_tokens?: int
  reasoning_tokens?: int
  total_tokens?: int
  provider_units?: Decimal
  provider_unit?: str
  provenance
}
```

`None = 未报告/未知`；`0 = provider 明确报告 0`。provider-defined 计划单位保持 opaque，
绝不冒充 token。

## 4. Error / reset facts：只保留安全归一字段

当前 `LLMHTTPError` 保存 status/body/provider，但没有结构化保留 `Retry-After` / reset facts。
RG-3A 不直接改 transport；先定义未来 transport 可以写入的安全合同：

```text
ProviderErrorFacts {
  provider_id / model_id / product?
  status_code?
  provider_code?
  retry_after_seconds?
  rate_limits: RateLimitResetFacts[]
  provenance
}
```

`RateLimitResetFacts` 可记录 requests/input/output/total-token metric 的 limit/remaining/window/
reset_at/reset_after。**合同故意没有 raw headers/body/cookie/auth/prompt/messages/api_key 字段**。
RG-3B 只允许从白名单 header 映射为这些 typed facts，避免把 header bag 变成新的数据泄露面。

## 5. Quota：独立于 rate 和 cost

Rate 是滚动速率，Quota 是额度；二者不能用同一字段替代。新合同支持：

```text
QuotaSpec / QuotaUsage {
  metric: requests | input_tokens | output_tokens | total_tokens | provider_units
  limit/used: Decimal
  window_seconds?
  reset_at?
  provider_unit?
  provenance
}
```

`provider_units` 用于 vendor 自定义套餐单位或加权额度；名称必须显式记录，模型/程序都不得
把它自动换算成 token、美元或真实运行秒数。

## 6. Pricing：静态 TokenPricing 继续兼容，新增动态 schedule

RG-0 的 `TokenPricing` 适合“一个模型一组静态 token 单价”，但不能完整表达：

- 价格随有效时间窗口变化；
- 价格随输入长度档位变化；
- service tier 不同价格不同；
- provider-defined unit 计价；
- subscription period 计价。

因此新增：

```text
PricingSchedule {
  product
  model_id?
  rules: PricingRule[]
  provenance
}

PricingRule {
  rule_id
  basis: input_million_tokens | cached_input_million_tokens |
         output_million_tokens | provider_unit | subscription_period
  price: MoneyAmount
  min_input_tokens? / max_input_tokens?
  service_tier?
  effective_from? / effective_until?
  provider_unit?
  period_seconds?
}
```

时间型价格由未来 adapter 根据 authoritative facts **物化成当前有效区间**；RG 不从日期、
provider 名或“峰谷经验”自行猜价格。一个 schedule 内只允许一种 currency，跨 currency
必须拆成不同 schedule。

## 7. Declared / observed profile 扩展

`DeclaredResourceProfile` 新增：

```text
quota_limits[]
product?
```

`ObservedResourceState` 新增：

```text
quota_usage[]
product?
```

`max_concurrency=None` 与上述字段同时存在是合法状态。这正是 RG-3A 要固定的关键语义：
**有 quota/cost/rate 事实不代表存在 concurrency 事实。**

## 8. Authority boundary

RG-3A 程序可以：

- 校验类型、非负数、时间区间、provider identity 一致性；
- 区分 unknown 与 zero；
- 保存非 secret provenance；
- 记录 operator/provider documentation/control-plane/response/usage-ledger 的来源类型。

RG-3A 程序不可以：

- 根据任务内容、质量、价值、复杂度决定是否值得花资源；
- 根据 provider 名猜套餐、RPM/TPM、并发、价格；
- 把缺失 header/usage 当作 0 或 unlimited；
- 根据 `cost_tier` 估算真实费用；
- 自动跨 provider 发送材料；
- 接管模型选择、Method applicability、completion；
- 实施 TrustDomain/cancel policy。

## 9. 本阶段显式不接线

下列生产路径在 RG-3A 必须保持行为不变：

```text
ResourceGovernor
ProviderCallCoordinator
LLMClient transport
Task / Fallback / 1210 recovery
SubAgent
Learning Plane
MemoryExtractor
Summarizer
```

也就是说，RG-3A 的新类型可以被 import/test/document，但不能被上述 production path 消费。

## 10. 后续顺序

### RG-3B — Transport Observation / Shadow

- HTTP/SSE 响应中只解析白名单 usage/error/reset facts；
- 不阻断请求；
- 不改 fallback；
- 记录 `None` 与 `0`；
- 验证三家真实返回差异。

### RG-3C — Unified Provider-Call Settlement

- Task / SubAgent / Learning / MemoryExtractor / Summarizer 统一从 provider-call boundary 结算；
- `request.usage` 继续作为 Task UI/event projection，不作为账号资源账唯一 SoT；
- execution class 分账。

### RG-3D — Vendor Fact Adapters

- GLM / MiniMax / DeepSeek 只负责把 authoritative product/account/plan/response 事实翻译成统一合同；
- adapter 不拥有策略权；
- endpoint/product identity 显式配置，不按 URL 猜套餐。

### RG-3E — Qualification / Enforcement

- concurrency/rate/quota/cost 四维独立 enforcement；
- unknown 不伪造 unlimited；
- foreground service order 不变；
- 先 shadow A/B，再有限 enforce。

TrustDomain 与 cancel 继续独立阶段处理。

## 11. RG-3A 验收

1. 新 contract 单测覆盖 product identity、unknown-vs-zero、safe error/reset、quota、pricing；
2. 证明 rate/quota/cost requirement 可在 `max_concurrency=None` 下合法存在；
3. contract 模块无 GLM/MiniMax/DeepSeek 硬编码；
4. Governor/Coordinator/LLMClient 不引用 RG-3A 新类型；
5. 既有 RG-0/RG-1/RG-2 测试全绿；
6. Ruff / Pyright / py_compile / git diff --check 全绿；
7. full non-real-LLM regression 100%/exit 0；
8. 不重启 8901，不做 cloud live call，不接 enforcement。

达到以上条件，RG-3A 才可独立提交；随后进入 RG-3B。
