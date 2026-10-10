# I5-G — independent operator-signed single GLM attempt (offline)

**Base:** I5-F `fe9437c66f711170c88fb992dcaf6fe30ef5aff0`.
**Candidate branch:** `feat/task-budget-i5g-positive-authority-20261009`.
**Disposition:** code-only offline candidate; **NOT production active**.

## Why new control-plane authority is necessary

I5-F establishes an event-durable, signed *zero-send* Run admission. Nothing
previously allowed an authorized positive physical Provider attempt. A raw
budget from an offline fixture, a chat message, a Web cookie, or a writable
config flag is not a genuine operator authorization. I5-G adds a disjoint
`tb3` Ed25519 grant domain and a separate manually started Unix-socket issuer.
Only independent human `op1` approval for the exact persisted EventStore
`message.appended` event may cause the issuer to sign this fixed profile.

## Fixed v3 policy — strictly limited guarantees

The signed `tb3` grant always has:

- Exact event `event_id`, `seq`, content/provenance digest, session, workspace,
  operator principal commitment and expiration (maximum 30 seconds).
- Exactly **one physical Provider attempt**. Tool invocations = **zero**;
  allowed tools empty; wake and subagent creation explicitly denied.
- Provider identity exactly `glm`, model exactly `glm-5.3`, `openai` HTTP
  protocol, verified TLS HTTPS endpoint exclusively under
  `open.bigmodel.cn` with path `/api/...` and no custom port, URL userinfo,
  query/fragment, or proxy.
- A manually trusted I5-D `IsolatedTransportProfile(verify=True, proxy=None)`
  must be bound by control-plane code. The actual exclusive worker itself
  checks the persisted, dispatched CAS reservation before opening HTTP.
- `physical_attempts=1` is charged before network dispatch and cannot be
  refunded merely because a response is empty, failed or cancelled.
  `settle` deliberately retains UNKNOWN billing and physical quiescence.
- Rounds, logical calls, prompt/response tokens, payload bytes and remote
  provider cost are **unqualified**, represented by `None`, not imaginary
  hard bounds. A 30-second budget expiry is checked on reads; a reliable
  external resource watchdog/HSM/chargeback receipt is not proven here.

The `tb2` zero-send profile remains the default even for explicitly bound
`SignedWebEventPlan` instances. The new positive grant requires **both** an
explicit trusted plan flag and a verifiable `tb3` token; never silently
upgrades a zero grant. A new nonce or alternate sign domain over the same
human event maps to the identical on-disk budget root, so I1 CAS allows one
owner Run at most.

## Independent issuer service — no automatic Web installation

`task_budget_operator_service.py` provides an explicit, operator-only Unix
socket endpoint. It **does not** create signing keys, start automatically,
register a Web API, accept Web login cookies or expose a model tool.

The service's startup contract requires:

1. A distinct **non-root** operator OS UID. The configured Web peer UID
   must be **different** from the signer's UID. Kernel-authenticated Unix
   peer credentials (`getpeereid` on macOS; `SO_PEERCRED` on Linux) are
   rechecked for every request.
2. A manually provisioned operator-private **budget signer** Ed25519 key
   stored in a service-owned, non-symlink, singly linked regular file with
   restrictive owner-only permissions; the Web process never receives it.
   Service and operator **human approval** keys are independently generated.
3. An independently maintained, bounded, owner-protected trust file with
   pinned public operator keys, explicit operator-to-key roles and current
   revocations; reloaded for each request to avoid stale permissions.
4. Read access to the authoritative EventStore in a separately qualified
   OS ACL arrangement. Current I5-F strict file mode is `0600` owned by Web;
   a truly separate operator service cannot read it without an intentionally
   provisioned read-only ACL or architecture change. **No ACL is installed
   by this patch.** The actual EventStore is freshly reread by exact identity.
5. A service-owned audit directory. An owner-only append-only receipt file
   records event/session/token SHA and is fsynced with its directory **before**
   any positive token escapes. Failed audit IO blocks the signed response.
   No operator secret, raw approval or budget private key is logged.

The Web-side client helper sends only the exact event/session and an `op1`
operator-signed **approval proof** through the Unix socket. It never sends an
operator password/private key, and cannot choose the provider, model, budget
limit or workspace. Replayed approvals cannot give a second Run a budget
because the budget store root uses the event's deterministic identity.

**Important:** the service's existence does not mean a production operator
approvals workflow exists. An operator must independently inspect and sign
the *post-persistence* human event. There is no approved human UX, delivery,
waiting/resume/recovery protocol, signing-key vault/HSM, ACL, service manager,
or live Web plan binder in this phase. A compromised Web account with access
to its own socket cannot forge the independent `op1` signature; nevertheless
neither OS account separation nor real human approval is provisioned here.

## Offline evidence and safety tests

`test_task_budget_positive_operator.py` exercises disjoint positive signature,
default-0 opt-in denial, fixed one-physical-call quota, same-event CAS replay,
bad op1, cross session/workspace, key revocation, wrong model/protocol/host,
no process isolation, missing dispatched reservation, and actual `LLMClient`
pre-HTTP mismatches. Its use of `httpx.Client` mocks does **not** make a real
GLM-5.3 request or prove remote cost limits.

`test_task_budget_operator_service.py` exercises the Unix IPC framing,
file permission/nofollow protection, platform kernel peer lookup, wrong peer,
rejected operator proof and revoked key, before-response durable audit and
its injected fsync failure. Test-only successful cross-UID peer routes use
an **explicitly monkeypatched** UID because CI does not own a second OS
account. This is protocol qualification, not live OS-security qualification.
The authentic same-UID path is independently tested and rejected.

Frozen adjacent suite (I5-A through I5-G plus EventStore and client):
**252 passed**. Focused Pyright: **0 errors / 0 warnings**. Official fixed-SHA
R9 and final whole-tree security scan must also pass before promotion.

## Required gates before `main` / publish / actual ON

1. Operator provisions a distinct OS service UID, its socket group/ACL,
   read-only EventStore visibility and appropriately protected keys without
   allowing the Web process to read private signing material. Verify actual
   UID, inode, permission and key rotation/revocation on the target host.
2. Independently authenticated human approves actual persisted event; the
   client callback obtains only the freshly authorized `op1` and `tb3`
   through an audited wait/resume workflow, never from model/user metadata.
   Audit/consumption must survive all crash points without second issuance.
3. Verify model registry identity and target URL against actual GLM-5.3
   configuration, DNS/TLS, timeouts, HTTP request payload and on-call
   ability to revoke the exact Run. Test cold start, Stop during TLS/DNS,
   process crash and budget expiration. If outbound proxy is mandatory,
   fail closed rather than silently extending the allowed egress.
4. Qualify OS worker count, spawn/start timeout, RAM/CPU limits and total
   child-lifetime watchdog. A killed local process and socket EOF do **not**
   prove provider-side cancellation, no continued processing or zero fees.
5. Only after R9/security/managed deployment qualification, use a reversible
   Web-only Canary (Feishu/Learning unchanged) with one separately approved
   limited real GLM-5.3 call; reconcile the exact dispatch ID and billing
   receipt, including UNKNOWN liability. Stop on any failed gate.

**Action boundary this phase:** no `main` merge, remote push, managed
`publish`, restart, production secrets/UID/ACL/config change or external
Provider call; ordinary Web TaskBudget remains OFF.
