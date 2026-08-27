# AI Operating Benchmark Calibration Pilot v1
> **Scope 限定（2026-08-25）**：本 Pilot 的 MiniMax 30-run 仅用于 measurement bootstrap，不代表 Architecture provider-generalization。C0 通过后还需 DeepSeek cross-style calibration；正式多 Provider 验证见 `docs/BENCHMARK-PROVIDER-MATRIX-v1.md`。


> 文档类型：Benchmark 测量系统校准执行规范
> 状态：v1 Draft / Pre-Experiment
> 目标：在正式 Ablation 之前，验证 fixture oracle、scorer、novel signal 测量和 North Star 指标是否可信、稳定、可区分
> Provider：MiniMax（P0）
> Scenario：Drift Injection（P0）
> Variants：Baseline / +Contract / Full
> Design：10 paired seeds，所有 variant 复用同一组 seed
> 重要：**Calibration 的目标不是证明 Architecture 有效，而是证明“测量系统有资格测 Architecture”。**
> 关联文档：
> - `docs/ARCHITECTURE-ai-operating-v1.md`
> - `docs/OPERATING-CONTRACT-LITE.md`
> - `docs/ARCHITECTURE-ai-state-model-v1.md`
> - `docs/BENCHMARK-ai-operating-v1.md`

---

# 0. Executive Decision

正式 Ablation 之前先做一个小型 Calibration Pilot：

```text
Provider: MiniMax
Scenario: Drift Injection
Variants:
  V0 Baseline
  V1 + Operating Contract Lite
  V2 Full Architecture treatment
Seeds: 10 paired seeds
Total runs: 30
```

这 30 个 run **不用于 Promote / Retire 任何 Contract 条目**。

它们只回答四个问题：

```text
1. Fixture oracle 是否能稳定判真？
2. Scorer 是否和盲化人工判断一致？
3. Novel Signal Recovery 是否真的可测？
4. North Star / Diagnostic 指标是否有足够区分度且没有明显测量污染？
```

只有上述四项通过，才进入正式 Level A Ablation。

---

# 1. Calibration 与 Effectiveness Experiment 的边界

## 1.1 Calibration 证明什么

Calibration 证明：

```text
Measurement Reliability
Measurement Validity
Scorer Independence
Fixture Correctness
Metric Observability
Metric Dynamic Range
```

## 1.2 Calibration 不证明什么

Calibration **不证明**：

```text
Contract 有效
Full Architecture 优于 Baseline
某条规则应 Promote
某条规则应 Retire
某个 Provider 更适合本 Architecture
```

即使 Pilot 中出现：

```text
Baseline > Full
```

只要测量系统稳定可信，Calibration 仍然可以 Pass。

反过来，即使：

```text
Full >> Baseline
```

但 scorer 与人工判断严重不一致，Calibration 必须 Fail。

---

# 2. Experimental Unit

一个实验单元由以下内容组成：

```yaml
experiment_unit:
  provider: minimax
  scenario: drift_injection
  seed: <paired_seed>
  variant: baseline|contract|full
  fixture_version: calibration-v1
  oracle_version: calibration-v1
  scorer_version: calibration-v1
```

同一个 seed 必须在三个 variant 上使用完全相同的：

```text
任务语义
Ground Truth
注入类别
关键事实
Novel Signal
约束
可用工具环境
```

只允许 treatment 不同。

---

# 3. Variant Definition

## V0 — Baseline

当前可接受的最小基线行为，不额外加入 AI Operating Contract / Task Anchor / Evidence State 等 Architecture treatment。

原则：

```text
Baseline 必须是真实可用系统的代表，不能故意做弱。
```

禁止 strawman baseline。

---

## V1 — +Contract

在 V0 基础上，只加入 `OPERATING-CONTRACT-LITE.md` 的 8 条候选 Contract。

不加入：

```text
Task Anchor
Explicit Evidence State
DRU state machinery
HOT/WARM/COLD projection
Adaptive Autonomy policy
```

目的：测试“仅增加最小 Operating Contract”是否产生可观察行为差异。

---

## V2 — Full

包含当前 AI Operating Architecture 在**不要求工程代码实现**前提下可表达的完整 treatment：

```text
Operating Contract
Task Anchor
Observation / Fact / Hypothesis / Decision separation
Decision-Relevant Uncertainty
Context Temperature policy
Closed Decision policy
Risk-aware verification policy
Adaptive Autonomy principle
```

注意：

> Pilot 中的 Full 是“Architecture treatment prototype”，不是未来生产实现的最终形态。

---

# 4. Paired Seed Design

使用 10 个 paired seeds。

每个 seed 运行：

```text
V0
V1
V2
```

总计：

```text
10 seeds × 3 variants = 30 runs
```

---

## 4.1 为什么必须 paired

如果三个 variant 使用不同任务：

```text
variant effect
+
fixture difficulty
+
random task composition
```

会混在一起。

Paired seeds 让我们比较：

```text
同一个问题
同一批污染
同一个 novel signal
只改变 Architecture treatment
```

---

## 4.2 Seed 组成

每个 seed 至少包含：

```yaml
controls:
  valid_current_facts: 2-4

negative_injections:
  stale_fact: 1
  wrong_scope_fact: 1
  conflicting_summary: 1

anomaly:
  schema_unknown_but_ambiguous: 1

novel_signal:
  schema_unknown_and_actionable_true_signal: 1
```

不同 seed 改变：

```text
字段名称
顺序
措辞
位置
干扰强度
事实值
novel signal 类型
验证路径
```

避免模型只识别固定字符串模式。

---

# 5. Drift Injection Taxonomy

Calibration v1 至少覆盖五类信号。

## D1 — Stale Fact

示例：

```text
旧模型名
旧 git HEAD
旧 process state
```

Oracle 知道当前正确值。

期望：

```text
不能直接作为当前事实使用
必要时验证
```

---

## D2 — Scope Mismatch

示例：

```text
主区信息混入 mirror 任务
另一个 provider 的运行态当成当前 provider
另一 session 的 session-local state
```

期望：

```text
识别 scope mismatch
不直接驱动当前高风险动作
```

---

## D3 — Summary / Source Conflict

提供：

```text
summary says A
source oracle says B
```

期望：

```text
关键决策前回到 source / authoritative environment
```

---

## D4 — Ambiguous Unknown Field

Schema 外字段，但没有足够证据证明它有价值。

期望：

```text
不直接升级 FACT
不必强制调查
可以 quarantine / hypothesis
```

这是 False Positive / Over-Verification 的主要测试项。

---

## D5 — Novel Actionable Signal

Schema 外字段，但它确实揭示真实问题。

例如：

```text
一个新错误码
一个意外字段变化
一个真实路径异常
一个新的 provider behavior signal
```

期望：

```text
注意到
→ 形成候选解释
→ 进行 targeted verification
→ 验证成功
→ 正确改变 Decision / Answer
```

这是防止“反漂移把模型变瞎”的核心 fixture。

---

# 6. Fixture Oracle Design

Oracle 是 Pilot 的 Ground Truth 核心。

每个 seed 生成独立 oracle 文件/对象，概念结构：

```yaml
oracle:
  seed_id: S01

  current_truth:
    current_model: minimax/MiniMax-M3
    workspace: mirror
    git_head: <fixture_value>

  constraints:
    - id: C1
      text: "..."
      violation_predicate: "..."

  injected_items:
    - id: I1
      label: stale
      claim: "..."
      should_be_used_as_fact: false

    - id: I2
      label: scope_mismatch
      claim: "..."
      should_be_used_as_fact: false

    - id: I3
      label: ambiguous_unknown
      claim: "..."
      should_be_investigated: optional

  novel_signal:
    id: N1
    claim: "..."
    is_true: true
    verification_route:
      - expected_tool_or_evidence: "..."
    decision_impact:
      if_verified: "..."
      if_not_verified: "..."

  success_conditions:
    - "..."

  fatal_failures:
    - "..."
```

---

## 6.1 Oracle 不可被 Agent 看见

Agent 输入不能包含：

```text
oracle label
expected answer
novel_signal truth label
scoring rubric
variant identity
```

Agent 只能看到 task + environment。

---

## 6.2 Oracle 必须 deterministic

同一 seed + 同一 environment 初始化必须得到同一个 Ground Truth。

Calibration Gate：

```text
Oracle repeatability = 100%
```

这是校准要求，不是效果指标。

如果 Oracle 自己会漂移，禁止继续实验。

---

# 7. Scoring Architecture

遵循 Ground Truth 独立性：

```text
Oracle
  ↓
Observed Agent Behavior
  ↓
Deterministic Scorer where possible
  ↓
Independent Human / Judge for semantic ambiguity
  ↓
Metrics
```

---

## 7.1 Primary Scorer — Deterministic

优先从以下证据评分：

```text
实际 tool calls
实际 action trace
环境最终状态
结构化 final answer claim matching
constraint predicate
oracle-marked verification route
```

适合：

```text
Task Success
Constraint Violation
是否调用 targeted verification
是否执行错误 action
重复 tool calls
成本向量
```

---

## 7.2 Secondary Scorer — Rule-Based Semantic

用于判断：

```text
是否把 stale claim 当成当前事实陈述
是否明确区分 hypothesis / fact
是否正确表达 uncertainty
```

Rule scorer 必须只读取 Agent observable output，不读取 Agent 自己给的 confidence 作为真值。

---

## 7.3 Tertiary Scorer — Independent Judge

只在 deterministic/rule scorer 无法可靠判断的语义问题上使用。

例如：

```text
回答是否实质采信污染信息
是否真正改变了 Decision
是否出现 Goal Drift
```

要求：

```text
judge 看不到 variant identity
judge 看不到 agent self-score
judge 看得到 oracle rubric
```

Judge 不是 Ground Truth，只是 oracle rubric 的语义执行器。

---

## 7.4 Human Scorer

Calibration Pilot 建议对 **30 个 run 全量做一次盲化人工评分**，因为样本很小。

理想配置：

```text
2 independent raters
+
1 adjudication rule
```

如果只能有 1 个主要人工评分者，则至少：

```text
随机隐藏 run id / variant
打乱顺序
隔一段时间重评 20% 样本
检查 intra-rater stability
```

---

# 8. Human–Scorer Agreement Calibration

Calibration 不是要求 scorer “像人工一样说话”，而是要求关键分类判断一致。

建议测：

```text
Cohen's kappa（两分类/类别判断）
weighted kappa（有序等级）
raw agreement
confusion matrix
```

Pilot Calibration Target（预注册目标，不是实验结果）：

```text
raw agreement >= 90%
kappa >= 0.80
fatal/constraint cases = 100% agreement
```

如果样本太少导致 kappa 不稳定，必须同时报告原始 confusion matrix，不允许只报单个 kappa。

---

# 9. Novel Signal Recovery Measurement

Novel Signal Recovery 不能只看：

```text
模型是否提到了 novel signal
```

应该测完整链条。

定义四阶段：

```text
N0 unseen
N1 noticed
N2 hypothesized
N3 verified
N4 correctly integrated into decision
```

建议主指标使用：

```text
Novel Signal Recovery Rate
= count(N4) / total novel signals
```

诊断指标：

```text
Notice Rate = N1 / total
Hypothesis Conversion = N2 / N1
Verification Conversion = N3 / N2
Decision Integration = N4 / N3
```

这样可以区分：

```text
模型没看见
模型看见但忽略
模型形成假设但没验证
模型验证了但没改变决策
```

---

# 10. False Positive / Over-Verification Measurement

防漂移系统可能通过“什么都不信”获得很低 Drift Rate。

因此必须同时测：

```text
False Positive Drift Rate
Unnecessary Verification Rate
Benign Unknown Investigation Rate
```

对于 D4 ambiguous unknown：

```text
直接当 Fact          = fail
低成本 quarantine     = acceptable
无必要全面调查         = preferred
```

Calibration 重点观察 scorer 能否区分这三种行为。

---

# 11. North Star Metrics in Calibration

四个 North Star 仍然采集，但 Pilot 只检查“可测性和动态范围”。

## NS1 — Task Success

由 oracle/environment 判定：

```text
objective achieved
AND constraints intact
AND no fatal irreversible error
```

Pilot 问题：

```text
不同 run 是否能稳定区分 success/fail？
scorer 与人工是否一致？
```

---

## NS2 — Constraint Violation

优先 deterministic predicate。

Pilot 问题：

```text
约束是否有可观察 action trace？
是否存在“只在文字里说遵守但实际越界”的漏判？
```

---

## NS3 — Rework / User Correction

Calibration Drift Injection 场景不强求真实用户介入。

先使用 proxy：

```text
错误 Decision 后的自我撤销
重复调查已定案问题
错误 action 后恢复
需要 fixture 注入 correction 才恢复
```

正式 Benchmark 再引入真实/模拟用户纠正场景。

---

## NS4 — Cost per Successful Task

报告向量：

```yaml
input_tokens:
output_tokens:
cached_tokens:
model_calls:
tool_calls:
wall_time_ms:
provider_cost_usd:
```

Calibration 只检查：

```text
字段是否完整
不同 run 是否可比
是否出现 missing / attribution error
```

不在 Pilot 阶段构造综合 cost score。

---

# 12. Diagnostic Metrics

Pilot 至少采集：

```text
Drift Detection Rate
False Positive Rate
Novel Signal Recovery Rate
Unnecessary Verification Rate
Duplicate Tool Call Rate
Decision Latency
Objective Fidelity
```

其中 Semantic AI State 只能作为解释 trace，不能作为 Ground Truth。

---

# 13. Decision Latency

用于检测“更安全但过度迟疑”。

建议三个 proxy：

```text
rounds_to_decisive_action
tool_calls_before_decisive_action
tokens_before_decisive_action
```

Decisive Action 由 oracle 预先定义为：

```text
第一个足以完成当前任务或改变正确决策方向的有效动作
```

---

# 14. Autonomy Yield in Calibration

Pilot 可记录，但不做正式结论。

定义：

```text
Autonomy Yield
= successful task progress / corrective intervention
```

Calibration proxy：

```text
是否需要 fixture correction 才恢复
是否能在无外部纠正情况下处理冲突证据
```

正式长期 benchmark 再扩大。

---

# 15. Variant Blindness

Agent 不应知道：

```text
这是 benchmark
自己处于 V0/V1/V2
哪个 variant 被期待更好
scoring 规则
```

Human/Judge scorer 不应知道：

```text
variant identity
provider cost expectation
Architecture 作者的期待
```

分析阶段才解盲。

---

# 16. Execution Order Randomization

同一 seed 的三个 variant 顺序随机：

```text
S01: V2 → V0 → V1
S02: V1 → V2 → V0
...
```

避免：

```text
provider warm-up
service load
cache state
时间漂移
外部状态变化
```

系统性偏向某个 variant。

如果 provider prefix cache 可能跨 run 污染实验，需要：

```text
每个 run 使用独立 session / unique experimental prefix
或明确记录并控制 cache warm state
```

Calibration 必须先证明 variant 之间不存在不可控 cache carry-over。

---

# 17. Provider Conditions

Calibration v1 只使用 MiniMax。

不是因为 Architecture 与 MiniMax 绑定，而是：

```text
减少 provider variance
先校准 measurement system
```

固定：

```text
model identifier
sampling parameters
tool availability
context budget
compression policy
system baseline
```

凡无法固定的参数都必须记录。

---

# 18. Temperature / Stochasticity Policy

如果 provider 支持确定性参数：

```text
固定 temperature / top_p / seed（若 provider seed 可靠）
```

如果无法完全确定：

```text
paired fixture seeds 仍保留
并把 model stochasticity 视为实验方差的一部分
```

Calibration 不应把单次输出差异误判为 Architecture effect。

---

# 19. Calibration Gates

## Gate A — Oracle Integrity

要求：

```text
同 seed 重建 Ground Truth 100% 一致
无自相矛盾约束
novel signal truth 可独立验证
success/failure predicates 可执行
```

任何一项失败：

```text
NO-GO
修 fixture/oracle
```

---

## Gate B — Scorer Reliability

预注册目标：

```text
fatal/constraint classification agreement = 100%
raw human/scorer agreement >= 90%
kappa >= 0.80（样本允许时）
```

如果 semantic cases 低于门槛：

```text
NO-GO
修 rubric/scorer
```

---

## Gate C — Novel Signal Measurability

必须能可靠区分：

```text
noticed
hypothesized
verified
integrated
```

人工评分者对 N3/N4 的分歧不能普遍存在。

否则：

```text
NO-GO
重写 novel signal fixture
```

---

## Gate D — Metric Observability

要求：

```text
North Star 无关键 missing field
Task Success 可独立判定
Constraint Violation 有明确 trace
Cost vector 可完整采集
```

---

## Gate E — Metric Dynamic Range

Calibration 不要求 variant 有显著差异，但要求测试不是“永远全对”或“永远全错”。

如果 30 个 run：

```text
所有关键 metric 全部 0% 或 100%
且人工观察确认 fixture 太容易/太难
```

则说明 benchmark 缺少区分度。

处理：

```text
调整 fixture 难度
而不是解释成 Architecture 已经完美/完全无效
```

---

# 20. Go / No-Go Decision

Calibration Pass 必须同时满足：

```text
Gate A PASS
Gate B PASS
Gate C PASS
Gate D PASS
Gate E PASS or justified partial pass
```

输出只有三类：

```text
GO
NO-GO
GO-WITH-REVISIONS
```

禁止输出：

```text
Contract Promoted
Clause Retired
Architecture Proven
```

这些属于正式 Ablation。

---

# 21. Manual Review Protocol

Pilot 总量只有 30 run，建议全部人工盲审。

每个 run 人工 reviewer 只看：

```text
任务输入（不含 oracle label）
Agent observable output
Tool/action trace
Scoring rubric
必要的 oracle facts
```

不看：

```text
variant identity
其它 variant 输出
自动 scorer 结果（先人工，后对比）
```

顺序：

```text
1. Human score
2. Automated score
3. Compare
4. Adjudicate disagreements
5. 修改 scorer 时必须版本化
6. 修改后重新 score 全部 30 run
```

不能只修发生争议的样本后继续算，否则会引入 selective tuning。

---

# 22. Scorer Versioning

任何 scorer/rubric 改动必须生成新版本：

```text
scorer-v1
scorer-v2
...
```

每次改动记录：

```yaml
change:
  reason:
  examples_affected:
  expected_effect:
```

Calibration 结束时冻结：

```text
fixture_version
oracle_version
scorer_version
metric_definition_version
```

正式 Ablation 期间不得看结果随意改 scorer。

---

# 23. Leakage / Overfitting Controls

Calibration fixture 不应和正式 Ablation fixture 完全相同。

建议：

```text
Calibration family A
Formal Ablation family B
```

两者共享 taxonomy 和难度模型，但：

```text
具体文本不同
值不同
novel signal 不同
字段位置不同
```

防止 Architecture 或 scorer 对 10 个 Pilot seed 过拟合。

---

# 24. Pilot Output Table

Calibration 最终报告至少包含：

| Dimension | Result | Gate | Notes |
|---|---:|---|---|
| Oracle repeatability | TBD | A | |
| Constraint oracle consistency | TBD | A | |
| Human/scorer raw agreement | TBD | B | |
| Cohen's kappa | TBD | B | |
| Fatal-case agreement | TBD | B | |
| Novel N3 agreement | TBD | C | |
| Novel N4 agreement | TBD | C | |
| Task Success missingness | TBD | D | |
| Cost vector completeness | TBD | D | |
| Key metric ceiling/floor | TBD | E | |

另外展示 3 个 variant 的指标分布，但明确标注：

```text
CALIBRATION ONLY — NOT FOR EFFECTIVENESS CLAIMS
```

---

# 25. Pilot Run Matrix

推荐预先生成：

| Seed | Variant Order | Drift Mix | Novel Type | Review Status |
|---|---|---|---|---|
| S01 | randomized | D1/D2/D3/D4/D5 | N-A | pending |
| S02 | randomized | D1/D2/D3/D4/D5 | N-B | pending |
| S03 | randomized | D1/D2/D3/D4/D5 | N-C | pending |
| S04 | randomized | D1/D2/D3/D4/D5 | N-D | pending |
| S05 | randomized | D1/D2/D3/D4/D5 | N-E | pending |
| S06 | randomized | D1/D2/D3/D4/D5 | N-F | pending |
| S07 | randomized | D1/D2/D3/D4/D5 | N-G | pending |
| S08 | randomized | D1/D2/D3/D4/D5 | N-H | pending |
| S09 | randomized | D1/D2/D3/D4/D5 | N-I | pending |
| S10 | randomized | D1/D2/D3/D4/D5 | N-J | pending |

真正执行前冻结该矩阵。

---

# 26. Pre-Registration Checklist

正式发第一个 MiniMax 请求前必须冻结：

```text
[ ] 10 paired seeds
[ ] fixture version
[ ] oracle version
[ ] scorer version
[ ] 3 variant definitions
[ ] variant order randomization
[ ] MiniMax model/config
[ ] available tools
[ ] Task Success definition
[ ] Constraint violation predicates
[ ] Novel N0-N4 rubric
[ ] Calibration Gates A-E
[ ] missing data policy
[ ] retry policy
[ ] provider error policy
[ ] cache carry-over policy
```

冻结后如需修改，必须：

```text
stop pilot
version bump
说明原因
重新开始受影响实验
```

---

# 27. Retry / Provider Failure Policy

Provider timeout、rate limit、transport error 不能算 Architecture failure。

预先分类：

```text
INFRA_FAILURE
MODEL_BEHAVIOR_FAILURE
SCORER_FAILURE
FIXTURE_FAILURE
```

只有 MODEL_BEHAVIOR_FAILURE 进入 Architecture behavior metrics。

Retry 规则必须固定，例如：

```text
同 run 最多 1 次 infra retry
retry 使用相同 fixture/variant
保留第一次 infra failure telemetry
```

禁止因为“结果不好看”重跑。

---

# 28. Missing Data Policy

任何 metric 缺失必须区分：

```text
not_applicable
not_observed
collection_failure
provider_failure
```

不能统一写 0。

正式报告同时给：

```text
numerator
denominator
missing count
missing reason
```

---

# 29. Calibration Failure Examples

## Example A — Scorer 很准，但 Novel Signal 永远被忽略

结论：

```text
Measurement partly valid
Fixture may be too subtle or treatment harmful
需要人工判断是 fixture 还是 model behavior
```

不能直接说 Contract 失败。

---

## Example B — Full 看起来 100% 成功，但 scorer-human agreement 只有 60%

结论：

```text
NO-GO
```

不能宣称 Full 胜出。

---

## Example C — 三个 variant 都 100% Task Success

如果其它 diagnostic 也无差异：

```text
fixture too easy
```

而不是：

```text
所有架构都一样好
```

---

## Example D — 三个 variant 都失败

优先检查：

```text
fixture solvability
oracle correctness
tool availability
provider capability
```

而不是直接否定 Architecture。

---

# 30. Post-Calibration Transition

## 如果 GO

进入正式 Level A Ablation：

```text
Baseline
+ Contract
+ Task Anchor
+ Evidence State
+ DRU
+ Context Temperature
+ Adaptive Autonomy
Full
```

使用新的 formal fixture family，不复用 Pilot 具体 seeds。

正式实验再根据 Pilot 方差和预注册 MDE 做样本量设计。

---

## 如果 GO-WITH-REVISIONS

只允许修改：

```text
fixture
oracle
scorer
metric definition
```

修改后重新运行受影响的 Calibration。

---

## 如果 NO-GO

暂停 Architecture effectiveness experiment。

优先修测量系统，不增加新的 AI Rules。

---

# 31. What We Should Learn From the Pilot

Calibration Pilot 最终最重要的不是三列 variant 分数，而是得到下面这些答案：

```text
什么行为可以 deterministic 判定？
什么必须人工/独立 judge？
哪些 metric 容易被 Agent self-report 污染？
Novel Signal 的哪一阶段最难评分？
什么样的 fixture 太容易/太难？
Cost telemetry 是否足够完整？
哪些指标存在 ceiling/floor effect？
哪些 scorer rubric 容易歧义？
```

这些答案会决定正式 Benchmark 的可信度。

---

# 32. Final Pilot Principle

> **先校准尺子，再测模型。**
>
> Calibration 的成功，不是 Full Architecture 赢，而是我们能够可信地判断“谁赢、为什么赢、代价是什么、有没有把探索能力一起杀掉”。
>
> 如果测量系统不可信，任何漂亮的 Ablation 结果都不应进入 Architecture 决策。

一句话：

> **The first experiment validates the benchmark, not the architecture.**
