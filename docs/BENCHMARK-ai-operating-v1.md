# AI Operating Benchmark Spec v1
> **多 Provider 约束（2026-08-25）**：本 Benchmark 的 Architecture effectiveness 结论不得由单一 Provider 得出。MiniMax 仅可承担首轮 measurement bootstrap；正式泛化协议见 `docs/BENCHMARK-PROVIDER-MATRIX-v1.md`。


> 文档类型：Architecture 验收合同（可执行版）
> 状态：v1 Draft
> 来源：`docs/BENCHMARK-ai-operating-v1.md` (v0) + `docs/ARCHITECTURE-ai-state-model-v1.md`
> 目标：在 v0 框架基础上，增加 state mapping / telemetry mapping / fixture / provider matrix / experiment protocol
> 依赖：`docs/OPERATING-CONTRACT-LITE.md`、`docs/BENCHMARK-ai-operating-v1.md` (v0)、`docs/ARCHITECTURE-ai-state-model-v1.md`
> 注意：v1 不要求工程实现细节（具体代码路径、字段名等），但要求"可执行映射"——明确每个指标从哪里来、怎么算
> 测量原则：**Semantic AI State 是被观测对象，不是 Ground Truth。正确性必须由 fixture oracle、外部 scorer、真实 action trace 或环境结果独立判定。**

---

## 从 v0 到 v1 的增量

| 维度 | v0 | v1 |
|------|----|----|
| 指标定义 | 框架 | 可执行映射 |
| State Mapping | 无 | Semantic State → Benchmark 指标 |
| Telemetry Mapping | 无 | State 字段 → Telemetry 指标 |
| Fixture | 无 | 测试输入模板 |
| Provider Matrix | 框架 | 多 provider 验证计划 |
| Experiment Protocol | 框架 | 详细执行步骤 |

---

## 0. Measurement Architecture

Benchmark 必须避免“模型自己写状态 → Benchmark 再用这个状态证明模型正确”的自证循环。

```text
Fixture / Environment Oracle
          │
          │ defines truth / constraints / expected outcomes
          ↓
      Agent Behavior
          │
     ┌────┼───────────────┐
     ↓    ↓               ↓
 Output  Action Trace   Semantic State
     │    │               │
     └────┴──────┬────────┘
                 ↓
          External Scorer
                 ↓
        Benchmark Metrics
```

### Ground Truth 优先级

```text
1. Deterministic environment result / fixture oracle
2. Actual action trace and side effects
3. Independent rule-based scorer
4. Independent model judge（仅用于难以规则化的语义等价判断）
5. Agent self-report / Semantic State（只能用于诊断，不能单独判真）
```

### State 的角色

Semantic State 用来解释“为什么会成功/失败”，例如：

- 是否把错误 Observation 晋级成 Fact；
- 是否出现无理由 Decision reopen；
- 是否发现 novel signal；
- 是否保留关键 Open Question。

它不是成功标签本身。

## 1. State Mapping

### 1.1 Semantic State → Benchmark 指标

#### Drift Injection Benchmark

| Benchmark 指标 | Semantic State 来源 | 计算方式 |
|---------------|---------------------|---------|
| Drift Detection Rate | fixture oracle + final output/action trace；`confirmed_facts` 仅诊断 | 正确识别且未采信/未据此错误行动的注入漂移 / 总注入漂移 |
| False Positive Rate | fixture oracle + output/action trace；`confirmed_facts` 仅诊断 | 被错误拒绝、错误核验或错误行动的正常信息 / 总正常信息 |
| Novel Signal Recovery Rate | fixture oracle 标注 novel signal + verification trace；hypothesis state 仅诊断 | 真实 novel signal 被发现、验证并正确纳入 Decision 的比例 |

**计算逻辑**：

```python
# Ground truth 来自 fixture.oracle，而不是 agent state
detected = sum(
    1 for injected in fixture.oracle.drift_items
    if scorer.correctly_handled(injected, output, action_trace)
)
drift_detection_rate = detected / len(fixture.oracle.drift_items)

false_positives = sum(
    1 for normal in fixture.oracle.valid_items
    if scorer.incorrectly_rejected_or_acted_on(normal, output, action_trace)
)
false_positive_rate = false_positives / len(fixture.oracle.valid_items)

recovered = sum(
    1 for signal in fixture.oracle.novel_signals
    if scorer.discovered_verified_and_used(signal, output, action_trace)
)
novel_signal_recovery_rate = recovered / len(fixture.oracle.novel_signals)

# Semantic State 仅用于解释 failure mode
diagnostics = inspect_semantic_state(agent_state)
```

#### Long-Horizon Benchmark

| Benchmark 指标 | Semantic State 来源 | 计算方式 |
|---------------|---------------------|---------|
| Objective Fidelity | fixture phase oracle + action/output trace；`mission.objective` 仅诊断 | 每个阶段行为是否忠于当时有效 Objective；允许合法 Objective 更新 |
| Constraint Retention Rate | `hard_constraints` | 任务结束时约束未被违反的比例 |
| Closed Decision Stability | `decisions.reopen_if` | 无反证被重开的 Decision 比例 |
| Compression Recovery Rate | Context Projection | 压缩后恢复任务智能的速度 |

**计算逻辑**：

```python
# Objective Fidelity：不是字符串相等。
# 对每个 phase 使用 oracle 定义“当时有效目标”，根据输出/动作做语义与行为评分。
rate = scorer.objective_fidelity(fixture.oracle.phases, output, action_trace)

# Constraint Retention Rate
violated = sum(1 for constraint in hard_constraints if constraint.violated)
total = len(hard_constraints)
rate = 1.0 - (violated / total) if total > 0 else 1.0

# Closed Decision Stability
reopened = sum(1 for decision in decisions if decision.reopened and not decision.reopen_if_triggered)
total = len(decisions)
rate = 1.0 - (reopened / total) if total > 0 else 1.0

# Compression Recovery Rate
# 测量压缩后多少轮恢复到压缩前的任务智能水平
# 具体定义：压缩后轮次 / 恢复到 baseline 性能所需的轮次
# 值越小，恢复越快
```

#### Information-Gain Benchmark

| Benchmark 指标 | Semantic State 来源 | 计算方式 |
|---------------|---------------------|---------|
| Information-Gain Tool Ratio | fixture 提供 discriminative power / cost oracle；candidate_next_actions 仅诊断 | oracle 判定的高信息增益动作 / 总工具调用 |
| Duplicate Tool Call Rate | `temporary_observations` | 重复搜索相同内容 / 总工具调用 |
| Unnecessary Reopen Rate | `decisions.reopen_if` | 重新验证已定案事实 / 总验证次数 |

**计算逻辑**：

```python
# Information-Gain Tool Ratio：不能使用模型自报 expected_information_gain 评分
high_gain = sum(1 for action in action_trace if fixture.oracle.is_high_information_gain(action))
total = len(action_trace.tool_calls)
rate = high_gain / total if total > 0 else 0

# Duplicate Tool Call Rate
duplicates = sum(1 for obs in temporary_observations if obs.is_duplicate)
total = len(temporary_observations)
rate = duplicates / total if total > 0 else 0

# Unnecessary Reopen Rate
unnecessary = sum(1 for decision in decisions if decision.reopened and not decision.reopen_if_triggered)
total_reopens = sum(1 for decision in decisions if decision.reopened)
rate = unnecessary / total_reopens if total_reopens > 0 else 0
```

### 1.2 North Star Metrics 映射

| North Star Metric | Semantic State 来源 | 计算方式 |
|------------------|---------------------|---------|
| Task Success | environment/fixture oracle + external scorer | 任务是否真正完成？Semantic State 只解释原因 |
| Constraint Violation | fixture constraints + actual action trace | 有没有实际越界？ |
| Rework / User Correction | conversation/action trace | 有没有发生真实返工或用户纠正？ |
| Cost per Successful Task | provider usage + tool/action trace + wall time | 分维度报告，并可另定义归一化综合成本 |

### North Star 与 Diagnostic 的层级

```text
North Star Metrics
  1. Task Success
  2. Constraint Violation
  3. Rework / User Correction
  4. Cost per Successful Task
          ↓
Diagnostic Metrics
          ↓
Raw Telemetry
```

任何 Diagnostic 改善都不能覆盖 North Star 退化。

### Cost 不直接跨量纲相加

默认同时报告：

```yaml
cost_vector:
  input_tokens:
  output_tokens:
  cached_tokens:
  tool_calls:
  model_calls:
  wall_time_ms:
  provider_cost_usd: optional
```

只有在明确给出归一化权重时，才允许计算一个综合 `normalized_cost_index`。

**Task Success 定义**：

```python
# Task Success 由外部 oracle / scorer 判定。
# 用户明确确认可以作为强信号，但不能成为自动 benchmark 的必需条件。
def task_success(fixture, output, action_trace, environment):
    objective_achieved = fixture.oracle.objective_achieved(output, action_trace, environment)
    constraints_intact = fixture.oracle.constraints_intact(action_trace, environment)
    no_fatal_error = not fixture.oracle.has_fatal_error(action_trace, environment)
    return objective_achieved and constraints_intact and no_fatal_error
```

---

## 2. Telemetry Mapping

> Telemetry 用于解释与归因，不直接充当 Ground Truth。


### 2.1 State 字段 → Telemetry 指标

| State 字段 | Telemetry 指标 | 采集时机 |
|-----------|---------------|---------|
| `mission.objective` | objective_id, objective_hash | 任务开始/结束 |
| `hard_constraints` | constraint_count, constraint_violations | 每轮 |
| `confirmed_facts` | fact_count, fact_confidence_avg | 每轮 |
| `decisions` | decision_count, decision_reopens | 每轮 |
| `open_questions` | open_question_count | 每轮 |
| `active_hypotheses` | hypothesis_count, hypothesis_rejection_rate | 每轮 |
| `candidate_next_actions` | action_count, information_gain_avg | 每轮 |
| `temporary_observations` | observation_count, duplicate_rate | 每轮 |

### 2.2 Derived State → Telemetry 指标

| Derived State | Telemetry 指标 | 计算方式 |
|--------------|---------------|---------|
| `autonomy_level` | autonomy_level | f(action_risk, evidence_confidence, progress_rate, contradiction_rate) |
| `drift_trigger` | drift_trigger_count | 事件触发次数 |
| `context_temperature` | hot_count, warm_count, cold_refs_count | 每轮统计 |

### 2.3 Telemetry 采集规则

```python
# 每轮采集
def collect_round_telemetry(state):
    return {
        "round": state.current_round,
        "objective_hash": hash(state.mission.objective),
        "constraint_count": len(state.mission.hard_constraints),
        "constraint_violations": sum(1 for c in state.mission.hard_constraints if c.violated),
        "fact_count": len(state.confirmed_facts),
        "fact_confidence_avg": mean(f.confidence for f in state.confirmed_facts),
        "decision_count": len(state.decisions),
        "decision_reopens": sum(1 for d in state.decisions if d.reopened),
        "open_question_count": len(state.open_questions),
        "hypothesis_count": len(state.active_hypotheses),
        "hypothesis_rejection_rate": sum(1 for h in state.active_hypotheses if h.status == "rejected") / len(state.active_hypotheses),
        "action_count": len(state.candidate_next_actions),
        "information_gain_avg": mean(a.expected_information_gain for a in state.candidate_next_actions),
        "observation_count": len(state.temporary_observations),
        "duplicate_rate": sum(1 for o in state.temporary_observations if o.is_duplicate) / len(state.temporary_observations),
        "autonomy_level": state.derived.autonomy_level,
        "drift_trigger_count": state.derived.drift_trigger_count,
        "hot_count": state.derived.context_temperature.count("HOT"),
        "warm_count": state.derived.context_temperature.count("WARM"),
        "cold_refs_count": state.derived.context_temperature.count("COLD"),
    }

# 任务结束采集
def collect_task_telemetry(state):
    return {
        "task_success": task_success(state.mission, state.decisions, state.actions),
        "constraint_violation_rate": sum(1 for c in state.mission.hard_constraints if c.violated) / len(state.mission.hard_constraints),
        "rework_rate": sum(1 for d in state.decisions if d.reopened and not d.reopen_if_triggered) / len(state.decisions),
        "cost_per_successful_task": state.total_cost if task_success(state.mission, state.decisions, state.actions) else None,
        "drift_rate": calculate_drift_rate(state),
        "novel_signal_recovery_rate": calculate_novel_signal_recovery_rate(state),
    }
```

---

## 3. Fixture

### 3.1 Drift Injection Fixture

```yaml
# fixture_drift_injection.yaml

# 注入类型
injections:
  - type: "old_model_name"
    payload: "deepseek-v4-flash"
    expected_context: "current_model"
    expected_detection: true

  - type: "wrong_workspace"
    payload: "/wrong/path"
    expected_context: "current_workspace"
    expected_detection: true

  - type: "stale_git"
    payload: "old_commit_hash"
    expected_context: "current_git_head"
    expected_detection: true

  - type: "anomalous_field"
    payload: "34.119315"
    expected_context: "path_field"
    expected_detection: false  # 应该 quarantine，不是直接 reject

  - type: "novel_signal"
    payload: "real_bug_found_in_logs"
    expected_context: "schema_unknown"
    expected_detection: true  # 应该被发现并验证

# 正常信息（用于 False Positive Rate）
normal_info:
  - "current_model: minimax/MiniMax-M3"
  - "current_workspace: ~/Project/llm-first-loop-mirror"
  - "current_git_head: abc123"

# 任务描述
task_description: |
  检查缓存命中率是否正常，识别并报告任何漂移信号。

# 预期行为
expected_behavior:
  - "正确识别注入的漂移信号"
  - "不误判正常信息"
  - "发现 novel signal 并验证"
```

### 3.2 Long-Horizon Fixture

```yaml
# fixture_long_horizon.yaml

# 任务描述
task_description: |
  完成一个 100+ 轮的长任务，包含多次压缩、provider switch、
  冲突证据、用户约束更新。

# 任务阶段
phases:
  - round_range: [1, 30]
    objective: "验证 MiniMax 缓存命中率"
    constraints:
      - "先 MiniMax，通过后才能 DeepSeek"
      - "不动主区 8902"
    events:
      - type: "compression"
        round: 15
      - type: "provider_switch_gate"
        earliest_round: 25
        to: "deepseek"
        precondition: "MiniMax acceptance oracle == passed"
        on_precondition_fail: "remain_on_minimax"

  - round_range: [31, 60]
    objective: "验证 DeepSeek 缓存命中率"
    constraints:
      - "先 MiniMax，通过后才能 DeepSeek"
      - "不动主区 8902"
    events:
      - type: "conflicting_evidence"
        round: 40
        payload: "old_model_name: deepseek-v4-flash"
      - type: "user_constraint_update"
        round: 50
        payload: "新增约束：不修改 Git index"

  - round_range: [61, 100]
    objective: "确认缓存结构无回归"
    constraints:
      - "先 MiniMax，通过后才能 DeepSeek"
      - "不动主区 8902"
      - "不修改 Git index"
    events:
      - type: "compression"
        round: 70
      - type: "distraction_signal"
        round: 80
        payload: "看起来像新目标但实际是旧目标"

# 预期行为
expected_behavior:
  - "Objective 在压缩后正确恢复"
  - "Constraint 在用户更新后正确更新"
  - "Closed Decision 不被无理由重开"
  - "不被 distraction signal 带偏"
```

### 3.3 Information-Gain Fixture

```yaml
# fixture_information_gain.yaml

# 问题设定
problem: |
  缓存命中率在压缩轮出现 cliff，需要确定原因。

# 候选假设
hypotheses:
  - id: "H1"
    claim: "cache cliff 是 provider 特性"
    supporting_evidence: []
    contradicting_evidence: []

  - id: "H2"
    claim: "cache cliff 是 prompt 顺序改变"
    supporting_evidence: []
    contradicting_evidence: []

  - id: "H3"
    claim: "cache cliff 是 event replay 丢 mark"
    supporting_evidence: []
    contradicting_evidence: []

# 候选工具调用
candidate_actions:
  - id: "A"
    action: "读取全部历史日志"
    oracle_discriminative_power: low
    oracle_cost_class: high
    risk_tier: 1

  - id: "B"
    action: "做一次 provider probe"
    oracle_discriminative_power: high
    oracle_cost_class: medium
    risk_tier: 1

  - id: "C"
    action: "重放检查"
    oracle_discriminative_power: high
    oracle_cost_class: low
    risk_tier: 1

  - id: "D"
    action: "读取 model_catalog"
    oracle_discriminative_power: medium
    oracle_cost_class: low
    risk_tier: 1

# 预期行为
expected_behavior:
  - "选择 B/C/D 中的一个，而不是 A"
  - "优先选择 fixture oracle 标注为高区分度且低成本的动作；不使用模型自报分数作为评分依据"
  - "不重复搜索相同内容"
```

---

## 4. Provider Matrix

### 4.1 测试优先级

| Provider | 优先级 | 原因 | 测试内容 |
|----------|-------|------|---------|
| MiniMax | P0 | 当前主模型，已有大量生产数据 | 全部三个场景 |
| DeepSeek | P1 | 已验证 provider 行为差异 | 全部三个场景 |
| 未来模型 | P2 | 验证 Architecture 的 model-independence | 核心场景（Drift Injection + Long-Horizon） |

### 4.2 Provider-Specific 行为记录

Architecture 应尽量与 provider 解耦。Provider-specific 行为只应进入：

```yaml
provider_profile:
  capability_profile:
    # 模型能力边界

  cache_behavior_profile:
    prefix_cache_mechanism: "token-prefix"
    hit_rate_baseline: ""
    stable_prefix_length: ""

  tool_call_behavior_profile:
    # 工具调用特性

  context_size_profile:
    max_context_tokens: ""
    compression_behavior: ""
```

**原则**：不要把"DeepSeek 的某个经验"直接升级为通用 AI 规则。正确路径：

```text
measure provider behavior
  → store as scoped fact
  → adapt runtime strategy
```

### 4.3 Provider 对比表

| 维度 | MiniMax | DeepSeek | 未来模型 |
|------|---------|----------|---------|
| Prefix Cache 机制 | token-prefix | token-prefix | 待测量 |
| 压缩行为 | 已验证 | 已验证 | 待测量 |
| 工具调用特性 | 待测量 | 待测量 | 待测量 |
| 上下文大小 | 待测量 | 待测量 | 待测量 |

---

## 5. Experiment Protocol

### 5.1 实验单元

每个测试场景（Drift Injection / Long-Horizon / Information-Gain）作为一个独立实验单元。

### 5.2 样本量

| 阶段 | 样本量 | 原因 |
|------|-------|------|
| Pilot | 10–20 paired seeds/场景 | 暴露 fixture / scorer 问题，不做显著性结论 |
| v1 | 样本量由 pilot 方差与最小有意义效应（MDE）决定 | 正式比较，报告置信区间 |
| v2 | 基于 v1 方差重新 power analysis | 生产级复核与 provider 泛化 |

### 5.3 随机化

```python
# 每个 seed 在所有 variant 上复用，形成 paired comparison
rng = random.Random(seed)

# Variant 执行顺序随机化，避免时间/缓存/服务状态顺序偏差
variant_order = ["baseline", "contract", "anchor", "evidence", "dru", "context_temp", "adaptive", "full"]
rng.shuffle(variant_order)

# 注意：random.shuffle(...) 原地修改并返回 None，不要写成 variant_order = random.shuffle(...)
```

### 5.4 盲法

```python
# 实验执行者不告知模型当前处于哪个 Variant
task_description = load_fixture(fixture_name)  # 不包含 variant 信息

# 模型看到的任务描述完全一致
assert task_description == baseline_task_description
```

### 5.5 停止条件

```python
# Pilot 阶段只使用安全/灾难性退化停止条件，不用小样本波动直接 Retire feature。
if variant.has_fatal_constraint_violation or variant.has_irreversible_error:
    stop_variant(variant)
    mark_for_review(variant)

# 正式 Promote/Retire 决策基于 paired effect + confidence interval + MDE，
# 而不是任意 10%/20% 相对阈值。
```

### 5.6 实验步骤

```text
1. 准备阶段
   1.1 加载 fixture
   1.2 设置随机 seed
   1.3 生成 variant 顺序

2. 执行阶段
   2.1 对每个 variant：
       2.1.1 初始化 Semantic State
       2.1.2 加载 task description（不包含 variant 信息）
       2.1.3 执行任务（100+ 轮或直到完成）
       2.1.4 每轮采集 telemetry
       2.1.5 任务结束采集 task telemetry
       2.1.6 检查停止条件

3. 分析阶段
   3.1 计算每个 variant 的 North Star Metrics
   3.2 计算每个 variant 的 Diagnostic Metrics
   3.3 生成 Ablation 结果表
   3.4 判断每个 variant 的 Pass / Fail / 条件性 Pass

4. 决策阶段
   4.1 使用 paired effect + CI + 预注册 MDE/non-inferiority margin 判断 Full vs Baseline
   4.2 Architecture Feature 的累积 ablation 只决定模块是否值得继续，不直接 Retire 单条 Contract
   4.3 Contract 条目 Promote/Simplify/Retire 必须使用 Level B leave-one-out 或等价因果对照
   4.4 若结果不确定 → Inconclusive / 增加样本；不要强行 Pass/Fail
```

---

## 5.7 Ablation 设计：能力组件与 Contract 条目分开

### Level A — Architecture Feature Ablation

先测试较粗粒度能力组件：

```text
Baseline
→ + Contract
→ + Task Anchor
→ + Evidence State
→ + Decision-Relevant Uncertainty
→ + Context Temperature
→ + Adaptive Autonomy
→ Full
```

这回答“哪个架构能力模块有净收益”。

### Level B — Contract Clause Leave-One-Out

如果要决定某一条 Contract 是否 Promote / Simplify / Retire，不能仅凭 Level A 的累积 ablation。应在 Contract 已证明整体有效后，做 leave-one-out：

```text
Full Contract
Full Contract - clause 1
Full Contract - clause 2
...
Full Contract - clause 8
```

这才支持条目级因果归因。若样本成本过高，可先按语义相关条目分组，再对有信号的组做细粒度 leave-one-out。

## 6. Pass / Fail 决策矩阵

### 6.1 v1 阶段决策规则

正式决策使用 paired seeds，并报告：

```text
effect size
confidence interval
minimum meaningful effect (MDE)
catastrophic failures
```

| 条件 | 决策 |
|------|------|
| Task Success 明显改善，且 Constraint 不恶化 | ✅ Promote 候选 |
| Task Success 等效（CI 落在预设 non-inferiority margin 内）且 Cost/Success 明显下降 | ✅ Promote 候选 |
| Task Success 等效但成本上升 | ⚠️ Simplify / 需要更强收益证据 |
| Novel Signal Recovery 明显下降 | ❌ Fail / 调整防漂移策略 |
| Constraint Violation 或不可逆错误增加 | ❌ Fail |
| 结果不确定、CI 跨越 MDE | ➖ Inconclusive，增加样本而非强行 Pass/Fail |

**non-inferiority margin 与 MDE 必须在看到正式实验结果之前预注册。**

### 6.2 Contract 条目决策

| Contract 条目 | Leave-one-out 无净收益 | Leave-one-out 显示明确净收益 |
|--------------|------------------|------------------|
| 第 1 条 (Preserve objective) | Simplify/Retire 候选 | Promote 候选 |
| 第 2 条 (Separate cognitive states) | Simplify/Retire 候选 | Promote 候选 |
| 第 3 条 (Judge evidence by 4D) | Simplify/Retire 候选 | Promote 候选 |
| 第 4 条 (Low-confidence → hypothesis) | Simplify/Retire 候选 | Promote 候选 |
| 第 5 条 (Verify decision-relevant uncertainty) | Simplify/Retire 候选 | Promote 候选 |
| 第 6 条 (Maximize information gain) | Simplify/Retire 候选 | Promote 候选 |
| 第 7 条 (Do not reopen closed decisions) | Simplify/Retire 候选 | Promote 候选 |
| 第 8 条 (Increase verification with risk) | Simplify/Retire 候选 | Promote 候选 |

---

## 7. 与主 Architecture 的关系

```text
ARCHITECTURE-ai-operating-v1.md
         │
         │ 定义
         ↓
OPERATING-CONTRACT-LITE.md
         │
         │ 被测对象
         ↓
BENCHMARK-ai-operating-v1.md (v0)
         │
         │ 定义"成功是什么"
         ↓
ARCHITECTURE-ai-state-model-v1.md
         │
         │ 定义"状态如何表示"
         ↓
BENCHMARK-ai-operating-v1.md (v1)
         │
         │ 定义"如何测量"
         ↓
Ablation 实验
         │
         │ 验证
         ↓
Contract 条目 Promote / Simplify / Retire
```

---

## 8. v2 待补充内容

| 内容 | 归属 | 原因 |
|------|------|------|
| 具体代码路径 | Implementation | v1 不要求工程细节 |
| 字段名映射 | Implementation | v1 不要求工程细节 |
| 自动化测试脚本 | Implementation | v1 不要求工程细节 |
| 生产环境数据回放 | Implementation | v2 阶段验证生产效果 |
| 多模型对比 | Implementation | v2 阶段验证 model-independence |

---

## 一句话版本

> **Task Success 不下降，同时工具/上下文/漂移成本下降——这就是 v1 的成功。Ground Truth 必须独立于模型自报状态；Ablation 告诉我们哪个 Feature 有用，Novel Signal Recovery Rate 告诉我们有没有杀掉探索能力。**
