# I5-E — signed real human event, offline evidence

**Candidate:** `feat/task-budget-i5e-signed-human-event-20261009` based on I5-D
`92163226d7066e94b7de60bcf5e9a6acd44275b3`. **Production:** gen207,
TaskBudget OFF, no new issuer endpoint or production signer.

## Why a new authority boundary

I5-A's `tb1` signs a nonce and human text digest at Run admission, **before**
the human `message.appended` event is persisted. It cannot prove which real
user event the approval belongs to. I5-E adds separate `tb2` Ed25519 domain,
fixed zero-send policy and authenticated operator callback. Legacy I5-A stays
unchanged for its prior offline tests; ordinary Web/Runs remain unbound.

## Exact signed human-event path

1. A genuine, nondelegated Web ingress acquires the Session Run lease and
   Run generation. With no explicitly bound `SignedWebEventPlan`, the old
   path is exactly unchanged. No Web route or model tool installs a plan.
2. The Engine appends its real user message to EventStore. A failed append
   hard-denies an I5-E Run. Only **after** append and **before** Provider/tool
   dispatch does the optional operator plan see the actual EventStore
   `event_id`, `seq` and complete payload.
3. `AuthenticatedEventBudgetIssuer` requires an **independent operator ticket
   authenticator**. It is neither the ordinary browser cookie nor Web bearer.
   Before signing, the issuer freshly reads the exact EventStore record from
   disk and checks event ID/seq/session, `message.appended`, user role/source,
   `origin_layer=user_instruction`, `program_origin=false`, plus exact
   content/provenance hash. No operator ticket or plaintext principal is
   written into the proof, messages or grants.
4. The Run independently rereads EventStore, validates the Ed25519 signature,
   canonical bounded fields, session/workspace/current user text/real Web
   ingress, policy and expiration. The grant is **zero physical attempts,
   zero tools, no wake or subagents**. Only then does `issue_root` use its
   atomic create-if-absent, followed by activation.
5. Every human event UUID deterministically maps to exactly one budget ID.
   Re-signing the **same event** with a different nonce cannot create a
   second budget or Run. Two different persisted events with identical text
   are separate. The budget is bound during the first generator step (prior
   to model/tool execution), then re-bound after each streaming resume and
   sealed on Run end; dispatched liabilities can never be auto-refunded.

This is a mechanical security/identity boundary, not a model semantic
decision. The user's ordinary unbound default-OFF path remains usable.

## Offline test evidence and baseline attribution

`tests/unit/test_task_budget_signed_human_event.py` covers real LoopEngine
EventStore append, four protocol zero physical calls, wrong operator cookie,
cross-session/workspace, text/event/seq/tamper, non-Web and delegated entry,
bad/expired signature, unknown key, replay and concurrent fresh-nonce
reapproval. The cumulative I5-A/B/C/D/E adjacent matrix is **181 passed**.

Initial combined collection showed 177 passed and 4 TLS fixture setup errors
in I5-D's `test_task_budget_process_lifecycle.py`. The **unchanged I5-D HEAD**
reproduced the same four fixture errors (155 passed, 4 errors), proving a
pre-existing test discovery/order issue. I5-E makes that test's TLS fixture
dependency explicit, with no baseline widening; 181/181 then passed.

## Remaining HOLD gates

- An independent **production** operator auth service, operator-vs-Web actor
  authorization, key vault/rotation/revocation and signed audit trail are
  **not connected**. The callback simulates that RPC solely in offline tests.
- EventStore's current append is not yet proved power-loss-durable/fsynced;
  separate hard durability and crash-recovery qualification is required for
  real financial authority. Normal Web cookie/bearer/loopback login cannot
  substitute for separate operator authentication.
- Positive limits, provider usage/fee reconciliation (GLM-5.3), bounded
  worker quotas/spawn time, delegated Run inheritance and live Canary are
  separately unqualified. Production enforcement remains **OFF**.

No main merge, push, publish, restart, external Provider invocation, operator
key provisioning or production configuration change was authorized here.
