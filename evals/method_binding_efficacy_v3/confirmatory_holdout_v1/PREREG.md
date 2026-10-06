# Subject-Binding v3 — Fresh Confirmatory Holdout Label Preregistration

Status: FROZEN before holdout blind scoring and before any holdout provider row.

Source development result: `behavior_protocol_v2/RESULT.json` PASS. Only the three viable abstract families are eligible:
- same_object_different_action
- same_evidence_different_claim
- same_workflow_different_phase

## Pool
- 18 intended-SKIP challenge cases: 6 per viable family.
- 6 intended-APPLY reverse-risk cases.
- all subject Method cards are fresh relative to v1, v2, and v3 development subject cards.
- all task text is fresh relative to previous efficacy/development pools.
- challenge task text states a positive objective and must contain zero unresolved direct anti-trigger disclosure.
- each case also stores a hidden RESULT.md carrier used later by the natural-closeout protocol; blind label raters never see that carrier.

## Blind label gate
Two independent proxy raters see only opaque id + task + subject Method card.
PASS requires:
- raw agreement >= 0.85
- Cohen kappa >= 0.70
- intended accuracy >= 0.90 for each rater
- challenge dual-certified >= 15/18
- each challenge family dual-certified >= 5/6
- APPLY reverse-risk dual-certified >= 5/6
- unresolved anti-leak findings = 0 on certified challenges

No third-rater rescue. Only dual-certified rows can enter confirmatory provider execution.

## Boundary
No holdout C0 preview, no provider call, no C1, no family tuning after seeing holdout outcomes. After label PASS, freeze the exact paired provider SPEC/order/gates before row1.
