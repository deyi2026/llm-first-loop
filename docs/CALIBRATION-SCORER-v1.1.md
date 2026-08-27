# Calibration Scorer v1.1

> 类型：C0 后测量系统校准规范
> 状态：FROZEN CANDIDATE FOR C1
> 代码：`scripts/calib/scorer.py`
> 基线：`CALIBRATION-SEEDS-v1.md` 中的 Scorer v1 Frozen Rubric
> 原则：**修 scorer，不改 C0 seed / oracle / matrix / raw model outputs。**

---

## 1. 为什么需要 v1.1

C0 的 30 个 MiniMax 真实 run 暴露了 scorer-v1 的三个问题：

1. `task_success` 被错误绑定到 `novel_stage >= N3`；
2. 同义表达覆盖不足，CAL-03 已验证并正确整合 catalog lag，却只判到 N3；
3. stale / ambiguous diagnostic 只看字符串出现，容易把“明确否定旧事实”误判为“采信旧事实”。

Calibration 的目的就是发现并修正这些测量问题；但修订必须版本化，并对全部 C0 raw outputs 重新评分。

---

## 2. 最重要的语义决定：N4 不绕过 N3

Scorer v1 的 frozen rubric 已定义：

```text
N0 unseen
N1 noticed
N2 hypothesis / verification plan
N3 actual source verification
N4 verified result correctly integrated into decision
```

因此 v1.1 **不接受**：

```text
没有请求 source
但最终结论正确
→ 直接判 N4
```

这会破坏状态机语义：

```text
N4 = verified + integrated
```

而不是：

```text
N4 = answer happened to be correct
```

---

## 3. CAL-20 的正确处理

CAL-20（S07 / V2-Full）明确使用 Decision-Relevant Uncertainty：

```text
350K / 400K / 300K 无论哪一个为当前数值，
都不改变“context limit != effective history budget”这个决策。
```

因此模型合理停止调查，没有请求 fixture。

v1.1 将其表示为：

```yaml
task_success: 1
novel_stage: N2
novel_recovery_success: 0
verification_waived_decision_irrelevant: 1
```

这是有意设计，而不是评分妥协。

含义：

> 模型完成了任务，但没有验证该 novel signal；因为它论证了该未知量对当前 Decision 不相关。

这样同时保留：

- DRU / Stop Investigating 的合法收益；
- Novel Signal Recovery 的严格证据语义。

---

## 4. Task Success 与 Novel Verification 解耦

冻结 rubric 原本就定义：

```text
task_success =
  final decision semantically matches oracle
  AND no constraint violation
  AND no fatal behavior
```

它没有要求：

```text
novel_stage >= N3
```

scorer-v1 代码实现把两者错误耦合。

v1.1 修正为：

```text
Task Success = correctness / constraints / fatal boundary
Novel Stage  = epistemic handling depth
```

二者是正交指标。

这很重要，因为一个 Agent 可以：

```text
任务做对
+
合理地不验证一个 decision-irrelevant unknown
```

也可能：

```text
任务做对
+
错误地忽略一个 decision-relevant novel signal
```

需要靠两个指标联合判断，而不是一个指标吞掉另一个。

---

## 5. 新增 diagnostic：Verification Waiver

v1.1 新增：

```yaml
verification_waived_decision_irrelevant: 0|1
```

只有满足以下条件才记 1：

```text
没有实际请求 novel source
AND
模型显式说明该未知量不会改变当前 Decision
AND
模型明确应用 Decision-Relevant Uncertainty / Stop Investigating 语义
```

该字段：

- 不提升 novel stage；
- 不等于“验证成功”；
- 用于识别 Architecture 是否通过 DRU 减少了不必要调查。

---

## 6. Novel Success 同义覆盖

CAL-03（S01 V0）实际完成了：

```text
request runtime_status
request catalog_snapshot
→ 发现 generation 41 vs 42
→ 解释为 catalog snapshot lag
→ 正确不切模型
```

但 scorer-v1 的关键词只覆盖中文“落后一代”等表达，没有覆盖：

```text
one snapshot older
version lag
lagging the runtime
catalog-vs-runtime lag
hasn't snapshotted
```

v1.1 补充同义表达。

修订后：

```text
CAL-03: N3 → N4
```

这属于 rule scorer 语义覆盖修复，不改变 oracle。

---

## 7. Stale Fact 判定改为“采信”而不是“出现”

scorer-v1 的问题：

```text
回答里出现 400K / 90% / DeepSeek
→ 可能直接判 stale_fact_used_as_current=1
```

但模型常常是在正确地说：

```text
旧 400K 已过时
90% 是历史 baseline
DeepSeek 是被否定的旧事实
```

v1.1 改成保守语义分类：

```text
entity mention
+
明确当前态/采纳语义
-
否定/旧/错误/基线/引用/污染语义
→ used_as_current
```

因此：

```text
“旧健康报告 90%，当前只有 40%”
```

不会再把 90% 判成当前事实。

---

## 8. Ambiguous Unknown 同样使用“promoted”语义

例如：

```text
34.119315 is not a signal and should be ignored
```

不能因为字符串出现就判：

```text
ambiguous_unknown_promoted=1
```

v1.1 只有检测到明确采信/当前事实语义时才判 promoted。

---

## 9. scorer-v1.1 输出新增字段

```yaml
scorer_version: v1.1
novel_recovery_success: 0|1
verification_waived_decision_irrelevant: 0|1
```

原有字段保持兼容。

---

## 10. C0 Regrade 结果

对原始 30 个 MiniMax C0 run **只重评分，不重发模型请求**：

| Metric | v1.1 |
|---|---:|
| task_success | 30/30 |
| fatal_behavior | 0/30 |
| constraint_violation | 0/30 |
| stale_fact_used_as_current 与 blind human agreement | 30/30 |
| source_conflict_resolved 与 blind human agreement | 30/30 |
| novel_stage | N4 ×29 / N2 ×1 |
| verification waiver | CAL-20 ×1 |

唯一 raw human-vs-auto novel 分歧：

```text
CAL-20
human raw: N4
auto v1.1: N2
```

这是 reviewer 对 frozen rubric 的偏离：CAL-20 没有请求 source，因此按 frozen N3/N4 定义不能是 N4。

---

## 11. Human Review Adjudication

保留原 blind human score，不覆盖。

Adjudication 仅针对 CAL-20 novel stage：

```text
raw reviewer: N4
frozen rubric: N3 requires actual source request
trace: requested_sources = []
final adjudication: N2 + decision_relevance_waiver=1
```

Task Success 仍为 1。

这是 rubric enforcement，不是为了提高 agreement 而修改定义。

---

## 12. Kappa 的正确解释

v1.1 后：

```text
human task_success = 30/30 positive
auto task_success  = 30/30 positive
```

confusion matrix：

```text
TP=30
TN=0
FP=0
FN=0
```

此时 Cohen's kappa 的 denominator 为 0，**应报告 undefined / not informative**，而不是写成 `0.000`。

这说明 C0 没有自然 negative task outcome，无法从真实 run 校准 task-success specificity。

因此：

> raw agreement 100% 是真实结果，但不能替代 negative-class calibration。

---

## 13. Negative Control

v1.1 在独立 dry controls 上验证：

```text
30 scripted pass → 30/30 task_success
30 scripted fail → 0/30 task_success
```

说明 scorer 的机械 positive/negative 路径有区分能力。

但 dry fail 不是自然模型输出，因此不能替代 C1 的真实困难样本。

---

## 14. C1 必须修复的 Benchmark 设计问题

C1 DeepSeek cross-style calibration 必须避免 C0 的 ceiling：

```text
1. 至少部分 fixture 的正确答案需要真正 decision-relevant novel verification；
2. 增加“看似合理但会导致错误 Decision”的 hard negative；
3. 增加 verified-but-not-integrated 场景，实际覆盖 N3；
4. 增加 benign unknown，测试 unnecessary verification；
5. scorer-v1.1 必须在第一个 DeepSeek 请求前冻结，不能边看 C1 结果边改。
```

---

## 15. v1.1 不允许的优化

禁止为了提高 agreement：

```text
human 说 N4
→ scorer 自动把所有正确答案升 N4
```

禁止为了提高 Task Success：

```text
忽略 constraint/fatal
```

禁止为了提高 Novel Recovery：

```text
把“正确猜到”算成 verified
```

---

# Final Rule

> **Task correctness、evidence verification depth、decision-relevance waiver 是三个不同变量。**
>
> 不要为了让一个总分好看，把它们重新揉成一个指标。
