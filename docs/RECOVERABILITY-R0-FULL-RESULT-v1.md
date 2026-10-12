# Evidence Recoverability Contract — Full R0 Result v1

Date: 2026-08-26
Contract: `R0-v1.1`
Overall status: **FULL R0 DETERMINISTIC PASS**
Scope: offline correctness only; no real provider confirmation

## Executive result

The original root-cause requirement is now mechanically satisfied offline:

> Context may be projected/compressed/provider-folded, but a previously acquired observation keeps a
> stable owner-scoped Evidence identity, a bounded queryless discovery path, and exact hydration
> without forcing the source action to run again.

The canonical regression reads a large source exactly once, removes the original tool observation
from HOT raw context, performs unrelated tool work, rebuilds context ten times across
DeepSeek -> MiniMax -> DeepSeek projection changes, then recovers the hidden middle through the
original EvidenceRef. Source read count remains one.

## What changed structurally

1. **BlobRef != EvidenceRef** — physical content dedupe is separated from logical owner/provenance.
2. **Capture before projection** — tool observation is durable before any model-visible reduction.
3. **Bounded hydration/discovery** — `read_evidence`, `search_evidence`, `list_evidence` form the
   recovery control plane; recovery calls do not recursively create Evidence.
4. **Provider-neutral Recovery Manifest** — regenerated from durable Ledger on every build and kept
   in the dynamic tail rather than the stable system/tools prefix.
5. **Compression preserves Evidence identity** — hidden history is captured before shrink; capture
   failure prevents shrink in enforce mode.
6. **Legacy ownership is proved, not guessed** — sidecars require session/tool-marker/hash proof;
   orphans remain quarantine-only and model-invisible.
7. **Lifecycle is reference safe** — session deletion retires logical owner state even when the
   current rollout mode is off; shared blobs delete only at global refcount zero; capture and GC share
   a durable race lock.
8. **No P2 Action Guard shortcut** — R0 did not solve amnesia by suppressing repeat actions.

## Phase status

| Phase | Result |
|---|---|
| 0 — Contract / frozen deterministic oracle | PASS |
| 1 — BlobStore + owner-scoped Ledger | PASS |
| 2 — Shadow capture | PASS |
| 3 — Capture-before-projection enforce | PASS |
| 4 — read/search/list Evidence | PASS |
| 5 — Compression/provider-neutral manifest | PASS |
| 6 — Legacy ownership/quarantine/GC | PASS |
| 7 — Full R0 aggregate gate | **PASS 12/12** |

## Full R0 evidence

- Frozen oracle SHA-256: `ee8927e80386af7e241aa1f83b21d6c37cf637d3b19779bbf8abe6fff59f47c9`
- Gate map and case outputs: `data/audit/evidence_r0_phase7_gate_v1.json`
- All 12 blocking cases: PASS.
- All 89 Evidence tests under a no-network pytest plugin: PASS.
- Full repository non-real-LLM regression: exit 0.
- Frozen prompt/A3/spec/design guardrail paths: no diff.

## Activation eligibility is a separate decision

**Full R0 PASS does not mean the current production configuration can immediately switch to
`EVIDENCE_MODE=enforce`.** Current `.env` is still:

```text
EVIDENCE_MODE: unset -> off
TOOL_PIPELINE_ENABLED=1
```

The code deliberately rejects enforce while the post-processing ToolExecutionPipeline is enabled,
because that pipeline can mutate `result.content` after Registry projection and could erase the
Evidence capsule. That combination is fail-closed by test.

Therefore the current decision is:

- **R1 historical trace replay: ELIGIBLE** — this is the next frozen-design phase.
- **Controlled shadow rollout: architecturally eligible** (`off -> shadow` changes no model-visible
  prompt/tool result), but it is not activated by this work.
- **Current production enforce: NOT ELIGIBLE** until pipeline ordering is integrated, or a controlled
  enforce environment explicitly disables the pipeline and then passes its rollout gates.
- **Provider effectiveness/generalization claim: NOT MADE**; fresh MiniMax/DeepSeek confirmation is
  R2 after R1, per frozen design.

No `.env` mutation was made.

## Next phase

Per `design.md` Phase 7 exit:

```text
R1 historical trace replay
-> R2 fresh MiniMax + DeepSeek provider confirmation
```

R1 should replay historical problematic traces against the new Evidence contract without contacting
providers, measuring recoverable projection, lost refs, repeat-without-freshness, manifest survival,
and provider-switch Evidence-set delta.
