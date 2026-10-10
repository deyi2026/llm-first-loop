# I5-B: local Provider-stream physical interruption and UNKNOWN liability

**2026-10-09 / isolated candidate:** `feat/task-budget-i5b-transport-stop-20261009`
on top of I5-A `ca2d6fa2c`. Production stays Web gen207, TaskBudget OFF;
no real Provider credentials, traffic, new service configuration or restart.

## Exact scope and changed mechanism

- `resources/task_budget_dispatch.py` now keeps an exact-Run registry of
  abort handles for already-open HTTP responses. Run Stop and Run terminal
  set the local deny latch **before** attempting transport shutdown and
  durable CAS; a storage failure cannot authorize more bytes or actions.
  Registration is lock-protected to exclude Stop/registration races; one
  Run's Stop cannot close a different Run's registered socket.
- `resources/task_budget_transport.py` is invoked only by *explicitly bound*
  budgeted requests. On HTTP/1.0 and HTTP/1.1, when HTTPX exposes the exact
  response's network socket, physical abort calls `shutdown(SHUT_RDWR)` to
  interrupt its blocked read. A 100-ms local watchdog detects durable Stop,
  local Stop or deadline, without substituting a cancel flag for transport
  exit. Shared HTTP/2/multiplexed sockets are **not** force-closed.
- Bounded HTTPX connect/read/write/pool waits (maximum one second for an
  explicit bound attempt) cover waits where an established response socket
  is not yet available. This is an idle I/O bound, **not** a proof that an
  arbitrary DNS resolver, proxy, TLS handshake or remote calculation halts.
- All four `LLMClient` SSE protocols use the same guarded iterator. Each
  budget check before/after a line, after EOF, and on transport exception
  refuses late post-Stop data. A deadline detected by the owning read loop
  also makes durable Stop; continuous drip does not renew its deadline.
- **Default OFF is unchanged:** no explicit budget uses the exact original
  `resp.iter_lines()` and the previous HTTPX timeout argument.

## Evidence and semantics

`tests/unit/test_task_budget_transport_stop.py` uses an actual loopback
HTTP/1 server, not a mocked `Response.close` or injected exception. It
records one physical POST, a blocked reader, a real Stop, reader completion,
and the server observing the connection's EOF/reset, across the OpenAI,
Anthropic, Google and LMS wire adapters. Additional negative cases cover:

- wrong session or Run cannot abort the owner's transport;
- two concurrent Runs keep distinct connections and liabilities;
- continuous SSE heartbeat/drip does not bypass the wall deadline;
- no-response-header and preheader Stop paths have bounded reads but are
  explicitly **not** claimed immediate out-of-band socket cancellation;
- injected durable Stop write failure still closes the local socket and
  leaves truthful ACTIVE/UNKNOWN liability rather than invented closure;
- HTTP/2 shared/multiplexed connection is not physically shut down by this
  HTTP/1-only mechanism; default-OFF timeout remains unchanged.

The ledger retains each dispatched reservation as `UNKNOWN`, and
`physical_quiescence_verified` remains **false**. A local peer EOF only
proves local connection shutdown, not remote provider accounting settlement.

## Outstanding qualifications (HOLD)

This I5-B unit is **not** a general production hard-cancellation guarantee:
TLS/proxy transport variations, DNS resolver blocking, HTTP/2 multiplexing,
actual Provider cessation and GLM-5.3 billing stop have no qualified proof.
The one-second bounded read can reject otherwise-valid long-think streams;
the applicable positive-budget timeout profile must be qualified separately.
No rollout, budget enforcement config, push, publish or restart is authorized
by these tests. A deployable positive-budget canary requires those remaining
physical/cost gates and the I5-A authenticated operator signing service.
