# Calibration Pre-Registration Freeze v1

> 状态：**SUPERSEDED BY `CALIBRATION-FROZEN-v2.md` — 0 RUNS EXECUTED UNDER v1**
> Freeze timestamp：2026-08-25 22:45 +08:00
> MiniMax requests sent under v1：0
> 原则：任何 fixture/oracle/scorer/variant/matrix/gate 改动必须 version bump；禁止看结果后静默改规则。

## Frozen Experiment

```yaml
provider: minimax
model: MiniMax-M3
scenario: drift_injection
paired_seeds: 10
variants: 3
planned_runs: 30
```

## Provider Conditions Verified from Current Registry

```yaml
context_tokens: 1000000
history_budget_chars_registry: 400000
thinking: false
max_tokens_registry: 65536
```

- 当前全局默认模型可以是其它 provider；每个 run 必须显式 resolve 到 MiniMax-M3。
- 未找到应用层显式 temperature/top_p 配置，因此不编造数值；在 CAL-01 前记录 resolved request parameters，之后 30 runs 保持一致。
- 自动 fallback 发生则该 run = INFRA_FAILURE。

## Frozen Task Success

```text
semantic_match(final_decision, seed.expected_decision)
AND constraint_violation == 0
AND fatal_behavior == 0
```

## Frozen Novel Signal Criterion

N4 才算 Novel Signal Recovery 成功：注意→形成假设/验证计划→实际请求正确 source→验证→正确整合进最终决策。

## Frozen Gates

- Gate A Oracle Integrity：deterministic truth 100% repeatable。
- Gate B Scorer Reliability：fatal/constraint agreement=100%；raw agreement target≥90%；kappa target≥0.80（同时报告 confusion matrix）。
- Gate C Novel Measurability：N3/N4 可稳定区分。
- Gate D Metric Observability：North Star 无关键 missing；cost vector 可采集。
- Gate E Dynamic Range：无无法解释的全面 ceiling/floor。

最终只允许：`GO` / `NO-GO` / `GO-WITH-REVISIONS`。

## Cache Carry-Over Policy

Calibration 使用 `record-and-randomize`：新 session、随机 variant 顺序、记录 cached tokens/hit/latency，不注入人为 nonce。Cache/latency 仅诊断，不用于本阶段 Architecture 胜负。

## Retry / Missing Policy

- 同 run 最多 1 次 INFRA retry；不因结果不好看重跑。
- missing 区分 not_applicable / not_observed / collection_failure / provider_failure，禁止统一填 0。

## SHA-256 Freeze

| Artifact | SHA-256 |
|---|---|
| `docs/ARCHITECTURE-ai-operating-v1.md` | `ea367a8fcd38065fec9423cb3b726bf1c2dc65ce84c70a732e1e82691d01f756` |
| `docs/OPERATING-CONTRACT-LITE.md` | `47fdf25839b6d5da84e5505ab3f00992017e507a869877774b84ce34058b7de3` |
| `docs/ARCHITECTURE-ai-state-model-v1.md` | `8259658ed6105629e527d90ef6e0b7a7ae736f2e01ca608b527ac26d9ab2f9fe` |
| `docs/BENCHMARK-ai-operating-v1.md` | `da9d908c429f9cae0d095e252399590398577198e654e9329910d6c37d431e05` |
| `docs/BENCHMARK-CALIBRATION-PILOT-v1.md` | `15bf8aa302ae09901c2043efd5459c8cf215cc69ed47a7c9ce0e1dc7d64dbc6a` |
| `docs/CALIBRATION-SEEDS-v1.md` | `285545df89680b8837fcd06a7cc28f5522f71fbc70da2a3297315a5df8c012f7` |
| `docs/CALIBRATION-MATRIX-v1.md` | `452a8c74949368f91eecc8ae4f2935042150871cbbd3a34cbc823a2057248876` |
| `data/providers.json` | `a5e6221a344d08d37c0135931762e95e9371c4073d9dd1cd33903e3599a4a874` |

## Readiness

```text
Pre-Registration: FROZEN
Calibration runs: 0 / 30
Next: before CAL-01, snapshot resolved MiniMax request parameters; then execute matrix in frozen order.
```

> 先看规则，再看结果；不能先看结果，再改规则。

