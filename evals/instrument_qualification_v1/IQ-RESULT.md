# IQ v1 结果（一次性裁决，2026-10-05T23:15:19+08:00）

- verdict：**PASS**（Q1=PASS / Q2=PASS / Q3=PASS）
- κ(R1,R2) = 1.0000，95%CI [1.0000, 1.0000]，raw agreement = 1.0000（40/40）
- R1 vs intended（A/C/D 构造确定 20 例）= 20/20 = 1.000
- 认证（双评一致判出 intended）：A 6/6｜B 14/20｜C 8/8｜D 6/6
- headroom：H⁺ = 14（门 ≥12）｜H⁻ = 8（门 ≥6）
- 分歧：0/40（门 ≤6）

## 门槛明细

| gate | 值 | 阈值 | 状态 |
|---|---|---|---|
| Q1_kappa | 1.0 (CI95 [1.0, 1.0], po 1.0) | >=0.70 (0.55-0.70 HOLD) | PASS |
| R1_vs_intended_ACD | 1.0 | 0.9 | PASS |
| A_cert | 6 | >=5/6 | PASS |
| D_cert | 6 | >=5/6 | PASS |
| B_cert | 14 | >=12/20 | PASS |
| C_cert | 8 | >=6/8 | PASS |
| disagreement | 0 | <=6/40 | PASS |
| Q3_headroom | H⁺=14, H⁻=8 | H⁺>=12, H⁻>=6 | PASS |

## 分歧清单（裁定不救认证；R1 理由留痕归因）

（无分歧）

> 披露：R2 非独立（L/D 归类作者、设计作者、评前已知 FORENSIC 内容）——载重结论挂 R1 与 κ（PREREG §8.1）
> PASS ⇒ 构造器 v2 挂 IQ-CTOR-v2；κ HOLD ⇒ 单轮指引修订+整表重评；任一 FAIL ⇒ 构造器/仪器重做；B/C 短缺 ⇒ 单轮替换（≤6/格，二轮仍短缺=构造器 FAIL）