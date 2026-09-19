# Peer Scorecard v0.2 — Side-by-Side Comparison View

This is a new protocol identity. It **does not amend, reinterpret, or overwrite** the frozen
v0.1 evidence (`docs/analysis/PEER-SCORECARD-v0.1.json`,
`sha256=4d63a512647d8c7826ce1cd13b97a6e5a25dd8a5208decf16594b3407b8487b0`), which stays
byte-identical and remains a separately referenced measurement.

v0.1 closed with `cross_vendor_composite = not_evaluated`. Asking to see the two columns
together is a legitimate request, and answering it by silently filling in the withheld
numbers would have defeated the whole point. v0.2 therefore adds a **view**, not a score.

## Objective

Render the subject and the counterparties side by side, with every cell labelled by what it
actually is, so the comparison is readable without pretending the columns are commensurable.

## Frozen treatment

- subject: `lfl`
- subject commit: `832b4dfaa2d6dba8143bd91239aa0b22b8f8dbf9` (unchanged from v0.1)
- counterparty set: unchanged from v0.1 (6 products)
- dimensions: unchanged from v0.1 (6 dimensions)
- machine contract: `docs/analysis/PEER-SCORECARD-v0.2.json`
- runner: `scripts/qualification/peer_scorecard_v0_1.py` (one implementation, two contract identities)

## Three channels, rendered side by side

| column | channel | tier | may be read as |
|---|---|---|---|
| **B** | declared judgement | `T4` | a recorded opinion by a named judge on a named date |
| **A** | subject measured rung | `V` | a verified lower bound on the evidence |
| **C** | counterparty inventory | `T1`–`T4` | the legacy figure plus whatever evidence actually backs it |

Normative properties:

1. The columns are rendered adjacent and are **never averaged together**.
2. No merged cell, blended score, or cross-channel composite may exist in the view.
3. A `C` cell with no retrieved evidence renders as `--`, not as a number.
4. The `A` column is a lower bound and is not comparable to a `0-10` judgement.
5. Channel `B` records the legacy table verbatim so that its arithmetic can be re-verified
   mechanically. Reproducing the arithmetic does **not** validate the inputs.

## Legacy arithmetic verification

The contract records all 42 legacy cells (7 subjects × 6 dimensions) with judge, date and
rationale, plus each published composite. The runner recomputes every composite from its own
cells and refuses the run on any mismatch.

This is the point of the exercise: the legacy arithmetic was **correct** — every published
composite reproduces to two decimals. Its defect was never the division. The defect was that
no cell carried a source, and that the subject was anchored at a revision whose label
contradicted its commit date.

## Gate

A run is **valid** when:

- the contract validates with zero violations;
- every judgement cell carries `subject`, `dimension_id`, `judged_value`, `scale`, `judge`,
  `judged_at` and `rationale`;
- every published composite matches the mean of its own judgement cells;
- no judgement cell carries a measured `rung_lower_bound`;
- every counterparty cell at or below `T2` carries no number;
- `cross_vendor_composite` remains `not_evaluated`.

## Freeze discipline

The contract, the tier list, the emission tier, the rung definitions, the anchor sets and the
recorded legacy cells must not be changed after the first measurement. Making a counterparty
column numerically comparable requires collecting `T1` verbatim evidence — a new protocol
identity, not an edit to this one.

## Explicit non-goals

- Not a release gate, an admission rule, or a prioritisation authority.
- Does not decide whether the subject is "ahead" or "behind". Rung `A` and judgement `B` are
  different kinds of quantities; comparing them numerically is exactly the error v0.1 was
  built to prevent.
- Does not upgrade any `T2` claim to `T1`. A paraphrase never becomes a quotation by being
  placed next to one.
