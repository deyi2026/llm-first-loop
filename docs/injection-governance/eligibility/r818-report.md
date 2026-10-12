# R8.18 — Session Digest Catalog On-Demand Closure

Status: **PASS**
Date: 2026-08-31
Surface: E09 `session_digest_catalog`

## Decision

SessionDigest remains a deterministic diagnostic/retrieval helper, but its generic catalog no longer has automatic prompt authority. The governing rule is the stricter context-admission boundary: **availability, recency, and catalog relevance are not sufficient reasons to modify working context**. Historical information stays retrievable; it is surfaced only after an explicit task dependency or model/user retrieval action.

## Root cause

Before R8.18, `digest_enabled` allowed the build path to update the digest, render unseen reference frames, persist a synthetic `session_digest_catalog` user message, and append that catalog into the provider tail during the first-K/task-switch policy window. The mechanism bounded volume, but it still assumed that a generic tool-success catalog was useful-now. That assumption conflicts with the clean-context rule and duplicated information already present in current tool results before compaction.

## Changes

- `src/llm_loop/core/loop/build.py`: removes automatic digest catalog generation, persistence, and tail aggregation. `digest_enabled` is now capability/compatibility state only.
- `src/llm_loop/core/prompt_eligibility.py`: removes `digest` from `PROMPT_DYNAMIC_PRODUCER_SLOTS` and centrally denies canonical legacy `injection_kind=session_digest_catalog` frames, including same-turn ones.
- Human-authored text is not filtered merely because it contains `ref=digest:*`; the deny rule depends on canonical program metadata.
- `SessionDigest.render()` / `render_reference_frames()` remain available as deterministic diagnostic helpers; no storage capability is deleted.

## Retrieval and information preservation

Current tool results remain ordinary protocol-visible tool results when they are part of the active unresolved task. After compaction, historical originals remain recoverable through ArchiveStore / `search_archive`; digest references stay usable as retrieval identity rather than automatic working-context content. Legacy stored catalog messages remain untouched in storage/event truth and are filtered only at provider projection.

## Verification

Implementation commit: `d458484` (`fix(injection): make session digest catalog on demand`).

Main-worktree focused verification:
- E09 / eligibility / digest-prefix / reference / injection-fingerprint suite: **43/43 PASS**.
- production + new-test pyright: **0 errors / 0 warnings**.
- canonical R0 replay: **PASS**.

Detached-clean verification at `d458484`:
- focused suite: **43/43 PASS**.
- pyright: **0/0**.
- R0-1 through R0-4: **PASS** after the standard read-only event-log/spec mounts.
- checkout clean after mounts were removed.
- frozen R0 reference remains `b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a`.

## Matrix result

E09 `PARTIAL → DONE`. Matrix becomes **DONE=29 / KEEP=1 / PARTIAL=4 / OPEN=0**. Behavior canary / R9 remain not started.
