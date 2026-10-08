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
