# TaskBudget I5-C — transport qualification and fail-closed multiplexing

**Date:** 2026-10-09. **Candidate:** isolated branch
`feat/task-budget-i5c-tls-proxy-transport-20261009` based on the independently
validated I5-B commit `77aaa1ede4218a17c2cdc9c9a65bff1546089083`.
Production remains Web gen207, TaskBudget default OFF. This is not a
production activation or remote billing qualification.

## Evidence matrix (distinguish local exit from remote cancellation)

| Path / condition | Real evidence | Qualification |
| --- | --- | --- |
| Direct HTTPS/TLS HTTP/1.1 after response headers | Temporary self-signed SAN certificate generated under pytest temp root; HTTPX validates the certificate against that explicit trust anchor. Real loopback TLS POST and SSE, four LFL wire protocols; exact Run Stop ends blocked read and TLS server observes physical EOF/reset. One dispatch, durable Stop and UNKNOWN reservation. | **Local physical exit qualified for this exact path only**. Not remote usage or payment ACK. |
| HTTP/2 or HTTP/3 multiplexed response | Explicitly bound budget refuses a known H2/H3 response **before any SSE line**. Durable Stop and UNKNOWN reservation; default-OFF H2 iteration unchanged. No shared connection is forcibly shut down. | **Fail closed, not physically qualified**. No real HTTP/2 multiplexed endpoint is tested; `h2` is absent in this environment. |
| DNS resolver in progress | `socket.getaddrinfo` intercepted entirely in memory before any external lookup; synchronous resolver remains blocked after Stop and finishes only when harness releases it. Ledger keeps UNKNOWN, never asserts physical stop. | **HOLD**. HTTPX I/O timeout and post-response socket hooks cannot kill a synchronous DNS lookup. |
| Proxy CONNECT before tunnel response | Local CONNECT-only listener captures the request but **does not forward** any traffic. Stop does not immediately unblock the request; bounded idle timeout eventually exits, liability stays UNKNOWN. | **HOLD**. Full proxied TLS relay/physical disconnect test was blocked by execution-environment safety control and was not circumvented. |
| TLS handshake, slow/trickle response headers, proxy-altered TLS, genuinely shared H2, DNS lifecycle, remote GLM-5.3 billing stop | No complete accepted live physical-stop and accounting evidence. Supplementary slow-header/handshake experimental tests were **not executed** because their run was blocked by the execution-environment safety control. | **HOLD**, not inferred PASS. |

## Delta from I5-B

`llm/client.py` adds a budget-bound fail-closed guard for a response that
explicitly reports `HTTP/2` or `HTTP/3`. Because a shared multiplexed
connection is not an exclusive socket for the current Run, I5-B's HTTP/1
shutdown must never be applied. The guard persists Stop and refuses model
SSE before delivery, without refunding or declaring Provider usage settled.
It is intentionally after the HTTP attempt: **a remote Provider may already
have received bytes and charged the request**, so the ledger remains UNKNOWN.

No budget intent continues along the legacy iterator; all default-OFF
model/provider behavior remains unchanged. The new mandatory gate is
mechanical, not semantic; no model can override it from prompt text.
Authorized operation without this experimental budget remains available
via the existing default-OFF path.

## Test setup and limits

- `test_task_budget_tls_transport.py`: temporary on-disk cert/key created
  by locally installed OpenSSL during fixture execution; no certificate or
  key is committed. The client explicitly trusts only that local cert, not
  `verify=False` and not a production API key. Four real protocol calls are
  restricted to the loopback server. Outcome: read exited and TLS peer EOF.
- `test_task_budget_unqualified_transports.py`: two H2/H3 gate cases, one
  unbound H2 control, one intercepted DNS-stall negative, one CONNECT-only
  no-forward negative. No real Provider network request is made.
- Existing I5-B `test_task_budget_transport_stop.py` remains the separate
  HTTP/1 stop proof. Existing provider/registry and signed I5-A negative
  cases continue to define default-OFF and UNKNOWN behavior.

The tests cannot establish remote quiescence, exact billing, or a universal
physical wall-clock bound. HTTPX's 1-second read/connect timeout is an
**idle interval**, not a continuous wall-clock budget; a stalled/slow TLS
handshake or partial-response-header drip is not proven physically
interruptible. A positive-provider-budget canary therefore remains **HOLD**.

## Required next evidence before activation

1. Production-grade authenticated operator signing, authoritative persisted
   human-message ID, trust anchor lifecycle, and narrow positive grant.
2. Safe and reliable pre-response socket ownership/cancellation across DNS,
   TCP connect, TLS handshake and CONNECT proxy; validate hostile drip, Stop
   races and forced teardown without affecting sibling Runs.
3. If supporting H2, isolate a physical per-Run transport or use an
   independently proven per-stream cancellation mechanism. Rejecting H2
   after a dispatched attempt is not a hard outbound cancellation guarantee.
4. GLM-5.3 real usage/product/billing reconciliation. Until then, retain
   `UNKNOWN` and `physical_quiescence_verified=false`.

**Operational invariant:** no main merge, push, publish, restart, production
configuration modification or real-model Canary in this I5-C phase.
