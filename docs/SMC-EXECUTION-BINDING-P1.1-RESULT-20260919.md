# SMC Execution Binding P1.1 — Qualification Result

> Date: 2026-09-19
> Status: **QUALIFIED_DETERMINISTIC / SYNTHETIC / NON-PRODUCTION**
> Exact implementation candidate: **3b723ecc5899dee8f17efe9055ac77e091e43672**
> P1.1 scope commit: **a7204efc757ffda210c783b0026b0bf27d45c809**
> Parent P1 result: **d0af187baa2819b76a6df31a962f3c0f0fa6c814**

## 1. Verdict

P1.1 closes the four follow-up gaps identified after independent review:

1. receipt-obligations contract-oracle parity;
2. ActionRef lifecycle sequencing;
3. capability-surface scale quantification;
4. deterministic TOCTOU interleaving.

All P1.1-G1 through P1.1-G12 have qualification evidence.

P1 remains historically immutable at its exact result commit and hashes. P1.1 is a follow-up qualification, not a rewrite of the P1 evidence record.

## 2. Receipt-obligations parity

The frozen Execution Binding contract defines nine binding-equivalence dimensions. The previous deterministic oracle encoded only eight and omitted receipt obligations.

P1.1 corrects the qualification oracle:

- binding-equivalence inputs now include same_receipt_obligations;
- EB3-01 remains the all-dimensions-equal allow case;
- EB3-02 remains a reject case with other semantic mismatches;
- EB3-03 is new and changes only receipt obligations while the other eight dimensions remain equal;
- EB3-03 deterministically rejects as binding_not_equivalent.

The independent P1 reference harness already included receipt_obligations in its equivalence signature. P1.1 adds an explicit receipt-only mutation test proving the independent harness also rejects it.

Current contract fixture count:

**25 cases**

This fixes text/oracle drift without removing the ninth dimension from the contract.

## 3. ActionRef lifecycle

P1.1 exercises ActionRef as a sequence instead of isolated input-to-decision checks.

Frozen sequence:

1. observe v1;
2. issue ar1;
3. admit ar1 at v1;
4. mutate synthetic object to v2;
5. reject ar1 as stale;
6. re-observe v2;
7. issue ar2;
8. confirm ar1 remains stale;
9. admit ar2 at v2;
10. advance deterministic logical time beyond ar2 expiry;
11. reject ar2 as expired.

Qualified invariants:

- ar1 and ar2 are distinct;
- issuing ar2 never revives ar1;
- no hidden re-observation changes the old handle;
- no silent successor substitution occurs;
- TTL remains retention-only rather than freshness;
- logical time is deterministic;
- real OS dispatch count remains zero.

Lifecycle evidence SHA-256:

**88b492935b82b91a1270a911d95a521e66e40f4378a3ebf4f34370e370d1b48c**

## 4. Capability-surface scale

P1.1 generates deterministic synthetic surfaces at:

**32 / 128 / 512 / 1024 capabilities**

and enumerates each at page sizes:

**16 / 32 / 64**

All generated manifest pages are validated against the frozen Execution Binding schema.

The only filters used are explicit mechanical fields:

- target_kind;
- semantic_verb;
- control_capability_class.

No task relevance, embedding similarity, semantic ranking or model-generated priority is used.

### Page-size 32 headline

| Capabilities | Pages | Full wire chars | char/4 token heuristic | Combined mechanical filter count | Filtered wire chars |
|---:|---:|---:|---:|---:|---:|
| 32 | 1 | 16,300 | 4,075 | 1 | 929 |
| 128 | 4 | 65,130 | 16,283 | 3 | 1,925 |
| 512 | 16 | 260,458 | 65,115 | 11 | 5,911 |
| 1024 | 32 | 520,858 | 130,215 | 22 | 11,389 |

The token column is only a mechanical characters-divided-by-four heuristic. It is **not** a provider tokenizer measurement.

The important design result is qualitative and exact at the character/page layer:

> Full unfiltered capability enumeration becomes very large at realistic high counts, while explicit mechanical filters can reduce the model-visible surface substantially without letting the program decide task relevance.

This supports the architecture rule:

**Capability discovery should use deterministic paging + explicit mechanical filters, not program-side semantic relevance ranking.**

Scale matrix SHA-256:

**304dfd1570ab444600edb2f09b3f86064d2e89d0b2743b48a6bbec7f0ace6562**

## 5. TOCTOU interleaving

P1.1 explicitly models four human/context-change injection positions around context-sensitive execution:

1. before_prepare;
2. after_prepare_before_revalidate;
3. after_revalidate_before_dispatch;
4. after_dispatch.

Deterministic results:

| Classification | Count |
|---|---:|
| prevented before dispatch | 2 |
| residual TOCTOU window | 1 |
| post-dispatch settlement | 1 |
| automatic replay | 0 |
| real OS dispatch | 0 |
| synthetic dispatch | 2 |

The key result is the third injection point:

**after_revalidate_before_dispatch**

A context change at this position is not generically eliminable by a contract that lacks an atomic compare-and-dispatch primitive.

P1.1 therefore does not claim zero race.

Instead the synthetic receipt records:

- classification = residual_toctou_window;
- status = ambiguous;
- context changed after revalidation;
- observed synthetic effect facts;
- automatic_replay = false;
- rollback_claimed = false.

This freezes the correct cross-platform contract:

> SMC should minimize and mechanically fence the revalidate-to-dispatch interval where possible, but generic bindings must honestly represent residual TOCTOU rather than promising zero concurrency risk.

These counts enumerate deterministic interleaving positions. They are **not real-world race probabilities**.

Interleaving evidence SHA-256:

**b4ba233d1c5292a5923d48b5ef15a54c5b09b34ec6409d6a2f0086186efd4ef9**

## 6. Deterministic qualification

Exact candidate:

**3b723ecc5899dee8f17efe9055ac77e091e43672**

Two independent evidence executions were identical.

Run SHA-256:

**f1a9fb6272d620d17f4bf4de9c5a96c1ede92cd7b258c35dedcc002fdba5ab65**

Canonical evidence SHA-256:

**a29dbcdd4e4688b5ee5b3da42a4ae484bd8d89b36dc17fe959bb6792c034d163**

Focused + adjacency qualification:

| Suite | Tests | Result |
|---|---:|---|
| P1.1 | 8 | PASS |
| P1 | 19 | PASS |
| Execution Binding contract | 13 | PASS |
| SMC contract conformance | 15 | PASS |
| P4-D adjacency | 19 | PASS |
| **Total** | **74** | **74/74 PASS** |

Additional checks:

- Ruff: PASS;
- Ruff format: PASS;
- Pyright: 0 errors / 0 warnings;
- updated contract fixture JSON: PASS;
- git diff check: PASS;
- commit security scan: PASS;
- forbidden real-OS/network/input imports in P1.1 surface: zero matches;
- src production changes from parent P1: zero.

## 7. Full repository gate

The full repository gate was run on the exact candidate using the repository-root Python binding.

Final exit status:

**0**

Observed:

- all-repo Ruff PASS;
- env-pin: 629 test files scanned / 0 undeclared;
- src Pyright: 0 errors / 0 warnings;
- tier0 PASS;
- xdist full repository PASS;
- final ci_gate summary PASS.

The existing 44 audit_test_side_effects findings remained non-blocking warnings.

The CI run produced the known pytest restart-preflight residue under scripts/data/audit. It was read back, confirmed to point to the pytest temporary tree with outcome=aborted, and only that verified residue was removed.

## 8. Gates

| Gate | Result |
|---|---|
| P1.1-G1 nine-dimension oracle parity | PASS |
| P1.1-G2 receipt-only mismatch cross-validation | PASS |
| P1.1-G3 ActionRef lifecycle | PASS |
| P1.1-G4 12-row scale matrix | PASS |
| P1.1-G5 mechanical filter surface reduction | PASS |
| P1.1-G6 four interleaving positions | PASS |
| P1.1-G7 residual TOCTOU honesty | PASS |
| P1.1-G8 no replay / no fictional rollback | PASS |
| P1.1-G9 deterministic double-run | PASS |
| P1.1-G10 focused + adjacency / static gates | PASS |
| P1.1-G11 full repository CI | PASS |
| P1.1-G12 zero src change / zero real OS dispatch | PASS |

## 9. Remote evidence status

Before P1.1, an ordinary push of the parent P1 exact commit was attempted to:

review/smc-execution-binding-p1-20260919

The MCP runtime could not acquire GitHub HTTPS credentials:

fatal: could not read Username for https://github.com: Device not configured

The failure occurred before remote mutation.

Therefore:

- parent P1 local exact commit remains valid;
- no remote branch SHA is claimed;
- remote evidence anchor remains **pending_auth**;
- formal main was not changed by that failed attempt.

P1.1 proceeded from the exact local P1 commit by explicit user authorization.

## 10. Non-claims

P1.1 does not prove:

- real macOS/Windows/Linux/Android/iOS execution quality;
- real-world race probability;
- real provider token counts for capability manifests;
- live human/AI co-control safety;
- model FCR on the final SMC control surface;
- P4-FCR v0.2 qualification;
- P4-LIVE qualification.

No production src code, deployment, restart or model request was used by P1.1.

## 11. Architecture consequence

P1.1 strengthens the next-stage contract in three important ways:

1. binding equivalence is truly nine-dimensional, including receipt obligations;
2. ActionRef is explicitly a lifecycle protocol rather than a static handle check;
3. context revalidation reduces races but does not magically create atomicity.

For future real-platform adapters, each binding should therefore declare whether it has:

- an atomic compare-and-dispatch primitive;
- a bounded non-atomic revalidate-to-dispatch window;
- or no safe context-sensitive dispatch mechanism.

That fact should become part of adapter qualification before real mutation is allowed.
