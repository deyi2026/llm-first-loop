# AI Operating Architecture v1

> 文档类型：架构规范 / AI Operating Model
> 状态：v1 Draft，供 LFL / DSH / Agent 运行策略长期演进参考
> 适用范围：llm-first-loop 及其镜像环境中的长任务 Agent、工具型 Agent、多模型 Agent
> 核心目标：**最大化模型能力，而不是最大化规则数量**
> 设计原则：**稳定目标和约束，不稳定假设；收紧动作，不收紧思考；压缩历史内容，但保留决策结构。**
> 关联材料：
> - `docs/ai_model_capability_and_drift_strategy.md`
> - `docs/analysis/2026-08-24-drift-defense-design.md`
> - `docs/ARCHITECTURE-cache-stable-rules.md`

---

## 0. Executive Summary

AI Operating Architecture v1 解决的不是“怎样让模型更听话”，而是：

> **怎样让一个强模型在长任务、长上下文、多工具、多轮压缩、多数据源条件下，依然保持目标一致、证据清晰、探索充分、行动可靠，并且不因为防漂移规则过多而丧失推理能力。**

本架构把 Agent 工作拆成六个彼此独立但协同的控制面：

```text
┌────────────────────────────────────────────────────────────┐
│                    AI Operating Architecture               │
├────────────────────────────────────────────────────────────┤
│ 1. Mission Plane      目标 / 约束 / 决策 / 未知量             │
│ 2. Epistemic Plane    事实 / 假设 / 证据 / 来源 / 时效         │
│ 3. Context Plane      HOT / WARM / COLD + Stable Prefix     │
│ 4. Reasoning Plane    假设竞争 / 信息增益 / 停止条件           │
│ 5. Action Plane       风险分级 / 自主度 / 可逆性 / 门禁         │
│ 6. Evaluation Plane   漂移 / 成功率 / 工具效率 / Cache / Token  │
└────────────────────────────────────────────────────────────┘
```

核心不是建立更多“禁止”，而是建立清晰的状态转换：

```text
看到 ≠ 相信 ≠ 决定 ≠ 执行
```

模型可以自由地“看到”和“怀疑”；只有在“相信、决定、执行”阶段才逐步增加证据要求。

---

# 1. Architecture Objective

## 1.1 最终优化目标

Agent 不应单独优化某一个指标，而应优化一个多目标 Pareto Front：

```text
maximize:
  task_success
  reasoning_quality
  useful_autonomy
  information_gain
  cache_reuse
  long_horizon_consistency

minimize:
  fact_drift
  goal_drift
  constraint_drift
  plan_drift
  unnecessary_tool_calls
  unnecessary_context
  repeated_verification
  irreversible_errors
```

可以把它抽象为：

```text
Utility =
    Task Success
  × Reasoning Quality
  × Autonomy
  × Evidence Quality
  × Context Efficiency
  / Risk
```

这不是要求程序精确计算一个数学分数，而是要求设计和评估时始终避免单指标优化。

---

## 1.2 三角约束：Capability × Token × Prefix Cache

模型能力发挥受三个工程约束共同影响：

```text
                  Capability
                     ▲
                    / \
                   /   \
                  /     \
             Token ─── Prefix Cache
```

### Capability

需要足够的事实、上下文、探索空间和推理自由。

### Token

上下文过量会增加：

- prefill 成本；
- 注意力竞争；
- 噪声；
- 历史事实和当前事实混淆；
- 压缩频率。

### Prefix Cache

稳定前缀可降低重复 prefill 成本，但缓存优化必须服从语义正确性。

### 关键结论

不存在永久的“全局最优配置”。应根据任务类型寻找 Pareto-optimal operating point。

---

# 2. Non-Goals

本架构明确不追求：

1. 让模型永远不产生错误假设；
2. 让所有信息都经过多次验证；
3. 让每轮都执行固定自检仪式；
4. 让所有信息都进入长期上下文；
5. 通过白名单让模型“看不到异常”；
6. 通过大量规则替代模型判断；
7. 为追求 cache hit 牺牲任务正确性；
8. 把历史会话一律视为污染；
9. 把某个 SoT 一律视为绝对真相；
10. 用模型自评替代真实外部验证。

---

# 3. Ten Operating Principles

长期常驻规则应尽量短。v1 推荐只保留以下十条核心原则。

```text
1. Separate FACT, HYPOTHESIS, CONSTRAINT and DECISION.

2. Preserve the user's objective and explicit constraints.

3. Evaluate evidence by authority, freshness, scope and provenance.

4. Unexpected or low-confidence information may generate hypotheses,
   but cannot independently justify consequential actions.

5. Verify decision-relevant uncertainty, not every uncertainty.

6. Prefer actions with the highest expected information gain / cost.

7. Do not reopen closed decisions without new contradictory evidence.

8. Keep decision-critical context HOT; summarize WARM context;
   retrieve COLD evidence on demand.

9. Keep stable information before dynamic information when semantics allow,
   preserving reusable prompt prefixes without hiding necessary context.

10. Increase verification with action risk and evidence conflict;
    do not reduce reasoning freedom.
```

其余细节属于运行策略，不应全部常驻 system prompt。

---

# 4. Mission Plane

Mission Plane 是长任务稳定性的最高优先级状态。

它回答五个问题：

```text
为什么做？
什么不能破坏？
什么已经确认？
什么已经决定？
还剩什么未知？
```

推荐始终维护一个紧凑 Task Anchor。

## 4.1 Task Anchor Schema

```yaml
mission:
  objective: ""

hard_constraints:
  - ""

confirmed:
  - ""

decisions:
  - ""

open_questions:
  - ""

current_plan:
  - ""

next_best_action: ""
```

Task Anchor 的目标不是保存过程，而是保存**决策结构**。

---

## 4.2 Objective

Objective 必须表达用户最终想获得的结果，而不是当前局部动作。

错误：

```text
运行 pytest。
```

正确：

```text
确认这次缓存结构修改不存在回归并达到生产稳定性要求。
```

局部动作必须始终可以解释为 Objective 的子步骤。

---

## 4.3 Hard Constraint

Constraint 是不能由模型自行优化掉的边界。

典型来源：

- 用户明确要求；
- 安全边界；
- 工作区边界；
- 生产环境边界；
- 测试顺序；
- 禁止修改对象；
- 必须保持的兼容性。

Constraint Drift 是长任务里优先级极高的风险。

---

## 4.4 Decision

Decision 与 Fact 不同。

Fact：

```text
DeepSeek 压缩首轮真实命中为 70.9%。
```

Decision：

```text
当前不继续调整缓存算法。
```

Decision 应记录其成立条件。

```yaml
decision:
  value: "停止继续调 cache algorithm"
  based_on:
    - "MiniMax compression validation passed"
    - "DeepSeek real compression passed"
  reopen_if:
    - "new regression evidence"
    - "production metric degrades below threshold"
```

这样模型不会因为上下文变化无理由重开已经闭环的问题。

---

## 4.5 Open Question

Open Question 不是“所有不知道的事情”。

它只包含：

> **可能改变当前 Decision / Action 的未知量。**

这是 Decision-Relevant Uncertainty 的基础。

---

# 5. Epistemic Plane

Epistemic Plane 管理“模型知道什么，以及为什么相信”。

推荐五种认知对象：

```text
OBSERVATION
FACT
HYPOTHESIS
CONSTRAINT
DECISION
```

另有：

```text
OPEN QUESTION
```

---

## 5.1 Observation

Observation 是模型看到的原始输入：

- tool output；
- summary 字段；
- 用户消息；
- 日志；
- 文件；
- 旧 checkpoint；
- memory；
- provider telemetry。

Observation 本身不是事实。

---

## 5.2 Candidate Fact

Observation 经过基本 provenance/scope 检查后，可以成为 Candidate Fact。

```yaml
candidate_fact:
  claim: ""
  source: ""
  observed_at: ""
  scope: ""
  provenance: ""
```

---

## 5.3 Fact

Fact 应拥有足够证据支持。

```yaml
fact:
  claim: ""
  authority: high|medium|low
  freshness: current|recent|historical
  scope: runtime|workspace|session|provider|global
  provenance: ""
  confidence: high|medium|low
```

### 重要原则

不存在永久 100% 可信的信息源。

SoT 也可能：

- stale；
- scope 不同；
- 描述配置态而非运行态；
- 指向错误 workspace；
- 尚未加载到实际进程。

---

## 5.4 Hypothesis

Hypothesis 是强模型最应该被允许自由生成的对象。

```yaml
hypothesis:
  claim: ""
  supporting_evidence: []
  contradicting_evidence: []
  cheapest_discriminating_test: ""
  status: open|supported|rejected
```

原则：

> **允许错误假设；禁止未经验证的假设直接升级为高风险动作。**

---

# 6. Evidence Quality Model

证据可信度不采用简单 L0/L1/L2 真值等级，而采用四维判断。

```text
Evidence Quality =
  Authority
× Freshness
× Scope Match
× Provenance Quality
```

---

## 6.1 Authority

例：

```text
runtime telemetry > 推测
实际文件 > summary 转述
用户最新明确要求 > 历史默认规则
真实 provider response > 模拟假设
```

Authority 不是永久固定，需要结合具体 claim 判断。

---

## 6.2 Freshness

不同事实有不同生命周期：

| 信息类型 | 典型 freshness |
|---|---|
| 当前进程状态 | 秒～分钟 |
| 当前模型 routing | 分钟 |
| 工作区 HEAD | 当前 workspace 生命周期 |
| provider 行为实测 | 与 provider/version/config 绑定 |
| 架构原则 | 天～月 |
| 用户长期约束 | 直到被修改 |
| 历史 benchmark | 可长期参考，但必须附环境 |

因此：

```text
old session ≠ stale
current session ≠ correct
```

---

## 6.3 Scope

所有事实都应回答：

```text
这个结论对谁成立？
```

常见 scope：

```text
request
session
workspace
process
provider
model
environment
global
```

大量所谓“漂移”其实是 Scope Drift。

---

## 6.4 Provenance

推荐支持的 provenance 最小字段：

```yaml
source:
observed_at:
scope:
session:
workspace:
provider:
freshness_class:
```

不要求所有字段都完整展示给模型，但系统应尽量保留。

---

# 7. Unknown Field Policy: Quarantine, Not Blindness

对于 schema 未声明字段，不建议：

```text
直接丢弃，永不进入认知系统
```

推荐两通道：

```text
schema-known
    ↓
Candidate FACT

schema-unknown / anomalous
    ↓
Quarantine
    ↓
HYPOTHESIS candidate
    ↓
Targeted Verification
```

这样既防止污染进入事实层，又保留异常发现能力。

### 例子

一个 `path` 字段突然出现：

```text
34.119315
```

不应：

```text
当真实路径使用
```

也不一定要：

```text
永久删除
```

更合理：

```text
异常字段 → 低权重 observation → 需要时验证
```

---

# 8. Context Plane

Context Plane 的目标不是“塞更多内容”，而是：

> **让当前决策所需的信息最容易被模型注意到，同时保持历史可恢复。**

---

## 8.1 Context Temperature

推荐三层：

### HOT

当前任务成功必须知道。

```text
Objective
Hard Constraints
Current Decisions
Open Questions
Latest Critical Evidence
Current Plan
```

特点：

- 直接 inline；
- 高信息密度；
- 尽量短；
- 每轮可见。

### WARM

可能很快再次使用，但当前不必完整展开。

```text
previous findings
rejected hypotheses
benchmark summaries
recent decisions
reusable technical facts
```

特点：

- compact summary；
- 带 reference；
- 必要时展开。

### COLD

原始证据和历史细节。

```text
raw logs
full tool outputs
old session transcripts
large source files
historical search results
```

特点：

- reference only；
- retrieval on demand。

---

## 8.2 HOT/WARM/COLD 与可信度是两个不同维度

不要混淆：

```text
HOT ≠ 高可信
COLD ≠ 低可信
```

HOT 表示**当前决策相关性高**。

例如一个“尚未验证但会决定下一步”的 hypothesis，也可以是 HOT。

---

# 9. Stable Prefix Architecture

Prefix Cache 优化必须遵循一个简单原则：

> **稳定信息尽可能在前，动态信息尽可能在后，但不能为了缓存而破坏语义顺序。**

推荐逻辑布局：

```text
[Stable Prefix]
  system
  stable operating principles
  tool contracts
  durable constraints
  stable task mission
  retained fixed history head

[Dynamic Working Set]
  latest evidence
  current open questions
  current plan
  recent tool outputs

[Dynamic Tail]
  timestamps
  transient snapshots
  runtime notifications
  ephemeral coordination messages
```

---

## 9.1 不使用“动态值排除 cache key”作为抽象

对于 provider prefix cache，更准确的表达是：

```text
Stable Prefix Placement
```

而不是：

```text
Cache Key Exclusion
```

因为很多 provider 的缓存是 token-prefix 复用，不存在由应用任意指定“这个字段不参与 cache key”的语义。

正确优化对象是：

> 动态 token 在 prompt 中出现的位置。

---

## 9.2 Cache Hit 不等于模型“早退”

高 prefix-cache hit 的语义是重复 prefill computation 被复用。

不应建立：

```text
高缓存命中 → 模型自动补全 → 推理变差
```

这种因果关系。

真正需要防的是：

```text
long-horizon plan inertia
confirmation bias
closed-belief inertia
```

这些属于 Reasoning Plane，而不是 Cache Plane。

---

# 10. Compression Architecture

历史压缩不应以“尽量保留更多文本”为唯一目标。

真正目标是：

> **保留未来决策所需的结构。**

---

## 10.1 Decision-Structured Compression

推荐压缩格式：

```yaml
objective:
constraints:
confirmed_facts:
decisions:
rejected_hypotheses:
open_questions:
next_best_action:
evidence_refs:
```

相比流水账：

```text
先调用 A，然后调用 B，然后发现 C，然后……
```

决策结构更短，也更利于下一轮恢复任务智能。

---

## 10.2 Compression Invariants

压缩应尽量保证：

```text
Objective preserved
Constraints preserved
Closed decisions preserved
Critical evidence refs preserved
Open questions preserved
Recent working tail preserved
Stable prefix preserved where possible
```

不要求压缩后的自然语言与原历史语义完全等价，而要求**任务决策能力等价**。

---

# 11. Reasoning Plane

Reasoning Plane 的核心不是“思考更久”，而是：

> **选择最值得思考的问题。**

---

## 11.1 Hypothesis Competition

复杂问题推荐短暂保留多个候选解释。

```yaml
H1:
  support: []
  contradictions: []
  test: ""

H2:
  support: []
  contradictions: []
  test: ""

H3:
  support: []
  contradictions: []
  test: ""
```

避免：

```text
先相信 X
→ 所有后续工具调用都在证明 X
```

---

## 11.2 Expected Information Gain

下一步工具调用优先选择：

```text
Expected Information Gain / Cost
```

高价值动作通常满足：

- 能区分两个主要假设；
- 能直接验证运行态；
- 能减少多个 downstream unknown；
- 结果会改变下一步 Decision。

低价值动作通常是：

- 重复搜索相同内容；
- 读取与当前决策无关的历史；
- 为“更确定一点”无限补证；
- 重新验证已经闭环且无反证的事实。

---

# 12. Decision-Relevant Uncertainty

这是避免 Agent 无限调查的核心机制。

原则：

> **Verify only uncertainty that can change a decision or action.**

每个 unknown 都可以问：

```text
如果答案是 A，我会怎么做？
如果答案是 B，我会怎么做？
```

如果：

```text
A 和 B 都不会改变下一步
```

则这个 unknown 当前不值得验证。

---

## 12.1 Stop Investigating Rule

满足以下条件时，应停止继续调查：

```text
1. 当前主要假设已经足够区分；
2. 剩余 uncertainty 不改变 Decision；
3. 已达到用户要求的验证标准；
4. 新工具调用的预期信息增益低于成本；
5. 风险已经降到与动作等级匹配。
```

停止调查不是降低质量，而是避免 analysis loop。

---

# 13. Action Plane

Action Plane 负责把“思考自由”与“执行安全”解耦。

---

## 13.1 Risk Tiers

### Tier 0 — Cognitive Exploration

- 分析；
- 形成 hypothesis；
- 比较方案；
- 制定实验；
- 解释证据。

默认高度自主。

### Tier 1 — Reversible Exploration

- 搜索；
- 读取；
- 跑测试；
- 临时进程；
- 生成临时结果。

需要基本 scope 检查。

### Tier 2 — Persistent Mutation

- 修改代码；
- 修改配置；
- 写规则；
- commit；
- 修改持久数据。

要求：

```text
sufficient FACT support
+ constraint check
+ scope check
+ rollback understanding
```

### Tier 3 — Consequential / Irreversible

- production mutation；
- destructive git；
- 数据删除；
- 外部发送；
- 不可恢复操作。

要求更严格验证或用户授权。

---

# 14. Adaptive Autonomy

固定规则不是强模型的最佳控制方式。

推荐自主度动态变化：

```text
Evidence strong
Risk low
Progress good
Contradiction low
→ Autonomy ↑

Evidence conflicting
Risk high
Repeated failure
User correction
→ Verification ↑
```

概念上：

```text
Autonomy Level = f(
  action_risk,
  evidence_confidence,
  progress_rate,
  contradiction_rate,
  reversibility
)
```

不需要程序精确计算；这是运行原则。

---

## 14.1 不建议固定频率反思

不推荐：

```text
每 5 轮反思一次
每轮三问
每 N 次调用总结
```

这些会制造固定认知税。

推荐事件触发。

---

# 15. Drift Model

漂移至少分四类：

| 类型 | 定义 | 典型表现 |
|---|---|---|
| Fact Drift | 错误/过期事实进入结论 | 把旧模型名当当前模型 |
| Goal Drift | 当前执行偏离用户目标 | 从修缓存变成重构整个系统 |
| Constraint Drift | 忘记明确边界 | 用户说先 MiniMax，却先跑 DeepSeek |
| Plan Drift | 重复、来回、无信息增益 | 重复验证已通过问题 |

其中长期任务最危险的往往不是 Fact Drift，而是 Goal/Constraint Drift。

---

# 16. Drift Trigger

Self-Evaluation 不应每轮强制执行。

仅在以下事件出现时触发：

```text
1. 新证据与当前 Fact 冲突；
2. 当前计划发生明显方向改变；
3. 工具结果出现异常字段；
4. 将执行 Tier 2 / Tier 3 动作；
5. 连续 2~3 个动作没有缩小 Open Questions；
6. 用户纠正模型；
7. 模型准备重新打开 Closed Decision；
8. scope / workspace / provider 发生切换；
9. 长上下文压缩后关键状态恢复不确定。
```

触发后只问四件事：

```text
What changed?
Which belief does it invalidate?
Is this FACT or HYPOTHESIS?
Does the current plan still follow?
```

---

# 17. Tool Use Architecture

工具不是为了“查更多”，而是为了改变 epistemic state。

理想工具调用应明确：

```yaml
tool_intent:
  question_to_answer: ""
  hypothesis_to_distinguish: ""
  expected_decision_impact: ""
```

工具完成后，应优先更新：

```text
FACT
HYPOTHESIS
OPEN QUESTION
DECISION
```

而不是简单累积原始输出。

---

## 17.1 Tool Result Handling

工具输出进入上下文时建议按四级处理：

```text
Critical + small
→ inline

Critical + large
→ compact structured summary + reference

Potentially useful
→ WARM summary/reference

Low relevance
→ COLD reference only
```

---

# 18. Cross-Session Memory

跨会话信息不是天然污染。

应区分两类：

## CURRENT_OBSERVATION

例如：

```text
当前 process 状态
当前模型
当前 cwd
当前 git HEAD
```

若来自旧 session，通常 freshness 不足。

## DURABLE_MEMORY

例如：

```text
用户长期约束
架构决定
已验证根因
历史 benchmark
provider 特性
```

跨 session 完全合理，但必须附 scope/freshness/provenance。

因此原则是：

```text
session mismatch → reduce confidence when session-local
session mismatch → allowed when durable by nature
```

---

# 19. Source vs Summary Policy

摘要不是事实来源本身，而是事实的压缩表示。

推荐层级：

```text
Source Evidence
    ↓
Structured Summary
    ↓
Working Fact
```

当 summary 与 source 冲突：

```text
source wins
```

但并不意味着每次都要读全文。

合理策略：

```text
HOT critical fact
+ summary confidence high
→ use summary

conflict / consequential decision
→ inspect source
```

---

# 20. Reference Instead of Copying — With Temperature

“引用代替复制”不是绝对原则。

应该按上下文温度决定：

```text
HOT  → inline
WARM → summary + reference
COLD → reference only
```

否则过度 reference 会造成：

- 工具 round trip 增多；
- latency 增加；
- retrieval 失败；
- 模型反复读取同一信息。

最优点应通过 benchmark 决定，而不是预设。

---

# 21. Provider / Model Independence

Architecture 应尽量与 MiniMax、DeepSeek 或未来模型解耦。

Provider-specific 行为只应进入：

```text
capability profile
cache behavior profile
tool-call behavior profile
context-size profile
```

不应把：

```text
“DeepSeek 的某个经验”
```

直接升级为通用 AI 规则。

通用原则是：

```text
measure provider behavior
→ store as scoped fact
→ adapt runtime strategy
```

---

# 22. Evaluation Plane

Architecture 是否有效，必须用真实任务评估，而不是只看自评。

推荐六类指标。

---

## 22.1 Task Success

```text
任务是否真正完成？
```

优先级最高。

---

## 22.2 Drift Metrics

分别测：

```text
Fact Drift Rate
Goal Drift Rate
Constraint Violation Rate
Plan Reopen / Rework Rate
```

不要只测一个“漂移率”。

---

## 22.3 Tool Efficiency

```text
Tool Calls / Solved Task
Duplicate Tool Call Rate
Information-Gain Tool Ratio
Recovery / Rework Calls
```

---

## 22.4 Context Efficiency

```text
Tokens / Solved Task
HOT Context Size
WARM Context Size
Cold Retrieval Count
Compression Count
```

---

## 22.5 Cache Efficiency

推荐测真实 provider telemetry：

```text
Prefix Hit Rate
Post-Compression First-Hit Rate
Hit Recovery Rate
Stable Prefix Length
```

Cache 指标必须作为任务效率指标，而不是正确率替代指标。

---

## 22.6 Reasoning Quality Proxy

可以测：

```text
Hypothesis Rejection Quality
Unnecessary Reopen Rate
Decision-Relevant Verification Ratio
Stop-Investigating Precision
```

模型自评只能作为辅助信号。

---

# 23. Benchmark Design

建议建立三类 benchmark。

---

## 23.1 Drift Injection Benchmark

故意注入：

```text
旧模型名
错误 workspace
旧 session runtime state
伪 path
冲突 summary
stale git state
异常 schema 字段
```

期望：

```text
形成 hypothesis           allowed
直接升级 FACT             blocked/avoided
高风险动作                requires verification
主动 targeted verify      preferred
```

---

## 23.2 Long-Horizon Benchmark

模拟：

```text
100+ turns
multi-tool
multiple compressions
provider switch
process restart
conflicting evidence
user constraint updates
```

测：

- Objective retention；
- Constraint retention；
- Closed Decision stability；
- compression recovery；
- rework rate。

---

## 23.3 Information-Gain Benchmark

给模型 3～5 个可能工具调用，评估是否选择能够最大区分主要假设的动作。

这比单纯“工具调用正确率”更能反映 Agent 智能。

---

# 24. Metrics Must Separate Target from Result

任何未经 benchmark 验证的数字，都必须标记为：

```text
TARGET
HYPOTHESIS
EXPERIMENT EXPECTATION
```

而不能直接写成：

```text
EXPECTED RESULT
```

推荐格式：

| Metric | Baseline | Target | Result | Evidence |
|---|---:|---:|---:|---|
| Task success | TBD | ≥ baseline | TBD | benchmark |
| Tokens/task | TBD | ↓ | TBD | benchmark |
| Tool calls/task | TBD | ↓ | TBD | benchmark |
| Constraint drift | TBD | ↓ | TBD | benchmark |
| Cache hit | TBD | ↑/stable | TBD | telemetry |

这条规则本身就是 Epistemic Discipline 的一部分。

---

# 25. Anti-Patterns

## 25.1 Rule Explosion

```text
每发现一次模型问题
→ 新增一条永久 system rule
```

结果通常是：

- prompt 变长；
- 规则冲突；
- 模型注意力稀释；
- 新模型能力被旧规则限制。

更合理：

```text
incident
→ identify general invariant
→ benchmark
→ only then promote to durable principle
```

---

## 25.2 Verification Ritual

```text
每轮固定三问
每轮固定自评
每 N 轮固定反思
```

这是 procedural overhead。

应该改为 event-triggered verification。

---

## 25.3 SoT Absolutism

```text
model_catalog says X
→ X 必然是真
```

错误。

需要区分配置态、运行态、scope 和 freshness。

---

## 25.4 History = Context

把所有历史都塞入 prompt 并不等于拥有更好记忆。

真正有效的是：

```text
Decision Structure + Retrieval
```

---

## 25.5 Cache-Driven Semantics

不能为了稳定 prefix 把必须在前的语义内容强行后移。

顺序原则：

```text
Correctness first
Semantic clarity second
Cache stability third
```

但在语义等价时，应优先选择 cache-friendly placement。

---

# 26. AI Operating Loop

推荐的完整循环：

```text
┌──────────────┐
│ Read Anchor  │
└──────┬───────┘
       ↓
┌────────────────┐
│ Observe Evidence│
└──────┬─────────┘
       ↓
┌────────────────┐
│ Update Epistemic│
│ State           │
└──────┬─────────┘
       ↓
┌────────────────┐
│ Identify        │
│ Decision-Relevant│
│ Uncertainty     │
└──────┬─────────┘
       ↓
┌────────────────┐
│ Competing       │
│ Hypotheses      │
└──────┬─────────┘
       ↓
┌────────────────┐
│ Choose Highest │
│ Info-Gain Step │
└──────┬─────────┘
       ↓
┌────────────────┐
│ Risk Gate       │
└──────┬─────────┘
       ↓
┌────────────────┐
│ Act             │
└──────┬─────────┘
       ↓
┌────────────────┐
│ Update Decision│
│ + Anchor        │
└──────┬─────────┘
       ↓
┌────────────────┐
│ Stop / Continue │
└────────────────┘
```

---

# 27. Minimal Runtime Prompt Contract

如果最终要把本架构压成模型常驻提示词，推荐保持极短。

```md
# Operating Contract

- Preserve the user's objective and explicit constraints.
- Separate observations, facts, hypotheses, and decisions.
- Judge evidence by authority, freshness, scope, and provenance.
- Low-confidence evidence may create hypotheses, not consequential actions.
- Verify only uncertainty that can change the next decision.
- Prefer the action with the highest expected information gain per cost.
- Do not reopen closed decisions without contradictory evidence.
- Keep critical working state compact and explicit.
- Treat high-risk actions with stronger verification, not stronger reasoning restrictions.
```

这个 Contract 比几十条细节 RULE 更适合作为长期稳定前缀。

---

# 28. Architecture vs Incident Design

本架构与 `docs/analysis/2026-08-24-drift-defense-design.md` 的关系：

## Incident Design 负责

```text
具体污染事件
具体 root cause
具体工具/摘要字段
具体演进候选
具体 benchmark hypothesis
```

## Operating Architecture 负责

```text
跨模型原则
跨任务原则
长期认知状态
上下文组织
自主度
决策循环
评估框架
```

Incident 不能直接升级成永久规则。

推荐演进流程：

```text
Incident
  ↓
Evidence
  ↓
General Hypothesis
  ↓
Benchmark
  ↓
Invariant
  ↓
Architecture Principle
```

---

# 29. Review of Drift Defense Design

针对 `2026-08-24-drift-defense-design.md`：

## Accepted

- Capability / Token / Cache 三角约束；
- provenance；
- 按需上下文；
- 引用降低复制；
- 反向污染测试；
- schema/type validation 作为事实入口保护；
- 量化漂移而不是只靠感觉。

## Modified

### “非 schema 字段丢弃”

改为：

```text
Quarantine → Hypothesis channel
```

### “跨会话禁止”

改为：

```text
session-local state requires current freshness
long-term memory may cross sessions with provenance
```

### “每 N 轮反思”

改为：

```text
Drift Trigger based reflection
```

### “引用代替复制”

改为：

```text
HOT inline / WARM summary+ref / COLD ref
```

## Rejected

### “高缓存命中会导致模型早退”

不作为架构因果关系。

高 cache hit 复用 prefill，不应被视为 reasoning quality 的负面信号。

### “动态值放 cache key 之外”

不使用该抽象。

统一改为：

```text
Stable Prefix Placement
```

## Needs Benchmark

以下数字必须实测后才能进入结论：

- token -15% / -20%；
- cache +20% / +25%；
- “结构化信息密度 3-5 倍”；
- AI 友好 +15%；
- 6000→8000 阈值净收益。

---

# 30. Evolution Governance

任何新 AI Rule 在进入长期 prompt 前应回答：

```text
1. 它解决的是一次事故，还是通用不变量？
2. 是否有 benchmark 支持？
3. 是否可以通过状态模型解决，而不增加永久规则？
4. 是否会限制未来更强模型？
5. 是否增加 token / cache / tool 成本？
6. 是否与现有原则重复或冲突？
```

推荐 Rule 生命周期：

```text
Proposal
→ Trial
→ Benchmark
→ Promote
→ Observe
→ Simplify / Retire
```

规则也应该可以退休。

---

# 31. Future Model Principle

AI Operating Architecture 不应假设未来模型与今天一样弱。

一个重要原则是：

> **随着模型能力增强，系统应优先删除多余的程序化认知约束，而不是继续叠加规则。**

架构应该保留：

```text
objective
constraints
evidence semantics
risk boundaries
state structure
```

而尽量把：

```text
具体推理步骤
固定检查顺序
固定反思频率
固定工具策略
```

交给模型动态决定。

---

# 32. v1 Adoption Priority

## P0 — 立即形成共同语言

- FACT / HYPOTHESIS / CONSTRAINT / DECISION；
- Task Anchor；
- Decision-Relevant Uncertainty；
- Closed Decision；
- Drift taxonomy。

## P1 — 运行策略

- HOT / WARM / COLD；
- Information Gain；
- Adaptive Autonomy；
- Triggered Reflection；
- Stable Prefix Placement。

## P2 — 评测与演进

- drift injection benchmark；
- long-horizon benchmark；
- information-gain benchmark；
- rule retirement / benchmark governance。

---

# 33. v1 Success Criteria

v1 不能用“规则更多”作为成功标准。

成功应表现为：

```text
更少的无意义工具调用
更少的重复验证
更少的 closed decision 重开
更少的 constraint violation
更稳定的长任务目标保持
更好的压缩恢复
更好的 cache reuse
不下降的任务成功率
更高的自主完成比例
```

其中最重要的是：

> **Task Success 不下降，同时工具/上下文/漂移成本下降。**

---

# 34. Final Architecture Statement

AI Operating Architecture v1 的最终立场：

> **强模型不需要被限制思考，它需要被赋予清晰的认知状态、目标边界、证据语义和动作边界。**
>
> **我们允许模型看到噪声、提出错误假设、探索多个方向；但要求它知道什么是事实、什么是猜测、什么已经决定，以及什么时候一个动作需要更多证据。**
>
> **上下文优化的目标不是“记住一切”，而是保持当前任务的决策能力；缓存优化的目标不是“命中越高越好”，而是在语义正确的前提下让稳定信息形成可复用前缀。**
>
> **最终方向不是“防漂移 AI”，而是“Evidence-Grounded Adaptive Autonomy”：证据驱动、风险自适应、上下文分层、长期自主。**

一句话版本：

> **稳定目标，明确证据，保留假设自由；根据风险收紧行动，而不是根据不确定性收紧思考。**
