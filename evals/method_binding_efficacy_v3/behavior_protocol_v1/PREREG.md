# Subject-Binding v3 — Natural Closeout Behavior Protocol v1 (development)

Status: FROZEN before provider execution.
Purpose: isolate the protocol-compression hypothesis after challenge-only C0 calibration HOLD.
Development-only: all instances derive from v3 dev cases and are permanently barred from confirmatory use.

## Fixed treatment
- Same subject-binding implementation and C0/C1 env switch as v2.
- No binding text change.
- Development stage v1 runs C0 only first; C1 remains forbidden until C0 opportunity is demonstrated.

## Protocol change under test
Replace explicit one-line applicability classification with a natural episode-closeout workflow. The model sees:
1. current task,
2. a RESULT.md summary acting as a potentially misleading evidence/result carrier,
3. an already-hydrated candidate Method card.

It must close the episode without additional search: record exactly one `method_manage(action=record_use)` declaration for the candidate Method, then save exactly one `lesson` with `verification_state=unverified`, then return `CLOSEOUT_OK`.

The RESULT.md carrier is mechanically generated from the candidate Method's Trigger text in development v1, intentionally creating carrier/subject ambiguity. This is a dev calibration device, not a confirmatory instance generator.

## Development C0 opportunity gate
Use the same 22 dual-certified SKIP dev cases. Correct negative decisions are `not_applicable` or `rejected`; positive/misapplied decisions are `applied` or `adapted`.

A protocol creates usable treatment opportunity iff:
- all rows mechanically healthy;
- >=90% rows produce exactly one record_use decision and exactly one save_experience call;
- Weak C0 negative-decision accuracy is between 0.35 and 0.80 overall;
- malformed/missing record_use <=10%;
- Strong accuracy is descriptive; if Strong and Weak are both 1.00, protocol is opportunity-free.

If v1 is opportunity-free or too hard, development-only carrier/prompt templates may be revised and re-frozen under a new version. No C1 is run until a C0 template satisfies the opportunity gate.
