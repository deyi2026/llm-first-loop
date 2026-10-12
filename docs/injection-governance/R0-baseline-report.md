# R0 Baseline Report（兼容入口）

旧版 R0 报告已被新版确定性数据门取代。权威产物：

- `r0/report.md` — 人类可读 R0 四门与基线
- `r0/baseline.jsonl` — human-turn 级结构数据
- `r0/baseline-manifest.json` — source hash / aggregate / gate 结果
- `r0/fixtures/structural-fixtures.json` — 脱敏确定性结构 fixture

说明：旧版“只按 marker 统计整条 user message”的口径会混淆 system notice 与 user-role program appendix，且无法给出重复/祈使/wire 结构归因，因此不再作为验收依据。
