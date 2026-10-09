# Knowledge consumption Canary preparation — 2026-10-09

## Scope and authority

The original isolated patch is 4d1dc3849, based on 4b9ff14e0. The integrated
candidate is based on main 74ea92522 and excludes its already-fixed TaskBudget
test style change. The six behavior files applied without conflict; new main's
test environment isolation is retained. The managed Web restart receipt for
gen217 at 74ea92522 is succeeded/confirmed_ok (2026-10-09 23:26 +08:00).
No main merge, remote push, publish, restart, production configuration change
or real model call is authorized by this preparation.
The v3 EFFICACY_NOT_QUALIFIED result remains authoritative for that experiment.

## Receipt contracts

| Stage | Evidence | Meaning |
| --- | --- | --- |
| Discovery | knowledge.discovery with snapshot_fp | Historical candidate found; applicability undecided |
| Preparation | knowledge.reference_prepared | Bounded appendix prepared, not sent |
| Final HTTP input | provider.transport.opened.prepared.knowledge_references | Exact run-prepared appendix appears at the tail of user content in final OpenAI JSON |
| Acceptance/settlement | Same call_id/attempt_id settlement with HTTP response facts | Check actual status/outcome; opened/prepared alone proves no delivery |
| Hydration | knowledge.hydration_observed with paired exact-ref search receipt | Record returned; zero-hit SUCCESS excluded |
| Method judgment | knowledge.method_declaration plus actual method_manage receipt | Model-declared decision, not independent benefit |
| Experience/Lesson judgment | knowledge.experience_declaration plus refine_experience receipt | Model-declared decision, source snapshot and verification preserved |
| Runtime outcome | knowledge.run_outcome | End reason, incomplete status, rounds, time and tokens; completed is not task PASS |

The callback is request-scoped, observes the exact final OpenAI JSON at the
existing pre-send transport boundary, and carries facts through the existing
journal. No new store, executor, request, retry or budget issuer is added.
Join transport settlement before claiming Provider acceptance. Model attention
is not observable. Other wire representations and recovery/fallback calls
without this callback remain unobserved; no compatibility claim is made.

refine_experience(action=record_use) accepts a stable experience ref,
use_decision=applied/adapted/not_applicable/rejected and optional bounded
note/evidence_refs. The existing document is read, and an experience-use/v1
JSON receipt is persisted through normal tool history. Original card bytes,
status and verification state are not changed. No Lesson promotion or benefit
verdict is automatic. document_projection_sha256 identifies the full parsed
document projection, not the original file bytes.

Run finalization observes terminal paired tool receipts even without another
provider round. Run-local de-duplication is retained. Event write failure
cannot establish a positive receipt or alter task execution.
The regression also exposed the existing hydration parser missing the actual
ToolResult status prefix. Only the matching status prefix is removed; exact-ref
and body checks remain, and zero-hit SUCCESS is still excluded.

## Validation and next deployment gate

The focused/adjacent matrix passed 97 tests on the integrated candidate, including real LoopEngine with
Fake Provider and captured LLMClient HTTP JSON through httpx.MockTransport.
These checks use no real endpoint. Official R9 isolated candidate gates,
static ratchets and security scans remain mandatory before any integration.
Their terminal receipts, not this document, establish release eligibility.

The separately authorized Web Canary should:
1. Reconcile this isolated patch against then-current main and repeat final
   gates on the actual integrated candidate.
2. Bind one dedicated Web session, authenticated ingress, release SHA and
   glm/glm-5.3. Resolve the weakest supported model from the current registry
   before creating its distinct comparison rows. Keep Feishu/Learning OFF.
3. Present exact launcher configuration, session allowlist and bounded paid
   call/token/time quotas for owner approval before mutation or calls.
   Reuse service_control and existing TaskBudget authority.
4. Freeze fresh unused tasks, independent correctness checks, knowledge refs,
   currentness evidence, side-effect scope and stop conditions before measured
   calls. Do not reuse consumed v3 holdouts.
5. Measure opportunities, discovered candidates, successful transport exposure,
   hydration, judgments and independently scored outcomes separately; compare
   FCR, errors/retries, correctness, elapsed time, whole-run wire tokens and
   reported usage/cost. Missing evidence remains missing.
6. Stop on unauthorized effects, source authority spoofing, incorrect pairing
   or replay, silent promotion or adverse correctness/cost evidence; revert
   advisor to shadow/OFF through the same configuration authority.

Small Canary results prove feasibility only. Promotion needs a new
preregistered effectiveness gate. Failure must preserve learning evidence.
TaskBudget production acceptance is not reopened, and increasing card count
is not a success criterion.

## Concrete single-session rollout draft (not activated)

Current effective Web advisor is shadow from dotenv, with no advisor allowlist.
Feishu and Learning resolve to off with an empty allowlist. The current Web
TaskBudget pointer is a separate admin-once configuration from 21:39; its
validity window has expired. Do not reuse its authorization or erase its ledger.

Proposed dedicated session ID: a8d9c417-32ab-41c0-a79b-04a6a55a0ee8.
This is a planned ID, not an existing production session. After approval,
create/confirm it through the existing SessionStore and freeze its model to
glm/glm-5.3 before issuing a new admin-once plan. If SessionStore allocates a
different ID, substitute that exact ID in both configurations and repeat the
read-only resolver check before activation. No wildcard or second session is
authorized by this draft.

The advisor delta belongs in the operational runtime.toml, not the source
checkout's .env. Preserve all existing unrelated sections:

```toml
[knowledge_advisor.web]
mode = "canary"
sessions = "a8d9c417-32ab-41c0-a79b-04a6a55a0ee8"
```

Use the effective runtime root and reject a conflicting CLI/shell override.
The read-only check must show both Web keys sourced from
runtime_toml_service:web, and both non-Web services still off/empty. Default
KnowledgeAdvisor bounds remain three candidate cards and 1,050 appendix
characters per discovery, at task start and at most one confirmed first-failure
frontier. References are transient and candidate status remains unchanged.

The first paid stage that the existing authority can support is exposure only:

| Item | Exact supported boundary |
| --- | --- |
| Human ingress | First durable event in that one Web session; immutable event/Run binding |
| Model | glm/glm-5.3 only |
| Physical Provider attempts | 1 total, including retries; no automatic reissue |
| Tool invocations | 0; allowed_tools is empty |
| Run grant deadline | min(issue time + 30 seconds, config expiration) |
| Admin config window | New authorization, approved start time T through T + 600 seconds |
| Wake/subagents | Denied |
| Token/fee ceiling | Not qualified; report observed usage, do not label max_tokens a billing cap |

The new operator JSON must use web-task-budget-admin-once/v1, a fresh 32-hex
authorization_id, the same exact session_id, the existing engine workspace_root,
model_ref glm/glm-5.3, and the approved T/T+600 validity window. Install it as an
owner-only regular file through the existing operator path and change only
web.task_budget_canary_config to that file. No proxy is proposed. These values
are created only after approval; this preparation does not sign or activate a
grant. Existing TaskBudget policy/profile/issuer code remains unchanged.

For that stage, freeze one fresh, low-risk, read-only diagnostic prompt with a
known relevant historical record. Success requires discovery, exact final-wire
reference facts, matching opened/settled call_id/attempt_id with a successful
HTTP response, no tools, and a terminal outcome. No hints/no transport facts/
an uncertain or unsuccessful settlement is not a positive exposure result.
Do not retry a failed or empty sample without a new explicit authorization.

This stage cannot prove hydration, judgment, adoption, or task improvement:
the approved one-attempt profile also denies every knowledge tool. Full
consumption needs a separately approved multi-decision/tool-capable allowance
using the existing budget machinery. That allowance is not expressible by the
current admin-once JSON schema. Do not silently bypass it by using an unbudgeted
session, repeatedly reissuing one-attempt plans, or editing the fixed production
profile. No efficacy comparison or weakest-model calls are included in this
one-attempt proposal. Freeze their fresh tasks and separate quotas before that
later stage.

After code integration, publish/restart only through existing service_control
and verify actual generation/SHA before enabling this delta. Snapshot the
prior operational configuration bytes. Stop after this one exposure sample;
restore advisor to shadow with sessions empty and restore the previous
TaskBudget pointer through the same configuration authority. Verify effective
settings and runtime identity after rollback. Do not delete receipts/ledgers.
