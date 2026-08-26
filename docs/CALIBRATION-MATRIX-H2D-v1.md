# H2d Matrix v1

Providers: MiniMax-M3 (non-thinking) + deepseek-v4-flash (thinking).
Seeds: J01-J04. Variants: Baseline / Contract / Full.
Total: 24 real runs (12/provider). Randomization seed: `202608260831`.
Canonical machine matrix: `data/calib/h2d_matrix_v1.json`.

Rules:
- provider blocks may run independently but scorer/fixtures/matrix are frozen before H2D-001;
- no fallback; every run is a fresh session; tool limit=2;
- first real request onward: zero edits to scorer v1.7, H2d scorer adapter, fixtures, treatments, matrix, runner, or judge protocol;
- any discovered scorer bug invalidates H2d and requires a version bump + entirely new H1e/H2e holdout.

Independent judge protocol: each MiniMax output is judged blind by DeepSeek; each DeepSeek output is judged blind by MiniMax. Judge sees task/oracle/tool trace/final answer, but not treatment, generation provider, or auto score. Gate: task/fatal/constraint exact agreement >=95%, novel exact >=90%, and zero adjudicated scorer bug.
