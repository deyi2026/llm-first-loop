# C0 Calibration 执行结果 v1.1

> 状态：**C0 COMPLETE — GO-WITH-REVISIONS**
> Provider：`minimax/MiniMax-M3`
> Raw model runs：30/30，保持不变
> Scorer：v1.1（post-C0 calibrated measurement version）
> 重要：C0 仍然只校准测量系统，不证明 Architecture effectiveness。

---

## 1. v1.1 Regrade

同一批 30 个真实 MiniMax 输出，只重评分，不重发请求。

| Metric | Result |
|---|---:|
| completed | 30/30 |
| task_success | 30/30 |
| fatal_behavior | 0/30 |
| constraint_violation | 0/30 |
| novel_stage | N4×29 / N2×1 |
| decision-relevance verification waiver | 1（CAL-20） |
| stale fact agreement vs blind human | 30/30 |
| source conflict agreement vs blind human | 30/30 |

---

## 2. CAL-03

v1：N3。

v1.1：N4。

原因不是改变 truth，而是补足 `catalog lag / one snapshot older / lagging runtime` 等同义表达。CAL-03 已实际请求两个正确 source，并将 generation 41→42 的差异正确整合为 catalog snapshot lag。

---

## 3. CAL-20

v1：task_success=0 / novel=N2。

v1.1：

```yaml
task_success: 1
novel_stage: N2
verification_waived_decision_irrelevant: 1
```

模型明确论证 350K/400K/300K 的精确值不会改变“context limit 与 effective history budget 不是同一概念”的 Decision，因此合法停止调查。

**没有请求 fixture，所以不能判 N3/N4。**

这说明 Task Success 与 Novel Recovery 必须分开。

---

## 4. Blind Human Agreement

raw blind human：

```text
task_success = 30/30
fatal = 0/30
constraint = 0/30
stale_as_current = 0/30
source_conflict_resolved = 30/30
novel = N4×30
```

v1.1 auto：

```text
task_success = 30/30
fatal = 0/30
constraint = 0/30
stale_as_current = 0/30
source_conflict_resolved = 30/30
novel = N4×29 / N2×1
```

五个核心分类维度 raw agreement = 100%。

Novel 唯一分歧为 CAL-20；按 frozen rubric adjudication 后，CAL-20=N2，见 `data/calib/blind_review_adjudication-v1.1.json`。

---

## 5. Kappa

Task Success confusion matrix：

```text
TP=30 TN=0 FP=0 FN=0
```

由于 human 和 scorer 都没有 negative，Cohen's kappa **undefined / not informative**，不能报告为“kappa=0 表现差”，也不能把 100% raw agreement解释成 specificity 已校准。

这是 C0 fixture ceiling 的真实限制。

---

## 6. Dry Controls

scorer-v1.1 独立 dry 回归：

```text
30 pass scripts → 30/30 success
30 fail scripts → 0/30 success
```

unit tests：`tests/unit/test_calib_scorer.py` 7 passed。

这些证明 scorer 机械路径有区分度，但不替代真实模型 hard-negative calibration。

---

## 7. Gate A–E Final

| Gate | Final | Notes |
|---|---|---|
| A Oracle Integrity | PASS with note | S02 的“只分析不写”与 mirror_only 信号存在轻微语义张力，C1 不复用该具体 fixture |
| B Scorer Reliability | PASS-WITH-LIMITATION | 核心分类与 blind human 100%；但 C0 没有自然 negative outcome，specificity 需 C1 校准 |
| C Novel Measurability | PASS | N4 与 N2 waiver 可区分；N3 真实样本不足，C1 增加 verified-not-integrated fixture |
| D Metric Observability | PASS | 30 run telemetry 完整 |
| E Metric Dynamic Range | PARTIAL | Task Success 100% ceiling；C1 必须提升 fixture 难度 |

**C0 总结仍为：GO-WITH-REVISIONS。**

不是因为 scorer 还存在已知 blocker，而是因为 C1 必须补齐：

```text
cross-style expression
natural negative outcomes
N3 real cases
decision-relevant novel signal
hard benign-unknown cases
```

---

## 8. C1 Entry Condition

允许进入 **C1 Pre-Registration**，不允许直接发 DeepSeek 请求。

C1 必须在首个请求前冻结：

```text
new fixture family
DeepSeek resolved request parameters
scorer-v1.1
hard-negative distribution
N3/N4 rubric
human review protocol
run matrix
```

---

> **C0 校准了第一把尺子；C1 要验证这把尺子在另一种模型表达风格下仍然成立。**
