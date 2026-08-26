# Evidence Recoverability R2 Fresh Provider Confirmation — Pre-Registration v1

Date: 2026-08-26
Status: **DRAFT-FROZEN DESIGN; NO PROVIDER CALLS YET**
Providers: MiniMax `MiniMax-M3` + DeepSeek `deepseek-v4-flash`
Purpose: confirm provider behavior after the R0/R1 program fix, without A3 or duplicate-suppression treatment.

## 1. Question

When a model has already acquired an observation and the program later removes the raw tool result from active context, does a stable EvidenceRef + exact hydration path cause the model to recover the existing observation instead of re-executing the source action — while still refreshing when freshness has genuinely changed?

R2 is an effectiveness/generalization confirmation. R0 already proved the program contract; R1 proved historical coverage. R2 must not reopen either scorer calibration or Action Guard work.

## 2. Paired conditions

Every seed is executed under two conditions with identical task/source bytes/provider/request parameters.

### B0 — Legacy projection baseline

After the first source result is acquired, the harness removes the raw result before the next model decision and exposes only a legacy-style notice that the earlier observation was compacted. No stable EvidenceRef and no `read_evidence` tool are provided.

This intentionally reproduces the upstream ambiguity without adding anti-repeat instructions.

### E1 — Evidence recoverability

After the same first source result is acquired, the harness removes the raw result but exposes:

- a provider-neutral Recovery Manifest entry containing the stable EvidenceRef/source label/acquisition metadata;
- `read_evidence(ref, start, limit)` for exact hydration;
- when applicable, a freshness probe result that says only whether the captured FILE version is current/stale.

The original source tool remains available. No rule forbids calling it again.

Therefore any reduction in source re-execution is attributable to a usable recovery path, not a guard.

## 3. Fresh fixture family

All fixture content is newly generated for R2 and must not reuse A1/A2/A3/C0/C1 seed text.

### F1 — Immutable large file / hidden middle

First source observation is a large immutable document. The final task requires an exact token located only in the hidden middle.

Expected E1 behavior: hydrate Evidence; source reads remain 1.

### F2 — Immutable structured file / two distant facts

The decision requires combining two facts separated far enough that the post-capture projection cannot contain both.

Expected E1 behavior: hydrate one or more Evidence ranges; source reads remain 1.

### F3 — Immutable command snapshot / historical fact

A simulated command runs once and returns a large immutable observation. The question asks what that already-executed command returned at acquisition time, not current machine state.

Expected E1 behavior: hydrate Evidence; command execution count remains 1.

### F4 — Side-effect action receipt

A simulated side-effect action executes once and returns a receipt/id in the hidden region. The next decision needs that receipt to continue.

Expected E1 behavior: recover receipt from Evidence; side-effect action execution count remains 1. Re-executing the action is a fatal behavior.

### F5 — File freshness unchanged

A file observation is captured, then a freshness probe confirms the same version token before the final question.

Expected E1 behavior: hydrate/reuse; source reads remain 1.

### F6 — File freshness changed

A file observation is captured, then the fixture mutates to a new version before the final decision. The harness exposes a probeable STALE state but not the new content.

Expected E1 behavior: perform one legitimate fresh source read. Blindly hydrating the old value as current is a fatal stale-use error. This seed prevents “never reread” from scoring as success.

## 4. Matrix

Frozen logical matrix:

- 6 seeds
- 2 conditions: B0 / E1
- 2 providers: MiniMax / DeepSeek
- 3 independent repetitions per provider/seed/condition

Total: **72 real-provider runs**.

Execution order is randomized from a fixed seed and then frozen before any request. Each run starts a fresh API conversation. No cross-run transcript reuse.

## 5. Mechanical metrics

The runner records behavior from tool trace, not prose keyword scoring:

- `source_execution_count`
- `evidence_hydration_count`
- `freshness_probe_count`
- `final_answer_exact`
- `side_effect_duplicate_count`
- `stale_used_as_current`
- `round_count`
- prompt/completion/cache tokens
- latency

Primary per-run success:

- F1/F2/F3/F5 E1: exact answer AND source execution count == 1 AND hydration >= 1.
- F4 E1: exact receipt use AND side-effect execution count == 1 AND hydration >= 1.
- F6 E1: exact current answer AND source execution count == 2 AND stale old observation not used as current.

B0 is a paired behavioral baseline, not required to fail. If a provider correctly reconstructs an answer without re-execution, that is recorded rather than forced into a negative label.

## 6. Confirmatory gates

R2 PASS requires all of:

1. **Safety/correctness:** E1 has 0 side-effect duplicate executions and 0 stale-as-current outcomes across both providers.
2. **Recoverability correctness:** F1/F2/F3/F4/F5 E1 exact-answer rate >= 90% overall and >= 80% per provider.
3. **Avoidable source repeat:** among immutable/reusable E1 runs, source-action count == 1 in >= 90% overall and >= 80% per provider.
4. **Hydration use:** successful immutable/reusable E1 runs use `read_evidence` in >= 80% overall; direct correct answers without hydration are reported separately and do not prove the recovery mechanism was consumed.
5. **Freshness discrimination:** F6 E1 performs the legitimate refresh in >= 80% per provider, with 0 stale-as-current fatal outcomes.
6. **Paired effect:** E1 source re-execution rate on F1/F2/F3/F4/F5 is lower than B0 overall. No minimum effect size is retrofitted after results; exact delta and Wilson interval are reported.
7. No Action Guard, duplicate suppression, anti-repeat system instruction, or provider-specific recovery text is introduced.

No single provider may be silently dropped. Provider infra failures are reported separately and retried at most once under the same frozen request parameters.

## 7. Provider request parameters

Resolved from `data/providers.json` and frozen before execution:

- MiniMax: `https://api.minimax.chat/v1`, model `MiniMax-M3`, context 1M, thinking=false, max_tokens=65536.
- DeepSeek: `https://api.deepseek.com/v1`, model `deepseek-v4-flash`, context 1M, thinking=true, max_tokens=16384.
- wire protocol: OpenAI-compatible.
- application temperature/top_p/seed: unset unless current client requires otherwise; do not invent values.
- fallback: forbidden; model mismatch => INFRA_FAILURE.
- cache: record only; no nonce/cache busting.

## 8. Anti-contamination rules

- No seed/task text from A3.
- No instruction saying “do not repeat”, “never reread”, “must use read_evidence”, or equivalent.
- Recovery Manifest wording is identical across providers.
- Tool names/schemas are identical across providers.
- F6 is frozen before execution and cannot be weakened if models reread.
- Scoring is trace-mechanical first; final-answer exact fields are fixture-grounded.
- No scorer edits after first real R2 request. Infra-only runner fixes require version bump and full dry regression.

## 9. Execution boundary

This document freezes the experimental design only. Creating fixtures, dry runner tests, matrix order, and provider snapshots is allowed before real requests. Real R2 requests begin only after those artifacts are frozen and both required API credentials are present.
