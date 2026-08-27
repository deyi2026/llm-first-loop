# Evidence Recoverability R0 Phase 4 Result v1

Date: 2026-08-26
Status: **DETERMINISTIC PASS — NOT FULL R0**
Provider calls: **0**
Production activation: **NO** (`.env` has no `EVIDENCE_MODE`; effective mode remains `off`)

## Phase 4 objective

Turn the Phase 3 recovery capsule from a promise into an actual owner-scoped recovery control
plane:

```text
EvidenceRef
  -> queryless discovery (`list_evidence`)
  -> lexical discovery (`search_evidence`)
  -> exact bounded hydration (`read_evidence`)
```

No recovery tool is allowed to re-execute the original source action or recursively create new
Evidence records.

## Implemented

### read_evidence
- model receives only `EvidenceRef`; BlobRef/hash is not an authorization capability;
- owner is injected from current run context and is absent from tool schema;
- cross-owner ref returns a generic unavailable response without owner/existence/content leak;
- `text_char` and `line` pagination are explicit and server-bounded (default hard max 4000);
- exact hydration returns current Evidence freshness without re-running the source action.

### list_evidence
- queryless bounded recent recovery list solves the "model forgot the old path/name" case;
- safe source labels hash command locators and remove URL query strings;
- output is owner-scoped and bounded (1..20).

### search_evidence
Frozen grammar:
- whitespace tokens: AND;
- explicit `OR`: alternative AND groups;
- quoted text: phrase token.

Search reads exact owner-authorized Evidence blobs. Positive snippets are centered on real match
positions. If required AND terms are too far apart for one window, deterministic per-match
fragments are joined so the visible result still contains the matched terms. This fixes the old
`search_archive` failure mode where a result could HIT but the returned head preview did not show
the match.

A machine-readable gold oracle is frozen at:
`tests/fixtures/evidence_search_r0_gold.json`.

### Freshness
- `read_file` and successful/dry-run `edit_file` capture a stable file stat token when the source
  version is observable;
- FILE evidence can be re-probed without re-reading/re-executing the source: unchanged ->
  `verified_current`, changed/missing -> `stale`;
- COMMAND (`snapshot_only`), WEB (`volatile`) and unversioned RUNTIME evidence remain `unknown`;
  ERC does not invent currentness;
- recovery reads do not rewrite `updated_at` when state is unchanged, so `ledger_version` remains
  stable under pure read/search/list operations.

## Registry/factory behavior

- `read_evidence`, `search_evidence`, `list_evidence` are registered only in `EVIDENCE_MODE=enforce`.
- They are not registered in `off` or `shadow`; the Phase 2 shadow promise of zero model-visible
  schema/prompt change is preserved.
- Registry classifies them as recovery control-plane tools and bypasses recursive Evidence capture.
- Legacy `search_archive` is hidden from the enforce tool directory so it cannot compete with the
  canonical recovery path. Off/shadow retain legacy behavior.
- Owner/session/workspace are never model parameters.

## Frozen search oracle

Gold cases cover:
- default AND precision/recall;
- explicit OR precision/recall;
- quoted phrase;
- no hit;
- owner isolation;
- match-centered visible snippets;
- far-apart AND terms with all required terms visible.

## Verification

- Phase 4 focused suite: 13/13 PASS.
- Combined R0 Phase 0-4 Evidence suite: 60/60 PASS.
- Broad affected regression suite: PASS (factory, Registry/pipeline, read/edit/command/web/DSH,
  Archive/history/session/introspection, legacy search_archive and quality gates).
- Ruff on ERC/touched files: PASS.
- Pyright on ERC/touched files: 0 errors, 0 warnings.
- Full repository non-real-LLM suite:
  `pytest -q --ignore=tests/unit/test_action_guard_a3.py` -> **exit 0**.
  The ignored A3 file is the already-stopped development artifact with its independent broken
  import and remains untouched.

A one-off repository-wide Ruff command surfaced 13 pre-existing unrelated lint findings in
`cache_guard`, `task_quality`, `job_registry`, etc.; they are outside ERC scope and were not
silently modified.

## Runtime boundary

Current `.env` remains:

```text
EVIDENCE_MODE: unset -> off
TOOL_PIPELINE_ENABLED=1
```

Therefore production behavior is still unchanged. Enforce + the currently enabled post-pipeline
continues to fail closed until their ordering is explicitly integrated.

## Remaining Full-R0 gap

Phase 4 proves exact recovery is possible once the model knows/gets the Evidence inventory. It
does **not** yet prove that the inventory itself survives:

- history compression;
- an unrelated tool round;
- repeated context rebuilds;
- DeepSeek -> MiniMax -> DeepSeek provider projection changes.

That is Phase 5. The required invariant is:

> Context bytes may differ by provider and compression state; the authorized Evidence identity
> set and bounded Recovery Manifest must not drift.

No provider API is required for the deterministic Phase 5 gate.
