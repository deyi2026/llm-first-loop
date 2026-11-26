# Ordinary development Lane: one bounded Host authorization

Status: **isolated candidate, not installed or enabled on a production Host**. The Mac issuer already exists; this change adds an operator entry to that same issuer. No new signing key, Web signing API, sudo delegation, or authority database. The existing `issue` and `revoke` modes remain available. Deepin installation and physical acceptance remain separate.

## Workflow

1. Open the development session in its exact independent linked worktree under `<repo>/.worktrees/`. Use the existing Goal, in-progress Task and active Lane with the same owner session. Do not create a second task or change the shared main workspace merely to obtain authority. An ordinary root-workspace session cannot be bound to a different worktree by this command.
2. As the ordinary repository owner, generate an **unapproved** request using the reviewed repository code. Replace the placeholders with the existing identifiers; use canonical absolute paths. The command only reads existing ledgers and Git identity; it does not create approvals or sign anything.

   ```sh
   python3 scripts/host_task_lease_issuer.py --mode lane-request \
     --repo "$REPO" --workspace "$WORKTREE" \
     --lane-id "$LANE" --task-id "$TASK" --session-id "$SESSION" \
     --ttl-seconds 14400 > "$REQUEST_FILE"
   shasum -a 256 "$REQUEST_FILE"
   ```

   Review the request's exact session, Goal, Task, Lane, branch, HEAD, Lane version, declared paths, workspace and verbs. A `HOLD` result is not a request. The request is fresh for 30 minutes; generate a new one if the scope changes or it expires. Default lease duration is four hours, maximum eight hours. These are entry defaults, not a change to the existing general Task Lease maximum.
3. **Only after** independent review, full R9, protected merge/CI and separate administrator installation of the exact reviewed issuer SHA, the Owner runs the installed issuer in a local terminal using the already approved isolated Python interpreter and existing administrator-to-UID462 authorization. Do not execute mutable worktree code as UID462 or configure NOPASSWD access. The request is passed on stdin, not a privileged file path. Supply the exact SHA256 printed above. Example (substitute the installed, verified interpreter path):

   ```sh
   sudo -u _lfl_dual_witness /path/to/verified/python3.13 -I -S \
     /Library/LFL-TaskHostIssuer/bin/task_lease_issuer.py \
     --mode issue-lane --request-sha256 "$REQUEST_SHA256" < "$REQUEST_FILE"
   ```

   The installed issuer independently checks the live Goal/Task/Lane and physical linked worktree, shows the exact request, and requires `APPROVE <first 12 SHA256 characters>` from its controlling terminal. It rechecks the snapshot after confirmation and under the per-session publication lock. Only then does it create the existing UID462-private 0600 approval and use the existing one-shot consumption, Ed25519 Lease/State, session binding and durable audit publication. No `--yes`, model confirmation, Web route, or signing from a normal UID. If the terminal is unavailable, the request is rejected; do not bypass it. Existing active bindings are rejected before another Owner confirmation; use the current lease instead. On an unknown or partial publication, inspect existing receipts; never automatically replay.
4. Start the next Web or CLI Run in the same owner session and exact worktree. Existing `resolve_task_execution_for_run` discovers the signed binding. Use `task_git_commit` for explicit Lane-owned files. A single lease can be reused by successive Runs until expiry/revocation while the Goal/Task/Lane remain eligible. PR135's trusted same-Run CAS continuation must also be present for multiple commits within one Run. The current Run is not retroactively granted authority; end it normally before starting the next. No extra Host approval for each permitted commit. A shared main session, wrong workspace, stale CAS, external branch drift, missing index, expired/revoked lease, or out-of-scope path remains denied.

## Boundaries and rollback

- The signed resource is **one isolated worktree** with fixed `read/write/create/rename/build/git_commit` verbs. No app/service, push, merge, release, arbitrary system privilege, or explicit delete grant. Existing runtime parent-scope and protected-root checks remain. Git commits still require current Lane-declared paths and exact branch/HEAD/CAS. The preview's HEAD and paths are not immutable signed claims: the lease intentionally covers the bounded task across its own legitimate commits, and the live Lane remains authoritative. A changed task/worktree/owner requires new authorization; do not silently rebind a session.
- The request reads only the canonical repository's existing bounded ledgers and uses fixed read-only Git queries. The privileged issuer imports no mutable repository code. Ledger or Git access denied to UID462 is HOLD, not a reason to chmod the user's home or audit directories.
- The original `revoke` mode is unchanged. Revoke the exact lease via the installed independent issuer; subsequent effects recheck signed state. Task/Goal/Lane lifecycle checks continue to deny ineligible work. Already-running subprocess cancellation is not claimed by this change.
- Rollback: stop issuing new Lane leases, revoke existing affected leases using the trusted issuer, restore the previously verified root-owned issuer via administrator-approved procedure, and revert the code through protected main. Preserve all receipts and keys. Do not disable the sandbox.

## Acceptance

Offline tests use real isolated linked worktrees, real Goal/Task/Lane records, and test Ed25519 keys/authority fixtures. They verify one approval and two separate Run activations/commits, revocation, wrong owner/root, branch/HEAD/Lane/task drift, digest/resource tamper, stale request, no Owner confirmation, unprivileged issue rejection, duplicate active binding and existing issuer behavior. They do not establish real UID462 access, administrator TTY behavior, production sandbox Git writes, or Deepin support. Final acceptance requires exact-SHA independent review, original full R9, CI/protected main, administrator installation, one real Owner approval and multiple real Web/CLI commits with the same lease, negative scope/revoke tests and one coordinated managed deployment. Web request/status UI is not added in this minimal CLI entry.
