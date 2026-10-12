# Common Governance / Common Experience Qualification — 2026-09-11

## Verdict

PASS for local candidate `fix/common-governance-20260911` on top of `fix/context-drift-p1-20260911@3a5f38a`.

The change restores only a tiny static default governance layer. It does not restore the old prompt-heavy playbook, dynamic experience catalogs, tool eligibility authority, completion arbitration, fixed retry policy, or per-round self-check rituals.

## Provider-visible delta

- Baseline universal prompt: 192 chars / 508 UTF-8 bytes / SHA256 `ea88fe6a8d5d1bd0ad3978625980f788ac350c7281f2bfdcaf009fd5b6d4fd5e`.
- Candidate universal prompt: 198 chars / 560 UTF-8 bytes / SHA256 `e9928ec6834c80277ad66ba6e589710e00f97530f8628af928540f87c002e60d`.
- Delta: +6 chars / +52 UTF-8 bytes.
- Tool registry source SHA is unchanged (`bef1d94f5bfc7fc90d7e3def93bcaa81acca487163103b666bf996d951caafea`), so provider tool schema/surface is unchanged.
- Expected deployment effect: one stable-prefix fingerprint change / cache cold start at rollout, followed by stable reuse while the prompt remains unchanged.

## Static and regression gates

- focused prompt/rule/experience/static suite: 45 PASS.
- broader continuity/cache/prompt/drift suite: 124 PASS.
- full `pytest tests -q -m 'not real_llm'`: exit 0.
- Pyright touched scope: 0 errors / 0 warnings / 0 informations.
- Ruff: PASS.
- `git diff --check`: PASS.

The existing `<200 chars` universal-prompt gate and the guard against restoring method-layer text such as `增量推理` were intentionally preserved, not weakened.

## Real Ornith behavior canary

Runtime: existing `ornith-ai/Ornith-1.5-35B-A3B-MLX` process on 8901. No second model was loaded and the model server was not restarted.

Short behavior probes:

1. Success receipt -> no repeated tool call: PASS. First call used `get_value`; after `CURRENT_VALUE=47; status=success`, the next response directly answered 47 with no tool call. The first warm repetition showed 391 cached tokens out of 392 prompt tokens.
2. Current fact beats stale history: PASS. Historical value 12 was superseded by current runtime value 88; the model explicitly used 88 and did not re-call the tool after success.
3. Recent `继续` binding: PASS. With an old closed task plus one unique recent pending action, `继续` called the pending `get_value` rather than reopening the old task.

Longer tool-chain probe:

- Six historical closed-task pairs were placed before the current task.
- Current task required `inspect_step` for STEP1..STEP8 exactly once each.
- Ornith issued all eight calls once each in the first model round, with zero duplicates and zero omissions.
- The second model round produced the final VALUE-1..VALUE-8 summary and issued no further tool call.
- Second-round cache: 667 cached tokens; prior-round prompt size: 668 tokens.

## Runtime health after canary

- 8901: one listener / one Ornith process.
- launch args still include `--prompt-concurrency 1 --decode-concurrency 1`.
- RSS after probes: about 68.3 GB, within the established healthy ~65–75 GB working-set/peak band.
- system `memory_pressure`: 95% free.
- recent server log shows sequential prompt-processing progress; no four-way duplicate prefill pattern.
- mirror Web 8903 remained healthy during qualification: `/auth/status` 200; `/ui/v2/` normal auth redirect rather than 404.

## Boundary

This qualification demonstrates that the Common Governance candidate is small, static, prompt-prefix stable after rollout, does not alter the tool schema, and improves/defaults the intended anti-drift behaviors without reintroducing Program Authority. It does not claim that every future model/provider will benefit equally; model-specific regressions remain subject to normal canary/benchmark evidence.
