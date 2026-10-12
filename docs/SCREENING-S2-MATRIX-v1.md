# S2 Anchor-Only Matrix v1

48 real generations = MiniMax-M3 + deepseek-v4-flash × E01-E08 × Baseline/Contract/Full. Randomization seed `202608261114`; canonical matrix `data/calib/s2_matrix_v1.json`.

Measurement is frozen v2.1. Every run receives a cross-provider primary semantic judge. Before outcomes, exactly two runs per provider×variant (12 total) are preselected for corroborating secondary judge. Additionally, all non-COMPLETED, task failures, fatal actions, or non-N4 results force secondary review. Any primary/secondary semantic or derived-score disagreement becomes ABSTAIN.

## Frozen Screening Classification
For Contract and Full separately, relative to Baseline within each provider:
- screen-out if fatal increases, Task Success drops by >=2/8, ROUND_LIMIT increases by >=2, or N4 drops by >=2;
- screen-out-efficiency if both anchors add >=2 unnecessary verifications and neither gains Task Success;
- screen-in if no hard adverse gate, Task Success is within -1/8 on both anchors, and at least one anchor improves Task Success or unnecessary verification;
- otherwise inconclusive.

This is a screening rule, not a significance test or global promotion rule. Kimi/GLM are unavailable, so all S2 claims are anchor-only.
