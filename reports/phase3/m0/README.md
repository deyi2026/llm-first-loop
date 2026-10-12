# M0 基线原始记录状态说明（事故记录，诚实优先）

- 2026-10-13 01:32 原始 M0 运行（12 份 S*.json，基于 pre-M1 代码）——其关键数字
  已引用进 docs/phase3-m0-baseline.md（成文 01:34）。
- 2026-10-13 01:41 过失覆盖：M1 开发后在同一目录重跑 tests/phase3_baseline/，
  原始 JSON 被含 M1 字段的新记录覆盖（grade=accepted 可证）。
- 原始文件不可恢复（reports/ 未纳入 git）。覆盖后的 M1 行为记录移至
  ../m1_rerun/。01:5x 起的修正版 S03/S04/S05 重跑记录（stop 路径语义与
  pre-M1 等价，M1 未触碰 cancel 链路）写入本目录并标注 ran_under=M1。
- 教训：基线输出目录已参数化（PHASE3_REPORT_DIR），重跑不再默认覆盖。

- 02:05 追记：一次运行时部署防护的自动 stash（phase3-wip-foreign）把 M1 版
  S01–S12 记录短暂带回本目录，已清理回 m1_rerun/；本目录保留 README 与
  S03/S04/S05（01:53 生产装配修正重跑，ran_under=M1-in-progress，stop 路径
  语义与 pre-M1 等价）。
