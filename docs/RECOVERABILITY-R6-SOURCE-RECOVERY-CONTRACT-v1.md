# Evidence Recoverability R6 — Source vs Recovery Contract v1

Date: 2026-08-26
Status: TDD contract frozen before production edit
A3: STOPPED
Production Evidence activation: unchanged

## Root cause carried from R5

R5 proved recoverability/currentness correctness but exposed one redundant overlapping source read. The model-facing source tools currently mix two competing actions: recover an already-acquired Evidence observation, or reacquire the original source. This document freezes the semantic boundary before editing tool descriptions.

## Shared contract

In Evidence enforce mode, a source-tool call means a **new acquisition** of source state. Recovery tools mean **reuse of an already-acquired observation**.

Decision is based on evidence state, not an anti-repeat prohibition:

1. **Covered + suitable currentness** — when an existing Evidence observation covers the needed content/result and its currentness is suitable for the task, use `list_evidence` / `search_evidence` / `read_evidence` to recover it. `EvidenceRef` is a control-plane handle, never the domain answer itself.
2. **Freshness/currentness required** — when the task asks for current source state and existing Evidence is stale/unknown where currentness matters, reacquire the source. A freshness refresh is legitimate new acquisition.
3. **Coverage gap** — when existing Evidence does not cover the needed source range/result, acquire only the genuinely uncovered source range when the tool supports ranges.

This is not Action Guard, duplicate suppression, or a ban on repeated calls. Truthful source acquisition remains available whenever currentness or coverage requires it.

## Source-specific semantics

- `read_file`: probeable file Evidence may satisfy covered bytes when verified current; stale/current requests require source refresh; non-overlapping uncovered ranges are legitimate source reads.
- `execute_command`: prior command Evidence is a historical execution snapshot. Recover it when the task needs the prior observation; execute again only when the task requires a new execution/current runtime state.
- `web_fetch`: prior page Evidence is a historical/previously acquired observation. Recover it when that is what is needed; fetch again for current remote state or uncovered remote content.
- `web_search`: prior search Evidence is a historical result set. Recover it for the prior result set; search again when current external results are required.

## Acceptance

All four source-tool model-facing descriptions must include the same shared contract and their source-specific currentness rule. No wording may say or imply `never reread`, `do not repeat`, `禁止重读`, or equivalent unconditional suppression.
