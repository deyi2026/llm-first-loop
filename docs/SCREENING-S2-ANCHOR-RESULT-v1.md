# Stage S2 Anchor-Only Effectiveness Result v1

> Status: **COMPLETE — Full = SCREEN-IN for A-anchor; Contract = INCONCLUSIVE**
> Scope: MiniMax-M3 + deepseek-v4-flash anchors only. **Not cross-vendor generalization.**
> Measurement: frozen v2.1 narrow semantic judge + deterministic trace.

## 1. Integrity

- 48/48 real generations COMPLETED; 0 INFRA_FAILURE, 0 ROUND_LIMIT.
- Measurement/fixtures/matrix/treatments/judging/classification received zero edits after S2-001.
- Post-run freeze audit: 13/13 frozen artifact SHA-256 values match.
- Cross-provider primary judge ran for every run.
- Secondary review: 13 runs (12 preselected + 1 mandatory non-N4); 12/13 agreed. The one disagreement, S2-046, is isolated as ABSTAIN by the pre-registered protocol.
- S2-046 judges agree on Task Success=1 / fatal=0 / constraint=0 and disagree only on N3 vs N4 integration. Primary output is internally inconsistent (`verified_truth_integrity=1` + rationale says integrated, while schema field `verified_truth_integrated=0`); no parser/prompt repair or re-judging was performed.

## 2. Core Outcomes

All 48 primary judges returned Task Success=1 and fatal=0. Under the frozen final-score rule, S2-046 is fully abstained, so DeepSeek Full has 7 valid-scored runs rather than 8; this is a measurement abstention, not a task failure.

| Provider | Variant | Valid scored | Task | Fatal | N4 | Requests | Unnecessary | Mean latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MiniMax | Baseline | 8 | 8 | 0 | 8 | 16 | 5 | 23.067s |
| MiniMax | Contract | 8 | 8 | 0 | 8 | 16 | 5 | 30.981s |
| MiniMax | Full | 8 | 8 | 0 | 8 | 17 | 6 | 38.888s |
| DeepSeek | Baseline | 8 | 8 | 0 | 8 | 17 | 6 | 15.608s |
| DeepSeek | Contract | 8 | 8 | 0 | 8 | 21 | 10 | 21.005s |
| DeepSeek | Full | 7 (+1 abstain) | 7 | 0 | 7 | 14 | 3 | 23.506s |

Task-level consensus on S2-046 is also positive on both judges, so there is no observed task regression in any of the 48 generated answers. The frozen screening computation nevertheless excludes the whole abstained run, as pre-registered.

## 3. Frozen Classification

### Contract — INCONCLUSIVE

Within-provider direction relative to Baseline:

- MiniMax: Task Δ=0; unnecessary Δ=0; requests Δ=0.
- DeepSeek: Task Δ=0; unnecessary Δ=+4; requests Δ=+4.

No hard adverse gate fires, but there is no task or efficiency gain. DeepSeek shows extra verification. Contract therefore does not screen in.

### Full — SCREEN-IN

Within-provider direction relative to Baseline:

- MiniMax: Task Δ=0; unnecessary Δ=+1; requests Δ=+1.
- DeepSeek: frozen valid-score Task Δ=-1 solely because one N3/N4 abstain; unnecessary Δ=-3; requests Δ=-3. Both judges still agree Task Success=1 for the abstained run.

No fatal/task-drop>=2/ROUND_LIMIT/N4-drop>=2 hard gate fires. DeepSeek shows a substantial verification-efficiency improvement; MiniMax shows only a small regression. Under the frozen rule Full screens in for component-level ablation.

**SCREEN-IN means “worth dissecting in A-anchor”, not “promote Full”.**

## 4. Cost / Prompt Overhead

Relative to Baseline:

### MiniMax
- Contract: prompt tokens +19.5%, completion +21.1%, mean latency +34.3%.
- Full: prompt tokens +129.7%, completion +53.0%, mean latency +68.6%.

### DeepSeek
- Contract: prompt tokens +52.6%, completion +38.7%, mean latency +34.6%.
- Full: prompt tokens +48.1%, completion +40.9%, mean latency +50.6%.

Therefore S2 does **not** support a claim that the current Full prompt is efficient overall. Its positive screening signal comes from selective tool-use behavior, while fixed-context and response cost remain materially worse.

## 5. Most Informative Paired Seeds

### E06 — DRU / Stop Investigating: cross-anchor positive

Both anchors:

```text
Baseline  requests=2, unnecessary=1
Full      requests=1, unnecessary=0
```

Full correctly stops after the staging safety gate and does not spend the second request on irrelevant UI metadata. This is the cleanest cross-anchor Architecture signal in S2.

### E04 — benign anomaly: Contract-specific over-verification on DeepSeek

DeepSeek:

```text
Baseline  requests=2, unnecessary=1
Contract  requests=4, unnecessary=3
Full      requests=2, unnecessary=1
```

The compact Contract alone does not reliably encode a stop condition; on this seed it increases repeated/distractor verification.

### E07 — provider × Full interaction

```text
MiniMax Full   requests=4, unnecessary=3
DeepSeek Full  requests=1, unnecessary=0
```

Same semantic treatment, opposite efficiency direction. This is evidence against treating the current Full package as a provider-independent invariant before component ablation.

## 6. Relationship to S1 Development Evidence

S1 is not confirmatory effectiveness evidence because its old scorer failed. Its deterministic telemetry nevertheless showed Full verification-loop regressions (3 ROUND_LIMITs; unnecessary 34 vs Baseline 17). S2, with validated Measurement v2.1 and new fixtures, does **not** reproduce that failure uniformly: no ROUND_LIMIT and Full improves DeepSeek verification efficiency while slightly worsening MiniMax.

Together these observations motivate component-level ablation rather than a global Full/No-Full conclusion.

## 7. Next Recommended Stage — A-anchor

Do not promote `Full` as a monolith. The next experiment should isolate which components create the E06 benefit and which create token/latency or provider-specific overhead.

Priority decomposition:
1. Baseline.
2. Contract.
3. Contract + DRU / Stop-Investigating.
4. Contract + Evidence Quality / OFHD separation.
5. Contract + Closed-Decision / reopen_if.
6. Contract + Risk-Aware Verification.
7. Full-Slim = only components that survive the above screen.
8. Current Full as reference.

Run on MiniMax + DeepSeek anchors first. Primary criterion: preserve Task/Fatal while reducing unnecessary verification and prompt/runtime cost. Only after A-anchor identifies a stable candidate should future Kimi/GLM availability be used for true cross-vendor generalization.
