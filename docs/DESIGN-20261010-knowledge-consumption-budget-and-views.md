# Knowledge consumption: bounded Web preparation

## Scope and current evidence

Preparation base: main bb3c090756580bb46d261b49fa6a84afaadf4311.
The read-only startup snapshot on 2026-10-10 shows managed desired gen219 at
that SHA and Web manifest with the same SHA. Web advisor resolves to shadow
from dotenv; Feishu/Learning are off. Operational .env/runtime.toml were
hashed before preparation. No production config change, publish, restart,
paid model request or remote push belongs to this phase.

The existing one-attempt profile cannot establish consumption: it permits
one GLM physical attempt and zero tools. Its policy, defaults, JSON schema,
signature domain and acceptance remain frozen. A separate opt-in fixed
profile reuses AdminOnceEventPlan, durable human EventStore append,
TaskBudgetStore issue_root CAS, existing Run ownership and isolated transport.
It adds no signer, scheduler, executor, store, automatic reissue or Goal.

## New opt-in profile

| Boundary | Value and meaning |
| --- | --- |
| Config schema | web-task-budget-knowledge-consumption/v1, closed fields |
| Profile | web-glm-knowledge-consumption-v1 |
| Model | glm/glm-5.3, OpenAI wire, verified exclusive process |
| Endpoint | Existing qualified HTTPS open.bigmodel.cn /api/ path; no proxy |
| Owner | One existing authenticated Web session, first durable human event, one Run |
| Physical attempts | 4 total, retries and interrupted attempts included |
| Tools | 8 total across serial or parallel tool calls |
| Tool surface | search_records(kind=method/experience/lesson); method_manage/refine_experience(action=record_use) |
| Run authorization deadline | min(issue + 180 seconds, config expiry) |
| Proposed config window | T through T + 600 seconds, fresh authorization_id |
| Replay | Same CAS namespace as old admin-once; changing profile cannot reuse a spent ID |
| Wake/subagent/shell/source mutation | Denied; use declarations never qualify/promote a card |
| Rounds/tokens/fee ceiling | Unqualified; no fabricated hard cap, report actual whole-run usage |

The deadline prevents further dispatch and retains the existing provider
worker termination path. It is not a claim that tool threads or remote
provider billing are quiescent by 180 seconds. Unknown reservations remain
unknown. The transport checks actual final URL/model and requires a durable
dispatched attempt before child creation.

Name-only tool permissions are insufficient because method_manage and
refine_experience also expose source-mutating actions. The pre-dispatch
check therefore examines the actual action for this profile only. Existing
record_use handlers still validate refs and bounded fields. Semantic
applicability, adoption and benefit remain model/independent-rater judgments.
The model can declare not_applicable/rejected or use the existing stop path.
There is no bypass that grants unapproved source mutation or additional quota.

search_records is explicitly restricted to those three kinds. In current
production the memory search branch can call a synchronous LLM query rewriter
in retrieval shadow mode. It is outside this feasibility task and could
consume the same allowance; kind=memory/all/archive is not available here.
Normal sessions and the old deny-all-tools profile preserve their behavior.

## Configuration prepared for review, not installed

Create/confirm one dedicated session only after activation approval; bind its
exact ID and workspace_root in both configurations. The prior planned ID
a8d9c417-32ab-41c0-a79b-04a6a55a0ee8 is not an existing-session claim.
Use the operational configuration root, not the source worktree.

```toml
[knowledge_advisor.web]
mode = "canary"
sessions = "<confirmed-session-id>"

# In the existing [web] section, change only this pointer:
# task_budget_canary_config = "<absolute-owner-only-config-file>"
```

```json
{
  "schema": "web-task-budget-knowledge-consumption/v1",
  "profile": "web-glm-knowledge-consumption-v1",
  "authorization_id": "<fresh-32-hex-id>",
  "session_id": "<confirmed-session-id>",
  "workspace_root": "<actual-engine-workspace-root>",
  "model_ref": "glm/glm-5.3",
  "valid_from_epoch_s": "<approved-T-as-number>",
  "valid_until_epoch_s": "<approved-T-plus-600-as-number>"
}
```

These placeholders are deliberately not an installable grant. No caller may
supply numerical attempts/tool limits, allowed tools, an arbitrary profile
or proxy through this schema. Install through the existing owner-only regular
file path (0600, no symlink/hardlink), after checking the session exists and
BackgroundRunner/EventStore are enabled. Resolve before restart: Web advisor
keys from runtime_toml_service:web, exact one-session allowlist; both other
services off/empty. Preserve all unrelated operational sections and secrets.

First integrate/qualify/publish this distinct code patch with advisor still
shadow if separately approved. Web-only restart uses service_control and
actual generation/SHA convergence; no bare restart or desired JSON editing.
Before live activation, recheck exact code/config binding and candidate
source hashes. Any drift requires explicit reconciliation before paid use.

## One fresh feasibility task, not an efficacy experiment

Frozen prompt and independent oracle live in
tests/fixtures/knowledge_consumption/feasibility-20261010.json.
The prompt diagnoses two new offline preflight receipts. Its facts are
explicitly fixture facts; it requests no actual release or restart. A
successful task answer must distinguish exit zero from positive validation
evidence, recognize the old import binding and avoid a false PASS.

Provider-free typed retrieval with current production stores yielded one
Method and one Experience candidate for the exact prompt. Their stable refs,
original source SHA256 and the discovery projection fingerprints are frozen
in the fixture. This is retrieval feasibility, not evidence that either is
applicable. Zero eligible Lesson hints were observed for the full prompt.
The model may read, adapt or reject these candidates and search a Lesson if
needed. Do not hardwire the expected adoption decision from search rank.

A feasible sequence fits four attempts/eight tools: first decision reads
candidate refs; subsequent decisions assess/apply/skip and append bounded
use declarations; final decision answers the diagnostic task. Retries spend
the same four attempts. No forced reads, forced application, repeated Run or
automatic reissue is permitted to manufacture a positive result.

Record discovery/preparation, final OpenAI JSON reference facts, matching
opened/settled call_id+attempt_id and actual HTTP outcome, paired exact-ref
hydration, paired model judgments and terminal Run facts separately. A use
declaration is not independent benefit; an opened request is not delivery;
completed is not task PASS. Score the answer against the fixture oracle.
Zero hydration/adoption remains zero; an appropriate skip is not a failure.
Wrong pairing, source mutation/promotion, unauthorized tools, extra Run or
quota bypass stops the experiment. Missing usage/cost remains unreported.

After the single Run, restore the previous operational bytes/pointer and
advisor shadow/empty allowlist through the same authority. Verify effective
config, health and runtime identity. Retain all event/usage/CAS receipts.
Do not erase the old authorization or issue a replacement without approval.
The weak-model comparison and fresh independently rated effectiveness matrix
are later, separately bounded stages. Prior v3 EFFICACY_NOT_QUALIFIED stands.

## P1 view designs (prepared, not production implementations)

The scope index is a derived view of existing Method description and
Experience scenario fields; there is no bulk when_to_use migration. Start
with the two frozen refs, not the entire pool. Each entry contains kind/ref,
status/verification, source SHA256, source field/short preview, and explicit
coverage. Group by an explicit caller-selected scope. A bounded scope summary
links to canonical refs; it does not inject every card or silently choose
applicability. Check the hash on expansion; a stale entry falls back to current
canonical hydration and cannot supersede or modify its source. No semantic
search/global injection switch changes in this phase.

The per-session digest is an explicit, session-scoped projection of existing
events and consumption receipts, not an automatic LLM memory producer:

| Field | Authority and limits |
| --- | --- |
| session_id/run_ref, event range/cursor | Exact EventStore owner/sequence |
| facts and use declarations | Event refs and payload hashes; declarations stay model-declared |
| decisions/unverified items | Only recorded statements, no inferred applicability or completion |
| transport/outcome/usage | Joined journal receipts; unknown or incomplete stays explicit |
| readable Markdown plus machine JSON | Same scope, stable ref and currentness; no implicit promotion |

These P1 designs can reuse the frozen feasibility fixture to prototype a small
derived index and digest after P0 code qualification. They are deliberately
independent of the budget patch and not claimed shipped, automatically
injected, portable across Agents or proven beneficial.

## Offline qualification

The RED regression failed on base because AdminOnceEventPlan had no explicit
consumption profile. New tests exercise real ToolRegistry pre-dispatch,
concurrent quota use, durable profile replay denial, exact final transport
reservation/URL checks, real LLMClient with a mocked isolated worker, and Web
startup binding. No public Provider is contacted. Existing one-attempt,
signed-positive, process-stop, Web cutover and consumption-receipt tests form
the adjacent matrix. Final results require the staged synthetic candidate R9
and whole-tree safety terminal receipts; this design is not that receipt.

The first official R9 attempt rejected two Ruff diagnostics already in the
bb3c09075 base: unused BODY and unsorted imports in
tests/unit/test_method_usage_watermark.py (introduced by the usage-ledger
watermark change). Preparation removes that unused import/blank separation;
watermark behavior and assertions remain unchanged. No static baseline or
test exemption is expanded. Its three regressions are included in the final
focused matrix before retrying the official candidate gate.
