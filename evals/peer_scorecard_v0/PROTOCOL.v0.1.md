# Peer Scorecard v0.1 — Reproducible Subject/Peer Evidence Protocol

This is a new protocol identity. It does not amend, reinterpret, or overwrite the
unpublished six-dimension table it replaces, and it does not inherit any of that
table's numbers.

## Objective

Replace an equal-weight 10-point subject-vs-peers score — whose figures carried no
provenance and were computed against a revision that did not match its own label —
with a measurement that a third party can re-run and get the same answer.

The protocol measures two things and refuses to merge them:

1. **Subject evidence rung.** For each declared dimension, the highest declared
   evidence rung whose required anchors are all mechanically verified present in the
   **committed tree** of one pinned commit, and whose declared counter-anchors are all
   verified absent.
2. **Counterparty evidence inventory.** Every counterparty claim recorded with an
   evidence tier, a URL and a retrieval date.

It does **not** measure product quality, engineering velocity, or what anyone should
build next.

## Frozen treatment

- subject: `lfl`
- subject commit: `832b4dfaa2d6dba8143bd91239aa0b22b8f8dbf9`
- subject commit date: `2026-09-16T16:32:27+08:00`
- anchor resolution: `committed_tree` — anchors resolve through git object lookup at the
  pinned commit. The working tree is never read. A dirty checkout cannot change a result.
- machine contract: `docs/analysis/PEER-SCORECARD-v0.1.json`
- runner: `scripts/qualification/peer_scorecard_v0_1.py`
- dimensions: exactly 6, declared in the contract before measurement
- counterparty set: exactly 6, declared in the contract before measurement

## Evidence tiers

| tier | meaning | may carry a number |
|---|---|---|
| `V` | subject only; anchor string verified present in the pinned committed tree | yes |
| `T1` | verbatim quotation from a vendor-published page, with URL and retrieval date | yes |
| `T2` | vendor page identified and dated, claim paraphrased rather than quoted | no |
| `T3` | third-party report or press item | no |
| `T4` | model-derived prose with no retrievable source | no |

`T1` is the minimum for a counterparty figure. A `T2` claim is still recorded — it is
useful intelligence — but it is recorded without a number, because a paraphrase cannot
support the same claim as a quotation.

## Rung semantics

A rung is the highest declared rung whose `requires` anchors are all verified present
and whose `forbids` counter-anchors are all verified absent.

- A rung is a **verified lower bound on the evidence**, not a measurement of capability
  degree.
- A rung is only meaningful inside its own dimension. Rungs are **not** comparable across
  dimensions and must never be averaged.
- When a rung cannot be reached, the first unsupported rung is reported by name. Missing
  evidence is reported as an unsupported rung, never as absence of capability.
- A counter-anchor is a declaration that a named capability is expected to be **absent**.
  If it is later found present, the report records the gap as `closed` and that is
  progress, not an error.

## Composite policy

There is no cross-tier composite in v0.1, by construction:

- the subject column is tier `V`; every counterparty column is at or below `T2`;
- one declared dimension (`D6_ecosystem_ux`) is not measurable from this repository at
  all, because distribution and adoption leave no in-repo fact;
- `aggregate_verdict` is therefore permanently `not_evaluated`.

Subjective or model-authored bands remain possible, but only in a separate
`declared_judgment_cells` channel, each carrying judge, date and rationale. They are never
merged into a measured rung and never averaged with counterparty tiers.

## Gate

A run is **valid** when:

- the contract validates with zero violations;
- every declared subject anchor resolves in the committed tree of the pinned commit;
- every counterparty cell above the emission tier carries URL, retrieval date and claim,
  and every cell at or below `T2` carries no number;
- `cross_vendor_composite` is `not_evaluated`.

A run is **invalid** (non-zero exit) when the frozen contract no longer matches the
checkout: anchor drift, a missing source, a number attached below the emission tier, a
widened emission-tier list, an enabled composite, a working-tree resolution, or a
judgement cell smuggling in a measured rung.

Non-zero exit means the contract and the checkout disagree. It is not a verdict on any
product.

## Freeze discipline

The contract, the tier list, the emission tier, the rung definitions and the anchor sets
must not be changed after the first measurement. Widening `band_requires_tier`, filling a
`T4` cell with a number, or adding an anchor after seeing the result each require a new
protocol identity (`v0.2`), not an edit to this one.

The prior table this protocol replaces would be invalid on three separate rules: it
carried numbers with no evidence tier at all, it scored the subject at a ref whose commit
date (`2026-09-13`) contradicted the ref name (`20260911`) and whose narrative also counted
later work, and it presented an equal-weight composite across columns whose evidence was
not symmetric.

## Explicit non-goals

- Not a release gate, an admission rule, or a prioritisation authority.
- Does not decide what to build next. Dimension ordering and roadmap sequencing remain
  model/human judgment, and the repository's own frozen roadmap already fixes some of
  that ordering independently of this scorecard.
- Does not claim vendor-symmetric measurement. Until `T1` evidence exists for a
  dimension, that dimension is unscored for every counterparty.
