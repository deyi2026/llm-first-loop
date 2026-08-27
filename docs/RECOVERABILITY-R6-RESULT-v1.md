# Evidence Recoverability R6 — Source vs Recovery Contract Result v1

Date: 2026-08-26
Status: **OFFLINE PASS / SEALED**
A3: **STOPPED**
Production Evidence activation: **unchanged**

## Purpose

R5 isolated one remaining program-level inefficiency: after a full current `read_file` acquisition plus durable Evidence, DeepSeek emitted `search_evidence(...)` and an overlapping `read_file(offset=...,limit=...)` in the same next tool batch. The source tool description simultaneously advertised Evidence recovery and generic segmented source reads. R6 removes that model-facing semantic conflict without adding Action Guard or runtime duplicate suppression.

## Frozen contract

A shared static contract now defines source acquisition versus Evidence recovery:

- source call = new acquisition;
- existing Evidence with sufficient coverage and suitable currentness = recover existing observation;
- currentness/freshness required = legitimately reacquire source;
- coverage gap = acquire only the genuinely uncovered source range;
- EvidenceRef = control-plane handle, never domain content.

Source-specific rules are attached to `read_file`, `execute_command`, `web_fetch`, and `web_search` from one central module.

## TDD evidence

Initial RED:

- `tests/unit/test_source_recovery_contract.py` failed at collection with `ModuleNotFoundError: llm_loop.tools.source_recovery_contract`.

Minimal implementation then produced:

- R6 contract tests: **4/4 PASS**;
- surrounding Evidence/tool focused tests: **PASS**;
- targeted Ruff: **PASS**;
- targeted Pyright: **0 errors / 0 warnings**;
- all Evidence tests plus R6 contract: **PASS**;
- R0 aggregate: **12/12 PASS**;
- full repository regression, excluding only the already-stopped A3 development test: **EXIT 0 / 100% PASS**.

The full-repo run emitted only existing dependency deprecation warnings and the existing non-blocking test-side-effect audit warnings.

## Change boundary

Production behavior was not changed:

- no source call is blocked or rewritten;
- no duplicate-call detector was added;
- no freshness logic changed;
- no Evidence capture/hydration identity changed;
- no prompt-level anti-repeat instruction was added;
- A3 remains stopped.

R6 changes only model-facing tool description/schema semantics plus their shared constant module and tests.

## Prefix/cache impact

The shared contract is 280 characters and appears in four static source-tool descriptions (1,120 repeated characters), plus source-specific static guidance. This increases the stable tools prefix baseline but does not introduce per-round structural variation. It is therefore a fixed cacheable prefix cost, not a source of prompt drift. R7 will measure whether the extra static prefix buys lower redundant source acquisition in fresh provider behavior.

## Next gate

Run a fresh, pre-registered MiniMax + DeepSeek efficiency holdout with unseen fixtures. Primary efficiency gates must use exact same source+canonical-args repeats and redundant overlapping covered ranges, not raw source-call count. Freshness refresh and genuinely uncovered non-overlapping ranges remain legitimate acquisitions.
