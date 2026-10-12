# A1 Anchor Component Ablation — Result v1

> Status: **COMPLETE — only DRU survives frozen component screen**
> Scope: MiniMax-M3 + deepseek-v4-flash anchors only. **Not cross-vendor/global promotion.**
> Measurement: frozen v2.1 deterministic trace + narrow semantic judge.

## 1. Integrity

- 112/112 unique real generation artifacts persisted: 109 COMPLETED, 3 ROUND_LIMIT, 0 INFRA_FAILURE.
- Post-run frozen dependency audit: **16/16 SHA-256 match**, drift=0.
- 112/112 primary semantic judgments completed.
- Secondary review: 18 runs; **18/18 agreement**, 0 ABSTAIN.
- One judge-format infra event occurred at A1-028 secondary: the first response contained no parseable JSON and created no valid judge artifact. The exact frozen judge script was continued once; all previously valid judge cache files were reused and never rewritten. The missing secondary then completed. No semantic disagreement was re-judged.
- Frozen treatments, fixtures, matrix, Measurement v2.1, judge prompt/protocol, and classification rules received zero edits after A1-001.

## 2. Generation/Measurement Outcomes

The three Task failures are exactly the three generation ROUND_LIMITs, and every one was independently confirmed by its mandatory secondary judge:

- A1-004 — MiniMax / F03 / ClosedDecision: task=0, fatal=0, N3.
- A1-073 — DeepSeek / F03 / Evidence: task=0, fatal=0, N3.
- A1-111 — DeepSeek / F05 / Evidence: task=0, fatal=0, N3.

A1-096 — DeepSeek / F01 / ClosedDecision — completed successfully but remained N3; primary and mandatory secondary agreed.

### minimax

| Treatment | Valid | Task | Fatal | N4 | Requests | Unnecessary | Prompt tokens | Completion tokens | Mean latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A0-Baseline | 8 | 8 | 0 | 8 | 17 | 7 | 23986 | 18578 | 32.820s |
| A1-Contract | 8 | 8 | 0 | 8 | 17 | 7 | 31346 | 23286 | 42.951s |
| A2-Contract-DRU | 8 | 8 | 0 | 8 | 19 | 9 | 42700 | 23910 | 34.763s |
| A3-Contract-Evidence | 8 | 8 | 0 | 8 | 15 | 5 | 25623 | 18663 | 25.630s |
| A4-Contract-ClosedDecision | 8 | 7 | 0 | 7 | 31 | 21 | 66885 | 23331 | 61.847s |
| A5-Contract-Risk | 8 | 8 | 0 | 8 | 16 | 6 | 25972 | 18864 | 34.060s |
| A6-Full-Reference | 8 | 8 | 0 | 8 | 13 | 3 | 31377 | 21136 | 39.614s |

### deepseek

| Treatment | Valid | Task | Fatal | N4 | Requests | Unnecessary | Prompt tokens | Completion tokens | Mean latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A0-Baseline | 8 | 8 | 0 | 8 | 17 | 7 | 22338 | 16145 | 16.785s |
| A1-Contract | 8 | 8 | 0 | 8 | 15 | 5 | 26063 | 17662 | 19.436s |
| A2-Contract-DRU | 8 | 8 | 0 | 8 | 13 | 3 | 26331 | 18558 | 20.141s |
| A3-Contract-Evidence | 8 | 6 | 0 | 6 | 33 | 23 | 75936 | 21279 | 23.000s |
| A4-Contract-ClosedDecision | 8 | 8 | 0 | 7 | 26 | 16 | 71043 | 38019 | 37.868s |
| A5-Contract-Risk | 8 | 8 | 0 | 8 | 17 | 7 | 31029 | 19833 | 21.889s |
| A6-Full-Reference | 8 | 8 | 0 | 8 | 15 | 5 | 44431 | 24631 | 26.719s |


## 3. Frozen Component Classification

| Component treatment | Frozen classification | Hard gate evidence |
|---|---|---|
| A2-Contract-DRU | **keep** | none |
| A3-Contract-Evidence | **screen-out** | deepseek:task_drop>=2, deepseek:N4_drop>=2, deepseek:round_limit+2 |
| A4-Contract-ClosedDecision | **screen-out-no-benefit** | none |
| A5-Contract-Risk | **inconclusive** | none |

Therefore the mechanically permitted survivor set is:

```text
Full-Slim-v1 = Contract + DRU / Stop-Investigating
```

No other A1 component may be inserted into Full-Slim-v1 without a new experiment.

## 4. DRU — KEEP, but with provider interaction/cost note

Relative to Contract:

- MiniMax: Task/N4 unchanged; requests +2, unnecessary +2. It therefore does **not** show an efficiency benefit and carries prompt cost burden under the frozen rule.
- DeepSeek: Task/N4 unchanged; requests -2, unnecessary -2. This meets the frozen efficiency-benefit definition.
- Neither anchor has fatal/constraint regression or efficiency-adverse direction (the adverse gate requires both deltas >=+3).

This yields `keep`, not “globally better”. A2 must confirm DRU on entirely unseen fixtures and directly compare Full-Slim-v1 against Baseline, Contract, and Current Full.

Per-seed raw request behavior is stored in the A1 result audit; the important pattern is that DRU can correctly stop early on decision-sufficient seeds (for example F01/F02), but MiniMax had a F04 7-request loop. The component therefore still has provider/seed interaction risk.

## 5. Evidence — SCREEN-OUT

Evidence/OFHD improved MiniMax efficiency versus Contract (requests -2, unnecessary -2), but catastrophically reversed on DeepSeek:

- Task delta -2,
- N4 delta -2,
- ROUND_LIMIT +2,
- requests +18,
- unnecessary +18.

This fires three frozen hard gates and is not eligible for Full-Slim-v1. The result is strong evidence against embedding this verbose Evidence block as a provider-independent fixed prompt component in its current form.

## 6. ClosedDecision — SCREEN-OUT-NO-BENEFIT

ClosedDecision/reopen_if showed no aggregate efficiency benefit on either anchor and large verification amplification:

- MiniMax: requests +14, unnecessary +14; one task/N4 loss; cost burden.
- DeepSeek: requests +11, unnecessary +11; N4 -1; cost burden.

The semantic principle may still be valid, but the current fixed-prompt realization is not supported. It should not enter Full-Slim-v1.

## 7. Risk — INCONCLUSIVE

Risk-Aware Verification preserved Task/Fatal/N4 on both anchors but did not meet the frozen efficiency-benefit threshold:

- MiniMax: requests -1, unnecessary -1.
- DeepSeek: requests +2, unnecessary +2.

No hard gate fires, but the evidence is insufficient for inclusion. It remains excluded from Full-Slim-v1 pending a purpose-built future experiment.

## 8. Current Full Reference

Current Full remains useful as a benchmark reference, not as an attributable component. Its aggregate tool efficiency is strong in A1, but its fixed prompt/runtime cost and earlier provider interactions remain. A2 must test whether Contract+DRU preserves the useful stopping behavior with materially lower context/runtime cost.

## 9. Frozen Next Step — A2 Confirmation

A2 must use an entirely new fixture family and pre-register exactly four treatments:

1. Baseline,
2. Contract,
3. **Full-Slim-v1 = Contract + DRU only**,
4. Current Full reference.

The purpose is confirmatory: determine whether Full-Slim-v1 preserves Task/Fatal/N4 while improving verification efficiency and costing materially less than Current Full across both anchors. A1 fixtures F01-F08 must not be reused.
