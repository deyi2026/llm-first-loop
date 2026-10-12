# TaskBudget I4-A: offline-only exact Run binding

**Status:** isolated candidate; no live signing service, no live budget or
Canary activation. Parent: d28c59fd7, production Web gen206 Shadow unchanged.

## Implemented

- `resources/task_budget_run_scope.py` adds a **test-owned** explicit
  `OfflineBudgetIntent` with an exact session, hashed workspace binding,
  fixed finite expiration, and a verified non-delegated `IngressToken`.
  It grants **zero** physical provider sends, **zero** tools, no wake,
  no subagents, and one provisionally recorded round/logical call.
- `core/loop/lifecycle.py::run_stream` binds this intent *only after*
  the exact Run generation is minted and its Session run lease acquired.
  The bound zero-resource policy is replayed across every generator resume;
  no asynchronous model/text authority is accepted.
- `resources/provider_calls.py` blocks any explicitly bound budget from
  dispatching an unsupported duck-typed provider. This is necessary:
  a FakeLLM lacks `LLMClient._transport_attempt_scope`; checking only at
  that method would allow a bound budget to be silently bypassed by a
  different client class. No bound budget leaves the legacy path unchanged.
- `task_budget_dispatch.py` recognizes the hashed workspace scope when
  verifying the actual per-Run context, without granting a cross-session,
  cross-workspace or cross-generation exception.

No production Web route, Factory or Resolver key installs
`bind_offline_budget_intent`. No scheduled wake path can sign or renew
an offline intent. This is an internal offline qualification mechanism;
it must never be advertised as a public user-authored policy.

## Demonstrated with real engine / fake provider

The offline unit suite uses real `LoopEngine.run`, isolated SessionStore
and a duck-typed `FakeLLM`, and verifies the **number of actual model
calls** rather than just checking a denial message:

- Unbound ordinary human task returns its normal FakeLLM answer with no
  task-budget files.
- Bound zero-send task does not call the FakeLLM; one exact root budget
  is visible with no reservations, zero provider permits and zero tools.
- Missing, forged, or scheduled delegated ingress cannot create a root.
- Different session/workspace or expired intent cannot create a root.
- The intent does not leak into the next normal human Run in the session.

## Not yet sufficient for active production

This is **not** a production task-budget issuer; it is not a true signed
identity across processes. Real Web, SSE, Feishu and Learning do **not**
receive a new grant. Neither positive-cost limited live execution nor
GLM-5.3 exact usage/cost is qualified. Budget-protected schedule creation,
wake recovery lineage, recursive subagents, physical cancellation, and
provider RG-3C usage reconciliation remain unimplemented.

Do not enable live enforcement; do not run a real GLM pressure smoke.
The only valid next gate is an independently qualified, operationally
signed issuer and derived work/cancellation contract. Until then code
can at most be considered for a **default-off** compatibility release
after formal full R9, with a separate deployment authorization.
