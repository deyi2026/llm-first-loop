# docs/ai_rules.lite.md — Agent/maintenance playbook (version=12; current-task authority + agency-first, owner-approved 2026-09-04)

> **Role (R8.24-A A-D2)**: reclassified from "universal model execution rules" to an
> **Agent/maintenance playbook** — read on demand by maintenance runs and operators;
> ordinary user runs reference it zero times and inject it into no prompt
> (standing assertion: tests/unit/test_model_contract_slimming.py).
> Full SoT: docs/ai_rules.md (superset; R8.24-A migration pointers in its trailing section).
> v7→v8 per-item disposition: .codeartsdoer/specs/r824_ab/lite-v7-v8-diff.md.

## Key constraints (v12 retained set)
1Honesty: verify against this round's tool receipts; never fabricate completion.
2Parameter autonomy: check params before tool calls; correct and retry after guidance.
3Stagnation: adjust or answer when repeating/no progress; success receipt = confirmation, no re-verify; research unknown commands, no trial-and-error; external wait → one status line then stop.
6Evolution: submit_evolution; self_evaluate when needed; accepted evolutions execute per permission & register; boundary items human-only. **Approval semantics / agency-first**: accepted confirms the problem/goal, not every proposed implementation detail. Tool/round limits, automatic completion/closure, automatic injection/replay and similar constraints must prove necessity and minimum scope; otherwise prefer not adding or removing them. Safety/ownership, tool-protocol integrity, data integrity, and real resource/side-effect boundaries may remain hard constraints when backed by concrete risk evidence, but must not expand into task strategy, quality, or completion decisions. Machine-readable Schema is the parameter-constraint truth; pure observability/self_eval stays lightweight and explicitly hydrated, never auto-injected or promoted to a blocker without independent evidence. Approval channel priority (mandatory): all human-approval items go through the **own-zone (mirror) Web console** `http://127.0.0.1:8903/ui/v2/` (Evolution panel) first; **approvals stay on their own zone, never cross-zone** (user decision 2026-09-03: mirror approvals go through mirror panel 8903, not main zone 8902); CLI and Feishu text commands are fallback only.
7Tool-first: if info exists only in tool results, fetch it first; never fabricate from priors.
12Identity: model identity follows model_catalog/architecture_status receipts, never priors.
23Current task/authority: the latest genuine user instruction is the task-authority truth. Short replies such as “continue/ok/yes/do that” bind only to the nearest relevant interaction; they do not reactivate older tasks. If that interaction explicitly requires a choice, missing parameter, or permission increase, a generic short reply must not fill the branch/parameter or widen authority; confirmation is valid only when the nearest pending action has one unambiguous meaning. Historical assistant proposals/plans and older task state/records are context only unless the current user explicitly authorizes them.
21Program feedback semantics: assistant text in history carrying the "[程序反馈·非模型回答]" prefix or any of [LLM 调用异常]/[已达轮数上限]/[停滞熔断]/[停滞提醒]/[缓存守卫拦截]/[上下文超限]/[上下文压缩] prefixes is program-injected runtime feedback (source=SYSTEM), **not a model answer or conclusion** — do not restate it, continue it, or cite it as a basis; conclusions must follow actual tool receipts.
  Transitional note (R8.24-A A-D12/A-4.1): migration protection only; deletion condition = both R8.24-B acceptance (B-G5 zero runtime notice in sess.messages) and R8.24-C acceptance (receipt factualization) pass; deletion itself is deferred, not executed this cycle.

## Disaster safety (hard constraint, do not touch)
Destructive commands are hard-blocked; production deploys/artifact releases/force-pushes/environment teardown need human approval.
