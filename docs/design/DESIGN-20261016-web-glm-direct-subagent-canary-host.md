# Web GLM-5.3 Direct-Child Canary — Host Admission and Durable Resource Contract

Date: 2026-10-16. Implementation candidate only — isolated Git branch
`fix/web-multiagent-canary-host-20261016`, base `c3c306f6d`.
**Not merged, released, enabled, or provider-tested.**

## Problem and explicit boundaries

The existing `web-task-budget-admin-once/v1` permit is expired and, even if
extended, is *mechanically incapable* of testing a parent/child Agent: it allows
1 provider attempt, 0 tools, and `allow_subagents=false`. The existing
knowledge-consumption profile also denies subagents. This is not a problem
that an LLM prompt or model-default change can safely fix.

This candidate adds a **distinct, operator-provisioned, startup-only** profile:
`web-task-budget-direct-subagent-canary/v1`. Normal Web traffic and the two
existing profiles are untouched. The operator must explicitly select
`--profile direct-subagent` when creating a NEW, exact-session, owner-only
0600 configuration; setting it as a live runtime Web config and any restart
requires *later separate authorization*. No ordinary user/model/tool input can
select the profile. Approval ID cannot be reused after first durable human
event admission; the EventStore must confirm genuine Web origin and exact
message/session/workspace/run generation.

## Fixed root rights (not controlled by configuration JSON)

| Resource/effect | Mechanism |
| --- | --- |
| Provider | Exact `glm` / `glm-5.3`, HTTPS `open.bigmodel.cn/api/` |
| Transport | Verified isolated transport; no implicit/environment proxy |
| Root lifetime | Earlier of 180 seconds since admitted Run or operator approval expiry |
| Physical attempts | At most **8**, across parent **and** its single child, durable CAS |
| Tool invocations | At most **3**, including failed/unknown dispatched attempts |
| Root tool names | `spawn_subagent` at most once; `subagent_result` at most twice |
| Spawn arguments | Nonempty bounded `task`, `requires={"tools":[]}`; no inherited context, no acceptance, no alternate model |
| Child tools | **Zero** (both schema discovery and Registry dispatch guarded) |
| Child depth | Exactly 1 direct child; no child/grandchild recursive delegation |
| Child rounds | At most 3 model decision rounds |
| Wake/shell/files/network/browser tools | Denied by this budget, not authorized by the canary |
| Cancellation | Parent root can revoke the shared ledger; child is generation-bound and denies all subsequent attempts |

The model may choose whether and when to delegate but may not expand these
authority boundaries. The actual per-root budget uses a single durable
`TaskBudgetStore` ledger; physical attempt reservations are persisted as
**dispatched before network send**. Missing quota, expired scope, wrong
provider/model/endpoint, mismatched session/workspace/generation, failed
persistence, duplicate spawn, re-used approval, forbidden tool arguments,
and cross-parent result lookup are rejected before physical dispatch.
A failed/interrupted provider attempt also freezes subsequent attempts;
successful responses with unknown *billing* remain conservatively charged.

## Child/member lifecycle

`SubAgentRunner.start` verifies the parent budget, model, first depth, empty
child tool set and existing physical spawn reservation, then creates a
durable member bound to the true generated child `session_id` and child
`generation`. It starts the background thread only after successful member
CAS. The thread binds its own `TaskBudgetExecution` member, not the parent's
session identity, and debits provider attempts from the *same root ledger*.

This is an opt-in special case of the existing same-session member contract:
only `web-glm-direct-subagent-canary-v1` may have a different-session member,
only one such member, and only directly under the root. The store validates
that lineage again on every disk read. The signed/public model cannot create
budget members or call `bind_member`; the Host uses the true internal child
identity and only after a dispatched `spawn_subagent` reservation.

The existing `SubAgentRunner.cancel_parent(root_sid,run_generation=...)`
drives generation-scoped cancellation; the root task budget is stopped through
the exact owner Run's existing shutdown path. Once the root ledger is stopped,
neither root nor child can make a later provider/tool attempt. **An in-flight
HTTP request may still finish remotely** and may have unknown billing; do not
treat cancel flags as an acknowledged remote abort.

## Production deployment and canary plan (not included in this authorization)

1. Complete deterministic positive and negative Host tests; ensure existing
   one-attempt/knowledge budgets remain unchanged, plus targeted tests and
   original Quick diagnostics.
2. Obtain one genuine **independent GLM-5.3 code-review terminal PASS, P0=0,
   P1=0**, bound to exact patch SHA and frozen source before the **original
   complete R9**. Freeze/commit only on isolated branch. No merge/push/restart.
3. Ask separately to prepare a dedicated **Stage A** Web operator approval,
   bind a new Web session, inspect a clean release and rolling active sessions,
   and perform a separately authorized Web-only restart. Do not enable this
   profile from the model, shared default, or current expired config.
4. Stage A: exact diagnostic root Web session, single real child, verified
   GLM physical attempts and child durable result/terminal; parent polls
   result and confirms `CANARY_SUM=58597`. Verify receipt IDs and spent
   attempts. Failure or missing settlement => stop; no retries.
5. Stage B (only after Stage A PASS and separate exact-session authorization):
   another root session/approval on the same qualified profile. Spawn a
   controlled child, cancel its **own** parent Run, verify durable cancel
   request/terminal, no late provider/tool effects, and unknown remote
   cancellation truthfulness. No interference with other foreground sessions.
6. Stage C three-level recursion is OUT OF SCOPE and requires a new exact
   `CHILD_SPAWN_GRANT` proposal and explicit approval. Never use `*`.

## Verified limits / honesty

This is a narrow Host **capability/effect** budget, not a full OS sandbox.
It does not grant general filesystem/network isolation or guarantee remote
model billing/transport termination. `8` attempted sends is a *ceiling*,
not a claim that 8 calls were used, necessary, or billable. Retry prevention
is a hard future-dispatch gate, not an assertion that a failed transport had
no bytes leave the host. The child has no tools, so it cannot run repository
operations or issue extra recursive tasks. A regular unbudgeted Web session
is not evidence of canary qualification.

No production Provider calls, session creations, runtime config changes,
deployments, restarts, pushes, or main worktree mutations are made by this
isolated implementation/verification.
