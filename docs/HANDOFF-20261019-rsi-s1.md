# HANDOFF：S1 gold/filler 对照（已终值 FAIL）

- 时间：2026-10-19 21:32 +08:00
- 状态：**S1 FAIL**；按 §10.2 停，禁止进 S2
- 跑批：`job-99e05734b5204218acd5` 完成，240/240 ok，0 空，finish 全 stop

## 终值

| arm | case_pass | rate |
|---|---|---|
| no_card（S0 继承） | 42/120 | 0.350 |
| gold_card | 98/120 | 0.817 |
| filler_card | 33/120 | 0.275 |

- G1=19（阈值 ≥2）满足；G2=3（c1/c2/c3，阈值 ≥2）满足；**F1=21（阈值 0）不满足 → FAIL**
- filler 翻动 21 个，其中 19 个与 gold 翻动重叠；check 分布 c3 13 / c1 9 / c2 4 / c4 0
- S0 D=28/R=16/p=0.096 复算一致；但 S1 证明该差异不能归因于目标行为

## 已提交

- `6003f2966`：S0 终值
- `38cd7a5ab`：S1 冻结包 + 审查 PASS
- 待提交：S1 结果 + `docs/REPORT-20261019-rsi-s1-gold-filler.md`

## 下一步（待用户裁决）

1. 停 S2；v1.3 check 不合格，不能用于接受判定。
2. 修 check（T4 或重设计）：c3 排除编号步骤/普通列表；c1 收窄内容断言；c2 收紧提问；c4 保持并补负例。
3. 修完后重跑 S0 + S1，门槛不变。
4. 替代路线：判分单位从“回复格式”改为“决策点行为证据 + 小批人工复核”。

## 复现

```
cd evals/methodcard_rsi_v1/s1_gold_filler
python3 analyze_s1.py --now 2026-10-19T21:26:00+08:00
```

输入 sha：calls_s1 `3bbca6d7…`；s0_calls `bf0aec40…`；判分器 `run_s0.GRADERS["v1.3"]`。
