# I5-D — isolated Provider worker termination (offline)

**Candidate:** `feat/task-budget-i5d-process-transport-20261009`, based on
I5-C `71d0b57a1b13e2a446929d882f0210dec5a1b881`.
**Scope:** independently tested OS-process transport termination, **not**
production budget activation or a claim of remote Provider/billing shutdown.

## Why this execution boundary is necessary

I5-B/C cooperative Stop plus an exclusive HTTP/1 socket shutdown work once
an HTTPX response exposes its socket. They do not give the caller a reliable
means to terminate synchronous DNS resolution, TLS/CONNECT setup or a
pre-response-header call, and cannot safely close a shared HTTP/2 connection.
The model cannot judge or cancel a kernel-blocked physical call by prompt.
The new control is therefore mechanical and its escape hatch is the
**existing default-OFF, unbound transport**; no model/prompt may bypass a
bound physical budget after it was installed.

## I5-D implementation

* `src/llm_loop/resources/task_budget_process_transport.py` exposes a
  **typed, explicitly installed** `IsolatedTransportProfile` and
  `bind_isolated_provider_transport`. No Web route, external config,
  scheduler, model output, Feishu, Learning or normal Run installs it.
* The parent reserves a Provider attempt via the **existing** I2/I3
  `checked_provider_attempt` boundary, keeps the durable TaskBudget
  authority and signs off all streamed bytes. It registers its child process
  abort callback **before** starting the subprocess, so a concurrent Stop
  latches even before a PID exists. It polls IPC in 25ms increments and
  validates the exact Run authority before and after every frame.
* The spawned, daemonized OS worker creates a **fresh** HTTPX Client and
  performs one POST, with redirects disabled, `trust_env=False` and
  `http2=False`. Transport profiles must explicitly provide TLS trust
  and optionally a proxy. TLS verification cannot be disabled. Non-loopback
  plaintext HTTP is rejected. The child is not passed the durable budget
  store, session authorization or grant. It inherits the host OS user's
  environment/filesystem access and is **not** a security sandbox.
* Credentials/body are passed through the multiprocessing launch pipe, not
  command-line arguments. A bounded JSON/binary IPC protocol transfers
  response metadata and lossless, chunked raw body bytes. The parent creates
  an HTTPX Response and retains the four existing SSE decoder implementations
  and response/usage accounting. One frame can be at most 256KiB; chunks are
  16KiB. No silent body truncation or invented usage exists.
* A local Stop calls `terminate`; the parent waits for the child, then
  escalates to `kill` and verifies OS process exit within bounded joins.
  Child IPC EOF/race must not overwrite an authoritative
  `TaskBudgetDeniedError` with a generic network error. Conversely, an
  unexpected worker exit without Stop remains a real network failure,
  **not** a falsely successful cancel.
* The worker watches its multiprocessing **parent process sentinel** every
  50ms and exits itself if the owning Web/Run process disappears. This avoids
  orphaned outbound transport after a host crash. This does not persist a
  remote shutdown acknowledgement.
* No explicit profile means LLMClient still calls the **same original
  `httpx.Client.stream` instance with the same timeout arguments**. This
  applies to every normal Run, and to older explicitly bound budget probes
  that do not select I5-D.

## Negative and positive physical evidence

Tests in `test_task_budget_process_transport.py` and
`test_task_budget_process_lifecycle.py` use actual independent spawned
Python child PIDs and local HTTP endpoints, not mocked cancellation flags:

| Property | Observation |
| --- | --- |
| Four wire adapters: OpenAI, Anthropic, Google, LMS | One local HTTP request, Stop ends reader, server sees EOF, child PID reaped, original grant is Stop/UNKNOWN |
| No response headers | Stop kills process rather than depending on HTTPX's idle read timeout |
| CONNECT-only local listener, **no forwarding** | Stop kills the blocked child; no provider target ever contacted |
| Strictly certificate-verified TLS/HTTP/1.1, four adapters | Stop kills isolated HTTPS child and TLS endpoint sees disconnect; no insecure TLS override |
| Full finite SSE and usage | Body/content and observed usage reach existing decoder intact; local complete response does not convert UNKNOWN into a billing ACK |
| Two independent live Runs | Stop A does not end B; each child is reaped only by its owner, liabilities remain separate |
| Unexpected worker exit | Network error, never a claimed Stop/settlement; UNKNOWN is retained |
| Parent process abrupt death | Child parent-sentinel watcher exits and server observes disconnect |
| No bound budget and untrusted TLS settings | Experimental isolated transport denies before any network effect |
| ContextVar propagation | The isolation profile does not cross arbitrary threads automatically |

The measured tests qualify **local OS-process termination** of the exercised
paths. A forced child termination is stronger than a connection `close()`
flag, but cannot retract bytes already received by the remote Provider or
prove it stopped computing/charging. All dispatched reservations continue as
`UNKNOWN`; `physical_quiescence_verified` remains **false**.

## Known HOLDs / prerequisites

1. The test-only profile is **not** connected to an authenticated
   production operator issuer, persisted human event ID or positive
   TaskBudget grant. No production positive-budget Run exists yet.
2. This is a process lifetime boundary, **not** an OS security/sandbox
   boundary: the child inherits environment and local filesystem access.
   Production hardening needs egress allowlists, credential minimization,
   startup authority, process quotas and measured spawn/IPC overhead.
3. Worker spawn/start itself is not yet proved hard-bounded for all platforms,
   crash windows and pool saturation. Current qualification is macOS
   `multiprocessing.spawn` in a controlled local environment. A future
   production runner should own worker lifecycle across process restarts.
4. The worker deliberately uses HTTP/1.1; real proxy-forwarding, genuine
   multiplexed HTTP/2, external DNS/hard-cancel and provider-side server
   usage/fee stop are **not** qualified here.
5. GLM-5.3 exact usage/product/account/billing reconciliation, wake/subagent
   inheritance, durable idempotent transport nonce and full positive Canaries
   remain independent gates. Never equate verified child exit with
   `physical_quiescence_verified=true`.

**Operational invariant:** main stays on production gen207
`a64e18b74`, TaskBudget stays OFF; no real-model request, main merge, push,
publish, restart or production configuration modification.
