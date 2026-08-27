# H2e Matrix v1

24 real runs = MiniMax-M3 12 + deepseek-v4-flash 12 = K01-K04 × V0/V1/V2. Randomization seed `202608260846`.
Machine matrix: `data/calib/h2e_matrix_v1.json`.
Cross-provider blind judge: MiniMax generations -> DeepSeek judge; DeepSeek generations -> MiniMax judge. Judge is blind to generation provider, treatment, and auto score.
Gate: task/fatal/constraint exact agreement >=95%; novel exact >=90%; zero adjudicated scorer bugs; no scorer/fixture/matrix/treatment/judge edits after H2E-001.
Any scorer bug => H2e FAIL and entirely new version/holdout.
