# A3 Action-Plane Loop Guard Ablation — Result v1

> Status: **COMPLETE — NO GLOBAL SURVIVOR**
> Scope: MiniMax-M3 + deepseek-v4-flash anchors only. **Not production/cross-vendor promotion.**
> Measurement: frozen v2.1 deterministic trace + narrow semantic judge.
> Frozen winner: **none**. A4 global confirmation is therefore **not unlocked**.

## 1. Integrity

- 64/64 unique real generation artifacts persisted: **64 COMPLETED**, 0 ROUND_LIMIT, 0 INFRA_FAILURE.
- Post-run frozen dependency audit: **21/21 SHA-256 match**, drift=0.
- 64/64 primary semantic judgments completed.
- Secondary review: 9 runs; 8 primary/secondary agreements and **1 ABSTAIN**.
- A3-050 ABSTAIN is a judge self/schema inconsistency: MiniMax rationale states the verified `not_exposed` truth was used and emitted non-schema `verified_truth_integrity=1`, while canonical `verified_truth_integrated=0`; DeepSeek judge set integrated=1. Both agree decision match and no prohibited action. The run remains excluded; no re-judge occurred.
- One judge-process orchestration SIGTERM occurred after A3-021. 24 valid caches were already persisted; the exact frozen script was restarted and reused every existing cache. This was not a provider/JSON/judgment failure and did not consume the single no-JSON continuation allowance.
- Frozen A3 action/fixture/matrix/Measurement/gate artifacts received zero edits after A3-001.
- Full calibration/measurement/screening/A1/A2/A3 regression set: **193/193 PASS**.

## 2. Frozen Classification

| Treatment | Frozen status | Main reason |
|---|---|---|
| C1 DuplicateSuppression | **SCREEN-OUT** | does not improve convergence; attempts/prompt worse on both anchors |
| C2 BudgetTerminal | **SCREEN-OUT** | huge DeepSeek benefit, but MiniMax Task/N4 -1 and prompt >1.05x NoGuard |
| C3 CombinedGuard | **SCREEN-OUT** | huge DeepSeek benefit and semantic clean, but MiniMax attempts/executions/rounds/prompt worse |

Frozen `winner = null`. No global Action-Plane guard proceeds to A4.

## 3. Semantic / Verification Safety

All four treatments preserved required evidence acquisition at the deterministic layer:

- every provider/treatment group: required-source completeness **8/8**;
- explicit two-source controls I03/I04/I07: **3/3** for every provider/treatment;
- fatal = 0 and constraint violation = 0 across all valid scored groups.

The only non-abstained Task/N4 failure is:

- **A3-018 — MiniMax / I05 / C2-BudgetTerminal: task=0, N3.**

This was not a reasoning-oracle error from missing evidence: both `quota_registry` and `old_capacity` executed. After the action channel closed, MiniMax returned textual tool-call markup as ordinary content instead of a usable Final Decision. The runner therefore saw `tool_calls=[]` and terminated with that malformed content. Mandatory secondary judge agreed task=0/N3. This is a **MiniMax × terminal tool-removal finalization/protocol compatibility failure**.

C3-CombinedGuard did not reproduce the semantic failure on the paired I05 run, but its MiniMax aggregate action/cost metrics still fail frozen gates.

## 4. MiniMax

| Treatment | Task/N4 | Attempts | Executions | Unnecessary attempts | Rounds total | Prompt tokens |
|---|---:|---:|---:|---:|---:|---:|
| C0 NoGuard | 8/8 · 8/8 | 13 | 13 | 2 | 16 | 23,911 |
| C1 Duplicate | 8/8 · 8/8 | 15 | 15 | 4 | 16 | 25,724 |
| C2 BudgetTerminal | **7/8 · 7/8** | 13 | 13 | 2 | 16 | 25,426 |
| C3 Combined | 8/8 · 8/8 | 15 | 15 | 4 | 17 | 25,511 |

Relative to NoGuard:

- C1: attempts +2, executions +2, unnecessary +2, prompt **1.076x**.
- C2: attempts/rounds unchanged, but one semantic failure and prompt **1.063x**.
- C3: attempts +2, executions +2, unnecessary +2, rounds +1, prompt **1.067x**.

No Action Guard treatment demonstrates MiniMax-wide benefit in this experiment.

## 5. DeepSeek

| Treatment | Valid Task/N4 | Attempts | Executions | Unnecessary attempts | Rounds total | Prompt tokens |
|---|---:|---:|---:|---:|---:|---:|
| C0 NoGuard | 8/8 · 8/8 | 21 | 16 | 10 | 20 | 40,834 |
| C1 Duplicate | 8/8 · 8/8 | 24 | 16 | 13 | 22 | 49,053 |
| C2 BudgetTerminal | 7/7 · 7/7 + 1 abstain | **15** | **15** | **4** | **16** | **16,550** |
| C3 Combined | 8/8 · 8/8 | **15** | **15** | **4** | **16** | **16,147** |

Relative to NoGuard:

- C2: attempts **-6**, executions -1, unnecessary attempts **-6**, rounds **-4**, prompt **0.405x**.
- C3: attempts **-6**, executions -1, unnecessary attempts **-6**, rounds **-4**, prompt **0.395x**; Task/N4 unchanged at 8/8.
- C1 is worse despite suppressing 7 duplicate executions: attempts +3, unnecessary +3, rounds +2, prompt **1.201x**.

DeepSeek therefore supplies strong evidence for **terminal action-channel control**, especially CombinedGuard, but not for duplicate-only suppression.

## 6. Mechanism Findings

### 6.1 Duplicate suppression protects execution, not convergence

Real DeepSeek examples demonstrate why attempts and executions must remain separate:

- A3-035 / I08 / C1: 4 attempts, 2 executions, 2 duplicates suppressed, 3 rounds.
- A3-054 / I02 / C1: 3 attempts, 2 executions, 1 duplicate suppressed, 3 rounds.
- A3-058 / I04 / C1: **6 attempts, 2 executions, 4 duplicates suppressed, 5 rounds**.

The external tool is protected, but the model can continue cognitively/action-wise looping on the suppressed call. Duplicate-only is therefore not a sufficient convergence mechanism.

### 6.2 Budget terminal removes the post-budget opportunity

Unseen DeepSeek NoGuard fixtures naturally reproduced the A2 failure family:

- A3-041 / I06 / NoGuard: 3 attempts, 2 executions, 3 rounds.
- A3-046 / I05 / NoGuard: 4 attempts, 2 executions, 4 rounds.
- A3-064 / I08 / NoGuard: 4 attempts, 2 executions, 3 rounds.

No DeepSeek BudgetTerminal or Combined run emitted >=3 tool attempts. Closing the action channel after the second actual execution therefore removed the repeated post-budget action opportunity and materially reduced context growth.

### 6.3 The mechanism is provider-sensitive

The same terminal idea that is strongly positive on DeepSeek is not globally safe on MiniMax. A3-018 shows that removing the tool can interact with provider output conventions: MiniMax may emit textual tool-call markup after tool removal instead of a normal final answer.

This is exactly the architecture distinction between a global principle and a provider profile: **Action Plane policy may need provider-specific realization even when the semantic operating principle is shared.**

## 7. Architectural Conclusion

A3 supports three conclusions:

1. **Do not globally deploy DuplicateSuppression.** It can save external duplicate execution but does not solve convergence and can increase prompt/round cost.
2. **Do not globally deploy BudgetTerminal/CombinedGuard yet.** Per-provider frozen gates fail on MiniMax.
3. **Do not discard terminal Action-Plane control.** DeepSeek C3 is a strong provider-specific candidate: semantic 8/8, no under-verification, attempts -6, rounds -4, prompt 0.395x NoGuard.

The evidence therefore favors a provider-profile interpretation rather than a universal fixed mechanism.

## 8. Recommended Next Step

Because frozen A3 has no global survivor, the pre-registered A4 global confirmation must not run.

Recommended new work should be split:

### P1 — DeepSeek Provider-Specific Terminal Guard Confirmation

Use an entirely new fixture family and only two treatments:

- DeepSeek Full-Slim / NoGuard;
- DeepSeek Full-Slim / CombinedGuard.

Confirm Task/N4/required-source completeness and the large attempts/rounds/prompt reduction on unseen tasks. Passing P1 would justify a **DeepSeek provider-profile strategy**, not a global architecture rule.

### M1 — MiniMax Terminal-Finalization Compatibility Development

Treat A3-018 as development evidence, not confirmation data. Investigate a structural finalization adapter for the case where the action channel is closed but MiniMax emits textual tool-call markup rather than a normal final response. Do not solve it by adding global prompt prose. Any candidate adapter must receive its own new-fixture holdout before use.

Until P1/M1 complete:

- keep production/global Action Guard unchanged;
- keep A3 frozen artifacts immutable;
- do not proceed to cross-vendor generalization on this mechanism.
