# MF534-R3 ref-kind / intent-to-tool-JSON deterministic RED protocol v0.1

Status: **TEST-ONLY DETERMINISTIC RED. NO MODEL REQUEST.**

## Purpose

Freeze the already-observed MF534-R2 B Row3 failure as a separate diagnostic from
Perceive/Operate capability routing. The incident is replayed from immutable measured
evidence; this protocol does not rerun the model, modify production, or claim a causal
effect from the compact-description treatment.

The diagnostic asks two mechanical questions:

1. did a Browser operation `diff_ref` get bound into an object-wait `grounding_ref` slot;
2. after the model-visible text explicitly recognized that the diff ref was not an object
   ref, did the serialized tool arguments still repeat the old diff ref.

## Frozen source

- measured identity: `MF534R2-ORNITH-AB-v0.1-MEASURED-489dd5a4`
- measured HEAD: `489dd5a47a7636ec0a6791dc1964c35c68bb7cf8`
- result freeze: `cbe225f52d4d59789fab9ba148230981b2abdcee`
- run: `03-fill_submit-r1-B`
- raw event log SHA-256:
  `43d97fd597a77f260f5d19f78d1f30db9a51c3e41e9ad5da56d952c753cdfe46`

The fixture stores only ref kinds/ref hashes, argument-key shapes, compact failure facts,
and two short model-visible intent statements. It excludes raw URLs, page bodies,
hidden reasoning, and full GroundingRef values.

## Deterministic RED conditions

The replay is RED iff all of the following are true:

- `browser_operate(do=set_text)` emits a `diff_ref`;
- the next object-text verification binds the same ref hash as `grounding_ref`;
- that ref is classified as `diff`, not `object`;
- generic `browser_perceive(action=hydrate)` accepts that ref and returns a
  `smc.semantic_diff.v0.1` projection;
- object-text wait then rejects the same ref with `object_ref_projection_mismatch`;
- the model-visible text later states that the diff ref is not a valid object ref and that
  it should use the original object ref, while the tool JSON still repeats the old diff-ref
  hash;
- repeated repair consumes the 12-round budget before Save is clicked.

This RED is a structured-output binding incident, not a task-semantic verdict.

## Provider-contract diagnostic

The current model-visible Perceive contract intentionally uses the same field name
`grounding_ref` for generic hydrate and object waits. The deterministic diagnostic records
whether the object-wait branch gives the provider a machine-readable ref-kind discriminator
(`pattern`, `format`, enum/const, or field-level type description). Absence is RED only as a
contract-visibility fact; it does not authorize a production schema change.

## Controls

The same measured matrix contains three other `fill_submit` rows:

- A/r1 performs post-`set_text` object-text verification with a real `/object/` ref and
  completes with zero repair;
- A/r2 clicks Save directly after `set_text` and never exercises object-text wait;
- B/r2 also clicks Save directly after `set_text` and completes with zero repair.

Therefore this fixture must report treatment causality as `NOT_ESTABLISHED`.
