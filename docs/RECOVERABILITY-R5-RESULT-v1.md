# Evidence Recoverability R5 — Freshness Oracle Holdout Result v1

Date: 2026-08-26
Frozen pack: `tests/fixtures/evidence_r5/frozen_v1.json`
Official frozen scorer: **FAIL (1 efficiency gate only)**
Freshness correctness: **PASS across all 24 rows**
Production rollout: **NOT YET ELIGIBLE**
A3: **STOPPED / excluded**

## Executive result

R5 removes the oracle ambiguity that affected R4 by mechanically pre-acquiring Evidence before provider request #1, discarding the raw tool result, mutating current-source fixtures, and exposing only the durable Recovery Manifest to the model.

The valid run completed **24/24** with:

- exact answer: **24/24**;
- MiniMax: **12/12** exact;
- DeepSeek: **12/12** exact;
- J1/J3 current answers: **12/12** exact;
- stale-as-current: **0/12 current rows**;
- J2 historical answers: **6/6** exact;
- explicit `allow_stale=true` historical access: **6/6**;
- J2 model current-source executions: **0/6**;
- J4 UNKNOWN snapshot: **6/6** exact;
- J4 snapshot source reruns: **0/6**;
- transport EvidenceRef used as domain answer: **0/24**;
- exact same source+canonical-args repeats: **0**.

The frozen scorer nevertheless returns **FAIL** because one DeepSeek J1 row has one `redundant_overlap_count` event. No threshold/scorer edit overrides this official result.

## The single failing row

`R5-006` (DeepSeek, J1 current target) is exact and freshness-safe:

```text
answer=CEDAR-741
stale_as_current=false
exact_source_args_repeat_count=0
```

Its source/recovery chain is:

```text
round 1:
  read_file(current file, default/full coverage)
  -> current observation captured as Evidence
  -> projected excerpt + EvidenceRef

round 2, same assistant tool batch:
  search_evidence("R5-CURRENT-TARGET")
  read_file(offset=100, limit=60)
```

The search call already finds the exact current field in the newly captured verified-current Evidence. The second source read overlaps bytes/lines already acquired by the round-1 full current observation, so the frozen overlap metric correctly records one extra source access.

This is **not** the original evidence-loss failure:

- the old stale Evidence remained discoverable;
- stale access was correctly blocked for a current query;
- a fresh current EvidenceRef was created;
- exact search recovery succeeded;
- there was no exact same-args source repeat;
- the model returned the correct current value.

It is a residual action-selection efficiency issue after recoverability has already succeeded.

## Program-level cause exposed by the trace

The model-facing `read_file` contract contains two valid but competing instructions:

1. Evidence-enforce text says omitted content should be recovered through stable EvidenceRef / `read_evidence`;
2. the generic tail says large files should be read directly with `offset/limit` segments.

DeepSeek's reasoning on R5-006 explicitly reflects both choices: after seeing the full-read excerpt and Evidence context it says it can “search the evidence or read the full file”, then emits both recovery search and direct range-read tools in parallel.

Thus the remaining extra call is not caused by a missing archive/ref. It is caused by **legacy source-continuation guidance and Evidence recovery guidance coexisting without a precedence rule**.

## Frozen gates

Machine report: `data/audit/evidence_r5/score_real_v1.json`

All gates PASS except:

```text
zero_redundant_overlap = false
```

The following critical gates PASS:

- 24/24 infra complete;
- zero transport-ref-as-domain;
- zero exact source+args repeats;
- current stale-as-current zero;
- current exact/provider floors;
- every exact current row refreshed source;
- historical exact/provider floors;
- every exact historical row explicit stale access;
- every exact historical row zero current-source access;
- UNKNOWN exact/provider floors;
- UNKNOWN recovery with zero source rerun and zero stale block;
- overall/provider exact floors.

## Post-run integrity

- R5 + R3 focused tests: PASS;
- all Evidence tests: PASS;
- R0 aggregate: **12/12 PASS**;
- targeted Ruff: PASS;
- targeted Pyright: **0 errors / 0 warnings**;
- frozen pack verification: PASS.

Hashes:

- valid runs: `41ec9364ab00e96816fcc4a82176be37f0410d04075af5bc7c3c963bf92dcea2`
- frozen score: `1c129801694f8a6de922523fd1e4b7a8948c8fcd3b631f5cbd9676e1aa28ee0a`
- frozen pack: `0c852983ad0130cabe38e280c9a2220ac15386a401fe80d66984a69534a7ff50`

## Decision

R5 provides strong confirmatory evidence that R3 v1.1 fixed the core freshness/current-vs-historical contract:

```text
recoverability continuity       confirmed
stale-as-current safety         confirmed
historical explicit access      confirmed
UNKNOWN non-overblocking        confirmed
transport/domain typing         confirmed
exact same-args repeat loop      0 observed
```

The only remaining frozen failure is one overlapping direct-source range read after a current EvidenceRef already existed.

Do not add Action Guard or duplicate suppression. The next root fix should audit and remove contradictory **source-vs-recovery tool contract guidance** across `read_file`, command and web tools, while keeping one stable schema after the change. Then validate that guidance with a fresh efficiency holdout; do not reuse R5 as confirmatory data.
