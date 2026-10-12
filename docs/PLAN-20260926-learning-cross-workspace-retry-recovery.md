# Learning cross-workspace retry recovery

Date: 2026-09-26

## Status

**Isolated qualification: PASS. Production deployment/retry recovery: NOT YET AUTHORIZED.**

Base production generation: 116
Base head: `bfd82cba7944de436a2a2d52e95131e7f8a60d7c`

This phase addresses two durable Learning jobs without deleting or hand-editing the
append-only journal:

- `learn:234dda64a513`, `memory_extract`, source session
  `852f577d-611a-4433-bd5a-e818387f9e1a`;
- `learn:e5f25020b688`, `reflection`.

No Web/Feishu version convergence and no semantic-scope expansion are part of this
change.

## Production facts that motivated the fix

The source session is durably owned by workspace partition
`--Users-yyj-Project-sy--`. Its whole-run lease is a real live lock held by the
production Web process, so it must never be removed as a stale-lock workaround.

Generation-116 Learning naturally retried the memory job from attempt 2 to attempt 3
and failed again with:

`SessionIdConflictError: session_id ... 已被其他工作区占用`.

This proved that the failure was persistent rather than historical.

The root cause is a gap in the earlier Learning workspace-isolation repair:

1. the dedicated Learning runtime correctly activates one workspace partition;
2. the global LearningJournal legitimately receives durable jobs produced by any Web
   workspace;
3. interval Memory extraction nevertheless used the Learning runtime's current
   `SessionStore.load(session_id)`;
4. ordinary SessionStore isolation correctly rejected a session owned by another
   workspace.

The ownership guard itself is therefore correct. The missing capability is a narrow,
background-only read path that follows an already-established durable session owner.

The Reflection retry is separate. Its historical `candidate_save_failed` came from an
older quarantined MethodStore. Generation 116 now has healthy Knowledge binding and writes
enabled, but the live source session's foreground run currently keeps P3 Learning
deferred. It should be allowed to retry naturally after foreground clears before any new
Reflection-specific fix is considered.

## Qualified design

### SessionStore owner-directed background read

`SessionStore.load_from_identity_owner(session_id)` is added as a deliberately
privileged read-only entrypoint for the global background Learning consumer.

It:

- resolves the durable owner from the existing global identity tombstone;
- for legacy sessions, accepts only one mechanically unambiguous historical owner;
- maps the owner only to a partition contained under the global `identity_root`;
- rejects absolute/path-escape owner values;
- rejects deleted, ambiguous, history-only-without-owner, missing-partition, or
  unreadable-owner states;
- uses a short-lived owner-bound SessionStore to preserve the configured JSON/event-log
  read semantics and message-retraction projection;
- never switches the caller's current SessionStore root;
- never rewrites an already-valid owner tombstone;
- does not change ordinary `SessionStore.load()`, which remains fail-closed across
  workspaces.

### MemoryExtractor scope

Only `trigger="interval"` may use the owner-directed reader. This is the durable
LearningJournal background path that can legally outlive workspace switching.

`manual` and `session_end` extraction retain the current-workspace `load()` behavior.
The change therefore does not turn SessionStore into a general cross-workspace reader.

## Tests and isolated qualification

Permanent regression coverage proves:

- ordinary cross-workspace `load()` still raises `SessionIdConflictError`;
- owner-directed background read retrieves the true owner session without changing the
  caller root or creating a copy in the caller workspace;
- an existing identity tombstone is byte-identical before/after the read;
- durable deletion remains authoritative;
- event-log read-path semantics are preserved;
- corrupted/path-escaping owner values fail closed;
- interval extraction uses owner-directed read while manual extraction uses current-root
  read;
- a max-attempt failed Learning job is not automatically runnable;
- an explicit append-only `mark_requeued` can grant one repair attempt;
- if that repair attempt fails, the job returns to non-runnable failed state instead of
  entering a toxic loop.

Verification results:

- Session/Extractor focused suite: 29/29 PASS;
- first Session/Workspace/Learning/provider adjacency: 98/98 PASS;
- second Workspace/Learning/foreground/provider/factory adjacency: 95/95 PASS;
- LearningJournal suite after repair-attempt contract: 23/23 PASS;
- Ruff PASS;
- modified-source compileall PASS;
- Pyright: 0 errors / 0 warnings / 0 information, matching the generation-116 base;
- `git diff --check` PASS;
- full tracked-tree security scan: 3,261 files PASS.

## Production-shaped real-session probe

Raw artifact:
`evals/retrieval_ab/learning-cross-workspace-extract-probe-20260926.json`.

Using the exact production source session and current provider/model
`glm/glm-5.3`:

- ordinary current-workspace `load()` still produced the expected ownership conflict;
- the new owner-directed read succeeded;
- the full interval MemoryExtractor provider path completed;
- 11 extracted entries were written only to a temporary MemoryStore;
- extraction recorded zero failures;
- production Memory index SHA remained unchanged;
- global identity tombstone SHA remained unchanged.

The source session JSON changed during the roughly 81-second probe because the live Web
process continued to hold and write the real foreground session. The probe itself is
read-only. This is positive evidence that the recovery must respect, rather than delete or
steal, the live whole-run lock.

Aggregate isolated evidence:
`evals/retrieval_ab/learning-cross-workspace-retry-qualification-20260926.json`.

## Production recovery boundary

The fix is not yet deployed. Production remains generation 116.

If deployment is authorized, the safe sequence is:

1. freeze a clean candidate commit from this qualified worktree;
2. satisfy the existing dual-root deployment invariants for the new worktree
   (canonical ignored `.env` Experience/Method bindings, and qualified WebUI artifact
   reuse only if tracked WebUI bytes are unchanged);
3. run Knowledge binding/preflight and managed service-control verify;
4. publish the exact candidate as the next desired generation;
5. restart **Learning only**; do not restart Web or Feishu and do not change semantic
   scopes;
6. verify Learning keeps Memory=1 / Method=1 / Archive=Docs=Experience=0 and Knowledge
   remains healthy/writable;
7. after the new Learning worker is healthy, append exactly one
   `LearningJournal.mark_requeued("learn:234dda64a513", "operator_repair_verified:cross_workspace_owner_read")`
   event. This is the established journal API, not JSONL editing;
8. leave the Reflection job untouched and allow its queued attempt to retry naturally
   when the foreground source run releases;
9. finish the current turn so P3 Learning actually receives a foreground-free window;
10. on the next observation, require the memory job and Reflection job to have reached
    justified terminal/retry states with no repeated loop, provider/resource settlement
    healthy, 8765 errors unchanged, and Web/Feishu unaffected.

Any new current-code failure is evidence for a new minimal diagnosis; do not suppress
ownership checks, remove a live run lock, or mass-reset journal state.
