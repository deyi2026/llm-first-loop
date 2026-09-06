# Optional private continuity store

LFL can use an optional **private companion Git repository** as a transport layer for cross-agent and cross-machine handoff. It is intentionally not a second runtime-memory authority.

## Authority boundary

The source repository remains the authority for code and public project documentation. Runtime Goal/checkpoint, event logs, HotCard, memory, and experiences keep their existing responsibilities. The private continuity store only carries versioned historical handoffs between environments.

A handoff is never automatically injected into a new task. It is read only when a user explicitly asks to resume prior work. After retrieval, volatile facts must be re-verified against the current source repository and runtime. Historical text such as "must", "continue", or "next step" has no current instruction authority.

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
