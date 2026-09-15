# Agent Qualification Envelope Step5 — A.5 Repository Review Gate

> Status: candidate verification complete; committed-state replay is required after the local commit.
> Baseline: `98cd5cee04aaf89a79b5b0b4e92cbf510482b5a1` — clean current-main Step1–4 replay plus the independent package-shadow harness prerequisite.
> Scope: A.5 G1-G4 structured declaration manifest plus exact changed-component presence/coverage review gate.
> Runtime impact: none. No scorer/runtime/task/evidence/provider behavior is changed.

## 1. Ruling being implemented

`docs/analysis/CONVERGENCE-DISPOSITION-20260910.md:657-705` defines A.5 as a
submission/review governance gate, not a Goal-completion gate and not a runtime
semantic controller.

The required first implementation is intentionally narrow:

1. every submitted change has one explicit changed-component manifest;
2. the manifest partitions the exact Git diff path set;
3. the submitter explicitly labels each component `control_machinery=true|false`;
4. a `true` component must reference a structured G1-G4 declaration;
5. the file-level matrix fields from A.5 §7.3 must be present;
6. the checker validates only structure, references, uniqueness and exact path coverage;
7. the checker must **not** infer from source text whether something is a control machine;
8. the checker must **not** score whether G1-G4 prose is persuasive/correct.

This is the only way to make omission mechanically visible without introducing the
semantic string parser explicitly rejected by A.5 §7.2.

## 2. Why every PR carries a manifest

A gate limited to paths guessed by code such as `*guard*`, `*scheduler*`, `cache/*`
would itself become a hidden semantic classifier. New control machinery could be placed
under an unexpected filename and bypass review; unrelated files could be falsely gated.

v0.1 therefore makes no such guess. The PR manifest covers **all** changed paths and the
submitter/reviewer owns the `control_machinery` classification. The program can then prove
two mechanical facts:

- no changed path was omitted from the declared review surface;
- every path classified as control machinery has a referenced G1-G4 declaration.

It cannot prove that `control_machinery=false` is truthful. That remains architecture
review/model/human judgment by design.

## 3. Implemented contract

### 3.1 Machine schema

`docs/governance/architecture-submission-v0.1.schema.json` freezes the closed
`lfl.architecture_submission.v0.1` shape.

A submission contains:

- `submission_id`;
- `components[]`;
- `declarations[]`.

Each component carries the A.5 §7.3 file-level matrix facts:

- `paths`;
- `owning_subsystem`;
- `disposition`;
- `evidence`;
- `verification_level`;
- `model_evidence_veto_recovery_exit`;
- `rollback_route`.

It also carries the explicit submitter classification `control_machinery` and, only when
true, `declaration_id`.

Each declaration has structured blocks:

- G1 `necessity`;
- G2 `authority_owner`, mechanical relationship (`reuse|replace|new_authority`) and
  `non_duplication`;
- G3 `model_evidence` plus `recovery_or_reason`;
- G4 `rollback` plus `verification`.

These fields are presence containers. Their prose is not parsed for semantic quality.

### 3.2 Mechanical checker

`scripts/check_architecture_submission.py` is the executable review gate.

Important boundaries in the implementation:

- schema/prefix identities are fixed at `scripts/check_architecture_submission.py:20-21`;
- `validate_manifest()` begins at `:92` and performs closed-shape/presence/reference checks;
- exact changed-path set equality is enforced by `validate_coverage()` at `:251`;
- rename/copy records include both paths via `parse_name_status_z()` at `:262`;
- auto-discovery requires exactly one changed submission manifest at `:285`;
- Git facts come only from staged diff or explicit `base...head` at `:299`;
- CLI orchestration begins at `:348` and prints
  `semantic_quality=not_evaluated classification_truth=not_evaluated` on success.

No production module imports this checker.

### 3.3 PR wiring and check identity

`.github/workflows/architecture-review.yml` is a dedicated `pull_request`-only workflow.
Its `architecture-review` job checks out the exact PR head with full history and compares
the exact GitHub PR base SHA to head SHA. The general `.github/workflows/ci.yml` no
longer defines the A.5 job.

This separation is load-bearing for remote enforcement. A job guarded only by
`if: github.event_name == 'pull_request'` inside a push+PR workflow still produces a
**skipped check run with the same job context on push**. GitHub required status checks do
not distinguish workflow event types, and a skipped check can satisfy a required context.
Therefore the required A.5 context must be absent on push, not merely skipped.

The PR-only job does not install model/runtime dependencies and does not inspect
application semantics. It invokes only the stdlib checker.

`.github/PULL_REQUEST_TEMPLATE.md:12-22` makes the contract visible to submitters and
explicitly states the authority boundary: CI checks presence/coverage; humans/models judge
whether the classification and G1-G4 substance are correct.

### 3.4 Bootstrap/self-declaration

`docs/governance/submissions/20260915-step5-a5-repo-review-gate.json` is the gate's own
A.5 declaration and exact file-level matrix. Step5 is itself control machinery, so it is
not exempt from the rule it introduces.

The declaration states:

- **G1:** exact diff coverage/required-field presence is a mechanical submission fact;
- **G2:** authority is reused from A.5 + submitter manifest; the checker owns no runtime,
  scorer, completion, classification or semantic verdict;
- **G3:** refusal output is exact missing/extra paths/fields; recovery is to edit/split/
  reclassify the submission and rerun review;
- **G4:** rollback is a plain Git revert; verification is deterministic and contains an
  explicit non-semantic negative control.

## 4. Non-semantic proof

The test fixture deliberately uses G1 text `for robustness`.

A.5 prose says a vague `for robustness` is architecturally insufficient
(`CONVERGENCE:665-669`). Nevertheless the v0.1 machine checker **accepts it structurally**.
This is intentional and is regression-tested: if a future implementation starts rejecting
that phrase or evaluating prose quality, it has silently crossed from presence gate into a
semantic architecture judge and must itself undergo a new A.5 review.

## 5. Deterministic failure surface

The gate fails only on mechanically enumerable contract violations, including:

- missing/unknown closed-schema fields;
- malformed/duplicate component or declaration IDs;
- malformed or duplicate repository paths;
- `control_machinery=true` without an existing declaration reference;
- non-control components claiming a control declaration;
- missing G1/G2/G3/G4 blocks or their required structural children;
- unused declarations;
- zero or multiple changed submission manifests;
- changed paths missing from the manifest;
- manifest paths absent from the changed Git set.

It does **not** fail because:

- a declaration is weak, vague or unpersuasive;
- a path looks like a scheduler/cache/gate/controller;
- a reviewer/model would classify a component differently;
- a runtime/agent trajectory is semantically inefficient;
- a Goal/task/scorer outcome is bad.

## 6. TDD evidence

The first focused run was genuinely RED: collection failed with
`ModuleNotFoundError: No module named 'scripts.check_architecture_submission'` because the
tests existed before the checker.

After the implementation, the focused suite became GREEN. It includes positive and
negative cases for:

- G1-G4 presence;
- A.5 §7.3 file-matrix presence;
- exact missing/extra diff coverage;
- duplicate paths;
- repo-relative path normalization;
- rename/copy coverage parsing;
- exactly-one manifest discovery;
- stale/unused declaration rejection;
- non-control components needing no declaration;
- the explicit `for robustness` non-semantic control;
- published schema identity matching the checker contract.

### 6.1 Clean-worktree prerequisites are baseline-owned

The historical Step5 qualification exposed two clean-checkout assumptions, but neither
belongs to the final Step5 diff. The recovery-provider fixture debt was fixed formally by
PR #5 / current `main@ba6f3a0d`: `_base_env()` accepts an explicit `providers_path`
injection point while preserving the production default. The `tests/scripts/__init__.py`
package-shadow debt is required even before Step5: the Step2/3 Envelope test imports
`scripts.qualification`, so the clean Step1–4 integration owns that deletion as a separate
non-control harness prerequisite at baseline `98cd5cee...`.

Accordingly the final Step5 manifest contains only one component,
`a5-repo-review-gate-v0.1`, with `control_machinery=true`. Step5 has no diff in
`tests/scripts/__init__.py`, `tests/unit/test_browser_smc_exact_recovery_capability.py`,
the FC2 runner, or production `src/`.

## 7. Activation boundary

The Step5 code change does **not** by itself alter GitHub repository rulesets/branch
protection and does not merge, restart or deploy anything. Publishing the change on a
review branch/PR is a separate repository action from activating required-check policy.

Once this exact commit lineage is pushed and used by a PR, the dedicated workflow will emit
the A.5 review status. A push event must emit **no check run with that required A.5
context**; this is a remote qualification fact, not something inferred from a local pass.
Whether GitHub is configured to make that status a required merge check is an external
repository-policy fact and must be verified/changed separately rather than claimed by
this code commit.

This distinction is deliberate: "checker is wired into PR CI" and "remote main cannot be
merged while the check fails" are two different facts.

## 8. Verification record

### 8.1 Initial narrow Step5 candidate

The initial `b6ac136a` candidate established the mechanical A.5 checker and passed its
committed-state qualification: focused **21/21**, combined adjacent **40/40**, full
`ci_gate.sh`, whole-tree security, exact 7-path self-coverage, and zero production `src/`
delta. Its first real PR run also exposed an enforcement-identity defect: because the A.5
job lived in the general push+PR CI workflow behind a job-level `if`, a push produced a
**same-name skipped A.5 check run**. That is safe for advisory CI but unsafe as a future
required-check identity.

### 8.2 PR-only check-identity follow-up

The follow-up is intentionally narrower than the original gate implementation: it changes
only how the existing A.5 check identity is emitted. Before the follow-up commit, the clean
working candidate produced these results:

1. TDD regression first failed because the dedicated PR-only workflow did not exist;
2. after the workflow split, Step5 focused suite: **22/22 PASS**;
3. focused Step5 + Envelope + exact-recovery regression: **41/41 PASS**;
4. general `.github/workflows/ci.yml` contains neither the `architecture-review` job nor
   the required A.5 check name;
5. dedicated `.github/workflows/architecture-review.yml` declares only `pull_request`;
6. JSON parsing, new Python/test `py_compile`, and `git diff --check`: PASS;
7. full `bash scripts/ci_gate.sh`: PASS, including Ruff, env-pin
   (**571 test files / 0 undeclared COMPACT_RATIO dependents**), Pyright
   (**0 errors / 0 warnings / 0 informations**), tier0, and full xdist;
8. production/runtime source delta under `src/`: remains **0 Step5 files**.

The final closeout still requires checks meaningful only after the exact follow-up commit
exists: `base...head` self-gate replay, exact changed-path identity, committed
whole-tree security/full-CI replay, clean worktree, and remote proof that a push run emits
**no required A.5 check context** while the pull-request run emits exactly that context.
Those post-commit/remote facts are kept as external qualification evidence rather than
self-referentially editing the commit after it has been qualified.
