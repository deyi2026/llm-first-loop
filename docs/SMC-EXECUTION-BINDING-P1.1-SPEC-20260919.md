# SMC Execution Binding P1.1 — Oracle Parity / Lifecycle / Scale / Interleaving

> Date: 2026-09-19
> Status: **FROZEN SCOPE CANDIDATE / SYNTHETIC / NON-PRODUCTION**
> Parent P1 result: **d0af187baa2819b76a6df31a962f3c0f0fa6c814**
> Parent P1 implementation: **11559ea640e4bdb19e39331975d824d7a0aacc58**
> Frozen Execution Binding contract: **3b7163a11dca88e7a4e2bd6c6b7146e5925adc31**

## 1. Purpose

P1.1 does **not** reopen or rewrite the qualified P1 result.

It adds four narrow follow-up qualifications prompted by independent review:

1. close the contract-oracle drift around receipt obligations;
2. test ActionRef as a lifecycle sequence rather than isolated predicates;
3. quantify deterministic capability-surface scaling without semantic relevance ranking;
4. model prepare/revalidate/dispatch interleavings and expose residual TOCTOU honestly.

No real OS adapter, provider-visible tool, model call, deployment, restart, P4-FCR treatment, or production src change is authorized.

## 2. P1.1-A — Receipt-obligation oracle parity

The frozen contract defines automatic binding equivalence across nine dimensions, including receipt obligations.

P1.1 MUST:

- update the deterministic contract oracle to include same_receipt_obligations;
- keep an allow case where all nine dimensions match;
- add a reject case where the first eight dimensions match and only receipt obligations differ;
- independently verify the P1 reference harness rejects the same receipt-only mismatch;
- preserve fallback_policy=equivalent_only.

P1.1 MUST NOT remove receipt obligations from the contract to make the old oracle pass.

## 3. P1.1-B — ActionRef lifecycle sequence

Use a deterministic logical clock and an ephemeral synthetic world.

The required sequence is:

1. observe object at version v1;
2. issue ActionRef ar1;
3. admit ar1 at v1;
4. externally mutate synthetic object to v2;
5. reject ar1 as stale;
6. re-observe v2;
7. issue ar2;
8. confirm ar1 remains stale;
9. admit ar2;
10. advance logical time past ar2 retention deadline;
11. reject ar2 as expired.

Hard rules:

- no silent refresh;
- no silent successor substitution;
- old ActionRef never becomes valid again merely because a new one was issued;
- timestamps are logical, not wall-clock;
- real OS dispatch count remains zero.

## 4. P1.1-C — Capability scale qualification

Generate deterministic synthetic capability surfaces at:

32 / 128 / 512 / 1024

For page sizes:

16 / 32 / 64

Record exact:

- total capability count;
- page count;
- full-enumeration wire characters;
- largest page wire characters;
- approximate token count using a documented mechanical character heuristic only;
- filtered count/page/wire cost under explicit mechanical filters.

Allowed filters in P1.1:

- target_kind;
- semantic_verb;
- control_capability_class.

Forbidden:

- semantic similarity;
- relevance score;
- task-aware ranking;
- model-generated priority.

Scale qualification is about surface cost, not Python runtime performance.

## 5. P1.1-D — Deterministic TOCTOU interleaving

The generic contract cannot promise zero race between context revalidation and physical dispatch.

P1.1 MUST explicitly model deterministic injection points:

1. before_prepare;
2. after_prepare_before_revalidate;
3. after_revalidate_before_dispatch;
4. after_dispatch.

Expected semantics:

- changes visible before revalidation -> reject before dispatch;
- change after revalidation but before non-atomic dispatch -> classify as residual TOCTOU window, dispatch outcome may require honest settlement;
- changes after dispatch -> settle actual synthetic effects;
- no automatic replay;
- no fictional rollback;
- no claim that residual window probability is zero.

The result MUST report:

- injection positions exercised;
- prevented-before-dispatch count;
- residual-window count;
- post-dispatch-settlement count;
- real OS dispatch count;
- synthetic dispatch count.

These are deterministic interleaving counts, **not real-world probabilities**.

## 6. Gates

| Gate | Requirement |
|---|---|
| P1.1-G1 | Contract oracle includes all 9 equivalence dimensions |
| P1.1-G2 | Receipt-obligations-only mismatch rejects in both oracle and independent P1 harness |
| P1.1-G3 | Full ActionRef lifecycle sequence passes with old-ref stale/new-ref valid/expiry semantics |
| P1.1-G4 | Scale matrix covers 4 capability sizes x 3 page sizes deterministically |
| P1.1-G5 | Mechanical filters reduce/project surface without semantic ranking |
| P1.1-G6 | All four interleaving positions are exercised |
| P1.1-G7 | Residual TOCTOU is reported, not asserted away |
| P1.1-G8 | No automatic replay/fictional rollback |
| P1.1-G9 | Double-run canonical evidence hash is identical |
| P1.1-G10 | Focused + adjacent tests, Ruff, Pyright, diff/security checks pass |
| P1.1-G11 | Full repository ci_gate exits 0 |
| P1.1-G12 | src production changes = 0 and real OS dispatch = 0 |

## 7. Evidence discipline

P1.1 result evidence MUST bind:

- exact Git commit;
- parent P1 commit;
- updated contract-oracle fixture hash;
- P1.1 synthetic evidence hash;
- scale matrix hash;
- interleaving matrix hash;
- focused/adjacent counts;
- full CI final status;
- zero-production-change and zero-real-OS-effect facts.

The earlier P1 result remains historically true for its exact pinned artifact hashes.

## 8. Remote evidence note

The recommended remote freeze of parent P1 was attempted before P1.1, but the MCP environment lacked GitHub HTTPS credentials and the push failed before any remote mutation.

Therefore:

- parent P1 exact local commit remains the P1.1 base;
- remote P1 evidence anchor is explicitly pending;
- P1.1 MUST NOT claim a verified remote branch until a later successful ordinary push + remote SHA check.
