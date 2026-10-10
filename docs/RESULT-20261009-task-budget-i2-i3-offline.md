# TaskBudget I2/I3 offline pre-dispatch qualification (2026-10-09)

> **Candidate only. Not a live enforcement release.** Parent: main
> 57e35b301 (includes DESIGN-20261009 and I0/I1 ledger).
> Web desired/runtime at implementation start: gen206 Shadow,
> Feishu/Learning gen204; Canary HOLD.

## What is actually implemented

- `resources/task_budget_dispatch.py`: per-Run in-process **explicitly
  bound** TaskBudgetExecution. It checks root/member/Run/Session/workspace
  identity, status, deadline, capabilities, generation and storage before
  consuming any authoritative root CAS reservation.
- `llm/client.py :: _transport_attempt_scope`: composes the hard budget
  check **before** the existing RG-3C transport observation context and
  before `httpx.Client.stream`. All four existing wire protocols go
  through this scope; OpenAI-compatible disconnect retry and empty-response
  retry must reserve another physical attempt.
- `tools/registry.py :: execute`: a capability/zero-budget check occurs
  before optional safety/escalation-token prechecks, and an atomic
  reservation/dispatch guard immediately precedes physical execution.
  One permit cannot be consumed twice concurrently. A budget-denied
  tool produces a paired BLOCKED result with its original tool_call_id.
- `core/loop/engine_services/tool_cycle.py`: bound execution filters
  model-visible tool schemas while the Registry remains the final deny
  authority; no-budget runs keep legacy projection.
- Bound executions **always** deny `schedule`, `schedule_cancel`,
  `execute_command` and `spawn_subagent` until the I4 child-lifecycle
  budget inheritance/worker termination contract is implemented, even
  if an allowlist mistakenly names one of them.

The feature is **inert by default**: no production entrypoint, service
config, factory, scheduler, Web UI, Feishu or Learning process calls
`bind_task_budget`. There is no automatic budget authority issuance.
This isolation is intentional; a public endpoint must never accept a
model-authored or user-text budget grant.

## Offline evidence and semantics

The real `LLMClient.chat` and `ToolRegistry.execute/execute_many` are
exercised through mocked `httpx.Client.stream` and fixture tools.
Assertions measure the number of *physical HTTP mock sends* and *actual
tool.execute calls*, rather than the error message alone.

| Case | Expected result |
| --- | --- |
| Unbound Provider request | Identical legacy provider protocol and one send |
| Bound one-physical-attempt budget | Second request rejected before HTTP send; first reservation stays charged |
| Empty response/internal retry | The hidden retry is blocked before second physical HTTP send |
| Connection failure/internal retry | The hidden retry is blocked; first attempt remains an unknown liability |
| Zero physical attempt profile | OpenAI, Anthropic, Google and LMS each reject before network send |
| Root stop/deadline | New physical sends refused; no fake transport termination ACK |
| Explicit zero tool allowlist | schedule and execute_command cause zero physical tool execution |
| One allowed read tool, second call | First succeeds, second returns BLOCKED, original tool_call_id retained |
| Two concurrent readonly tools, one permit | Exactly one executes; one is BLOCKED |
| Schedule allow_wake=true | Still BLOCKED until future durable wake adapter is qualified |
| Model tool projection | Bound zero-budget returns [] and unbound returns original schemas |
| Run/session mismatch | Mismatched owner cannot borrow bound root quota |
| Tool timeout | Reservation remains UNKNOWN; no physical closure claim |

R9 static ratchets, security scan, full-tree CI and parent/production
identity are mandatory before considering any merge.

## What is **not** implemented or qualified

1. No production issuer/signed human task binding, explicit allowlist,
   start-of-Run Scope bootstrap or **automatic attachment** of the budget.
   The in-process context may be used by offline unit code only.
2. No budget reservation of actual logical call or model round;
   `TaskBudgetLimits.logical_calls/rounds` are persisted but **not
   enforced** by I2. Physical transport attempts are the enforced
   dimension here.
3. No exact actual provider request byte count, exact GLM-5.3 tokenizer
   binding, reasoning/output token bound or RMB account billing/cost cap.
4. No provider-ACK or RG-3C mapped settlement for real token usage.
   Provider reservations remain UNKNOWN even on a successful mocked
   HTTP response. Do not confuse an observed successful answer with
   confirmed billing/quiescence.
5. No server-wide wall clock cancellation, process-group reap,
   detached Job or schedule_wake inheritance; cancellation **only revokes
   future admission**. Running external tasks remain unverified.
6. No per-account/provider/global concurrency/rate budget: the store
   controls one bound root, not GLM account quota.
7. The current CAS retry bound and snapshots are for low-volume
   isolated work; neither runtime memory nor lexical tool names can
   be treated as a verified cross-process signer.

**Deployment ruling:** The code is eligible for a later default-off
compatibility deployment *only after the full R9 gate*, but **not** for
turning on live Web Budget Enforcement. To reach active production
eligibility, first implement a trusted Web issuer, explicit task
root/Run/schedule grant lineage, complete logical/round/wall admission,
non-bypassable worker cancellation, and provider physical usage
reconciliation. Keep Canary HOLD and GLM live pressure tests prohibited
until those conditions are independently verified.
