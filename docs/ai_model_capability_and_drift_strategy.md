# 大模型能力发挥与「漂移」治理建议

> **目标不是让模型“更保守”，而是让模型在可信事实边界内尽可能自主地推理、探索、调用工具和纠错。**
>
> 漂移治理如果做得太重，会把强模型降级成“规则执行器”；做得太松，又会出现错误事实沿推理链不断放大。比较好的方向是：
>
> **事实有边界，假设有自由；高风险动作严格校验，低风险探索充分放权。**

---

## 一、现有方案的评价：方向正确，但不要压制模型能力

当前 A～E 方案本质上是在增强 **Grounding / Provenance / Verification**，方向正确，但若直接固化为强规则，会有几个副作用。

### 1. `L0 = 100%可信` 过于绝对

即使是 `git status`、`architecture_status`、`model_catalog`、当前 cwd，也可能存在数据过期、scope 错位、运行态与配置态不一致等情况。

更合理的是：

```text
Evidence = Authority × Freshness × Scope × Provenance
```

即使 SoT 也要判断：是否当前 workspace、当前 process、当前时间窗口，以及它表达的是配置态还是运行态。

### 2. 「字段不白名单 → 不进推理」太硬

强模型的重要能力之一，就是从未预料字段里发现异常。因此建议改成：

```text
非预期字段 ≠ 丢弃

非预期字段：
- 可以形成 HYPOTHESIS
- 不可以直接形成 FACT
- 不可以直接触发高成本/不可逆动作
```

核心是：**限制证据权重，不限制模型看到信息。**

### 3. 「非当前会话 = 残留」也太强

架构决策、git commit、用户长期约束、provider capability、已验证 bug 根因和历史 benchmark 都可能跨会话长期有效。

应从“当前/非当前会话”升级为：

> **信息生命周期 / freshness class**

| 信息 | 合理时效 |
|---|---:|
| 当前运行进程 | 秒/分钟 |
| 当前模型 routing | 分钟 |
| git HEAD | 当前 workspace 生命周期 |
| 架构原则 | 天～月 |
| 用户明确决策 | 直到被修改 |
| benchmark | 保留环境与日期后长期可参考 |

### 4. 「三问每轮必做」容易产生认知税

不建议所有轮次都机械执行“当前会话吗 / 声明字段吗 / 与 SoT 一致吗”。

更合适的是 **事件触发式核验**，仅在以下情况下触发：

- 新事实会改变当前计划；
- 两个来源冲突；
- 将执行高成本动作；
- 将修改代码或生产环境；
- 来源可信度不足；
- 会推翻之前结论。

### 5. 「L2 不进推理」会削弱探索能力

建议改为：

```text
L2 可以进入假设推理
L2 不可以独立进入事实结论
```

合理链路应该是：

```text
异常字段
   ↓
形成假设
   ↓
主动设计验证
   ↓
获取新证据
   ↓
升级为事实 / 淘汰
```

---

## 二、真正应该治理的是认知状态，而不是简单的信息等级

相比 L0/L1/L2，更推荐维护以下五类对象：

```text
FACT
HYPOTHESIS
CONSTRAINT
DECISION
OPEN QUESTION
```

### FACT — 已验证事实

```yaml
fact:
  claim: 当前 mirror web 监听 8903
  source: process_status
  observed_at: ...
  scope: current_runtime
  confidence: high
```

事实必须有 provenance。

### HYPOTHESIS — 尚未验证的解释

例如：

```text
压缩轮缓存 cliff 可能因为 summary 插到了 fixed-head 前。
```

允许模型大胆生成，但必须明确它不是事实。

### CONSTRAINT — 不允许自行突破的边界

例如：

```text
先 MiniMax，稳定后才 DeepSeek
不要修改主区 8902
不要动 Git index
```

长任务里，Constraint Drift 往往比 Fact Drift 更危险。

### DECISION — 已作出的决策

例如：

```text
不调整 production history 配置。
采用已验证的 fixed-head 策略。
```

没有新反证时，不应该反复重新打开已经闭环的决策。

### OPEN QUESTION — 当前真正未知的事情

模型每轮最值得问的不是“我知道什么”，而是：

> **当前还剩哪个未知量最值得消除？**

---

## 三、采用「证据状态机」，而不是简单白名单

```text
               ┌───────────────┐
               │  Observation  │
               └───────┬───────┘
                       ↓
              ┌────────────────┐
              │ Candidate Fact │
              └───────┬────────┘
                      │
             provenance / scope
             freshness / conflict
                      │
          ┌───────────┴───────────┐
          ↓                       ↓
   ┌────────────┐          ┌────────────┐
   │ Confirmed  │          │ Hypothesis │
   │    Fact    │          │ / Unknown  │
   └─────┬──────┘          └─────┬──────┘
         │                       │
         │                       ↓
         │                 targeted verify
         │                       │
         └────────────┬──────────┘
                      ↓
                 ┌─────────┐
                 │Decision │
                 └────┬────┘
                      ↓
                risk-based gate
                      ↓
                  ┌────────┐
                  │ Action │
                  └────────┘
```

核心原则：

> **不要阻止模型提出错误假设；要阻止模型把未经验证的假设直接变成动作。**

---

## 四、按动作风险分级，让模型「思考自由、行动受控」

### Tier 0：自由推理

分析、提出假设、比较方案、阅读、搜索、benchmark 设计等，应给予模型高度自由。

### Tier 1：可恢复动作

跑测试、临时测试实例、搜索日志、生成临时文件，只需要基本 scope 校验。

### Tier 2：持久修改

代码、配置、规则、commit 等要求：

```text
FACT 支持
+
CONSTRAINT 检查
+
影响范围明确
```

### Tier 3：生产 / 不可逆动作

production 配置、destructive git、数据删除、对外发送等，要求更严格的双重验证。

> **在思考阶段大胆，在行动阶段根据风险逐级收紧。**

---

## 五、长会话最重要的是维护一个极小 Task Anchor

```md
## Mission

让普通轮结构稳定，压缩轮保持稳定 prefix-cache hit。

## Hard Constraints

- 先 MiniMax，通过后才能 DeepSeek
- 不动主区 8902
- 不修改 Git index
- production history 配置保持不变

## Confirmed

- APPEND_COMPRESSION 顺序 bug 已定位并修复
- MiniMax compression fixed-head hit 已验证
- DeepSeek real compression: 93.6% → 70.9% → 94.8%

## Open

- 无必须项，当前进入收口阶段

## Current Decision

停止继续调 cache algorithm。
```

这个 Anchor 通常只需几十到几百 token，却能有效抑制 Goal Drift、Constraint Drift 和 Plan Drift。

---

## 六、Context 应拆成「稳定前缀 + 动态工作集 + 可检索归档」

```text
[Stable Prefix]
System / global safety
AI operating principles
Tool contracts
Hard user constraints
Task mission

--------------------------

[Dynamic Working Set]
Current facts
Decisions
Open questions
Latest tool evidence
Current plan

--------------------------

[Archive / Retrieval]
Old evidence
Old hypotheses
Historical logs
Detailed previous execution
```

不要把大量历史摘要放到规则、目标和最新证据之前。

---

## 七、压缩历史时，保留「决策结构」而不是过程流水账

推荐摘要结构：

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

例如缓存问题真正值得长期保留的是：

```text
ROOT CAUSE
APPEND_COMPRESSION inserted archive-summary before fixed-head.

EVIDENCE
Old real DeepSeek compressed request hit exactly 8,960.
New ordering preserves head.

VALIDATION
MiniMax compressed 70.2%, fixed-head 99.8%.
DeepSeek real 93.6% -> 70.9% -> 94.8%.

DECISION
Do not tune cache algorithm further.
```

相比几十轮流水账，这种表示更短，也更能保持任务智能。

---

## 八、工具调用从「遇到不确定就搜」升级为「最大化信息增益」

强模型应该优先思考：

> **哪一个工具调用最能以最低成本区分当前主要假设？**

例如：

```text
H1: cache cliff 是 provider 特性
H2: cache cliff 是 prompt 顺序改变
```

相比继续阅读大量日志，更高信息增益的实验是：

```text
same prefix
+
one controlled structural difference
```

然后直接 provider probe。

即：

```text
Next Action ≈ max(Expected Information Gain / Cost)
```

---

## 九、复杂问题使用「假设竞争」，避免单一路径确认偏误

| Hypothesis | 支持证据 | 反证 | 最低成本验证 |
|---|---|---|---|
| summary 顺序破坏 prefix | 8,960 固定 cliff | 暂无 | 比较消息顺序 |
| DeepSeek 不支持中段 prefix | provider probe | 自然 endpoint 可复用 | endpoint warm probe |
| event replay 丢 mark | replay 状态异常可能 | system fp 稳定 | 重放检查 |

模型可以短暂保留 H1/H2/H3，然后优先执行信息增益最高的验证，而不是一开始选定 X 后不断证明 X。

---

## 十、Self-Evaluation 改成事件触发，而不是每轮执行

### Drift Trigger

仅当以下事件出现时启动自检：

```text
① 新证据与当前事实冲突
② 当前计划发生方向改变
③ 工具结果出现意外字段
④ 将执行 Tier 2/Tier 3 动作
⑤ 连续 2~3 个动作没有缩小 unknown set
⑥ 用户纠正模型
⑦ 模型准备重新调查一个已经 closed 的问题
```

触发后检查：

```text
What changed?
Which previous belief does it invalidate?
Is this FACT or HYPOTHESIS?
Does current plan still follow?
```

---

## 十一、漂移应拆成四类，而不只是事实错误

| 类型 | 表现 | 危害 |
|---|---|---|
| **Fact Drift** | 采信错误/过期事实 | 推理错误 |
| **Goal Drift** | 做着做着换了目标 | 最严重 |
| **Constraint Drift** | 忘记“不要动什么” | 高风险 |
| **Plan Drift** | 重复已完成工作、来回切方向 | 浪费成本 |

长期 prompt 最值得固定的是：

```text
Preserve objective.
Preserve explicit constraints.
Do not reopen closed decisions without contradictory evidence.
```

---

## 十二、建议的 RULE-AI-21

```md
## RULE-AI-21 Evidence-Grounded Autonomy

### 1. 区分事实与假设
工具输出、摘要、历史信息均可用于形成假设；
未经来源、范围及时效确认的信息，不得直接作为高风险行动依据。

### 2. 保持任务锚点
持续维护：
- Objective
- Hard Constraints
- Confirmed Facts
- Decisions
- Open Questions

不得在无新反证情况下偏离 Objective、
突破 Hard Constraints 或重新打开已关闭决策。

### 3. 证据可信度按四维判断
证据可信度由以下因素共同决定：
- Authority
- Freshness
- Scope
- Provenance

不存在永久 100% 可信的信息源。

### 4. 冲突驱动验证
仅在以下情况主动追加核验：
- 来源冲突
- 新事实将改变计划
- 将执行高成本/不可逆动作
- 信息 scope / freshness 不明确

避免对所有事实机械重复验证。

### 5. 假设自由，动作受控
允许模型利用低可信信息生成 hypothesis；
但 hypothesis 不得直接升级成事实或高风险动作，
必须通过针对性证据验证。

### 6. 风险分级
低风险阅读、分析、探索给予模型充分自主权；
持久化修改和生产动作提高验证门槛。

### 7. 信息增益优先
存在多个假设时，优先执行能够以最低成本区分主要假设的动作，
避免重复搜索和低信息增益工具调用。

### 8. 漂移事件检测
重点检测：
- Fact Drift
- Goal Drift
- Constraint Drift
- Plan Drift

仅在漂移触发条件出现时执行自检，
避免每轮产生固定认知税。
```

---

## 十三、长期 Prompt 建议只保留 7 条核心原则

```md
# AI Operating Principles

1. Separate FACT, HYPOTHESIS, CONSTRAINT and DECISION.
2. Preserve the user's objective and explicit constraints.
3. Treat evidence according to authority, freshness, scope and provenance.
4. Low-confidence evidence may generate hypotheses, but not justify high-risk actions.
5. Verify when evidence conflicts or before consequential actions.
6. Prefer the next action with the highest expected information gain.
7. Do not reopen a closed decision without new contradictory evidence.
```

其余详细规则按任务需要动态注入，不建议全部驻留 system prompt。

---

## 十四、最终方向：从「防漂移 AI」转向「受约束的自主 AI」

旧思路：

```text
不可信
→ 过滤
→ 校验
→ 再行动
```

更推荐：

```text
观察
 ↓
自由形成多个假设
 ↓
证据状态管理
 ↓
选择信息增益最大的验证
 ↓
形成事实 / 淘汰假设
 ↓
根据动作风险决定验证强度
 ↓
自主执行
```

核心区别：

> **不要试图通过减少模型可用信息来提高正确率。**
>
> 应让模型拥有尽可能完整的信息，同时明确区分“看到”“怀疑”“相信”“决定”“执行”这五件事。

这样才能同时得到：

**更低漂移 + 更少工具调用 + 更强根因分析 + 更长任务自主性。**

---

## 推荐优先级

| 优先级 | 建议 | 对模型能力提升 |
|---|---|---|
| **P0** | Task Anchor：Objective / Constraints / Decisions / Open | 极高 |
| **P0** | FACT 与 HYPOTHESIS 分离 | 极高 |
| **P0** | 高风险动作才提高验证门槛 | 极高 |
| **P1** | Authority × Freshness × Scope × Provenance | 高 |
| **P1** | Information Gain 驱动工具调用 | 高 |
| **P1** | Closed Decision 防重复开启 | 高 |
| **P2** | Trigger-based Drift Evaluation | 中高 |
| **P2** | L0/L1/L2 改成证据状态模型 | 中高 |
| **不建议** | 每轮机械三问 | 会降低效率 |
| **不建议** | 非白名单字段完全禁止进入推理 | 会压制异常发现 |
| **不建议** | 上会话信息默认污染 | 会浪费长期记忆 |
| **不建议** | SoT 永远视为 100% 正确 | 会产生另一类漂移 |

一句话概括：

> **稳定目标和约束，不稳定假设；收紧动作，不收紧思考；压缩历史内容，但保留决策结构。**

这比单纯做“漂移防御”更能把 MiniMax、DeepSeek 以及后续更强模型的推理能力发挥出来。
