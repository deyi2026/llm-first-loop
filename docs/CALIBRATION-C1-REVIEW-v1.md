# C1 DeepSeek Calibration Review v1

> 文档类型：Post-Execution Independent Review
> 审阅对象：`CALIBRATION-C1-RESULT-v1.md` / `CALIBRATION-FROZEN-C1.md`
> 结论：**C1 可作为 exploratory scorer-development + cross-style compatibility evidence；不能作为独立 confirmatory scorer validation。**
> Screening 状态：**NO-GO for formal S; GO for holdout measurement validation.**

---

## 1. Executive Verdict

C1 有三类真实价值：

1. DeepSeek thinking 多轮 tool loop 已真实跑通；
2. scorer 暴露了真实跨表达风格缺陷，并形成 v1.4；
3. over-verification 在 T04 被稳定观察到。

但 C1 不能证明：

```text
scorer-v1.4 已经在独立 DeepSeek holdout 上验证通过
```

因为 v1.4 正是在 C1 的真实输出上开发出来的。

因此 C1 应重分类为：

```text
Exploratory Cross-Style Calibration / Scorer Development
```

而不是：

```text
Independent Cross-Style Validation
```

---

## 2. 核心测量学问题：Post-Outcome Scorer Tuning

Pre-Registration 明确写了：

```text
C1 真实执行开始后，禁止边看 DeepSeek 结果边改 fixture / scorer / matrix。
```

实际发生：

```text
CAL-31 real output
→ scorer v1.3（否定短语 / evaluation markers）

CAL-45 + T02 real outputs
→ scorer v1.4（否定 / 目标语境 / novel integration synonyms）
```

这些修订本身是合理的 scorer bug fix，也都有 version bump 和回归记录；问题不在透明性，而在**数据独立性**。

同一批 18 个 run 同时承担：

```text
发现 scorer 缺陷
+
修改 scorer
+
证明修改后的 scorer 可靠
```

会产生 development-set reuse。

Version bump 能保证 provenance，不能恢复 holdout independence。

---

## 3. Runner Infra Fix 与 Scorer Tuning 必须区分

CAL-31 首次 400：DeepSeek thinking tool-call continuation 需要回传 `reasoning_content`。

这是 wire-protocol / runner infra 缺陷：

```text
模型行为尚未形成可评分输出
→ 修复 protocol
→ INFRA retry
```

该修复可以接受，不构成 benchmark semantic tuning。

但 scorer v1.3/v1.4 不同：

```text
已经看到真实模型语义输出
→ 修改分类规则
```

这属于 measurement development。

两者不能统一写成“version bump 合规，因此均不影响 confirmatory validity”。

---

## 4. C1 Gate Reassessment

| Gate | 原结论 | Review 结论 | 原因 |
|---|---|---|---|
| A Oracle Integrity | PASS | **PASS** | fixture/oracle 未在真实结果后改动 |
| B Scorer Reliability | PASS-WITH-LIMITATION | **DEVELOPMENT PASS / CONFIRMATORY NOT TESTED** | v1.4 对 C1 outputs 有 post-outcome tuning |
| C Novel Measurability | PASS-WITH-LIMITATION | **PARTIAL** | 18/18 N4，无真实 N3/N2/N1 negative stage |
| D Metric Observability | PASS | **PASS** | tool/reasoning/over-verification telemetry 正常 |
| E Metric Dynamic Range | PARTIAL | **FAIL FOR SCREENING READINESS** | task 18/18、fatal 0、constraint 0、novel 全 N4，仅 over-verification 有变化 |

C1 总结：

```text
EXPLORATORY GO
CONFIRMATORY NO-GO
FORMAL SCREENING NO-GO
```

---

## 5. 18/18 Human-Auto Agreement 应如何解释

这 18/18 agreement 仍有价值：

```text
v1.4 能解释 C1 这批输出
```

但不能外推为：

```text
v1.4 能可靠评分新的 DeepSeek 输出
```

因为 scorer 已经针对这些具体语言模式增加：

```text
“不触发全量切换”
“不将…判定为已完全同步”
“实现…完全同步”
T02 v4 integration synonyms
```

正确用法：

```text
C1 = scorer training/development evidence
new unseen set = scorer validation evidence
```

---

## 6. Negative-Class 问题要拆成两个不同问题

### 6.1 Scorer Specificity / Sensitivity

不应该等待真实模型“自然犯错”才能校准 scorer。

应建立**独立、预标注的 behavioral control bank**：

```text
correct + verified + integrated        → N4 / success
verified but ignored                   → N3 / fail or partial depending objective
noticed, planned, no verification      → N2
stale fact adopted                     → stale=1
fatal action recommended               → fatal=1
constraint violation                   → constraint=1
benign unknown over-verified            → unnecessary_verification>0
correct DRU waiver                     → task=1 + waiver=1 + novel<N3
```

这些 controls 用来验证 scorer 的 confusion matrix，不计 model performance。

### 6.2 Benchmark Dynamic Range

另一个问题是：真实模型在 C0/C1 都接近 ceiling。

这需要更难的**真实 holdout fixture**，不是人工造错误回答：

```text
conflicting authoritative sources
late user constraint update + sunk-cost plan
verified evidence conflicts with strong prior
multi-step tool evidence where first source is plausible but stale
novel signal whose verification changes an irreversible action
benign anomaly with expensive distractor tool
verified evidence that requires abandoning an already-written plan
```

二者不能混为“negative-class calibration”。

---

## 7. 推荐新增阶段：C1H Holdout Measurement Validation

在正式 S 前新增：

```text
C1H = C1 Holdout
```

### H1 — Frozen Scorer Control Bank

目的：测 scorer v1.4 的分类准确率。

建议至少：

```text
8 behavior classes × 5 examples = 40 labeled traces
```

要求：

- 全部在 scorer-v1.4 freeze 后生成并锁定；
- scorer 不得在看到 H1 结果后修改；
- 若发现 bug：H1 失败，升级 scorer v1.5，然后必须使用新的 H1b holdout，而不能在原 H1 上重新宣称通过。

建议 Gate：

```text
fatal / constraint: 100% sensitivity + specificity
Task Success: >=95% balanced accuracy
Novel N0-N4: >=90% exact agreement + confusion matrix
stale / scope / ambiguous: >=95% balanced accuracy
```

阈值属于 C1H pre-registration target，不是 Architecture invariant。

### H2 — Unseen DeepSeek Real Holdout

目的：确认 scorer 在 unseen DeepSeek expression 上可用，并检查 benchmark dynamic range。

建议：

```text
8 new paired seeds × 3 variants = 24 real runs
```

但这 24 run 仍然不是 Architecture effectiveness experiment。

要求：

- fixture 文本与 T01-T06 完全不同；
- scorer-v1.4 完全冻结；
- 第一个请求后 zero scorer edits；
- blind human review 在 auto score 解盲前完成；
- 至少包含明确可产生 N2/N3/waiver/over-verification 的结构；
- 任务难度不能依赖“模型必须犯错”，但应避免全 100% ceiling。

---

## 8. C1H 的 Holdout Discipline

最重要的新规则：

```text
如果 scorer 在 H1/H2 上发现 bug：
  1. 当前 holdout 判 FAIL；
  2. 允许修 scorer 并 version bump；
  3. 原 H1/H2 变成 development data；
  4. 必须生成全新的 H1b/H2b 才能重新验证。
```

禁止：

```text
看 holdout
→ 修 scorer
→ 在同一 holdout 上 regrade
→ 宣称 holdout PASS
```

这是 C1 最重要的经验。

---

## 9. 是否进入正式 Multi-Provider Screening？

当前结论：

```text
NO
```

不是因为 DeepSeek 表现不好，而是因为：

```text
measurement system 还没有独立 holdout validation
+
benchmark task-success dynamic range 仍接近 0
```

如果现在进入 S：

```text
MiniMax / DeepSeek / Kimi / GLM
× Baseline / Contract / Full
```

很可能得到：

```text
全部 task_success ≈ 100%
```

然后只剩 token / verbosity / tool-call 差异，无法回答 Architecture 是否提升任务能力。

---

## 10. Screening Readiness Gate

进入 S 前至少满足：

```text
[ ] scorer frozen on a truly unseen holdout
[ ] balanced negative controls pass
[ ] blind human vs scorer agreement meets preregistered thresholds
[ ] real holdout produces more than one observable behavioral outcome
[ ] N3/N2/waiver/over-verification 至少有部分真实覆盖
[ ] no post-outcome scorer tuning on the final holdout
```

满足后再进入：

```text
S — Multi-Provider Screening
MiniMax / DeepSeek / Kimi / GLM
Baseline / Contract / Full
```

---

# Final Decision

> **C1 成功地把 scorer 从 v1.2 推进到了 v1.4，但它因此成为 scorer development set，而不是 scorer validation set。**
>
> 现在不应直接进入正式多 Provider Screening。下一阶段应是 `C1H Holdout Measurement Validation`：用冻结的 v1.4 在全新数据上证明“尺子没有再被这批数据调过”。
