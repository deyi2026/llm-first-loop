# Optional private continuity store

LFL can use an optional **private companion Git repository** as a transport layer for cross-agent and cross-machine handoff. It is intentionally not a second runtime-memory authority.

## Authority boundary

The source repository remains the authority for code and public project documentation. Runtime Goal/checkpoint, event logs, HotCard, memory, and experiences keep their existing responsibilities. The private continuity store only carries versioned historical handoffs between environments.

A handoff is never automatically injected into a new task. It is read only when a user explicitly asks to resume prior work. After retrieval, volatile facts must be re-verified against the current source repository and runtime. Historical text such as "must", "continue", or "next step" has no current instruction authority.

## Continuity layers are separate

LFL currently has three continuity concerns with different authority and lifetimes. They must not be collapsed into one shared "continuity state":

1. **Private handoff transport** — this document's optional companion Git store. It moves historical handoffs across agents, machines, or clones. It is never runtime-memory authority and is never injected automatically.
2. **S1 fold / working-state continuity** — in-session provider projection for long active tool runs. `Session.working_state_checkpoint` can preserve model-authored opaque state plus model-selected exact raw evidence. A checkpoint is eligible only for the exact transcript/provider/model boundary on which it was built, and checkpoint selection must have completed with `finish_reason=stop`. The production runtime currently contains checkpoint storage/validation/projection consumers; the model-driven checkpoint producer is still a separately gated capability and is not default-enabled by this integration.
3. **Interruption / provider-truncation continuity** — recovery of an unfinished model output. The exact partial assistant bytes remain durable and are marked `llm_interrupted`; provider token-limit stops additionally carry `provider_truncated` and the exact provider finish reason. On the next genuine human ingress, that partial can be exposed one-shot through `RunState.interruption_resume`, with only a factual provider-view truncation marker and no program-authored continuation instruction.

The runtime ownership rule is mechanical: an S1 checkpoint cannot be created from a `length` selection; any later persisted transcript message invalidates the old S1 boundary; therefore a later provider-truncated partial and new human ingress cannot simultaneously reuse that old checkpoint as current working state. The truncation path recovers the unfinished output, while S1 remains responsible only for fold/evidence continuity at its own exact boundary.

Do not copy one layer's state into another layer merely to make recovery "more robust". If a future change needs cross-layer coordination, preserve these authority boundaries and add a mechanical regression proving that only one layer owns the same recovery state at a time.

## Public/private split

The public repository contains only this protocol, `AGENTS.md`, the generic CLI, and tests. Private configuration is stored in the source repository's local Git config (`.git/config`) and is never tracked.

Supported local keys:

- `lfl.continuity.remote` — optional private Git remote;
- `lfl.continuity.path` — external local checkout path;
- `lfl.continuity.project` — project identifier used inside the private store.

The continuity checkout must live **outside** the source worktree. No `.memory-link`, embedded private repository, token-bearing URL, or credential file is required.

## Private repository layout

The V1 store is append-oriented and deliberately small:

```text
projects/<project-id>/
  handoffs/<handoff-id>/
    manifest.json
    HANDOFF.md
  closures/<handoff-id>.json
```

There is no shared mutable index file. Candidate indexes are derived locally by scanning manifests. Closing a handoff writes a separate closure record instead of editing historical handoff content.

## Handoff contents

`manifest.json` records mechanical facts such as source commit, branch, dirty counts, a working-tree fingerprint, portability classification, workstream ID, Goal ID if supplied, and creation time. It does **not** record the source checkout's absolute path or any remote URL.

`HANDOFF.md` contains model-authored semantics under fixed sections:

- Objective
- Verified Facts
- Completed
- Decisions
- WIP State
- Open Questions
- Suggested Next Step — explicitly historical and non-authoritative

Do not store API keys, passwords, tokens, `.env` contents, private keys, raw reasoning chains, full chat transcripts, large event logs, or binary files. V1 caps an input handoff at 64 KiB and runs a conservative secret scan before commit.

## Source portability

A private handoff is not a backup of uncommitted source files. V1 classifies source portability conservatively:

- `complete`: source worktree is clean and the source HEAD is contained by at least one local remote-tracking ref. This is local tracking evidence, not a live guarantee against later remote history rewrites; resume still re-verifies current state;
- `metadata_only`: the source worktree is dirty/untracked, or no remote-tracking ref proves the source HEAD is durable.

For dirty work, the manifest records only counts and a fingerprint; it does not copy source diffs or untracked file contents. If cross-machine recovery is required, first create a durable WIP commit/branch in the appropriate source repository remote.

## Configure

Run the CLI from the source repository worktree whose state is being handed off or resumed. The CLI resolves source identity from the current working directory; invoking the script by an absolute path from another repository does not retarget it.

Use a credential-free SSH remote or a credential-helper-backed HTTPS remote. Credentialed HTTP(S) URLs are rejected.

```bash
./scripts/continuity.py configure --remote '<private-git-remote>'
```

A local-only store can be initialized without a remote:

```bash
./scripts/continuity.py configure
```

The command intentionally does not print the private remote or the absolute continuity checkout path.

## Create a handoff

Semantic handoff data is supplied through a JSON file so private text does not need to appear in shell arguments:

```json
{
  "workstream_id": "example-workstream",
  "goal_id": "optional-goal-id",
  "agent": "optional-agent-label",
  "objective": "Current objective",
  "verified_facts": ["Fact with evidence"],
  "completed": ["Verified completion"],
  "decisions": ["Decision and rationale"],
  "open_questions": ["Unknown that remains"],
  "suggested_next_step": "Historical suggestion only",
  "affected_paths": ["repo/relative/path"]
}
```

Then run:

```bash
./scripts/continuity.py handoff --input /path/to/private-handoff.json
```

Only the input file's **contents** are copied into the private store. Its absolute path is never persisted. If a private remote is configured, the CLI attempts a bounded sync; network failure leaves the local handoff committed and reports `remote_synced=false` without deleting it.

## Resume

List candidates explicitly:

```bash
./scripts/continuity.py candidates
./scripts/continuity.py candidates --workstream example-workstream
./scripts/continuity.py show <handoff-id>
```

Candidate output reports only mechanical Git relation states:

- `EXACT_HEAD`
- `CURRENT_IS_DESCENDANT`
- `HANDOFF_IS_DESCENDANT`
- `DIVERGED`
- `UNKNOWN`

The program does not decide which handoff is semantically relevant. The model/user selects from candidates, then verifies current state.

## Close and sync

Closing is append-only:

```bash
./scripts/continuity.py close <handoff-id>
./scripts/continuity.py sync
```

Git operations are serialized with a local file lock. Commits stage only the files created by that operation, never `git add .`. Push uses ordinary non-force semantics with one bounded fetch/rebase retry. A sync failure keeps local history intact.

## Relationship to `handoff_now`

V1 does not automatically export the existing local `handoff_now` output. That tool currently has a separate local archive lifecycle. After V1 is proven in real use, the model-facing handoff tool can be unified with this transport layer without granting historical content automatic prompt authority.

## Durable truncation recovery

A model/provider/tool output may be too large for the current provider view, but
representation pressure must not destroy the source that produced it.

The runtime therefore separates **capture** from **projection/replay**:

- terminal model interruptions (`cancelled`, `llm_error`, provider token-limit stops)
  promote exact received model text/reasoning to an immutable, private,
  content-addressed truncation artifact before bounded tails are projected;
- an open-stream crash checkpoint is promoted on the next genuine human ingress,
  before the overwrite-only in-flight sidecar can be replaced or cleared;
- the compact `truncated:...` episode index remains the discovery surface;
  `search_records(kind=episode, query="truncated:...")` explicitly hydrates the exact
  source when an artifact exists, while legacy rows honestly fall back to their stored
  tails;
- an explicit second read is not subjected to the ordinary compact-history display
  budget again. If the exact source fits the tool's physical recovery page it is
  returned completely; only a genuinely larger source is split into monotonic,
  non-overlapping `next_offset` pages;
- generic `llm_error` artifacts remain historical evidence only and are **not**
  automatically replayed into a later provider request. Provider-truncation/open-stream
  continuation eligibility remains owned by the existing mechanical continuity rules.

The same ordering applies to delegated/tool observations: governed CodeArts results flow
through Evidence/archive capture before Registry projection, and `dsh_task(ctx_path=...)`
passes an exact file reference plus mechanical size/hash facts instead of silently
replacing the source with an 8K prefix. These rules preserve source bytes without giving
storage or projection code semantic task authority.

## Exact source hydration for attachments and delegated parent context

The first provider view of a large source is a representation, not the source itself.
Two recovery paths keep the exact source available without granting storage code semantic
authority:

- Web uploads persist the original bytes plus a verified model-readable extraction when
  one is available. The initial user-message projection keeps only bounded attachment
  facts/excerpts and exposes the opaque `attachment://...` ref and `read_attachment`
  capability.
- `read_attachment(ref, offset=...)` is an explicit source-recovery operation. It does
  not reuse the initial excerpt budget. Up to 100,000 exact characters are returned in
  one read; only a genuinely larger readable representation is split into monotonic,
  non-overlapping character pages using `next_offset`.
- `source_complete` and `page_complete` are separate facts. A page can be fully read
  while the available representation is still incomplete (for example, a multi-page
  scanned PDF when the current local vision fallback covers only part of the source).
  The runtime never converts that condition into a claim of full-document coverage.
- Older attachment records remain readable: an explicit hydration may derive a complete
  text representation from the already-durable original bytes and then persist its
  length/hash/coverage facts. This is lazy source recovery, not automatic summarization.
- `read_attachment` is a recovery control-plane tool. In Evidence-enforced execution its
  output is not recursively captured or re-projected through the ordinary Evidence
  display budget.

For `spawn_subagent(inherit=true)`, the existing small recent-parent slice remains a fast
working view. In addition, when the shared immutable artifact store is available, the
runtime records a complete chunked parent storage transcript and exposes an
`artifact://...` reference to the child. The child can explicitly page that artifact with
`read_file` if its task requires older or longer parent context. This artifact contains
conversation/tool storage facts but deliberately excludes private assistant
`reasoning_content` and provider replay state; parent-context recovery is not a channel
for cross-agent reasoning replay.

Neither path creates a program-authored task summary. Model-authored long-source synopsis
remains a separate derived-view capability and must stay bound to an exact source ref/hash.

## Model-authored Source Synopsis

Long source/reasoning synopsis is a **derived navigation view**, not a replacement for
source truth and not a WorkingState authority.

- `snapshot_complete=true` means the exact model-readable bytes bound by the synopsis were
  fully persisted; `source_complete` separately reports whether that representation covers the
  underlying source completely. Interrupted reasoning can therefore be snapshot-complete while
  still source-incomplete.
- Exact source first: `attachment://`, `artifact://v1/`, `evidence://v1/`, and exact
  `truncated:` recovery refs are mechanically resolved before a synopsis can be saved.
- The model authors `summary`; the program does not generate, score, select, rewrite, or
  decide semantic importance/task applicability.
- `source_synopsis(action=save)` binds the model text to the resolved source SHA and an
  explicit `[source_start, source_end)` range. `expected_source_sha256` is an optional
  mechanical version precondition.
- Before the derived record is committed, the exact model-readable source representation
  is copied into a content-addressed immutable synopsis source blob. A later change in the
  live source representation therefore cannot rewrite what an older synopsis referred to.
- `source_synopsis(action=read_source)` reads that immutable source snapshot. A source that
  fits the physical page budget is returned in one read; larger sources use absolute,
  monotonic `next_offset` pages and never repeat the first page as a recovery substitute.
- `search_records(kind=synopsis)` is index-only and returns compact cards/stable refs.
  `source_synopsis(action=read_summary)` is the exact summary hydration path;
  `source_synopsis(action=read_source)` is the exact source-snapshot hydration path. This
  keeps explicit rereads out of ordinary Evidence/result projection so they are not
  immediately shortened again. Explicit synopsis reads may mechanically report whether
  the original source ref still resolves to the same snapshot SHA.
- `source_ref_state` is only a ref/snapshot identity fact (`same_snapshot`,
  `changed_representation`, `unavailable`, `not_checked`). It is **not** external-source
  freshness and is never converted into task applicability.
- A synopsis record is always session-scoped, even when its cited source is a workspace-scoped
  attachment/artifact. This prevents model-authored derived text from silently widening current
  session context into another session. The source access scope is retained only as a factual
  provenance field; cross-session reuse requires a separate explicit promotion mechanism.
- Session deletion removes its synopsis records and only garbage-collects exact source snapshot
  blobs proven unreferenced by all remaining records. Corrupt remaining records fail closed for GC.
- Private provider replay state is never promoted by synopsis persistence.
- Saving/reading a synopsis is a derived-view/recovery control-plane operation and does not
  recursively create Evidence records.
- No core-loop automatic synopsis producer is installed. The model decides whether/when a
  long source it has read merits a synopsis. This also prevents a hidden background summary
  request from competing with a single-slot local model.
- `WorkingStateCheckpoint` production remains HOLD. Synopsis persistence does not authorize
  automatic prompt injection, evidence selection, completion judgment, or recovery replay.

Legacy `search_archive(with_summary=true)` remains accepted for compatibility but no longer
runs an LLM over the archive's short `content_preview`. It returns a truthful preview/index
view with `projection_complete=false`; full-source summarization must start from an exact
recoverable source instead of a preview that silently omits middle content.
