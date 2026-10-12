# Evidence Recoverability R0 Phase 5 Result v1

Date: 2026-08-26
Status: **DETERMINISTIC PASS — NOT FULL R0**
Provider API calls: **0**
Production activation: **NO** (`EVIDENCE_MODE` remains unset -> `off`)

## Objective

Phase 5 closes the root-cause gap that motivated ERC: a recoverable Evidence identity must
survive history compression, unrelated tool activity, repeated context rebuilds and provider
projection changes.

Invariant:

> Context bytes may differ by provider/compression state; the current owner-authorized Evidence
> identity/recovery path must remain available and deterministic.

## Implemented

### Durable compression bridge

When enforce-mode history removes a message from the provider-visible projection:

```text
session message
  -> owner-scoped Evidence capture/reuse
  -> only after canonical capture succeeds may history shrink
  -> legacy ArchiveStore remains a compatibility copy
  -> context.compressed event records evidence_ref
```

If canonical Evidence capture fails, enforce compression fails closed before writing provider
`cache_compacted_for` markers. Bytes are not silently hidden merely because a legacy archive copy
might exist.

Tool messages that already carry a valid enforce EvidenceRef reuse that record instead of creating
a second `history-msg:*` record.

### History identity

- resolvable `msg_seq` -> `history-msg:<seq>`;
- legacy archive id when available -> `history-archive:<id>`;
- fallback -> persistent `Message.ts + role + content digest`.

Thus two identical messages at different times remain distinct observations, while provider
replay of the same message reuses the same logical capture.

EvidenceCapture itself now has idempotent replay semantics: same owner + stable capture id + blob
reuses the first committed acquired_at/state if the other immutable metadata agrees. This fixes a
real provider-switch deterministic collision found by the Phase 5 tests.

### Recovery Manifest

Every enforce `_build_llm_messages()` rebuild regenerates a bounded Recovery Manifest from the
durable Evidence Ledger. It is appended as a dynamic user-tail frame, never inserted into the
stable system/tools prefix.

Default bound: `EVIDENCE_MANIFEST_LIMIT=8` (runtime clamp 1..20).

Non-conversation/tool Evidence is prioritized before compressed conversation records so repeated
history folding cannot immediately evict the most useful source/tool refs from the small manifest.
Older records remain discoverable through `list_evidence/search_evidence`.

Manifest content includes stable EvidenceRef, safe source label, coverage and freshness plus an
explicit recovery route (`list/search/read_evidence`) instead of encouraging a repeated source
action.

Manifest fingerprint is part of the projection version. A legitimate Ledger/Manifest change
therefore produces a normal projection `miss`, not a false nondeterminism `mismatch`; a subsequent
unchanged build returns `ok`.

### search_archive compatibility

Enforce exposes exactly one `search_archive`, implemented as `SearchArchiveCompatTool` over the new
owner-scoped EvidenceSearch. It supports new AND/OR/phrase semantics and returns stable refs; it is
not the old ArchiveStore whole-string substring implementation. Existing compression/system
instructions that still name `search_archive` therefore remain functional without routing the
model back to the historical ~90.5% MISS path.

Off mode retains the existing legacy `search_archive`; shadow keeps its zero-schema-change promise.

## Canonical root-cause proof

A deterministic test now executes the exact failure chain that started this investigation:

```text
large target file
-> read_file executes exactly once
-> immediate model view is bounded; deep middle marker is hidden
-> real assistant/tool round persisted
-> unrelated tool round
-> enough long history to compress old raw observations
-> exactly 10 context rebuilds
-> DeepSeek -> MiniMax -> DeepSeek projection switch
-> original tool projection no longer exists in raw context
-> original EvidenceRef remains in Recovery Manifest every build
-> read_evidence hydrates the hidden middle marker
-> target read_file execution count is still exactly 1
```

This proves the program can preserve evidence continuity without requiring repeated source-tool
execution after truncation/compression.

## Additional deterministic gates

- Manifest bytes are identical across DeepSeek -> MiniMax -> DeepSeek when the Ledger state is
  unchanged even if raw provider history visibility differs.
- Progressive fold creates records monotonically then converges; repeated rebuilds do not archive
  the same message forever.
- Provider replay does not create a new record merely because compression is evaluated again.
- Two identical message texts with distinct persistent timestamps produce distinct logical
  Evidence records.
- Tool Evidence remains prioritized in a bounded Manifest despite many newer compressed
  conversation records.
- Manifest survives `tool_round_zero` projection.
- Early compressed conversation text is discoverable with `search_evidence` and the enforce
  `search_archive` compatibility alias.
- `context.compressed` events carry `evidence_ref`.
- Manifest render failure does not remove `read/search/list` recovery tools.
- Empty Ledger injects no empty Manifest noise.
- Enforce capture failure prevents compression/provider marker mutation.

## Verification

- Phase 5 focused suite: **15/15 PASS**.
- Phase 0-5 Evidence suite: PASS.
- Targeted Ruff: PASS.
- Targeted Pyright: **0 errors, 0 warnings**.
- Broad history/compression/archive/event/cache/factory/session regression: PASS.
- Full repository non-real-LLM suite:
  `pytest -q --ignore=tests/unit/test_action_guard_a3.py` -> **exit 0**.
  The ignored A3 file is the already-stopped development artifact with its unrelated broken import.

## Runtime boundary

Current `.env` remains:

```text
EVIDENCE_MODE: unset -> off
TOOL_PIPELINE_ENABLED=1
```

No production Evidence behavior is enabled. Enforce + the currently enabled ToolExecutionPipeline
still fails closed until post-hook/capsule ordering is explicitly integrated.

## Remaining R0 work

Phase 6:
- legacy `data/audit/tool_outputs` / `cmd_outputs` ownership-proof migration;
- unowned sidecar quarantine (never model-visible);
- shared Blob reference lifecycle / GC integration;
- Session delete behavior.

Phase 7:
- aggregate R0-1..R0-12 full deterministic gate;
- post-run integrity/status audit;
- only then decide whether local controlled shadow/enforce rollout is eligible.

No provider-effectiveness conclusion is made by Phase 5.
