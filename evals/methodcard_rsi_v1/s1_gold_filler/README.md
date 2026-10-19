# S1：gold / filler 阳性-阴性对照

依据：`docs/ANALYSIS-20261019-rsi-self-improvement-requirements.md` §10.2（R15）/ §10.3（R16）/ §10.5；`../s0_p28/GATE-AMENDMENT-v2.md` §4（D2 前置 3）。

## 文件

| 文件 | 作用 |
|---|---|
| `cards/gold.md` | 人工写的显式 gold 卡（四个可观测面：不猜内容 → 给选项 → 问 → 停） |
| `cards/filler.md` | 等长、同结构、内容无关的 filler 卡（CSV 导入前 schema 校验） |
| `S1-SPEC.md` | 冻结的判分与门槛（G1/G2/F1、D 集合、缺失/void 规则） |
| `CALIBRATION-FREEZE-s1.json` | 卡/规格/池/基线/判分器 sha256 与等长记录 |
| `run_s1.py` | 两臂 × 120 实例跑批（一题一调用，断点续跑） |
| `analyze_s1.py` | 复用 v1.3 grader 的汇总与门槛判定 |
| `results/` | `calls_s1.jsonl`、`analysis_s1.json`、`analysis_s1.md` |

## 命令

```
python3 run_s1.py --dry-run          # 校验 FREEZE + 打印 jobs=240
python3 run_s1.py --threads 2        # 正式跑批（后台）
python3 analyze_s1.py                # 汇总 + G1/G2/F1 判定
```

## 判分摘要

- 基线：S0 `no_card` 120 条（继承，不重跑）；D = S0 v1.3 的 28 个卡依赖实例。
- gold：G1（D 中 ≥2 实例 fail→pass）且 G2（≥2 条 check 种类翻转）。
- filler：F1（任何实例 fail→pass 的数量 = 0）。
- 任一不满足 → 仪器不合格，禁止进 S2；先修 check 或换实例。

## 边界

S1 只校准仪器，不证明 orig 卡有效。orig 卡的效应仍由 S0 的 D=28 / R=16 / p=0.096 描述；S2 才做接受判定。
