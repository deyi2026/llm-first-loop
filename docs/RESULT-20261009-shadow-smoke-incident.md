# gen206 Web Shadow: bounded smoke incident and qualification boundary

**Status:** post-mortem evidence qualified; live Canary/efficacy **HOLD**.

## 1. Evidence, not an HTTP retry hypothesis

- Desired gen206 / Web runtime `da8629b0b66be5eba214b1490daefcf0cccaa306`,
  Knowledge Advisor `shadow`; Feishu/Learning remained gen204 `off`.
- The one isolated **synchronous Web HTTP smoke** sent
  `pytest pytest pytest` to a newly created current-workspace session
  `8040dc96-b886-4c1c-9ec4-718baa958b66`.
- EventLog first human ingress at seq=2, 05:34:47+08, metadata
  `ingress_entry=web`, `ingress_delegated` absent, 20 chars.
- At seq=223–227 of the same run, the model successfully called the
  `schedule` tool. The corresponding durable tool receipt confirms
  **`wake=true`**, an automatic continuation in the same session.
- First Run: generation `f7e79827...`, 20 rounds, cancelled at seq=330
  05:39:41+08, 342,355 input / 1,211 output tokens.
- At seq=334, 05:40:16+08, a **distinct 407-char user-role ingress** has
  `ingress_entry=scheduled:schedule_wake` and
  `ingress_delegated=true`. The second Run did not originate from an
  HTTP request replay; it was a delegated wake scheduled during Run 1.
- Second Run: generation `868bd50d...`, 16 rounds, cancelled at seq=658
  05:42:24+08, 421,595 input / 6,294 output tokens.
- Total 38 provider opened/settled, 35 tool started/finished, and 4
  `knowledge.discovery`. `knowledge.reference_prepared=0`,
  `knowledge.method_declaration=0`, reflection
  `reason=no_durable_episode`.

The HTTP client timeout did **not** stop server-side work. The initial
test used normal production tools and prompt-only "do not use tools"
instructions, which were **not** a security or cost boundary. GLM-5.3
also launched a full `pytest -q` subprocess. This unexpected task
was killed through the exact session-scoped Job API; both run generations
were then cancelled via the official Web endpoint. The session was
archived, with EventLog retained, and the shared current user session
was unchanged.

**Do not diagnose an automatic sync-HTTP retry bug from these events.**
The Scheduler's existing same-session human-grant delegation is its
specified behavior, not proof that it mishandled a cancelled HTTP
request. A future design can examine the distinct policy question:
whether a model may create `wake=true` schedules without the user's
explicit semantic request; this is out of scope for the offline gate.

## 2. Offline hard limits

The new executable `scripts/shadow_smoke_offline.py --offline`
is the **only** supported harness entry. No live mode exists.

| Control | Enforced mechanism |
| --- | --- |
| Provider | `FakeLLM` only, invalid offline endpoint and denied socket connect |
| Callable tools | Empty `ToolRegistry`; `execute_many` trapped |
| Provider attempts | Before-call cap: 1 |
| Model rounds | Fixed offline Settings: 1 |
| Input tokens | Explicit fake-provider usage must be 1–2,000 |
| Output tokens | Explicit fake-provider usage must be 0–128 |
| Request bytes | Pre-dispatch UTF-8 JSON wire ≤80,000 |
| Wall time | Parent 20 s deadline, terminates child process group |
| Data / secrets | Fresh temporary HOME/DATA_DIR; no inherited provider secrets |
| Shadow | One discovery event; zero `reference_prepared` and zero tool starts |

The token caps refer to explicit **synthetic FakeLLM usage**, not a
claim of exact token-count enforcement on a live GLM provider. Input
byte cap is separate and deliberately described as bytes. Any future
live smoke must qualify an actual provider-call budget gate and
tool-execution deny authority **before** it can run. These test-local
fences are not production changes.

## 3. Promotion conditions

Keep Web gen206 Shadow observable and Canary **HOLD**. Do not publish,
restart, modify Feishu/Learning, or push the isolated candidate for
the sake of this diagnostic test. Before attempting live efficacy:

1. Qualify the offline no-network/no-tool gate, timeout cleanup and
   unchanged OFF/Shadow provider wire, with an official R9 test receipt.
2. Freeze a real-provider call/token/time budget enforced in the
   invocation boundary, plus an independent zero-tool allowlist.
3. Use explicit narrow non-actionable task inputs, isolated sessions,
   no `schedule` capability, and no automatic retry after client
   timeout; record exact per-run ingress identities.
4. Compare randomized OFF versus Shadow runs with equivalent tools,
   provider, attempts, input/context and success criteria; require
   fewer mistakes/retries and acceptable whole-run cost before Canary.

This phase demonstrates boundary safety and correct attribution, **not
Method/Experience efficacy**. No additional production smoke is
authorized by this document.
