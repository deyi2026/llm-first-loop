# AI State Model v1

> 文档类型：Semantic AI State 定义
> 状态：v1 Draft
> 来源：`docs/ARCHITECTURE-ai-operating-v1.md` + LFL 反馈 + Benchmark Spec v0
> 目标：定义 Semantic / Ephemeral / Derived AI State，以及 persistence boundary
> 依赖：`docs/OPERATING-CONTRACT-LITE.md`、`docs/BENCHMARK-ai-operating-v1.md`
> 关键区分：Semantic AI State ≠ Context Projection State ≠ Engine Run State

---

## 核心原则

### 三层状态模型

```text
┌──────────────────────────────────────────────────────┐
│ A. Semantic AI State                                 │
│                                                      │
│ Objective                                            │
│ Constraints                                          │
│ Facts                                                │
│ Hypotheses                                           │
│ Decisions                                            │
│ Open Questions                                       │
│ Evidence refs                                        │
│ Rejected Hypotheses                                  │
└───────────────────────┬──────────────────────────────┘
                        │
                    projection
                        ↓
┌──────────────────────────────────────────────────────┐
│ B. Context Projection State                          │
│                                                      │
│ HOT                                                  │
│ WARM                                                 │
│ COLD refs                                            │
│ Stable prefix / dynamic working set                  │
│ Autonomy level (derived)                             │
│ Drift trigger (derived)                              │
└───────────────────────┬──────────────────────────────┘
                        │
                    execution
                        ↓
┌──────────────────────────────────────────────────────┐
│ C. Engine Run State                                  │
│                                                      │
│ _RunState (现有)                                      │
│ warning flags                                        │
│ stagnation counters                                  │
│ overflow                                             │
│ build info                                           │
└──────────────────────────────────────────────────────┘
```

**这一层划分是架构决策，不是工程便利。** 混在一起会导致"状态越来越胖、语义越来越模糊"。

### 为什么不能把 Semantic AI State 塞进 `_RunState`

`_RunState` 当前包含：

```text
stagnation_state
overflow_reinject_count
context_warning_injected
round_warning_injected
exhaustion_decision_used
last_snapshot_count
last_breakdown
last_build_info
```

这些都是 **Engine Execution State**：

- 解决"本轮是否提醒过"
- 解决"overflow 是否注入过"
- 解决"snapshot 是否节流"
- 解决"当前会话执行状态是否串台"

它们和 Architecture 中的 Objective / Constraints / Facts / Hypotheses / Decisions / Open Questions 是完全不同的抽象层。

**混在一起的代价**：

1. 状态模型越来越胖，无法快速定位"模型认知状态"
2. Engine 代码和 AI 逻辑耦合，修改一处影响另一处
3. Benchmark 无法区分"执行状态"和"认知状态"的变化

### Benchmark 反过来定义 State

```text
Desired Capability
      ↓
Observable Behavior
      ↓
Benchmark
      ↓
Required State / Telemetry
      ↓
Implementation
```

Semantic AI State 的设计不是由现有代码字段决定的，而是由 Benchmark 需要观测的行为决定的。

---

## A. Semantic AI State

### 定义

Semantic AI State 是模型认知的 SoT（Source of Truth）。它回答：

```text
我们当前在做什么？
我们不能做什么？
我们已经确认了什么？
我们还在怀疑什么？
我们已经决定了什么？
```

### 持久性边界

```text
Durable Semantic State
  跨 compression / restart / model switch 值得恢复

Ephemeral Cognitive State
  只服务当前推理，不一定值得持久化
```

### Durable Semantic State

跨 compression / restart / model switch 值得恢复：

```yaml
mission:
  objective: ""
  # 用户最终想获得的结果，不是当前局部动作

hard_constraints:
  - ""
  # 不能由模型自行优化掉的边界
  # 用户明确要求、安全边界、工作区边界、生产环境边界、测试顺序、禁止修改对象、必须保持的兼容性

confirmed_facts:
  - claim: ""
    authority: high|medium|low
    freshness: current|recent|historical
    scope: runtime|workspace|session|provider|global
    provenance: ""
    confidence: high|medium|low
  # 已验证事实，必须有 provenance

decisions:
  - value: ""
    based_on:
      - ""
    reopen_if:
      - ""
  # 已作出的决策，记录成立条件

open_questions:
  - question: ""
    decision_relevance: ""
    # 只包含可能改变当前 Decision / Action 的未知量
    # 这是 Decision-Relevant Uncertainty 的基础

open_hypotheses:
  - claim: ""
    why_still_open: ""
    cheapest_discriminating_test: ""
    evidence_refs: []
    # 仅保存跨 compression / restart / model switch 后仍需要继续的关键假设

rejected_hypotheses:
  - claim: ""
    rejection_reason: ""
    # 被拒绝的假设，避免重复踩坑

evidence_refs:
  - claim: ""
    source: ""
    scope: ""
    # 证据引用，不是证据本身
```

### Ephemeral Cognitive State

只服务当前推理，不一定值得持久化：

```yaml
active_hypotheses:
  - claim: ""
    supporting_evidence: []
    contradicting_evidence: []
    cheapest_discriminating_test: ""
    status: open|supported|rejected

candidate_next_actions:
  - action: ""
    expected_information_gain: ""
    cost: ""
    risk_tier: 0|1|2|3

current_information_gap: ""

temporary_observations:
  - ""
  # 尚未经过 provenance/scope 检查的原始输入

current_risk_assessment:
  level: low|medium|high
  basis: ""
```

### 持久性决策规则

| 状态 | 持久化 | 原因 |
|------|--------|------|
| mission.objective | ✅ | 跨压缩/重启必须恢复 |
| hard_constraints | ✅ | 跨压缩/重启必须恢复 |
| confirmed_facts | ✅（有条件） | 不是所有 Fact 都永久保留；只有跨轮/跨恢复仍有决策价值的 Fact 才进入 Durable State |
| decisions | ✅ | 已关闭决策防止重开 |
| open_questions | ✅（有条件） | 仅保留仍会改变后续 Decision 的未知量 |
| open_hypotheses | ✅（有条件） | 仅保留跨恢复边界仍需继续验证的关键假设 |
| rejected_hypotheses | ✅（有条件） | 仅保留高复发/高成本/会影响未来决策的拒绝结论 |
| evidence_refs | ✅ | 引用比复制更省 token |
| active_hypotheses | ❌ | 当前推理中间态，压缩后可丢弃 |
| candidate_next_actions | ❌ | 当前决策候选，压缩后可丢弃 |
| current_information_gap | ❌ | 当前推理中间态 |
| temporary_observations | ❌ | 未验证输入，压缩后可丢弃 |
| current_risk_assessment | ❌ | 当前态，下一轮可能变化 |

---

## Semantic State 生命周期与晋级规则

“已确认”不等于“永久保存”。Durable Semantic State 必须控制增长，否则长期运行会把 Semantic State 重新变成历史堆积。

### Durable Admission

一个 Fact / Hypothesis / Decision 只有满足至少一项条件时才值得进入 Durable State：

```text
- 跨 compression / restart / model switch 后仍会影响 Decision；
- 是 Hard Constraint 或其解释依据；
- 是已关闭 Decision 的关键 based_on / reopen_if；
- 若丢失会显著增加重复调查或高成本错误风险；
- 是后续任务高概率复用的稳定技术事实。
```

否则应留在当前 working set，或只保留 evidence reference。

### Refresh / Demote / Retire

Durable State 也必须允许降级：

```text
current fact --freshness expires--> needs_refresh
needs_refresh --no longer decision-relevant--> evidence_ref only
open question --resolved/stale--> retire
rejected hypothesis --low recurrence value--> retire
decision --no longer relevant to active mission--> archive
```

### Compression / Restart Checkpoint

`active_hypotheses` 默认是 Ephemeral，但在 compression / restart / model switch 边界前，如果某个假设仍是 decision-relevant，必须先把最小恢复信息晋级为 `open_hypotheses`：

```yaml
open_hypotheses:
  - claim: ""
    why_still_open: ""
    cheapest_discriminating_test: ""
    evidence_refs: []
```

恢复后可以重新派生完整的 `active_hypotheses`。这避免“为了保持状态轻量而把正在进行的关键调查一起压没”。

## B. Context Projection State

### 定义

Context Projection State 是 Semantic AI State 在当前请求下的投影。它回答：

```text
当前决策需要什么信息？
这些信息应该放在 prompt 的什么位置？
```

### 与 Semantic AI State 的关系

```text
Semantic AI State
      │
      │ projection
      ↓
Context Projection State
      │
      │ execution
      ↓
Engine Run State
```

Context Projection State 不是 Semantic AI State 的副本，而是：

```text
Semantic AI State
  + Current request
  + Current evidence
  + Current decision context
  ↓
Derived Projection
```

### 内容

```yaml
hot:
  - objective
  - hard_constraints
  - current_decisions
  - open_questions
  - latest_critical_evidence
  - current_plan
  # 当前任务成功必须知道
  # 直接 inline，高信息密度，尽量短，每轮可见

warm:
  - previous_findings
  - rejected_hypotheses
  - benchmark_summaries
  - recent_decisions
  - reusable_technical_facts
  # 可能很快再次使用，但当前不必完整展开
  # compact summary + reference，必要时展开

cold_refs:
  - raw_logs
  - full_tool_outputs
  - old_session_transcripts
  - large_source_files
  - historical_search_results
  # 原始证据和历史细节
  # reference only，retrieval on demand
```

### 重要区分：HOT ≠ 高可信

```text
HOT ≠ 高可信
COLD ≠ 低可信
```

HOT 表示**当前决策相关性高**。

例如一个"尚未验证但会决定下一步"的 hypothesis，也可以是 HOT。

### Derived State（不持久化）

以下内容**不应该成为持久化事实**：

```yaml
autonomy_level: high|medium|low
  # 不是长期事实
  # 下一轮风险变高，它可能立刻变成 low

next_best_action: ""
  # 不是长期事实
  # 下一轮证据变化，它可能立刻变化

drift_trigger: ""
  # 不是长期事实
  # 下一轮事件变化，它可能立刻变化

context_temperature: HOT|WARM|COLD
  # 不是事实属性
  # 是"当前 Decision 下的信息相关性"
```

这些是 Derived State：

```text
Semantic State
  + Current request
  + Current evidence
  ↓
Derived Projection
```

它们应该在每次请求时重新计算，而不是持久化。

---

## C. Engine Run State（现有，不动）

### 定义

Engine Run State 是执行机械状态，不是模型认知状态。

### 现有内容

```yaml
stagnation_state:
  fp: null|str
  count: int
  reminded: bool

overflow_reinject_count: int

context_warning_injected: bool

round_warning_injected: bool

exhaustion_decision_used: bool

last_snapshot_count: int

last_breakdown: any

last_build_info: any
```

### 与 Semantic AI State 的边界

| 维度 | Semantic AI State | Engine Run State |
|------|------------------|------------------|
| 归属 | 模型认知 | 执行机械 |
| 持久化 | 值得持久化 | 会话内有效 |
| 修改频率 | 事件触发 | 每轮/每次执行 |
| 可见性 | 模型可见 | 模型不可见 |
| 示例 | Objective, Constraints, Decisions | stagnation, overflow, snapshot |

**原则**：Engine Run State 的原始机械字段不是 Semantic SoT，不应直接进入模型认知状态。必要的执行信号（例如“上下文即将耗尽”）可以经过明确投影进入 Context，但 `count/flag/build_info` 等原始机械状态仍保持模型不可见。

---

## State 转换规则

### Observation → Candidate Fact

```text
Observation
  + provenance check
  + scope check
  ↓
Candidate Fact
```

条件：
- 来源可追溯
- 范围明确
- 时效可判断

### Candidate Fact → Fact

```text
Candidate Fact
  + authority check
  + freshness check
  + conflict check
  ↓
Fact
```

条件：
- 权威性足够
- 时效性符合当前任务
- 与已有 Fact 无冲突

### Observation → Hypothesis

```text
Observation (schema-unknown / anomalous)
  ↓
Quarantine
  ↓
Hypothesis candidate
  ↓
Targeted Verification
```

条件：
- 不直接进入 Fact
- 不直接触发高风险动作
- 需要验证后才能升级

### Fact → Decision

```text
Fact
  + constraint check
  + scope check
  + risk assessment
  ↓
Decision
```

条件：
- 有足够 Fact 支持
- 不违反 Constraint
- 影响范围明确
- 记录成立条件（based_on / reopen_if）

### Decision → Action

```text
Decision
  + risk tier check
  + verification level check
  ↓
Action
```

条件：
- Tier 0：自由执行
- Tier 1：基本 scope 检查
- Tier 2：FACT support + constraint check + scope check + rollback understanding
- Tier 3：更严格验证或用户授权

---

## 与 Benchmark 的观测映射（非 Ground Truth）

**重要**：Semantic AI State 只能作为解释性 telemetry / behavior trace，不能作为 Benchmark 正确性的 Ground Truth。Ground Truth 必须来自 fixture oracle、外部 scorer、实际 action trace 或真实环境结果。


### Drift Injection Benchmark 需要的 State

| Benchmark 指标 | 需要观测的 State |
|---------------|-----------------|
| Drift Detection Rate | confirmed_facts（解释模型是否采信；最终评分由 fixture oracle + 输出/动作 trace 决定） |
| False Positive Rate | confirmed_facts（解释状态；最终评分由 fixture oracle 决定） |
| Novel Signal Recovery Rate | active/open hypotheses（解释发现路径；最终评分由 oracle-marked novel signal 是否被验证决定） |

### Long-Horizon Benchmark 需要的 State

| Benchmark 指标 | 需要观测的 State |
|---------------|-----------------|
| Objective Retention Rate | mission.objective（是否变化） |
| Constraint Retention Rate | hard_constraints（是否被违反） |
| Closed Decision Stability | decisions.reopen_if（是否被无理由重开） |
| Compression Recovery Rate | Context Projection（压缩后恢复速度） |

### Information-Gain Benchmark 需要的 State

| Benchmark 指标 | 需要观测的 State |
|---------------|-----------------|
| Information-Gain Tool Ratio | candidate_next_actions（是否选择高信息增益动作） |
| Duplicate Tool Call Rate | temporary_observations（是否重复搜索） |
| Unnecessary Reopen Rate | decisions.reopen_if（是否无理由重开） |

---

## v1 待补充内容

| 内容 | 归属 | 原因 |
|------|------|------|
| State 序列化格式 | Implementation | 如何持久化 Semantic State |
| State 投影算法 | Implementation | 如何从 Semantic State 生成 Context Projection |
| Telemetry 字段映射 | Implementation | 如何从 State 生成 Benchmark 指标 |
| Compression 策略 | Implementation | 如何在压缩时保留 Durable State |
| Restart 恢复逻辑 | Implementation | 如何从持久化 State 恢复 |

---

## 一句话版本

> **Semantic AI State 是模型认知的 SoT；Context Projection 是当前决策下的信息布局；Engine Run State 是执行机械状态。三层分离，各司其职。**