# Stage S0 — Provider Resolution v1

> 类型：Multi-Provider Screening / Provider Onboarding Pre-Registration
> 状态：**CONFIGURATION RESOLVED / REAL REQUESTS NOT AUTHORIZED**
> 日期：2026-08-26
> 目标：在 Stage S 首个真实请求前冻结 provider/model/wire/thinking/output-budget 语义；不通过历史名称猜当前模型。

## 1. 结论

Stage S 的目标 panel 固定为：

```text
Anchor  : MiniMax / MiniMax-M3
Anchor  : DeepSeek / deepseek-v4-flash
Holdout : Kimi Code / k3
Holdout : GLM / glm-5.2
```

MiniMax/DeepSeek 来自当前 workspace registry；Kimi/GLM 使用 2026-08-26 官方文档确认的当前模型能力。

**本阶段没有发送任何 provider 请求。**

## 2. Provider Resolution

| ID | Role | Service / Model | Context | Thinking | Credential | State |
|---|---|---|---:|---|---|---|
| minimax | Anchor | `MiniMax-M3` | 1M | no | present | resolved / pending smoke |
| deepseek | Anchor | `deepseek-v4-flash` | 1M | yes | present | resolved / pending smoke |
| kimi | Holdout | Kimi Code `k3` | 1M | yes | present | resolved / pending smoke |
| glm | Holdout | `glm-5.2` | 1M | yes | **missing** | blocked until credential + smoke |

### Kimi resolution

当前 workspace 的历史 Kimi integration 使用 `api.kimi.com/coding/v1` + `KIMI_API_KEY`。官方 Kimi Code 文档当前提供 `k3`（1M）和 `k3-256k` 等 model ID，并明确要求使用 model ID 而不是产品名；K3 需保持 thinking 启用。

因此 S1 冻结：

```yaml
provider: kimi
service: Kimi Code API
base_url: https://api.kimi.com/coding/v1
model: k3
context_tokens: 1048576
thinking_supported: true
api_key_env: KIMI_API_KEY
```

这里不使用 Kimi API 开放平台的 `kimi-k3`，避免把两套独立计费/API-key surface 混在一个 provider profile 里。

### GLM resolution

官方 GLM 文档当前推荐 `glm-5.2`：1M context、128K 最大输出、支持 function calling、默认 thinking，并要求 interleaved thinking + tool 时保留 reasoning content。

S1 冻结：

```yaml
provider: glm
base_url: https://open.bigmodel.cn/api/paas/v4
model: glm-5.2
context_tokens: 1000000
provider_max_output_tokens: 131072
thinking_supported: true
api_key_env: GLM_API_KEY
```

`GLM_API_KEY` 是本 benchmark 新定义的本地 env 名称；当前未设置，因此 GLM **不能执行真实 smoke/run**。

## 3. Common Runtime Controls

为了减少 provider runtime confound，S1 统一：

```yaml
wire_protocol: openai
benchmark_max_tokens: 16384
reasoning_effort: high
timeout_s: 300
temperature: provider_default
top_p: provider_default
cache_policy: record-and-randomize
fallback: forbidden
```

`provider_default` 表示没有应用层显式配置时不编造数值；每个 provider 的首次 smoke snapshot 记录实际请求配置。

## 4. Thinking-mode Covariate

```text
MiniMax: thinking=false
DeepSeek: thinking=true
Kimi K3: thinking=true
GLM-5.2: thinking=true
```

Reasoning content 只进入 Policy B diagnostic（chars/reflection），不直接决定 Task Success / Fatal / Constraint / Novel Stage。

## 5. Smoke Gate

真实 Screening 前，每个 provider 先执行独立 smoke，不计 Architecture score：

1. plain completion；
2. one `request_fixture` tool-call round trip；
3. usage/reasoning telemetry sample；
4. resolved model 与 frozen model 必须一致；
5. thinking provider 必须能完成 reasoning-content round trip；
6. fallback / model alias mismatch → FAIL。

Smoke 失败允许修纯协议/adapter bug，但必须 version bump S freeze；不得拿 smoke output 调 scorer 语义。

## 6. GLM Blocker

当前唯一 provider-level blocker：

```text
GLM_API_KEY = missing
```

这不阻止完成 S1 Pre-Registration，但阻止 Full Panel 真实执行。

Stage S completion 在本项目采用比 PROVIDER-MATRIX-v2 更强的门槛：

```text
MiniMax + DeepSeek + Kimi + GLM
全部完成 Baseline / Contract / Full
```

除非后续显式记录 GLM waiver，否则不把 3-provider 结果称为 Full Multi-Provider Screening。

## 7. Frozen Manifest

机器可读版本：`data/calib/s_provider_manifest.json`。
