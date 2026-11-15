# LFL context_capacity_unavailable: root-cause repair design (2026-11-15)

Status: isolated candidate, NOT production-approved. Baseline: Mac Web gen416 SHA `3eb4bf8fa8f4ecdb03e1f644f5f53156b13e67b9`.

## Verified failure families

1. Session `43f1a49b-8500-4a12-9ddd-6c067043a5bd`: three Qwen local runs, all HOLD at round 2. Input authority 32,768 tokens; 101 callable tool schemas consume 28,863 authoritative tokens, leaving 3,905 history tokens (3,514 chars). The completed `web_fetch` receipt is 5,141 chars. This is confirmed tool-schema starvation, not missing evidence.
2. Session `1e206631-b5cb-4bb0-8e7d-6be6e9b7bf0d`: MiniMax round 103 HOLD at EventLog seq1921 and incomplete at seq1924; prior request 176,455 / 184,000 input tokens, history budget 410,792 chars, latest receipt 250 chars. Offline original 225-message/production-policy rebuild preserves latest group at 408,470 / 410,792 chars. **Actual in-process rejection stage is unknown** because no budget/rebuild/preflight diagnostics were recorded. Subsequent Run completed 77 rounds; this does not repair the earlier Run.

## Hard invariants

- Final Provider request includes exact current-run ingress and latest complete assistant/tool group, or owner/version/hydration-verified readable EvidenceRef. Never fake summaries or refs; no raw tool re-execution for recovery.
- Preserve every healthy, authorized callable tool name and its order; no keyword/LLM-driven tool selection, permission expansion, TaskBudget bypass or altered execution-time argument validation.
- Emergency index representation is allowed only when `get_tool_schema` remains callable. It is a discovery-first degraded parameter *representation*, not a hidden tool or a permission change.
- Physical non-fit, invalid pairing, owner mismatch, missing evidence and unsafe preflight remain fail-closed with `run_incomplete=true`. Never claim completion or auto-switch models.
- Isolated stage cannot modify main, production, other sessions or their locks.

## Minimum viable repair

A. **Capacity-aware tool schema admission.** After runtime-health/TaskBudget eligibility and before history projection, use the same model input token authority and tool-schema counter (authoritative tokenizer preferred; existing conservative chars/token fallback). If tool schemas consume more than half of allowed input tokens, try whole-surface `ToolRegistry.index_schemas(desc_chars=80,48,0)` in that order. Pick first tier under the schema-share target; if none fits, choose smallest only when it saves budget. The tool names/order must be identical; `get_tool_schema` must be callable. Recompute the actual budget and cache/tool fingerprint from the representation sent, not the original. No unbounded retries or tool execution in this step.

B. **Convergence diagnostics.** Preserve current view -> durable conservative rebuild -> owner-verified exact-ref qualification. On HOLD record only non-secret stage facts: active ingress present, latest group valid, raw visibility, raw projected chars, effective history budget, model-limit authority, rebuild state/retired count, preflight hard overflow and reason (`raw_not_visible`, `rebuild_invalid`, `raw_over_budget`, `preflight_overflow`, `ref_not_qualified`). Keep public `context_capacity_unavailable` until UI consumers migrate. Never log tool arguments, contents, credentials or ref bodies.

C. **Safe incomplete recovery.** If smallest admissible request still cannot fit, preserve incomplete Run and evidence for an explicitly controlled continuation; do not auto-replay side effects. The UI should eventually distinguish true physical non-fit from projection/authorization uncertainty.

## Acceptance

- 32K / 101 tools: first round reserves usable history; after 5,141-char recorded result, second Provider request includes exact raw paired receipt or qualified ref without re-executing source tool.
- 184K/1M MiniMax: no unnecessary index mode; original 225-message snapshot conservatively rebuilds and preserves latest raw group. **Do not claim original in-process fault explained without new branch telemetry.**
- Negative: no callable get_tool_schema, missing/unauthorized tools, TaskBudget/runtime health filtering, invalid pair, cross-owner/stale evidence, actual minimum non-fit, hard preflight overflow, privacy leak -> no unsafe Provider send.
- Same callable names/order and execution-time validation; cache fingerprint and budget reflect actual schema. Focused tests, Ruff/Pyright, independent GLM-5.3 PASS P0/P1=0, original full R9 exit0, remote CI and separate managed release authorization before live switch.
