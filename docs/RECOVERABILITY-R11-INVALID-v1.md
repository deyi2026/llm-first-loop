# Evidence Recoverability R11 v1 — Paired Stress Invalidated by Production Activation Blocker

Date: 2026-08-26
Status: **PAIRED EXPERIMENT INVALIDATED BEFORE ENFORCE PROVIDER REQUEST #1**

## B0/off evidence retained

The frozen off condition completed its measured 12-turn session and remains valid baseline evidence:

- 40 API requests;
- one stable tools_count value = 55;
- one stable stress budget = 50,000;
- post-warmup median cache hit ratio = 0.8988;
- `context.compressed` = 88;
- max compression events between adjacent requests = 12;
- 23 physical read_file results with 11 repeated source paths;
- 5/12 user turns satisfied all requested current+recall codes;
- final turn nevertheless recovered all ten source codes.

This demonstrates that high cache hit can coexist with compression storm, physical source rereads and behavioral drift.

## Why the paired experiment is invalid

The enforce subprocess exited during `build_engine()` before any provider request:

`RuntimeError: evidence enforce and tool post-pipeline are not integrated yet`

Production `.env` has:

- `TOOL_PIPELINE_ENABLED=1`
- `TOOL_MATERIALIZE_ENABLED=1`
- `TOOL_GUARD_ENABLED=0`

The R11 preregistration required off/enforce to differ only by `EVIDENCE_MODE`. Disabling the pipeline only for enforce would violate the frozen causal design, and the already-observed B0 cannot be retroactively rerun under a new treatment definition.

Therefore R11 v1 receives no paired PASS/FAIL score. The failure is promoted to a rollout blocker: current production configuration cannot activate Evidence enforce.

## Next prerequisite

Integrate Evidence enforce with the actually used pipeline subset while preserving capture/projection safety, then run a fresh paired long-session stress with unseen source tokens.
