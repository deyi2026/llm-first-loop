# Task Budget I4-B: bound provider stream cooperative stop (2026-10-09)

**Scope:** isolated I4-B candidate based on main `aaf5aa24e`. Default
OFF remains bit-for-bit equivalent on the HTTP SSE iterator. This is not
a production issuer, a physical socket watchdog, or a billing stop ACK.

## Implemented boundary

Four physical provider stream paths in `llm/client.py` (OpenAI compatible,
Anthropic, Google and LMS Chat) now consume
`_iter_task_budget_checked_lines`. When a TaskBudgetExecution is explicitly
bound, the iterator validates the persisted root/member/Run/session/workspace
identity, active status and root wall deadline before reading and after
each delivered SSE line. This includes the next outer generator resume
after a UI/protocol delta. On revocation/expiry the HTTP stream context
exits via the existing exception path. The physical attempt remains
UNKNOWN, because remote compute and billing may have continued.

When **no** task budget is bound, the wrapper delegates using exactly
`yield from resp.iter_lines()` and never reads the ledger. No new
configuration or production ingress wiring was added.

## Offline negative evidence

The physical client/transport fixture counts HTTP mock sends, actual SSE
lines yielded, context `__exit__` exceptions and durable reservation phases.
For each of four protocols:

- An initial content delta can be delivered normally.
- A root stop requested after the first delta rejects the next resume
  *before* a second SSE line is read; the transport context exits.
- Advancing the authoritative fake clock past the root wall deadline
  similarly stops before a second SSE line.
- In both cases the already-dispatched attempt stays UNKNOWN, not
  SETTLED/zero-cost/CLOSED_VERIFIED.
- A separate unbound control reads all lines with the unchanged
  provider wire and creates no budget directory.

## Open gates before production active enforcement

1. An idle/blocked network `iter_lines()` is **not interruptible by
   this cooperative check**. Socket cancellation/worker termination must
   be separately implemented and qualified, including real transport
   closure and unknown remote billing semantics.
2. `Runner.cancel` does not yet propagate an exact generation-scoped
   `TaskBudgetExecution.request_stop`; the test calls that API directly.
3. There is no production Web issuer, durable wake/subagent inheritance,
   exact GLM usage/cost authority, or end-to-end physical quiescence
   verification. Do not declare the broader I4/I5/I7 matrices PASS.
4. The only qualified release scope is **default OFF** after full R9
   and explicit managed deployment authorization. No live real-model
   pressure trial is authorized by these offline results.
