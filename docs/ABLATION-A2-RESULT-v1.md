# A2 Full-Slim Confirmation — Result v1

> Status: **COMPLETE — Full-Slim-v1 FAILS frozen A2 confirmation gate**
> Scope: MiniMax-M3 + deepseek-v4-flash anchors only. **Not cross-vendor/global promotion.**
> Candidate: **Full-Slim-v1 = Contract + DRU / Stop-Investigating only**.
> Measurement: frozen v2.1 deterministic trace + narrow semantic judge.

## 1. Integrity

- 64/64 unique real generation artifacts persisted: 63 COMPLETED, 1 ROUND_LIMIT, 0 INFRA_FAILURE.
- Post-run frozen dependency audit: **19/19 SHA-256 match**, drift=0.
- 64/64 primary semantic judgments completed.
- Secondary review: 10 runs; **10/10 agreement**, 0 ABSTAIN.
- One judge-format infra event occurred at A2-048 primary (MiniMax judge): the first response contained no parseable JSON and created no valid judge artifact. The one continuation explicitly permitted by the A2 freeze was used; all valid judge cache files were reused and never rewritten. No second format failure occurred.
- Frozen treatments, G01-G08, matrix, provider profiles, Measurement v2.1, judge protocol, and candidate gates received zero edits after A2-001.
- Frozen 173-test calibration/screening/A1/A2 regression set: **173/173 PASS**. Measurement v2.1 semantic-judge units: **4/4 PASS**.

## 2. Frozen Verdict

Frozen `analyze_a2.py` returns:

```text
FAIL
deepseek:requests_worse_vs_baseline
deepseek:unnecessary_worse_vs_baseline
deepseek:prompt_cost_not_20pct_below_full
```

The candidate is therefore **not eligible for cross-vendor holdout or global promotion**. There is no near-pass override in A2.

## 3. Measurement Outcomes

### minimax

| Treatment | Valid | Task | Fatal | N4 | Requests | Unnecessary | Prompt tokens | Completion tokens | Mean latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0-Baseline | 8 | 7 | 0 | 7 | 23 | 13 | 43421 | 17075 | 25.446s |
| B1-Contract | 8 | 8 | 0 | 8 | 16 | 6 | 26702 | 18749 | 33.478s |
| B2-Full-Slim-v1 | 8 | 8 | 0 | 8 | 15 | 5 | 25662 | 19085 | 30.112s |
| B3-Full-Reference | 8 | 8 | 0 | 8 | 18 | 8 | 48611 | 25460 | 49.786s |

### deepseek

| Treatment | Valid | Task | Fatal | N4 | Requests | Unnecessary | Prompt tokens | Completion tokens | Mean latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0-Baseline | 8 | 8 | 0 | 8 | 16 | 6 | 20476 | 14903 | 15.391s |
| B1-Contract | 8 | 8 | 0 | 8 | 17 | 7 | 28947 | 18287 | 19.651s |
| B2-Full-Slim-v1 | 8 | 8 | 0 | 8 | 18 | 8 | 61168 | 25157 | 24.623s |
| B3-Full-Reference | 8 | 7 | 0 | 7 | 17 | 7 | 52576 | 26532 | 30.225s |

The only Task/N4 failures in A2 are not Full-Slim runs:

- A2-002 — MiniMax / G08 / Baseline: generation ROUND_LIMIT; task=0, N3; mandatory secondary agreed.
- A2-034 — DeepSeek / G01 / Current Full: generation COMPLETED but semantic task=0, N3; mandatory secondary agreed.

Full-Slim-v1 itself is semantically clean on both anchors: **16/16 Task success, 16/16 N4, 0 fatal, 0 constraint, 0 ROUND_LIMIT**.

## 4. Why Full-Slim-v1 Still Fails

A2 is confirmatory and requires efficiency/cost stability on **each** anchor, not just a favorable pooled average.

| Provider | Task Δ vs Baseline | N4 Δ | Request Δ | Unnecessary Δ | Prompt ratio vs Full | Latency ratio vs Full |
|---|---:|---:|---:|---:|---:|---:|
| minimax | +1 | +1 | -8 | -8 | 0.528x | 0.605x |
| deepseek | +0 | +0 | +2 | +2 | 1.163x | 0.815x |

- MiniMax is strongly favorable: requests -8, unnecessary -8 vs Baseline; runtime prompt tokens 0.528x Current Full.
- DeepSeek reverses direction: requests +2 and unnecessary +2 vs Baseline, violating two per-anchor gates.
- DeepSeek Full-Slim runtime prompt tokens are **1.163x Current Full**, violating the required <=0.80x gate, even though the static Full-Slim system prompt is shorter (1288 chars vs 2138 chars).
- Cross-anchor aggregate requests/unnecessary are -6/-6, but A2 intentionally forbids one provider from masking a regression on the other.

## 5. Primary Failure Pattern — DeepSeek G01 Stop-Condition Loop

The DeepSeek efficiency/cost failure is highly concentrated in **A2-043 / G01 / Full-Slim-v1**.

- Oracle expected source: `fixture://G01/cache_runtime` only.
- Full-Slim requested 6 times: `cache_runtime`, `old_runbook`, repeated `cache_runtime`, irrelevant `ui_layout`, then repeated `cache_runtime` twice more.
- 5/6 requests are deterministic unnecessary verification under the frozen oracle.
- After the two-source fixture limit was exhausted, the model continued making requests after `SOURCE_LIMIT_EXCEEDED` rather than terminating tool use and answering.
- The final answer was nevertheless correct (task=1, N4), so this is a **stop/execution instability**, not a reasoning-correctness failure.
- This one run consumed 38,656 prompt tokens and 72.526s, dominating the DeepSeek candidate cost.

Post-hoc diagnostic only (not used to alter the frozen gate): excluding DeepSeek G01, the remaining seven Full-Slim runs use 22,512 prompt tokens vs 35,413 for Current Full (0.636x), and requests/unnecessary improve by -2/-2 vs Baseline. This confirms that A2 FAIL is dominated by a severe loop outlier rather than broad degradation; the frozen result remains FAIL.

## 6. Current Full Is Not a Promotion Winner Either

A2 does **not** imply that Current Full should be retained as the global architecture:

- DeepSeek Current Full has its own G01 semantic failure (A2-034: task=0/N3) and 5-request loop.
- MiniMax Current Full has a G06 6-request / 110.229s verification loop.
- Full-Slim is semantically stronger than Current Full on DeepSeek in A2 (+1 Task, +1 N4), but fails the frozen efficiency/cost stability requirements.

The correct conclusion is therefore **neither Full-Slim-v1 nor Current Full has earned provider-independent promotion**.

## 7. Architectural Interpretation

A1 supported the DRU/Stop-Investigating principle as the only component survivor. A2 shows that the current fixed-prompt realization `Contract + DRU` is not stable enough to become a provider-independent Full replacement.

The failure is consistent with the architecture rule **“tighten actions, not thinking”**: the model explicitly reasoned that UI layout was irrelevant, yet the action loop still emitted repeated tool requests. Adding more global prompt prose would likely increase fixed context and does not directly address the observed failure mode.

## 8. Recommended Next Step

Do **not** advance to the planned cross-vendor holdout. Do **not** tune Full-Slim on G01 and rerun A2, because that would reuse observed confirmation data.

The next experiment should isolate an **Action-Plane loop guard** on a new fixture family, while leaving reasoning freedom intact. Candidate mechanisms should be structural rather than prompt-heavy, for example:

1. suppress an exact duplicate tool call after an identical deterministic result;
2. treat a hard tool-budget exhaustion result as terminal for that tool/action channel and remove that action from subsequent rounds;
3. expose a structured `tool_budget_exhausted` state so the model can finish from evidence already obtained;
4. preserve the ability to request a genuinely different decision-relevant source while budget remains.

This must be tested as a new treatment on unseen fixtures. The frozen A2 artifacts remain evidence and must not be modified or regraded.
