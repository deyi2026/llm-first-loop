# SMC Browser FC2-B — Bounded Semantic Operation Contract v0.1

Status: **IMPLEMENTATION_CANDIDATE — qualification in progress**

## Authority boundary

The model owns every semantic choice: ordered clauses, object identity, wait predicate, mutation verb/args, and whether the user task is complete. The program may only expand those declared clauses into already-qualified Browser mechanics.

The program MUST NOT fuzzy-match, best-match, select a target, select a latest snapshot/ref, substitute/rebind identity, invent a clause, reorder clauses, automatically retry/replay a mutation, or infer task completion/success.

## Closed contract

`browser_semantic_operation` accepts exactly one field: `clauses`, containing 1..8 ordered clauses.

Object identity is closed and model-declared:

- required: `kind`, `name`
- optional: `role`
- matching: strict equality against canonical `SemanticObject`
- exact match count = 1: continue
- exact match count = 0 or >1: halt with a mechanical receipt; no side effect and no fallback

Supported clause families:

1. object mutation: `click | fill | select | scroll`
2. page navigation: `navigate` with an exact current page resource
3. object wait: model-declared Predicate fields + bounded `timeout_ms` / `interval_ms`

## Mechanical expansion

For every clause, the tool performs only the minimum declared mechanics:

- fresh Browser observation;
- exact-unique grounding of the model-declared identity;
- typed Predicate polling for a declared wait;
- delegation of a declared mutation to `browser_semantic_execute`;
- the existing `BrowserActionAdapter` performs mandatory version checks, stable identity resolution, single physical dispatch, one post-dispatch observation/diff, and append-only ActionReceipt.

Atomic `browser_semantic_execute` and typed wait tools remain the lower-level primitives and retain their existing safety semantics.

## Receipt semantics

The operation receipt is `smc.bounded_semantic_operation_receipt.v0.1` and always carries:

- clause-by-clause mechanical facts;
- `automatic_retry_performed=false`;
- `task_completion=not_evaluated`.

`execution_status=clauses_exhausted` means only that the model-declared clauses were mechanically processed. It MUST NOT be interpreted as user-task completion.

## Real-Chrome mechanical qualification

A dedicated isolated qualifier verifies:

- exact-unique object identity dispatches once;
- same `kind + name` ambiguity halts with zero additional effect;
- model-declared typed wait can precede a single mutation;
- no automatic retry;
- no program-side task completion;
- no security-agent spawn.

An initial live probe intentionally exposed why name-only matching is invalid: Chrome DOM/AX can produce the actionable button plus same-name `StaticText`/`InlineTextBox` children. The contract was therefore tightened to require model-declared `kind + name`; it was **not** repaired by fuzzy ranking or best-match selection.

## Non-claims

This candidate does not qualify task-level success, cloud providers, fuzzy semantic search, selector synthesis, autonomous planning, automatic target recovery, mutation retry/replay, or program-side completion judgment. Real-model qualification requires a fresh protocol identity and evidence set.
