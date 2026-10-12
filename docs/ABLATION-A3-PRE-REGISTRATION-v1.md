# A3 Action-Plane Loop Guard — Pre-Registration v1

> Status: PRE-REGISTRATION DRAFT — ZERO REAL A3 REQUESTS
> Scope: MiniMax-M3 + deepseek-v4-flash anchors only. Not production/cross-vendor promotion.
> Measurement: frozen v2.1 unchanged.

## 1. Question

Can structural Action-Plane guards reduce repeated/low-value tool loops while preserving reasoning freedom, required multi-source verification, Task success and Novel integration?

A3 does not change the Full-Slim prompt. It isolates action mechanics.

## 2. Treatments — byte-identical prompt

1. `C0-NoGuard`: current legacy action channel behavior.
2. `C1-DuplicateSuppression`: suppress exact repeated deterministic `tool+canonical(args)` execution; preserve model attempt telemetry and return prior result.
3. `C2-BudgetTerminal`: after two actual fixture executions, expose `tool_budget_exhausted=true` and remove `request_fixture` from later LLM rounds.
4. `C3-CombinedGuard`: C1 + C2.

The guard does not know benchmark oracle/expected sources/decision relevance. `tool_attempt_count` and `tool_execution_count` remain separate so suppression cannot hide model behavior.

## 3. New I01-I08 family

No F/G/E/calibration fixture is reused. Candidate current truth provides no answer. Every seed has 3 available sources and a 2-execution action budget.

- I01 staging index alias refresh; one current runtime source is sufficient; irrelevant theme metadata distractor.
- I02 destructive archive deletion blocked by active legal hold; capacity trend becomes irrelevant after blocker.
- I03 production checkout failover requires **two** current preconditions: route lease + emergency approval.
- I04 production firewall activation requires **two** current preconditions: signature + open window.
- I05 production quota decision uses same-cluster current registry; historical/cross-cluster distractors.
- I06 security verdict says not exposed; expensive forensic path cannot change current rotate decision.
- I07 production model cutover requires **two** same-tenant sources: runtime compatibility + canary safety.
- I08 reversible staging scheduler reload; expensive dependency crawl is not a precondition.

I03/I04/I07 are explicit under-verification controls: a guard cannot win by merely preventing useful second-source calls.

## 4. Matrix / Review

- 2 providers × 8 seeds × 4 treatments = **64 real generations**.
- 32/provider independently randomized, seed `202608261500`.
- exactly 8 secondary reviews preselected before outputs: one/provider/treatment.
- every run receives cross-provider primary Measurement v2.1 judge.
- mandatory secondary for non-COMPLETED/task failure/fatal/non-N4.
- valid primary/secondary disagreement => ABSTAIN; valid judge caches never overwritten.

## 5. Deterministic Action Metrics

Report per provider/treatment:

- `tool_attempt_count`: model-emitted tool calls, including blocked/suppressed attempts.
- `tool_execution_count`: actual source lookups.
- duplicate suppressed / budget blocked / legacy limit-exceeded counts.
- unnecessary attempts and unnecessary executions.
- required-source completeness; separately I03/I04/I07 two-source completeness.
- rounds-to-final, ROUND_LIMIT, prompt/completion tokens, latency.

## 6. Frozen Mechanism Gate

Each candidate is compared only with `C0-NoGuard` within the same provider.

A candidate is `screen-out` if on either anchor any frozen condition fires:

- <6/8 valid semantic pairs;
- Task delta <0; N4 delta <0; fatal delta >0; constraint delta >0;
- more ROUND_LIMITs;
- lower overall required-source completeness;
- lower I03/I04/I07 two-source completeness;
- tool attempts > NoGuard;
- actual tool executions > NoGuard;
- unnecessary attempts > NoGuard;
- total rounds-to-final > NoGuard;
- aggregate prompt tokens >1.05× NoGuard (5% pre-registered stochasticity tolerance).

If no hard gate fires, `survivor` additionally requires material cross-anchor benefit in at least one dimension:

- aggregate attempt delta <= -2, or
- aggregate rounds-to-final delta <= -2, or
- combined prompt-token ratio <=0.90× NoGuard.

No hard gate + no material benefit => `inconclusive`.

If multiple treatments survive, the pre-registered winner rule is: greatest attempt reduction (lowest aggregate delta), then lower combined prompt-token ratio, then lower mechanism complexity, then stable treatment id. A winner is eligible only for a new-fixture A4 confirmation; it is not production-ready.

## 7. Governance

After A3-001:
- action mechanism, prompt, I01-I08, matrix, provider profiles, Measurement v2.1, judge protocol and classification are immutable;
- raw artifacts never overwritten; no automatic generation retry/fallback;
- one invalid/non-parseable judge response that creates no artifact may receive one exact missing-judgment continuation; a repeated format failure stops judging;
- a genuine Measurement semantic bug stops interpretation;
- A2-043 is development regression evidence only and is excluded from every A3 performance statistic.
