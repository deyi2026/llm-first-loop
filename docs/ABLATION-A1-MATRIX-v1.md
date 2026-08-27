# A1 Matrix v1

Canonical machine-readable source: `data/calib/a1_matrix_v1.json`.

- randomization seed: `202608261001`
- providers: MiniMax-M3, deepseek-v4-flash
- provider blocks: 56 runs each
- per provider: 8 seeds × 7 treatments exactly once
- total: 112 runs
- secondary review sample: 14 runs, exactly one per provider × treatment, selected before real outputs
- provider blocks are independently randomized; analysis remains within-provider paired by seed

No A1 real request may occur until `ABLATION-A1-FROZEN-v1.md` is produced and its hash table verifies.
