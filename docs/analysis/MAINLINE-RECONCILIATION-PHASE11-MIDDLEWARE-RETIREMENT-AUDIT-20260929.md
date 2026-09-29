# Mainline Reconciliation Phase 11 — Active Middleware Retirement Audit

- Date: 2026-09-29
- Canonical main: `aeca3aa4805e99285e9b3ba210793f6f44fe7a47`
- Middleware branch: `fix/middleware-m1-currentness-gen120-20260926@101beba03604479b80585caad6707fe65935f541`
- Result: **AUDIT COMPLETE — worktree retirement blocked on production browser decoupling**

## Findings

### 1. The branch is not disposable

The middleware branch is clean, but it is not contained by canonical main. It has **34 true unique commits** while main is **52 commits ahead**. The unique history contains the complete `src/envelope_mw/` subsystem, `scripts/mw/`, middleware tests, specifications, qualification evidence, and LFL integration changes.

**Disposition:** retain the branch as an archive/experimental line. Worktree retirement and branch deletion are separate decisions; branch deletion is not currently safe.

### 2. The adapter is currently idle at a safe durable boundary

The live supervisor/runner stack is not launchd-managed. The latest durable state is **turn-10 / `armed`**, with no captured ingress, no engine result, no final, and no `recovery-blocked.json`. That is a safe stop boundary, but it is edge-sensitive: a human message can arrive asynchronously, so the state must be rechecked immediately before any stop.

Supervisor shutdown is graceful by design: SIGTERM sets `stop_requested`, terminates the child runner, waits for exit, and writes `supervisor.json` with status `stopped`.

### 3. Worktree-local runtime state is not ordinary disposable cache

- Middleware runtime artifacts: about **10.5 MiB**. Two logs account for most bytes; 50 structured JSON files hold durable turn/recovery evidence. The runner schema includes human text and final answers, so this is private runtime evidence and must not be committed to Git.
- Dedicated Chrome profile: about **429.2 MiB** and includes Cookies/Login Data/Web Data/Local Storage/Sessions. This is authenticated browser state, not a source artifact.

Both roots are ignored by Git, explaining why the tracked worktree is clean despite hundreds of MiB of runtime state.

### 4. Production currently depends on the Chrome runtime inside this worktree

Production is configured with `CHATGPT_WEB_ENABLED=1` and `CHATGPT_WEB_CDP_ENDPOINT=http://127.0.0.1:9229`, using the same ChatGPT Project as the middleware lab. The only 9229 Chrome instance uses the profile physically located under this middleware worktree.

CDP inspection shows both the middleware surface lease and the production `data/chatgpt-web-provider/surface-lease.json` target are live pages in that same browser instance. The default production model remains `glm/glm-5.3`, so idle services do not need to hold a socket to 9229; however any configured `chatgpt-web/web-gpt` route needs that browser.

Canonical main's `ChatGPTSurface` **connects** to an existing CDP endpoint and can recreate a missing owned tab from its durable lease, but canonical main contains no Chrome/browser lifecycle launcher. Therefore the Chrome/profile is an external production dependency even though the middleware Python adapter itself is experimental.

### 5. Main only partially supersedes the branch

Canonical main contains the newer ChatGPT Web model provider, surface lease, session binding, queue identity, and transport logic. It does **not** contain `src/envelope_mw/` or the direct-human ingress/supervisor stack from this branch. The correct classification is **partial supersession**, not “branch merged”.

## Retirement gates

1. **R1 — Freeze/revalidate ingress.** Immediately before stop: latest durable turn must still be `armed`, with no ingress/engine/final/recovery block, and no intended pending lab task.
2. **R2 — Stop adapter only.** SIGTERM the supervisor and verify supervisor+runner are gone and `supervisor.json` says `stopped`. Keep Chrome 9229 alive at this step so production web-gpt is unaffected.
3. **R3 — Resolve private evidence retention.** Prefer moving the ~11 MiB runtime artifacts to a private non-Git archive with a manifest/hash; alternatively require explicit authorization to discard them.
4. **R4 — Extract the production Chrome runtime.** In a controlled maintenance window, stop Chrome, migrate the authenticated profile to a production-owned ignored path outside `.worktrees`, and establish an independent reproducible lifecycle owner. Do not delete the old profile until validation succeeds.
5. **R5 — Re-establish 9229.** Relaunch Chrome on the same endpoint from the new profile. Login/Project must remain usable. Stale target IDs are acceptable because canonical `ChatGPTSurface` can recreate/rebind its owned target from the durable conversation URL.
6. **R6 — Production web-gpt acceptance.** Run a controlled `chatgpt-web/web-gpt` smoke on canonical main, verify lease/session binding, then re-run production `service_control verify` and default-service health.
7. **R7 — Remove worktree.** Only after no process/open handle references the worktree and all state has been migrated/resolved, remove it without force.
8. **R8 — Retain branch.** Keep `fix/middleware-m1-currentness-gen120-20260926` at `101beba03604479b80585caad6707fe65935f541`; its 34 unique commits require a separate archival/merge review before any future deletion.

## Readiness

- Adapter stop: **READY subject to immediate edge recheck**.
- Physical worktree removal: **NOT READY**.
- Branch deletion: **NOT READY**.
- Blocking dependency: production web-gpt's only Chrome/profile runtime is physically rooted inside the middleware worktree.

No process was stopped, no profile/artifact was moved or deleted, no production service was changed, and no branch/worktree was removed during Phase 11.
