# TaskBudget I5-A: operator-signed Web zero-send proof (2026-10-09)

**Scope:** isolated `feat/task-budget-i5a-issuer-20261009` based on production
Web gen207 `a64e18b74`. This phase does **not** authorize production
enforcement, a positive provider call, or a live GLM-5.3 smoke test.

## Authority and physical boundaries

`resources/task_budget_authority.py` adds an operator-side Ed25519 signing
capability and a separate public-key verification path. A configured operator
must supply the signing key, approve the exact intended session/workspace and
human text, and keep its private key outside all model/agent tool contexts.
The Run-side verifier accepts only a preconfigured trusted public key ID and
domain-separated canonical signed proof; no unsigned Web payload, model text,
Session history, prompt or environment switch can issue a grant.

The signed approval has a random 128-bit nonce, distinct root budget ID,
human-turn digest incorporating that nonce, exact workspace/session, bounded
TTL (max 60 seconds), and an **immutable** policy profile:

- Web + nondelegated human ingress only; post-Session-lease Run generation
  bound to the durable root and persisted as the first/only root member
- `physical_attempts=0`, `tool_invocations=0`, no wake/subagents, no tools
- provider model/account not asserted; no token or money hard-limit claim
- persisted flock-protected one-use issuance: repeated proof is denied,
  including concurrent presentations and presentations after Run terminal

`core/loop/lifecycle.py` attempts this *only* when a typed explicit intent is
already installed by trusted program code. The original I4-A offline intent
remains available, and no intent retains normal default-OFF semantics.
No production Web route, factory, Resolver, Feishu, Learning or scheduler
installs the signed intent. Production signing service and authenticated
operator approval UI/transport are **not implemented by I5-A**.

## Negative evidence

`tests/unit/test_task_budget_signed_web_issuer.py` (23 PASS) uses real `LoopEngine`,
`FakeLLM` counting calls, real `ToolRegistry.execute_many`, and the four
`LLMClient` protocol entrypoints with mock transport send counters.

- A bound signed root produces **zero FakeLLM calls**, zero HTTP sends for
  OpenAI-compatible/Anthropic/Google/LMS, and zero tool side effects.
- Forged or delegated ingress, wrong session/workspace/text, expiry, unknown
  trust key and modified signature create no budget root and no provider call.
- Even a **valid signature** for an expanded physical/tool allowance is
  rejected by the enforced fixed zero-capability profile.
- One proof cannot reset a root budget in a new Run, and concurrent proof
  presentations allow only one accepted issuance.
- User text containing the signed approval does not activate a budget.
- An ordinary unbound Run remains unchanged and calls its FakeLLM once.

## Scope that remains HOLD

I5-A is an authorization/zero-execution kernel, **not** a production signer
deployment or live positive budget. Operator authentication, production trust
anchor provisioning/rotation/revocation and audit, physical socket stop and
UNKNOWN provider liability reconciliation, durable wake/subagent inheritance,
GLM-5.3 exact token/product/billing qualification, and bounded live Canary
are separate gates. Do not enable budget config, publish/restart, or push.

The signed digest binds the exact text within a session, while the first
admitted Run's generation is bound atomically at consumption. A separate
Web-authenticated **human message/event ID** is not yet provided to the
signer/consumer as an authoritative field; future positive-budget activation
must enforce this independent turn identity rather than treating a nonce as
proof of a particular persisted user message.

## Offline verification

- New I5-A negative tests: **23 passed**.
- Four adjacent budget suites: **101 passed**.
- Formal `scripts/ci_gate.sh`: **exit 0**, Ruff/env-pin/Pyright/tier0,
  complete xdist suite and architecture checks all PASS; tier0 310 passed.
- Security scan must be rerun on the committed immutable candidate: the
  precommit pass only covered 4,244 *tracked* files, not new untracked code.
