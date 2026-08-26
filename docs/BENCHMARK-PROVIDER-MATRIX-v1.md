# AI Operating Benchmark — Multi-Provider Matrix v1

> 文档类型：跨模型/跨 Provider 泛化验收规范
> 状态：**SUPERSEDED BY `BENCHMARK-PROVIDER-MATRIX-v2.md` — 0 EXPERIMENT REQUESTS UNDER v1**
> Supersedes timestamp：2026-08-25
> 核心原则：**MiniMax 只是一个 calibration provider，不是 Architecture 的代表模型。**
> 目标：验证 AI Operating Architecture 的收益是否跨不同模型族成立，并识别 provider × treatment 交互，而不是用单一模型决定通用规则。

---

# 1. Why Multi-Provider Is Mandatory

AI Operating Architecture 声称的是：

```text
model-independent operating principles
```

因此任何以下结论都不能只来自 MiniMax：

```text
Operating Contract should be promoted
Task Anchor improves long-horizon behavior
Evidence State reduces drift
DRU reduces unnecessary verification
Context Temperature improves efficiency
Adaptive Autonomy improves task completion
```

单 provider 结果只能写成：

```text
observed on <provider/model>
```

不能写成：

```text
Architecture invariant
```

---

# 2. Current Provider Reality

当前 `data/providers.json` 已注册：

| Provider | Model | Context | Thinking | Registry Status |
|---|---|---:|---|---|
| DeepSeek | `deepseek-v4-flash` | 1M | yes | active |
| DeepSeek | `deepseek-v4-pro` | 1M | yes | active |
| MiniMax | `MiniMax-M3` | 1M | no | active |
| Local | `qwen/qwen3.8-27b` 等 | 128K/1M mixed | mixed | active |

工作区还有 Kimi 的历史实现、测试与真实运行记录，但 **Kimi 当前不在 `data/providers.json` 的 active registry 中**。

GLM 当前也 **不在 active registry 中**。

因此 Provider Matrix 分两类：

```text
Registered Now
  DeepSeek
  MiniMax
  Local/Qwen

Provider Slots Requiring Resolution Before Run
  Kimi
  GLM
  future providers
```

不在 registry 的 provider 不猜测 model id；在其实验 freeze 前解析并冻结实际 provider/model/config。

---

# 3. Provider Selection Is Capability-Stratified

品牌不是唯一维度。正式 Provider Panel 应覆盖不同能力形态：

```text
thinking vs non-thinking
large vs smaller effective context
cache telemetry styles
high vs low output budget
tool-call behavior
provider latency/cost regime
```

推荐 Panel：

## Anchor Providers

### A1 — MiniMax

```text
MiniMax-M3
non-thinking
1M context
```

作用：非 thinking 大窗口模型代表。

### A2 — DeepSeek

```text
deepseek-v4-flash
thinking
1M context
```

作用：thinking 大窗口 + 不同 cache telemetry/provider 行为代表。

这两个模型构成最小 cross-style measurement calibration pair。

---

## Confirmatory Providers

### C1 — DeepSeek Pro

```text
deepseek-v4-pro
```

作用：同 provider 不同能力/成本档，检测 Architecture effect 是 provider-level 还是 model-level。

### C2 — Kimi

```text
kimi/<resolved-model-at-freeze>
```

要求：

```text
current provider endpoint resolved
model id resolved
context resolved
thinking mode resolved
quota/availability checked
```

不得从历史 `k3` / `k3-256k` 名称自动假设当前实验模型。

### C3 — GLM

```text
glm/<resolved-model-at-freeze>
```

要求与 Kimi 相同。当前 registry 未配置，因此在 provider onboarding/freeze 前不编造具体型号。

---

## Robustness Provider

### R1 — Local Qwen

可选，用于判断 Architecture 是否只对云端强模型有效，还是对较小/本地模型也能保持基本收益。

Local 不与云 provider 做绝对 latency/cost 横比。

---

# 4. Two Different Questions

必须区分：

## Q1 — Is the measurement system provider-robust?

即：

```text
同一个 oracle/scorer
面对不同模型表达风格
还能稳定判分吗？
```

这是 Calibration 问题。

## Q2 — Is the Architecture provider-general?

即：

```text
同一个 treatment
在不同模型上
是否维持任务成功并降低漂移/返工/成本？
```

这是 Effectiveness 问题。

不能混在一个实验里。

---

# 5. Experimental Stages

## Stage C0 — Measurement Bootstrap

```text
Provider: MiniMax-M3
Scenario: Drift Injection
Variants: Baseline / Contract / Full
Seeds: 10 paired
Runs: 30
```

目的只验证：

```text
oracle
scorer
novel-signal rubric
metric observability
```

**不产生 Architecture effectiveness claim。**

---

## Stage C1 — Cross-Style Measurement Calibration

C0 通过后：

```text
Provider: DeepSeek-v4-flash
Scenario: Drift Injection
Fixture family: Calibration A2（与 C0 不同具体文本）
Variants: Baseline / Contract / Full
Seeds: 5–10 paired
```

目的：

> 验证 scorer 不只是适配 MiniMax 的回答风格。

只有 C0 + C1 都通过，scorer 才能标记：

```text
measurement-calibrated-across-anchor-providers
```

---

## Stage S — Cross-Provider Screening

不要一上来把 8 个 Architecture Variant × 所有 Provider 全部跑满。

先对每个 Provider 跑：

```text
Baseline
Contract
Full
```

Provider panel：

```text
MiniMax-M3
DeepSeek-v4-flash
Kimi resolved model
GLM resolved model
```

DeepSeek Pro / Local 可作为 confirmatory/robustness。

目的：快速检查：

```text
是否有 provider 出现 treatment 方向反转？
是否有明显 capability loss？
是否有某模型对 Contract 极度敏感？
```

---

## Stage A — Detailed Architecture Ablation

详细 Level A：

```text
Baseline
+Contract
+Task Anchor
+Evidence State
+DRU
+Context Temperature
+Adaptive Autonomy
Full
```

优先只在两个 Anchor Provider 上跑：

```text
MiniMax-M3
DeepSeek-v4-flash
```

原因：控制成本，同时覆盖 thinking/non-thinking 两种主要行为形态。

---

## Stage G — Generalization Confirmation

从 Stage A 得到候选最佳 Architecture 后，在 holdout providers 上只跑：

```text
Baseline
Best Treatment
```

Holdout：

```text
Kimi
GLM
DeepSeek Pro
(optional Local Qwen)
```

这里才回答：

> Anchor provider 上发现的收益是否能够泛化？

---

## Stage B — Contract Clause Leave-One-Out

Clause 级：

```text
Full Contract
Full - clause 1
...
Full - clause 8
```

不必对所有 provider 全跑。

推荐：

```text
Anchor 1: MiniMax-M3
Anchor 2: DeepSeek-v4-flash
```

如果某 clause 在两者方向一致，再挑 1 个 holdout provider 做 confirmatory check。

---

# 6. Shared Fixture, Provider-Specific Runtime

跨 provider 对比必须保持：

```text
semantic task = same
oracle = same
constraint = same
novel signal logic = same
scoring rubric = same
```

允许变化：

```text
provider/model id
wire protocol
provider-specific max tokens
provider-specific context budget
provider-specific cache telemetry field
provider timeout
```

这些变化必须记录为 provider profile，而不是 treatment。

---

# 7. Prompt Equivalence

Architecture treatment 的语义必须跨 provider 一致。

推荐：

```text
same Contract wording
same Task Anchor semantics
same Evidence State semantics
same DRU policy
```

只允许 provider adapter 对：

```text
system/user message wire format
tool schema protocol
reasoning-field protocol
```

做机械适配。

禁止为了让某 provider “表现更好”单独改 Contract 内容，否则不再是同一 treatment。

---

# 8. Context Normalization

不同模型 context/window 不完全一致，所以 Long-Horizon Benchmark 需要两种模式。

## Absolute Workload Mode

所有 provider 输入完全相同的任务内容。

用于测：

```text
普通真实任务泛化
```

## Capacity-Relative Stress Mode

按各 provider 的 effective context/history budget 比例构造负载，例如：

```text
35% / 60% / 80% of effective working budget
```

用于测：

```text
compression/recovery architecture
```

不能把 1M 模型的绝对输入直接塞给 128K 模型然后说后者 Architecture 更差。

---

# 9. Treatment Effect Must Be Computed Within Provider

不推荐：

```text
MiniMax Full score
vs
DeepSeek Baseline score
```

这种比较无法区分 provider 能力和 Architecture treatment。

正确单位是：

```text
Δ_provider = Treatment - Baseline
```

例如：

```text
ΔTaskSuccess_MiniMax
ΔTaskSuccess_DeepSeek
ΔTaskSuccess_Kimi
ΔTaskSuccess_GLM
```

再看：

```text
direction consistency
effect magnitude
confidence interval
provider × treatment interaction
```

---

# 10. Cross-Provider Promotion Rule

一个 Architecture Feature 想升级成“通用原则”，建议至少满足：

```text
1. Anchor providers 上 Task Success 不劣；
2. Anchor providers 上 Constraint Violation 不恶化；
3. 至少一个主要效率/稳定性指标有净收益；
4. Holdout provider 没有明显方向反转；
5. Novel Signal Recovery 没有系统性下降；
6. 没有 provider-specific catastrophic failure。
```

如果只在某 provider 有收益：

```text
不要 Promote 成 global rule
→ provider-specific strategy/profile
```

---

# 11. Model-Specific vs Architecture-Level Facts

结果必须标 scope。

例如：

```text
FACT:
  Contract reduced unnecessary verification on MiniMax-M3.
  scope: minimax/MiniMax-M3
```

只有跨 provider 证据成熟后才能写：

```text
INVARIANT CANDIDATE:
  Contract clause X improves decision efficiency across tested providers.
```

这与 Architecture 的 Evidence Quality 原则完全一致。

---

# 12. Provider Matrix

| Tier | Provider/Model | Role | Current Status |
|---|---|---|---|
| Anchor | MiniMax / MiniMax-M3 | non-thinking large-context anchor | registered |
| Anchor | DeepSeek / deepseek-v4-flash | thinking large-context anchor | registered |
| Confirm | DeepSeek / deepseek-v4-pro | same-provider higher tier | registered |
| Holdout | Kimi / resolved-at-freeze | cross-vendor generalization | needs registry resolution |
| Holdout | GLM / resolved-at-freeze | cross-vendor generalization | needs registry resolution |
| Robustness | Local Qwen | smaller/local behavior | registered, optional |

---

# 13. Cost Metrics Across Providers

不能比较原始：

```text
latency
price
tokens
```

就得出 Architecture 优劣。

正式报告分两层：

## Within Provider

```text
Treatment vs Baseline
```

测：

```text
Δinput tokens
Δoutput tokens
Δcached tokens
Δtool calls
Δwall time
Δprovider cost
```

## Across Providers

只报告：

```text
direction of treatment effect
normalized percentage delta
heterogeneity
```

而不是把不同 provider 的美元、缓存价格、生成速度混成一个总分。

---

# 14. Cache Metrics Are Provider-Scoped

不同 provider：

```text
cache semantics
TTL
minimum prefix
telemetry field
billing behavior
```

可能不同。

因此 Cache 只作为：

```text
provider-scoped diagnostic metric
```

Architecture 通用层关注的是：

```text
stable-prefix preservation behavior
```

而不是强求所有 provider 达到同一 hit-rate 数字。

---

# 15. Thinking vs Non-Thinking Interaction

Operating Contract 可能对 thinking/non-thinking 模型产生不同影响。

特别观察：

```text
Decision Latency
Unnecessary Verification
Output verbosity
Tool-call count
Novel Signal Recovery
```

如果：

```text
Contract 对 MiniMax 有益
但对 DeepSeek thinking 模型造成明显过度反思
```

正确结论不是 Contract 全局失败，也不是忽略 DeepSeek。

而是：

```text
存在 treatment × reasoning-mode interaction
```

需要 Simplify Contract 或做 provider capability adaptation。

---

# 16. Provider Capability Adaptation Boundary

允许 adaptation：

```text
context budget
max output
wire protocol
timeout
cache telemetry parser
reasoning field parser
```

谨慎 adaptation：

```text
Contract wording
verification policy
risk threshold
```

如果后者必须因 provider 不同而改变，则应明确进入：

```text
Provider Capability Profile
```

而不是偷偷改变 global Architecture。

---

# 17. Kimi / GLM Onboarding Gate

Kimi / GLM 在进入正式 Provider Matrix 前必须冻结：

```text
provider id
model id
endpoint/wire protocol
context window
thinking mode
max output tokens
timeout
history budget
cache telemetry availability
tool-call compatibility
```

并跑最小 smoke：

```text
one plain completion
one tool-call round trip
one usage telemetry sample
```

Smoke 只验证实验环境，不计 Architecture score。

---

# 18. Provider Holdout Principle

至少保留一个 provider 不参与 Architecture 调参。

推荐：

```text
Kimi or GLM = true holdout
```

在 Anchor providers 上决定 candidate design 后，才解锁 holdout。

这样可以防止：

```text
Architecture overfit to MiniMax + DeepSeek
```

---

# 19. Recommended Experimental Funnel

```text
C0 MiniMax measurement bootstrap
        ↓
C1 DeepSeek cross-style scorer calibration
        ↓
S  Multi-provider Baseline / Contract / Full screening
        ↓
A  Detailed ablation on MiniMax + DeepSeek
        ↓
G  Best-treatment generalization on Kimi + GLM (+ DeepSeek Pro)
        ↓
B  Clause leave-one-out on anchor providers
        ↓
Promote global / provider-specific / retire
```

这比：

```text
MiniMax 30 runs
→ 直接决定 Architecture
```

更符合 v1 的 model-independent 目标。

---

# 20. Final Principle

> **用单模型校准实验系统可以；用单模型定义通用 AI Architecture 不可以。**
>
> Architecture 的“通用”必须通过跨 provider 的 treatment effect 得到，而不是从一个模型的绝对分数外推。
>
> MiniMax、DeepSeek、Kimi、GLM 应被视为不同能力分布上的样本，而不是谁代表“大模型”。
