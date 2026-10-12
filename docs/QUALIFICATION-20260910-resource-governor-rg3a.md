# QUALIFICATION-20260910：Resource Governor RG-3A Cloud Resource Facts

> 状态：**QUALIFIED on unified integration feature candidate**
> Implementation commit：`62ddbd4 feat(resources): define RG-3A cloud resource facts`
> Unified baseline：`608ec12 chore(integration): preserve restart and CI hardening on RG-2 baseline`
> 前置 RG-2 qualification：`docs/QUALIFICATION-20260910-resource-governor-rg2.md`
> 专项设计：`docs/DESIGN-20260910-resource-governor-rg3a-cloud-facts.md`

## 1. 本次资格范围

RG-3A 只验证 **cloud resource facts contract**，不验证 cloud enforcement，也不把任何
GLM / MiniMax / DeepSeek 的当前套餐数字硬编码进运行时。

本阶段实现范围严格为 5 个文件：

1. `src/llm_loop/resources/contracts.py`
2. `src/llm_loop/resources/__init__.py`
3. `tests/unit/test_resource_governor_cloud_contract.py`
4. `docs/DESIGN-20260910-resource-governor-rg3a-cloud-facts.md`
5. `docs/DESIGN-20260910-adaptive-reasoning-learning-architecture.zh.md`

实现 commit 统计：**5 files changed, +872 / -1**。

## 2. 已冻结合同

### 2.1 Product / account identity

新增 `ResourceProductIdentity`：

```text
provider_id
product_id
account_alias
api_family?
region?
project_alias?
provenance
```

约束：product/account/region/api family 都必须来自显式机械事实；不得从 provider 名、
base URL、模型名、`cost_tier` 自动推导套餐。

### 2.2 Resource dimensions

新增：

```text
ResourceDimension = concurrency | rate | quota | cost
ResourceRequirement(key, dimension)
```

同一个 `ResourceKey` 可以只有 rate/quota/cost，`max_concurrency=None` 完全合法。
这消除了“有 cloud quota key 就必须伪造 concurrency”这一错误建模压力。

### 2.3 Provider usage facts

新增 `ProviderUsageFacts`：

- `input_tokens`
- `output_tokens`
- `cached_input_tokens`
- `reasoning_tokens`
- `total_tokens`
- `provider_units / provider_unit`
- product + provenance

所有数值均可为 `None`；**`None = provider 未报告/未知`，`0 = provider 明确报告 0`**。
provider-defined units 使用 `Decimal` 并保持 opaque，不自动折算成 token/美元/时间。

### 2.4 Provider error/reset facts

新增 `ProviderErrorFacts` + `RateLimitResetFacts`，可表达：

- HTTP status
- provider business code
- normalized retry-after
- limit / remaining / exact window / reset time
- provider/model/product/provenance

合同明确没有：raw headers、raw body、cookie、Authorization、API key、prompt、messages。
后续 RG-3B transport 只能白名单归一为 typed facts，不允许直接保存 header bag。

### 2.5 Quota

新增 `QuotaSpec` / `QuotaUsage`：

```text
requests
input_tokens
output_tokens
total_tokens
provider_units
```

Quota 与 rate、cost、concurrency 分离。`provider_units` 需要显式 `provider_unit` 名称，
避免把套餐自定义权重单位误当标准 token 或 wall-clock seconds。

`DeclaredResourceProfile` 新增 `quota_limits/product`；
`ObservedResourceState` 新增 `quota_usage/product`；全部带默认空值，RG-2 本地路径行为不变。

### 2.6 Dynamic pricing

保留 RG-0 的 `TokenPricing` 兼容合同，同时新增 `PricingSchedule` / `PricingRule`：

- input/cached-input/output per-million-token basis
- provider-unit basis
- subscription-period basis
- input length bounds
- service tier
- effective time interval
- one-currency-per-schedule

这允许未来 adapter 表达时段价、长度档位价、service-tier 价和订阅产品，而不把三家
云厂商强行压成一个静态 `TokenPricing`。

## 3. LLM-First / Authority 验证

新增合同字段经过机械反例测试，禁止出现：

```text
task_text
prompt
messages
quality / quality_score
complexity
relevance / importance
completion
should_run
method_applicability
model_preference
```

`contracts.py` 还被测试确认没有 `glm` / `minimax` / `deepseek` vendor 名硬编码。

因此 RG-3A 仍然只提供**资源事实语言**，没有形成第二套模型选择、任务价值或完成判断系统。

## 4. Runtime 零接线验证

资格测试明确检查以下 production 文件没有引用 RG-3A 新 cloud 类型：

```text
src/llm_loop/resources/governor.py
src/llm_loop/resources/provider_calls.py
src/llm_loop/llm/client.py
```

本阶段也没有修改：

```text
Task primary/fallback/1210 recovery
SubAgent
Learning Plane
MemoryExtractor
Summarizer
ProviderRegistry / ModelClientPool
```

因此：

- 没有 cloud admission/enforcement 行为变化；
- 没有 fallback 行为变化；
- 没有 provider routing 变化；
- 没有跨 provider 自动外发；
- 没有 TrustDomain/cancel 接线；
- 没有 8901 配置、进程或模型变化。

## 5. Precommit 验证

在 `integration/rg3-unified-20260910`、父基线 `608ec12` 上：

- resource/cloud focused：**48/48 PASS**
- Ruff `src tests`：**PASS**
- Pyright：**0 errors / 0 warnings / 0 informations**
- `py_compile`：**PASS**
- `git diff --check`：**PASS**
- full `pytest tests -q -m 'not real_llm'`：**100% / exit 0 / 162.6s**
- commit hook `git_security_scan`：**5 files PASS**

过程中 `git diff --check` 曾发现 RG-3A 设计文档头部 3 行 Markdown trailing whitespace；
仅删除这 3 处尾空格后重新验证通过，没有修改合同语义。

## 6. Clean committed-state 验证

implementation commit `62ddbd4` 生成后，从 clean committed HEAD 重新执行：

- `git show --check`：**PASS**
- resource/cloud focused：**48/48 PASS**
- Ruff `src tests`：**PASS**
- Pyright：**0 errors / 0 warnings / 0 informations**
- `py_compile`：**PASS**
- worktree：**clean**
- full `pytest tests -q -m 'not real_llm'`：**100% / exit 0 / 157.7s**

full suite 仅出现既有第三方依赖 deprecation warnings；无 RG-3A 新失败。

## 7. Unified baseline 资格

RG-3A 不是从旧 `b6b151b` Learning 分支直接继续开发，而是在统一基线：

```text
dac7c57   RG-2 qualification
   ↓
608ec12   preserve b6 restart/CI hardening only
   ↓
62ddbd4   RG-3A cloud resource facts
```

`608ec12` 本身在进入 RG-3A 前已通过：

- focused restart/arch：24/24 PASS
- Ruff全仓 PASS
- Pyright 0/0/0
- `git show --check` PASS
- full non-real-LLM：100% / exit 0 / 159.7s

因此本次 RG-3A 资格证据不依赖旧 Learning 冲突版本，也没有丢掉 b6 独立 restart/CI 更新。

## 8. 仍然明确未解决的问题

RG-3A **不等于 cloud Resource Governor 已完成**。下列问题仍然存在，并被有意留给后续：

1. `ResourceGovernor` runtime 仍只执行 concurrency lease；rate/quota/cost 尚未 enforce；
2. `ProviderCallCoordinator` cloud facts 尚未接入，cloud unknown 仍维持 RG-2 legacy bypass；
3. `LLMHTTPError` 尚未结构化保留安全 Retry-After/reset facts；
4. 历史 `LLMResponse` usage 的 `0` 兼容语义尚未改变；
5. Task `request.usage` 仍只是 Task event projection，不是 provider-neutral account ledger；
6. Learning / MemoryExtractor / Summarizer 等 cloud 调用还没有统一 settlement；
7. GLM / MiniMax / DeepSeek 的具体 product/account/plan facts 尚未通过 adapter 显式装配；
8. pricing schedule 只定义合同，不自动抓取、刷新或选择 provider 当前价；
9. TrustDomain 与 provider cancellation 继续保持未接线。

这些限制不是缺陷掩盖，而是 RG-3A 独立收口的阶段边界。

## 9. 下一阶段入口：RG-3B

RG-3B 应只做 **Transport Observation / Shadow**：

1. 在 provider call 边界捕获 typed `ProviderUsageFacts`；
2. 从 HTTP/SSE 只白名单提取 safe `ProviderErrorFacts` / reset facts；
3. 保持 `None` 与真实 `0`；
4. 不阻断、不排队、不改 fallback、不做 cost/rate enforcement；
5. 用 GLM / MiniMax / DeepSeek 真实但最小的 cloud call qualification 验证返回事实；
6. 只有 transport facts 稳定后，才进入 RG-3C unified settlement。

**RG-3A qualification：PASS / CLOSE。**
