# Execution Knowledge Loop v1 — bounded retrieval, use and feedback (2026-10-08)

## 1. Purpose and authority boundary

Method and Experience, including not-yet-qualified candidates, need to be
retrievable and *usable during real work*. An error can contribute to later
diagnosis without permanently banning candidate exploration. The prior v3
EFFICACY_NOT_QUALIFIED conclusion remains authoritative for **independent task
benefit**. It is neither a usage ban nor proof that exploration is effective.

This is a thin, opt-in vertical loop, not a new plugin/knowledge store/permission
layer/provider wrapper/tool executor or synchronous Learning worker. No production
change is authorized by the local code implementation.

## 2. Source-of-truth contracts

- Discovery: existing RecordSearcher with separate method / experience / lesson
  kinds; never a single kind=all pool that can starve later categories.
- Eligibility: candidate/qualified/active Methods can be offered as historical
  references. Hold/invalidated/retired are never automatic recommendations.
- Historical labels: record_kind, verification_state, status and freshness are
  evidence signals; legacy_unclassified is not silently upgraded to verified.
- Prompt: only a not-yet-sent next provider decision may receive a transient
  InjectionLayer.REFERENCE appendix. No Session history mutation, tool execution,
  user-origin message or system authorization is created.
- Learning: existing save_experience and MethodStore APIs only; model may try,
  adapt, skip, and save hypotheses as unverified Lesson. No automatic creation
  of Lesson/Experience/Method or automatic qualification or promotion.
- Outcomes: actual assistant tool declaration ID must pair with a settled
  tool message. Tool success and self-declared applied are **not** independent
  evidence of task improvement or recovery.

## 3. Rollout and strict conditions

ToolRuntimeSettings.knowledge_advisor_mode reads the independent
LFL_KNOWLEDGE_ADVISOR=off|shadow|canary configuration; default **off**.
LFL_KNOWLEDGE_ADVISOR_SESSIONS is an exact comma-delimited Web session allowlist.

- Off makes zero knowledge queries, event writes or prompt changes.
- Shadow performs bounded retrieval and emits discovery facts only, with zero
  provider-visible reference bytes.
- Canary requires ALL: explicit canary mode, valid non-delegated current Web
  IngressToken, exact token/session binding, matching human-origin metadata,
  exact allowlisted session ID, low-risk task, sufficient prompt budget.
  Historical metadata alone cannot authorize canary use. CLI, Feishu and
  delegated continuations remain observation-only.

The retrieval starts before the first provider decision, or once after the
first verified recoverable tool failure at the NEXT provider decision. The
discovery gives a bounded three-kind summary (per-kind up to 4; total up to 3;
body approximately 1050 chars plus reference framing) with stable refs and
historical qualification. Full original Method/Experience is never auto-hydrated;
the model can request an exact stable ref via the normal tool.

Command-shaped historical prose is withheld by the existing reference
neutralizer. The original ToolRegistry, safety, approval, WAL, receipts,
settlement, provider structure and overflow limits remain authoritative.
Embedding retrieval might incur real provider latency/API cost; no unmeasured
zero-cost claim is made.

## 4. Receipt ledger and retry

Telemetry uses the existing EventStore; **no new append-only database**.
All events carry deterministic knowledge_event_key and run_ref. The event
stream is not claimed to be exactly once; consumers deduplicate by
(run_ref,knowledge_event_key,event_type). Run-local call IDs prevent duplicate
observation of the same persisted tool receipt.

| Event | Meaning (and explicit non-claim) |
| --- | --- |
| knowledge.discovery | Candidate refs and diagnostics; task applicability not evaluated |
| knowledge.reference_prepared | Reference rendered; actual provider delivery not confirmed |
| knowledge.hydration_observed | Model invoked exact search ref; not proven applied |
| knowledge.method_declaration | Model-authored record_use; task benefit not evaluated |
| knowledge.failure_observed | Actual paired failure; root cause not evaluated |
| knowledge.followup_tool_observed | Later tool completion; recovery NOT proven |
| knowledge.learning_saved | Exact stable Experience ref and confirmed-create receipt |
| knowledge.learning_unconfirmed | Conflict, uncertain or malformed save result is NOT saved |

An adjacent wrapper bug is fixed with the feedback change: the original
registry_experience wrapper classified every text beginning with
[save_experience] as success even for FileExists conflict and commit uncertainty.
Only an exact positive create receipt is now SUCCESS; refine_experience likewise
requires the actual confirmed status-transition text. Typed errors stay errors.

No tool outcome is automatically re-executed after a reference is shown.
An incomplete read or uncertain write must be reconciled from exact store
evidence before any retry.

## 5. Failure and improvement contract

An observed failure is evidence for investigation, not a root cause. If the
model concludes a candidate was wrong or an environment assumption broke,
it can first recover by normal safe tools and then save an unverified Lesson
with evidence and currentness verification steps. Only independently tested,
evidence-backed positive results may become a verified Experience through
the existing tool policy. A future task may retrieve both kinds and reconsider
their applicability. Proposed Method revisions retain parent ref; qualification
or automatic promotion is not part of this batch.

The minimal disposable end-to-end test must demonstrate a failed paired tool
receipt, a valid unverified Lesson save via the real ExperienceStore, then
retrieval of that Lesson from a **new run**; it must not assert benefit without
an independent task evaluator.

## 6. Release gates and future experiments

Before any main merge, preserve off=zero behavior; forbid historical
reference authority/ingress spoofing/cross-session effects; verify failure
dedup, tool pairing, unconfirmed save semantics, no unapproved effects,
Ruff/Pyright ratchets, architecture and full official R9 CI.

Stop rollout on unauthorized tool activity, new user-origin spoofing, factual
source leakage, incorrect replay, unverified content silently promoted to
verified, or adverse weak-model/whole-run wire cost outcomes.

Then freeze a NEW task comparison (do not reuse consumed v3 holdouts) using
GLM-5.3 and the weakest supported model. Measure opportunity→discovery→
exposure→hydration→declared use→independent task outcome, FCR, errors/retries,
total wire tokens, cost and unexpected side effects. Failing the experiment
stops PROMOTION but must not erase the learning evidence.

This batch needs separate owner authorization for main FF and later Web-only
Canary; no production publish, restart, remote push, or Feishu/Learning enablement.

## 7. Predeployment hardening (2026-10-09)

Release readiness must be assessed against the real next-provider input,
not only against a mocked KnowledgeAdvisor return string.

1. **GLM-1210 tail structure:** a separate program-reference user message
   immediately following the genuine user message produces consecutive tail
   users, a known provider rejection shape. The isolated predeployment change
   uses copy-on-write to join a lower-authority, explicitly labeled REFERENCE
   appendix to the last user projection if it is already a user. The first
   bytes of that user's content, its exact active ingress marker and the
   persisted Session/EventStore message are not overwritten. If the projection
   currently ends in a tool/assistant, one program-labeled user reference can
   be appended after the complete tool-result pair. No extra provider call,
   tool invocation, or retry is performed.
2. **Run identity:** Session ID and persisted turn offset do not uniquely
   identify a re-admitted execution of that same turn. Bind the run-local
   observation ledger to the existing current_run_generation when present;
   a different run may not inherit a previous failure latch or discovery set.
3. **Hydration truth:** search_records may return SUCCESS with zero hits or
   degraded evidence. Exact query plus SUCCESS is not proof that the named
   record was hydrated. Require a matching rendered complete Method/Experience
   record in the paired actual tool receipt before writing a hydration event.
   Model-declared use remains separate from verified impact.
4. **Regression:** use real LoopEngine and offline Fake Provider to confirm
   bounded reference insertion; an actual failed read_file followed by recovery
   at the next provider decision; unchanged tool-call identities, no extra
   program-initiated effects, and no reference persisted into Session history.
   Enforce mechanical provider-structure checks, default OFF and Web identity
   negative controls.

Predeployment exit requires official R9 synthetic full CI terminal receipt,
security scan, postcommit gates, a clean main-line fast-forward after
user-authorized integration and no live deployment changes. Local green
proves eligibility for a gen205 deployment with advisor OFF; it does NOT
prove live GLM-5.3 compatibility, shadow retrieval cost or Canary task efficacy.
Web-only shadow/Canary activation is a separate identity-bound change requiring
explicit authorization, actual provider smoke and frozen effectiveness tests.

## 8. Web-only Shadow configuration authority (2026-10-09)

The gen205 application understands LFL_KNOWLEDGE_ADVISOR, but its
runtime.launch resolver omitted that key from the closed RuntimeConfig
schema. Editing .env therefore did not reliably set the process's
ToolRuntimeSettings; adding an unknown runtime.toml section could fail
launch before the Web process started. This is a source-binding defect,
not proof that KnowledgeAdvisor discovery was ineffective.

The next isolated candidate registers only:

- LFL_KNOWLEDGE_ADVISOR = off | shadow | canary, default off.
- LFL_KNOWLEDGE_ADVISOR_SESSIONS = exact Web-only session allowlist
  (empty by default).

The authoritative TOML spelling is the service-scoped
[knowledge_advisor.web] with mode = "shadow" (and optional sessions).
A global [knowledge_advisor] activation, or
[knowledge_advisor.feishu]/[knowledge_advisor.learning], is rejected
before service restart. Feishu/Learning always receive off and an empty
allowlist, including when .env, shell override or
LFL_ALLOW_RUNTIME_OVERRIDE=1 supplies a different value. The output
provenance explicitly records a disabled service scope. Session allowlist
IDs are masked in resolver dry-run summaries.

**Mixed-version deployment:** do not append [knowledge_advisor.web] to the
shared production runtime.toml while Feishu/Learning run older resolvers.
Older releases parse every TOML key and may fail on a later independent
restart, even if the new key targets Web only.

The safer separately authorized sequence is:

1. Qualify and publish this schema patch in a new immutable release with
   Knowledge Advisor OFF by default.
2. In a separately authorized Web-only Shadow activation, use the canonical
   runtime-root .env key LFL_KNOWLEDGE_ADVISOR=shadow, leaving sessions
   empty. The new resolver projects this for Web only; old Feishu/Learning
   code keeps its existing behavior. Validate resolved Settings and
   provenance at the actual launcher, not simply the file contents.
3. Restart Web only through service_control, respecting real run-idle
   locks. Verify the exact restart receipt, PID, immutable SHA, effective
   Shadow mode, and knowledge-store health.
4. Exercise low-risk tasks to check the real per-kind Method/Experience/
   Lesson discovery events, zero knowledge reference in provider input,
   no automatic application, bounded search latency and no unexpected
   provider call.
5. On errors, latency regression or observation leakage, revert to OFF
   using the same authoritative configuration path. Canary still requires
   independent human authorization and controlled effectiveness evidence.

The initial read-only real-store probe found 693 Method cards and 343
Experience files. Independent lexical searches found Method, positive
Experience and Lesson records. A KnowledgeRun Shadow query returned two
candidate references and one observation event with zero provider-reference
bytes. No model/provider call, execution tool or knowledge write occurred.
This verifies the discovery path, not GLM-5.3 task-benefit efficacy.
