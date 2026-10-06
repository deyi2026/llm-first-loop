# Subject-Binding Efficacy v3 — Difficulty Calibration Contract

Status: provider-free design contract. No v3 provider row authorized by this document.

## 1. Single changed variable

The first v3 successor changes **challenge construction/difficulty only**.

Keep fixed from v2 for the first successor:

- Strong/Weak model identities
- C0/C1 binding switch
- exact formal applicability output contract
- full Method-card exposure
- cost/safety accounting

Reason: v1 mb-024 shows the treatment can produce a semantic correction even under the explicit-classification prompt. Changing both prompt and case construction at once would destroy attribution.

If the new calibrated pool still produces C0 ceiling, only then open a separate protocol experiment that removes explicit applicability prompting / moves measurement to natural save_experience decision behavior.

## 2. Constructor hard rules

A candidate purpose-level near miss is invalid if the task text directly states why the subject Method should be skipped.

Forbidden in confirmatory near-miss tasks when they negate the subject Method's trigger/discriminator:

- `没有 / 不存在 / 不需要 / 不是 / 尚未 / 并非 / 非...`
- `只需要 / 只问 / 当前唯一目标 / 只是...`
- direct phrases like `不涉及 <subject method action>`, `卡片前提不成立`, or equivalent

These tokens are not globally banned from natural language; the mechanical linter flags them and a blind constructor audit must prove that they do not disclose the intended SKIP rationale.

A valid near miss must instead satisfy all of:

1. **positive-purpose statement** — task says what it is trying to accomplish, not what it is not;
2. **shared domain** — task and subject Method share at least two meaningful domain anchors;
3. **shared evidence/action primitive** — at least one operational primitive or evidence source overlaps, so superficial matching is plausible;
4. **purpose divergence** — the decisive difference is the claim subject / intended action / workflow objective;
5. **no answer sentence** — removing the Method card from view must leave no sentence in the task that is already a natural-language explanation of `SKIP`;
6. **carrier/subject ambiguity preferred** — wherever possible, include a result/output/record/fixture that resembles the Method domain while the true task claim subject differs.

Historical mb-024 is the canonical positive example.

## 3. Two independent qualifications

### A. Label validity (provider-free)

Blind independent raters judge intended APPLY/SKIP and purpose rationale. This gate answers only: **is the label defensible?**

It must never again be called headroom or structural reachability.

### B. Difficulty / opportunity calibration (development provider split)

Use a development set that is permanently excluded from confirmatory efficacy.

- Run **C0 only** during difficulty calibration; never run C1 on dev cases.
- Evaluate difficulty at the **abstract challenge-family** level, not by cherry-picking individual wrong cases.
- A family is viable only if it creates non-trivial control error on the weakest supported model and does not collapse into malformed/OTHER behavior.
- Provisional target band for Weak C0 B accuracy: **0.45–0.80** across the family dev set. This yields real error opportunity without making labels arbitrary.
- Strong C0 may be easier, but a family with Strong=1.00 and Weak=1.00 is rejected as confirmatory-ineffective.
- Do not change thresholds after looking at dev C1 because dev C1 is forbidden.

Dev outcomes may tune **family templates/rules**, never select the same dev instances into confirmatory.

## 4. Fresh confirmatory holdout

After family calibration:

- generate fresh task instances/cards not used in dev;
- rerun provider-free label validity;
- run the anti-leak linter;
- freeze all cases, order, models, gates, and hashes before any confirmatory provider row;
- no control-only preview on holdout;
- then execute paired C0/C1 once.

The holdout must contain reverse-risk APPLY cases built with the same ambiguity style, so a subject-binding over-filtering regression remains measurable.

## 5. Family templates to seed dev construction

1. **same-object / different-action** — e.g. identifier existence verification vs writing an identifier allowlist artifact;
2. **same-evidence / different-claim** — same result/record/output is present, but it is evidence for a different claim subject;
3. **same-workflow / different-phase** — both concern the same pipeline or test failure, but the Method acts at another phase; express the active phase positively, never as `尚未进入 X`;
4. **same-infrastructure / different-decision** — same browser/service/network entities, but the Method's decision boundary differs from the task's positive objective.

## 6. Mechanical gates before dev C0 calibration

- zero reuse of v2 confirmatory task text;
- zero direct anti-trigger disclosure after blind audit;
- all expected labels independently qualified;
- family IDs frozen before C0 dev execution;
- development cases explicitly marked non-confirmatory forever;
- provider runner inherits run2 fail-closed runtime-root/provider-registry assertions before O_EXCL reservation.

## 7. What this contract does not authorize

No provider calls, production changes, Method promotion, prompt tuning, subject-binding text change, publish/restart, or push.
