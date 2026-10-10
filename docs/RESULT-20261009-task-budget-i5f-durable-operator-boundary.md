# I5-F — strict human-event durability and independent operator proof

**Candidate:** `feat/task-budget-i5f-durable-operator-20261009` based on
I5-E `090f09ee21d12632666fcafda3e48a04f1afd2b2`.

**Status:** isolated offline mechanism; NOT production operator authentication,
NOT a positive TaskBudget grant, NOT a GLM-5.3 billing/cost qualification.
Production Web remains on gen207, TaskBudget OFF. No main merge, push,
publish, restart, real Provider call, key provisioning or config edit.

## Evidence and exact trust boundary

I5-E introduced the `tb2` approval after an EventStore `message.appended` but
its old `EventStore.append` only flushed Python's buffer, not the file and
directory to durable media. A process might sign an event that existed in
memory/on a page cache but disappeared after a crash or power loss. In
addition, I5-E's operator callback accepted a simulated ticket and its
independent identity check was not cryptographic.

I5-F closes these *offline mechanism* gaps:

1. `EventStore.append_durable_human_message` is a deliberately narrow new
   synchronous path for `source=user`, `role=user`, provenance
   `origin_layer=user_instruction`, `program_origin=false`. The ordinary
   EventStore path remains fail-open for unrelated messages and tools.
2. The strict path uses cross-process `flock` without lock fallback,
   refuses untrusted owner/mode, symlinks and multiply linked files, appends
   exactly one true `message.appended` event, `fsync`s the file and its
   containing directory and ancestor EventStore directory in correct order,
   then independently rereads by exact `event_id`, `seq`, payload, and checks
   no malformed/skipped entries. *Only then* may the operator signer see it.
3. An error before physical append is a definite denial; after possible
   append, a failed `fsync` or readback is
   `EventCommitUncertainError(event_id?)`. The caller never creates a budget
   from it and **never assumes refund/rollback** just because the event may
   or may not be durable. A visible file is insufficient evidence.
4. `core/loop/events.py` and `engine.py` choose that strict path **only**
   when a trusted I5-E signed event plan is explicitly installed. A missing
   EventStore or I/O error cannot be converted to a best-effort warning in
   that mode. The first Provider and tool gates still run after its verified
   event and signed budget admission.
5. Separate domain `op1` requires an independently pinned *operator* Ed25519
   key to approve the exact persisted event ID/seq/content+provenance hash,
   Web session, workspace and bounded clock window. The budget issuer uses a
   distinct Ed25519 key to produce the existing `tb2` token. A Web login
   cookie, unknown/revoked operator, mismatched event/scope, forged signature
   or expired proof cannot authorize a budget.
6. The operator public-key trust loader reads only a bounded local regular
   file with owner and permission checks and no symlink. It rejects a private
   key accidentally placed in the public-key mapping, and reloads revocation
   on each call. No new key is generated or installed in production. The
   `OfflineOperatorApprovalSigner` is a fixture/operator-process helper, not
   a Web route or a runtime source of user authorizations.
7. Because actual `tb2` budgets still have **zero** physical Provider and
   tool calls, this phase can only prove authorization and denial mechanics,
   not a positive-cap production execution contract.

## Negative coverage / strict stop rules

`test_task_budget_durable_operator.py` tests file and directory sync,
independent readback, injected fsync failure **with bytes still readable**,
no Web model/provider effects, default EventStore behavior untouched,
unsafe lock or event symlinks/permissions, exact two-key approval, Web cookie
rejection, revoked/unknown/stale/mismatched operator signatures and scopes,
private keys in public trust store, and dynamic key revocation. The existing
I5-E signed human-event, EventStore, I5-D process-stop and I5-A/B/C tests
remain the adjacent regression authority.

An OS-process kill proves only local process exit and local socket shutdown;
it does NOT prove the remote Provider stopped computing or stopped billing.
The budget ledger must retain `UNKNOWN` liability after dispatched work.

## Production qualification still required before ON

1. A truly separate trusted *operator identity and signing service* running
   outside the Web process security domain, with independently provisioned
   keys, protected private key custody/HSM or equivalent, operator role
   checks, rotation/revocation, signed audit receipts, and authenticated
   human approval UX. In-memory offline signers and the LFLM control
   console's current `auth_enabled=false` do not qualify.
2. Crash-recovery fault injection across event append, budget issuance and
   Run admission; complete durability provenance for actual release/runtime
   filesystem and power-loss behavior. The current fsync contract covers
   file and directory receipt in tested local filesystem conditions.
3. Proper positive-cap contracts signed by that operator and enforced on
   all Provider attempts, retry/fallback, tool, wake and subagent derivation.
   A production canary must start with tools/wake/subagents denied and a
   very small bounded physical-call quota, only after independent approval.
4. Worker OS process quotas, spawn/kill hard wall boundary, egress/credential
   containment and cross-Run owner lifecycle. GLM-5.3 exact token/fees and
   cancellation billing remain **UNKNOWN** without verified provider receipts.
5. Exact managed Web-only release and restart identity, automatic rollback
   conditions, zero unexplained dispatched attempts, and staged live canary
   approval. Feishu/Learning remain out of scope.

**Decision:** qualify offline mechanics if final SHA R9/adjacent/safety pass;
retain production `TaskBudget=OFF` and deny all positive-budget usage until
the independent authority and resource/cost gates are proven.
