# Runner v2 冻结（下一轮矩阵执行基础设施）

**范围**：仅执行基础设施；protocol.py / pool 构造规则 / 判据阈值不动——那些属于下一轮 SPEC 的预注册内容。v1 冻结件（run_matrix.py / analyze.py / RESULT.json / SYNTHESIS.md）原样保留，不回写。

## 变更清单（对应 D1–D5 摩擦收口）

| 项 | v1 缺陷 | v2 修复 | 验证 |
|---|---|---|---|
| D4 根因 | healthy() 裸名 `MODEL` vs canonical `model_used` 永假 → 80 cell 全双跑 | `healthcheck.py` 单一事实源：canonical 比较（`model_canonical_ok` 优先，legacy 行回退字符串比较）；runner/analyzer 共用 | test_runner_v2 #1–6 |
| v1 analyze 潜在缺陷 | line19 `A and B and C and D==X or E is True` 优先级错误（偶然无害） | 同上共享门 | 回放零 diff |
| D3 残留 | smoke 门双语启发式解析（"不"字逻辑脆弱） | 提示已纯英文 → 严格 `\b(YES|NO)\b` 单 token | test_runner_v2 #7–9 |
| D1 接口 | DATA_DIR 优先于 LFL_DATA_DIR（toml 压制）、LLM_MODEL 裸名 | 保持实证行为 + worker 断言（已在 v1 修），文档化于 run_matrix_v2 头注 | — |
| worker 字段覆盖 | v1 已修（git 3c6399531，数据前） | 加入回归 fixture 防回退 | test_runner_v2 判决/门解析组 |

## 零-provider 验证（2026-10-05）

- **fixture**：test_runner_v2.py **15/15 PASS**（健康门正/反例、严格 smoke、verdict 解析、latest-wins 80 cell、安全重跑算术含不对称触发）。
- **回放**：analyze_v2 在冻结 matrix 上输出 `RESULT.v2.json`，**与 RESULT.json 逐字节同 sha256（6f60fb70…）**，裁决字符串一致——v2 健康门零语义漂移。

## 冻结哈希

```
29c94c7e2876d54c  healthcheck.py
503b56d491df2670  run_matrix_v2.py
066d430788ec34ee  analyze_v2.py
d6bec1606281c146  test_runner_v2.py
e621d9910571b9d1  forensic_v1.py
```

## 下一轮执行规约

1. 正式矩阵只允许 run_matrix_v2.py + analyze_v2.py（v1 件仅存档）；任何改动 = 新偏离登记。
2. wall 指标：D4 修复后总成本回到 1×；G2 wall 分量如保留，须配对分批设计，否则按传输噪声记（FORENSIC §5）。
3. 数据采集前须先过 fixture 15/15 + smoke 前置门；重跑仍限技术失败、最多 1 次、禁止 outcome-driven。
