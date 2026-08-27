# Calibration Pre-Registration Freeze v2

> 状态：**FROZEN — READY FOR C0 MEASUREMENT BOOTSTRAP**
> Freeze timestamp：2026-08-25 22:50 +08:00
> Supersedes：`CALIBRATION-FROZEN-v1.md`（v1 下执行请求数 = 0）
> 变更原因：明确 Architecture 为多 Provider 验证；MiniMax 仅是 C0 measurement bootstrap，不代表通用模型。

## 1. Experiment Funnel Frozen

```text
C0  MiniMax-M3: measurement bootstrap (10 paired seeds × V0/V1/V2 = 30 runs)
 ↓
C1  DeepSeek-v4-flash: cross-style scorer calibration (new calibration fixture family, 5–10 paired seeds)
 ↓
S   Multi-provider screening: Baseline / Contract / Full
    MiniMax + DeepSeek + Kimi(resolved) + GLM(resolved)
 ↓
A   Detailed architecture ablation on anchor providers
    MiniMax-M3 + DeepSeek-v4-flash
 ↓
G   Holdout generalization
    Kimi + GLM + DeepSeek Pro (+ optional Local Qwen)
 ↓
B   Contract clause leave-one-out on anchors + confirmatory holdout
```

**只有 C0 的 30-run matrix 在本 freeze 中已具体冻结。C1/S/A/G/B 必须各自独立 pre-register 后才能运行。**

## 2. C0 Scope

- C0 只验证 oracle/scorer/novel-signal rubric/metric observability。
- C0 不能输出 `Architecture Proven`、`Contract Promoted`、`Provider-General`。
- C0 即使 Full > Baseline，也只能说明 measurement bootstrap 中观察到差异，不能外推。

## 3. C1 Requirement

C0 Gate A–E 通过后，必须在 `deepseek/deepseek-v4-flash` 上使用新的 Calibration fixture family 进行 cross-style scorer calibration，验证 scorer 不只适配 MiniMax 的表达风格。

只有 C0 + C1 都通过，measurement system 才可标记：

```text
measurement-calibrated-across-anchor-providers
```

## 4. Provider Panel

| Role | Provider/Model | State |
|---|---|---|
| Anchor | `minimax/MiniMax-M3` | active registry |
| Anchor | `deepseek/deepseek-v4-flash` | active registry |
| Confirm | `deepseek/deepseek-v4-pro` | active registry |
| Holdout | `kimi/<resolve-at-freeze>` | historical/test support; not current active registry |
| Holdout | `glm/<resolve-at-freeze>` | not current active registry |
| Robustness | Local Qwen | active registry; optional |

Kimi/GLM 进入实验前必须分别冻结真实 model id、endpoint/wire protocol、context、thinking、max tokens、timeout、history budget、cache telemetry、tool-call compatibility。不得从历史名称猜。

## 5. Cross-Provider Analysis Rule

正式 Architecture 效果以 provider 内 treatment effect 为单位：

```text
Delta_provider = Treatment - Baseline
```

禁止用 `MiniMax Full` 直接对比 `DeepSeek Baseline` 来归因 Architecture。跨 provider 只比较 effect direction、normalized delta、heterogeneity 与 provider × treatment interaction。

## 6. Global Promotion Gate

任何 Feature 要升级为 global Architecture principle，至少要求：

1. 两个 Anchor provider 上 Task Success 不劣；
2. Constraint Violation 不恶化；
3. 至少一个主要效率/稳定指标存在净收益；
4. Holdout provider 无明显方向反转；
5. Novel Signal Recovery 无系统性下降；
6. 无 provider-specific catastrophic failure。

若收益只存在于一个 provider，降级为 `provider-specific strategy/profile`，不得 Promote 成 global rule。

## 7. C0 Frozen Details

- Seeds：S01–S10。
- Variants：V0 Baseline / V1 Contract / V2 Full。
- Runs：30，顺序见 `CALIBRATION-MATRIX-v1.md`。
- Ground Truth：synthetic deterministic fixtures。
- Scorer：`CALIBRATION-SEEDS-v1.md` scorer-v1。
- Cache carry-over：record-and-randomize；C0 不对 cache effectiveness 做结论。
- Resolved model 必须 `minimax/MiniMax-M3`；fallback → INFRA_FAILURE。

## 8. C0 Gates

- Gate A Oracle Integrity
- Gate B Scorer Reliability
- Gate C Novel Signal Measurability
- Gate D Metric Observability
- Gate E Metric Dynamic Range

C0 输出仍只允许：`GO` / `NO-GO` / `GO-WITH-REVISIONS`。

## 9. SHA-256 Freeze

| Artifact | SHA-256 |
|---|---|
| `docs/ARCHITECTURE-ai-operating-v1.md` | `ea367a8fcd38065fec9423cb3b726bf1c2dc65ce84c70a732e1e82691d01f756` |
| `docs/OPERATING-CONTRACT-LITE.md` | `47fdf25839b6d5da84e5505ab3f00992017e507a869877774b84ce34058b7de3` |
| `docs/ARCHITECTURE-ai-state-model-v1.md` | `8259658ed6105629e527d90ef6e0b7a7ae736f2e01ca608b527ac26d9ab2f9fe` |
| `docs/BENCHMARK-ai-operating-v1.md` | `cb17baf8469c27fb3dee77d47d4f5f9ac04d34353353130bc4bd4821f2ecce79` |
| `docs/BENCHMARK-CALIBRATION-PILOT-v1.md` | `3b354266061dfffc41ac8a9a556631c4170a4a72fedde67624499f3ce93b55de` |
| `docs/BENCHMARK-PROVIDER-MATRIX-v2.md` | `e3a94e1d5192edd1e6c6abf3b5e672699c234ec3a1d9a8e35b8616f3bf048357` |
| `docs/CALIBRATION-SEEDS-v1.md` | `285545df89680b8837fcd06a7cc28f5522f71fbc70da2a3297315a5df8c012f7` |
| `docs/CALIBRATION-MATRIX-v1.md` | `452a8c74949368f91eecc8ae4f2935042150871cbbd3a34cbc823a2057248876` |
| `data/providers.json` | `a5e6221a344d08d37c0135931762e95e9371c4073d9dd1cd33903e3599a4a874` |

> 注：`BENCHMARK-PROVIDER-MATRIX` 于 2026-08-25 由 v1 升 v2（v1 下执行实验请求数 = 0，无污染）。
> v2 仅补 P2/P3/P4（§15.1/§15.2/§5），属 C1/S/A/G/B 阶段设计更新，**不影响 C0 freeze**；
> C0 的 seed/oracle/scorer/matrix/provider conditions 未变。

## 10. Mutation Rule

从 v2 freeze 起，若修改 C0 seed/oracle/scorer/matrix/gates/provider conditions，必须停止 C0 并 bump freeze version。C1/S/A/G/B 尚未具体冻结，因此后续设计它们不算修改 C0 freeze，但每阶段在首个请求前必须单独 pre-register。

## 11. Current Readiness

```text
Architecture scope: multi-provider
C0 Pre-Registration: FROZEN
C0 runs: 0 / 30
C1: NOT YET PRE-REGISTERED
Kimi: provider/model unresolved for benchmark
GLM: provider/model unresolved for benchmark
```

> **单模型可以校准尺子；通用 Architecture 必须跨模型证明。**

