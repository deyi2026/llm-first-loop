# Subject-Binding Efficacy v3 — Development Difficulty Calibration Preregistration

Status: FROZEN before any v3 development provider row.
Source contract: `evals/method_binding_efficacy_v2/posthoc_opportunity_v1/V3-CALIBRATION-CONTRACT.md` at source commit `e347fe3fa7a97cd0163a71a726f3968bc9b606cb`.

## Purpose

Qualify a development-only challenge set that can measure **control difficulty**, not treatment efficacy. Development instances are permanently barred from confirmatory use.

## Construction

- 24 intended-SKIP purpose-level near misses, 6 in each predeclared family:
  - `same_object_different_action`
  - `same_evidence_different_claim`
  - `same_workflow_different_phase`
  - `same_infra_different_decision`
- 8 intended-APPLY positive controls used only to verify blind-rater discrimination.
- Every SKIP task uses a positive task-purpose description. Direct anti-trigger disclosure is forbidden.
- Every SKIP row records `subject_method_id`, `source_method_id`, `family`, `shared_surface`, and `purpose_divergence`.
- Exact task text must be fresh against v1 and v2 efficacy pools.

## Provider-free label qualification

Two independent blind proxy raters see only opaque id, task, and subject Method card. They do not see family, intended label, source method, or purpose divergence.

Pass gates:

- raw agreement >= 0.85
- Cohen kappa >= 0.70
- overall intended accuracy for each rater >= 0.90
- intended-SKIP dual-certified >= 20/24
- each SKIP family dual-certified >= 5/6
- APPLY controls dual-certified >= 7/8
- anti-leak linter: 0 unresolved direct anti-trigger disclosures among certified SKIP rows

`dual-certified` means both raters independently give the intended verdict. No third-rater rescue is used for development difficulty calibration.

## C0-only development calibration after label PASS

Only dual-certified SKIP rows enter provider difficulty calibration. Both Strong and Weak run C0 only; C1 is forbidden on development instances.

Family viability is decided from Weak C0 family accuracy:

- viable band: 0.45 <= Weak C0 accuracy <= 0.80
- Strong C0 accuracy is diagnostic; a family with both Strong=1.00 and Weak=1.00 is rejected as opportunity-free
- malformed/OTHER counts as incorrect outcome but remains an outcome, not a retry reason
- technical retries follow the same mechanical-only exactly-once rule as v2

Viability selects **abstract families only**. Development instances themselves remain permanently non-confirmatory.

## Confirmatory boundary

After viable family selection, generate new holdout instances from those families. Do not preview C0 on holdout. Re-run provider-free label qualification and anti-leak audit, then freeze the paired C0/C1 confirmatory SPEC before any holdout provider row.
