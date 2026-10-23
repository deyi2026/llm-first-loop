# 活水基准可得性盘点 (T2, 2026-10-14 实测)

锚点: glm-5.3 API 注册日 2026-08-14 (UTC)。目标 = 该日之后发布/结束的题, 按构造无污染。

## 实测结果 (全部一手验证)

| 基准 | 公开数据现状 | 验证方式 | post-2026-08-14 题量(公开) |
|---|---|---|---|
| LiveBench (HF livebench/*) | math max 2024-08, reasoning/language max 2024-11, coding max 2024-07, data_analysis max 2024-06; if/object 401 gated | parquet 下载 + duckdb 实数; 官方 README 明言"当前 release 2025-04, 全公开只到 2024-11" | **0** |
| LiveCodeBench (livecodebench/code_generation_lite) | 卡片最新 release_v5 (至 2025-01); HF refs 无任何 version tag | /refs API 实测 tags=[] | **0 (待用 datasets 库终验)** |
| SWE-bench-Live (SWE-bench/SWE-bench-Live) | 存在, **gated** (HTTP 401) | hub API 实测 | 未知, 需 HF token 解门控 |

## 结论与路线调整

1. "活水"基准生态当前普遍把新题藏进门控或 leaderboard, 公开管道实质停摆于 2024-11~2025-04。
2. 对 2026-08 模型, 最可靠的开放 post-cutoff 评测源 = **2026-08-14 之后结束的 Kaggle 竞赛**
   (T3 的 MLE-bench 路线: 已结束竞赛 + 自建 harness + 私有 holdout)。T2/T3 合流。
3. 可选并行: 若有 HF 账号 token, 申请 SWE-bench-Live 与 LiveBench(if/object) 门控 (多为自动批准)。
4. Terminal-Bench core 0.1.1 保持回归用途 (题目多为 2025 及以前, 不作 post-cutoff 证据)。

## 下一步

- [ ] 盘点 2026-08-14 后结束、数据公开可下载的 Kaggle 竞赛清单 (T3 入口)
- [ ] (可选) 用户提供 HF token → 解锁 SWE-bench-Live / LiveBench gated
- [ ] LCB 用 datasets 库终验 (加载 version_tag 列表)
