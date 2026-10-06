# Subject-Binding Line — Production Value Audit & Retire Decision

Date: 2026-10-06 | Cost: 0 provider calls | Scope: production data in the canonical runtime root (main repo mirror)

## Question
Does real production show subject mis-binding (method/experience applied to a claim whose subject does not match) at a frequency/loss that justifies a v4 iteration of the subject-binding cue?

## Evidence (all mechanical counts, reproducible)

### Exposure
- Production retrieval surface: **7,864 `search_records` calls** across **1,352 session event logs** (data/event_logs, 2.5G).
- Method registry: **631 cards**; **278/631 (44%)** carry explicit guard/exclusion clauses (不适用/仅当/仅中/不要在/前提).
- Experiences: **323** production EXPERIENCE-*.md; episodes: **634** files.

### Observed use decisions (the only auditable application events)
- `data/methods/usage.jsonl` (authoritative record_use registry): **5 events** (2026-09-23 → 2026-10-05), **all `applied`**, 0 not_applicable/rejected.
- Episodes transcripts: **~4 detectable use decisions** (3 applied, 1 adapted), **0 negative**.
- Combined n=9, all positive; **zero mis-binding events observable**.

### Incident sweep
- Keyword sweep (误用/错用/错误套用/误绑/经验污染/旧经验误导/错误引用/套错了/套用错误/漏用/不该跳过/过度拒绝/本应套用/should have applied) across experiences/, docs/, data/episodes/:
  - **0 method/experience subject mis-binding incidents**; only incidental semantic matches (e.g. Django model misuse, flock path-function misuse — unrelated).
  - 漏用/过度拒绝 hits are eval design docs (ELIG discipline lines), not production incidents.
- Guard clauses in method cards: essentially first-principles writing at distillation time; **1 of 278** references a real lesson/incident.

### Measurement gap
Production has no at-scale record_use telemetry (n=9 total vs 7,864 retrievals). Even if mis-binding occurred, it is currently **unmeasurable** in production; and any v4 PASS could not be tied to production value.

## Verdict
**Production pain evidence: INSUFFICIENT.**

- 0 documented incidents, 0 quantified loss, observable decision stream all-positive.
- The only evidence mis-binding can happen is the constructed eval series itself (v2 dev C0 73% error on hard families; v3 confirmatory C0 challenge inaccuracy) — artificial holdout, not production.
- Reverse-risk guard value (cue prevents over-SKIP: strong 4/6→6/6, weak 6/6→6/6 in v3) also has **no production incident** behind it; research observation only.

## Decision (pre-stated rule from 2026-10-06 review)
> "若痛点证据不足，retire 比再烧一轮更诚实" — triggered.

**The subject-binding cue promotion line is RETIRED (≥6 months).** No v4. No production promotion (v3 verdict already `EFFICACY_NOT_QUALIFIED`, `production_promotion_authorized=false`).

## Reopen prerequisites (must ALL hold before any v4 proposal)
1. Production telemetry first: record_use (or equivalent) wired into the real closeout loop so mis-binding frequency becomes measurable (n target: ≥100 natural decisions).
2. ≥3 documented production incidents of subject mis-binding with quantifiable loss.
3. New confirmatory must pre-register thresholds from power analysis; stop rule: one more FAIL retires the line permanently.

## Preserved assets
- v3 confirmatory frozen set: SPEC/FREEZE/plan/matrix(92)/RESULT/SYNTHESIS in this directory.
- v2 dev + holdout label qualification artifacts under `behavior_protocol_v2/`, `confirmatory_holdout_v1/`.
- All reusable as-is if reopen conditions are ever met.
