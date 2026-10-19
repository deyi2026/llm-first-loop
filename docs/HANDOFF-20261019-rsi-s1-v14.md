# HANDOFF — S1 check v1.4 与 DPE（2026-10-19）

## 当前状态

- **S2 停**（未启动，无进程、无契约推进）。
- S1 v1.3 终值仍为 FAIL（G1=19 过、G2=3 过、F1=21 不过）。
- v1.4 check 已实现并离线重判：S1 机械门槛全过（G1=19、G2={c2,c3}、F1=0），但**注入测试 F1 0→14**，判定不可信；**不进 S2**。
- 替代路线 DPE 已备好 60 条盲标包与评分脚本；**人工复核未完成**。

## 关键数值

| 项 | 值 |
|---|---|
| S0 v1.4 D/R | 30 / 0（刚好 D≥30；但 v1.0/1.1/1.2 全 D<R → `S0 mixed — revision flipped direction`） |
| S1 v1.4 gold case_pass | 77/120 |
| S1 v1.4 filler case_pass | 0/120 |
| S1 v1.4 G1 / G2 / F1 | 19 / {c2,c3} / 0（数值过门槛） |
| 注入后 F1 | 14（P28-006/009/010/017/023/041/063/070/073/075/096/099/104/110） |
| v1.4 c1 / c4 饱和度 | c1 340/360 pass（仅 1 fail）、c4 360/360 pass |

## 本次新增文件

- `evals/methodcard_rsi_v1/s0_p28/grade_v14.py` — v1.4 判分器 + c4/c1 负例单测
- `evals/methodcard_rsi_v1/s1_gold_filler/reanalyze_v14.py` — S0+S1 离线重判 + 注入测试
- `evals/methodcard_rsi_v1/s1_gold_filler/results/analysis_v14.json` — 全量结果
- `evals/methodcard_rsi_v1/dpe/` — DPE 规格、抽取器、评分器、60 条盲标包、pilot 记录
- `docs/REPORT-20261019-rsi-s1-check-v14.md` — 报告

## 下一步（二选一，需用户裁决）

1. **DPE 人工复核**：两位复核者按 `dpe/review_guide.md` 独立填 `dpe/review_pack.csv`，运行 `python3 dpe/score.py <rater1> <rater2>`。kappa ≥0.6 后看 G1/G2/F1。
2. **重设计 S1 阴性对照**：换一个不改变谨慎程度的无关卡（现 filler 是 CSV schema 校验，与 gold 同属“先校验再动手”，不是正交对照），重新跑 S1（需新的 API 跑批）。

## 不要做

- 不要用 v1.4 的 F1=0 进 S2；注入测试已证明它是措辞合规。
- 不要继续给 c3 加成本词表；每加一个词，注入测试就能绕一次。
- 不要把 DPE pilot 的模型初标当人工复核结果。
