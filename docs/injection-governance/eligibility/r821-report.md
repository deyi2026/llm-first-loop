# R8.21 — Provider-Bound Historical Reasoning Replay

Status: **PASS**
Date: 2026-08-31
Surface: E05 `historical_reasoning_content`

## Decision

Historical reasoning is not ordinary task context. It remains provider-visible only when the actual provider protocol for the current request attempt requires those bytes. Resolved/consumed history is retired before this protocol projection, and private reasoning is never duplicated into EpisodeStore retrieval.

The policy is bound to the actual provider selected for each request attempt, not to the process-wide default `llm_base_url`.

## Provider policy

- local / cognilocal endpoints: replay no historical reasoning;
- MiniMax with `thinking=false`: replay no historical reasoning;
- GLM / BigModel interleaved tool protocol: replay reasoning only on assistant tool-call turns;
- official DeepSeek tools requests: retain all still-visible assistant reasoning required by the provider protocol;
- unknown providers: retain the configured fail-safe policy rather than guessing capability.

This is a protocol minimum, not a model-quality heuristic.

## Root cause

The former `_reasoning_tail_for(settings)` derived one replay policy from the global default endpoint. A session model override or provider switch could therefore apply the wrong reasoning policy to the actual routed provider.

A second cross-provider defect existed in fallback: the fallback chain reused the primary provider's already-projected message list. That could send a GLM-minimized history to DeepSeek, where required reasoning bytes may be missing, or leak DeepSeek reasoning into a provider that does not require it.

R8.21 makes both the primary build and each fallback candidate use the candidate provider registry snapshot and rebuild the provider-specific message view.

## Real-data effect

After R8.20 consumed-tool retirement, the current session corpus still contained:

- 3,167 messages carrying historical reasoning;
- 6,356,327 reasoning characters total;
- 4,679,101 chars on assistant tool-call turns;
- 1,677,226 chars on ordinary non-tool assistant turns.

Under current provider configuration:

- local / cognilocal and MiniMax-M3 with `thinking=false` can remove **100% / 6,356,327 chars** from their provider view;
- GLM can remove the non-tool reasoning portion, **1,677,226 chars / 26.39%**, while retaining tool-call reasoning required for interleaved tool protocol;
- DeepSeek retains still-visible reasoning as protocol bytes when tools are supplied.

## Fallback isolation

Cross-provider fallback now accepts a candidate-specific request builder. The engine rebuilds messages and tool schemas for each fallback candidate from session truth using that candidate's immutable registry snapshot. Tests prove a GLM primary projection does not constrain a DeepSeek fallback projection.

## Verification

Implementation commit: `423614e` (`fix(injection): bind reasoning replay to provider`).

Detached clean fixed-point:

- reasoning/history/tool-pair/cache/1210/model-pool/factory/fallback/eligibility/resolved/consumed/core-loop broader suite: **290/290 PASS**;
- changed pyright: **0 errors / 0 warnings**;
- py_compile: **PASS**;
- canonical R0-1 through R0-4: **PASS**;
- checkout clean before and after.

## Matrix result

E05 `PARTIAL -> DONE`. Matrix becomes **DONE=32 / KEEP=1 / PARTIAL=1 / OPEN=0**. Only E06 durable effective constraints/decisions remains PARTIAL. Behavior canary / R9 remain not started.
