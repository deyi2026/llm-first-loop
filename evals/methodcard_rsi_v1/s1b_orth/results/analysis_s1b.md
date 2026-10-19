# S1b：gold vs 正交 filler 阴性对照（v1.4 grader）

- 实例数：120；新批次两臂：gold_card / filler_orth_card；no_card 继承 S0。

## 臂汇总

| arm | n | case_pass | rate | 95% CI | c1 | c2 | c3 | c4 |
|---|---|---|---|---|---|---|---|---|
| no_card | 120 | 0 | 0.0 | [-0.0, 0.031] | 1.0 | 0.3667 | 0.0 | 1.0 |
| gold_card | 120 | 65 | 0.5417 | [0.4526, 0.6281] | 0.9833 | 0.8917 | 0.6 | 0.9917 |
| filler_orth_card | 120 | 0 | 0.0 | [-0.0, 0.031] | 1.0 | 0.2167 | 0.0 | 1.0 |

## 门槛

- v1.4_D（n=30）：G1=16（≥2）G2=2 ['c2', 'c3']（≥2）→ gold PASS
- v1.3_D（n=28）：G1=16（≥2）G2=2 ['c2', 'c3']（≥2）→ gold PASS
- F1=0（=0）→ filler_orth PASS

## 新旧 gold 批次一致性（描述性）

- 可比实例 120；case_pass 一致 62（0.5167）；旧 pass 77 / 新 pass 65；两批都 pass 42。

## 注入测试（诊断，不改门槛）

- no_card: 0 → 20（+20）
- gold_card: 65 → 97（+32）
- filler_orth_card: 0 → 1（+1）
- F1 after inject = 1

## 完整性

- gold_card: ok=120 err=0 dup=0 pv=['p2'] model=['glm-5.3-flash'] card_sha=['4c9d22cad90a42378ef917b6ac585119c6d11e01cbf5b2afa6172f147ad4f8a6']
- filler_orth_card: ok=120 err=0 dup=0 pv=['p2'] model=['glm-5.3-flash'] card_sha=['58275883879b49f7a1dbe67b43289f00de22b5b3cf0356e095121fc35855e9d1']
