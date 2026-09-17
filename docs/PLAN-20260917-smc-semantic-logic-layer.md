# SMC Semantic Logic Layer（N3-inspired）需求设计规划书 v0.1

## 1. 项目背景

当前 SMC（Semantic Manipulation Contract）已经形成较完整的语义操控基础设施，核心包括：

- `SemanticObject`
- `WorldSnapshot`
- `SemanticDiff`
- `Predicate`
- `SemanticAction`
- `ActionReceipt`
- 横切上述对象的 `GroundingRef`

Browser Phase 1 已经验证了以下能力：

- grounded perception；
- SemanticDiff；
- Predicate / Wait；
- staleness / version pressure；
- mutation precondition；
- append-only ActionReceipt；
- DOM / AX 多传感器冲突诚实表达；
- no silent rebind；
- no hidden retry；
- no task-completion program authority。

现阶段主要矛盾已经不再是“有没有语义对象”，而是：

1. 模型仍需要维护部分本来可以机械推导的关系；
2. `grounding_ref / target / scope_ref / version / verb args` 存在交叉绑定错误；
3. 不同 domain 正在重复实现相似的 semantic invariants；
4. 多来源事实、冲突、unknown、version、provenance 尚缺统一推理层；
5. Python 代码已经可以验证这些规则，但缺乏统一、声明式、可组合、可证明的 Semantic Logic Layer；
6. model-facing surface 仍承担了一部分“不应该由模型记忆”的机械结构复杂度。

N3 的价值因此不是替换 SMC，而是为 SMC 提供一种可借鉴的：

> **Graph Facts + Context + Rules + Provenance + Derivation**

表达范式。

---

## 2. 总体目标

建立一个新的：

# Semantic Logic Layer

位于：

```text
LLM Semantic Choice
        │
        ▼
SMC Model-facing Contract
        │
        ▼
Semantic Logic Layer
        │
        ▼
Domain Adapter
        │
        ▼
Physical World
```

其核心职责是：

> 把模型已经作出的语义选择，机械闭包成完整、可执行、可审计的 SMC contract。

最终形成四层明确分工：

```text
LLM
负责：
- 选择什么对象重要
- 选择观察什么属性
- 选择什么操作
- 是否需要等待
- 当前结果意味着什么
- 用户任务是否完成

Semantic Logic Layer
负责：
- 机械语义关系闭包
- scope / target / version 推导
- coverage / conflict / unknown 推导
- Predicate 机械闭包
- action precondition derivation
- provenance / proof chain

Adapter
负责：
- DOM / AX / FS / API / Vision 等物理 observation
- physical grounding
- physical dispatch

Runtime
负责：
- authority
- permission
- version fencing
- idempotency
- single dispatch
- durable receipt
```

---

## 3. 明确非目标

本项目第一阶段**不得**成为：

### 3.1 自动规划器

禁止：

```text
login page
→ 自动决定 fill username
→ 自动 click submit
```

Rule Layer 只能说明：

```text
username field:
mechanically_fillable = true
```

是否 fill，由模型决定。

### 3.2 Semantic Router

不得使用规则：

```text
用户说“看看”
→ browser_perceive

用户说“修改”
→ browser_operate
```

Perceive / Operate 的语义选择仍由模型负责。

Logic Layer 只负责模型作出选择之后的参数机械闭包。

### 3.3 自动任务完成判断器

禁止：

```text
Predicate satisfied
→ task complete
```

只能得到：

```text
PredicateResult = satisfied
```

是否完成用户任务仍由模型判断。

### 3.4 模型自产生 authority rule

模型生成的规则：

```text
X => canOperate
```

绝不能立即进入生产 authority path。

模型生成规则最多进入：

```text
candidate
```

生产 RulePack 必须：

```text
versioned
reviewed
hashed
deterministically tested
qualified
```

### 3.5 用 N3 替换现有 SMC JSON contract

外部 contract 继续使用当前 typed SMC objects。

N3 或 N3-compatible representation 第一阶段只存在于内部 Semantic Logic Layer。

---

## 4. 核心设计原则

### P1. SMC 是协议，N3 是逻辑

两者不是竞争关系。

```text
SMC:
对象和 wire contract

N3-style Logic:
对象之间有什么可机械推出的关系
```

### P2. Fact 与 Interpretation 分离

Semantic Logic Layer 只能处理：

```text
mechanically observable fact
mechanically derivable fact
```

不能产生：

```text
important
recommended
best
likely useful
task relevant
should click
probably complete
```

### P3. Source-qualified truth

不建立一个简单的：

```text
button.enabled = true
```

事实池。

而是保留：

```text
DOM:
button.enabled = true

AX:
button.enabled = false
```

然后推出：

```text
canonical enabled = unknown
conflict = true
```

不能提前压平 source。

### P4. Observation-context truth

事实必须绑定：

```text
scope
snapshot
version
sensor contract
grounding
```

即：

```text
{ button enabled true }
groundedBy snapshot_101
```

而不是永恒声明：

```text
button enabled true
```

### P5. Open-world honesty

缺少事实：

```text
没有看到 X
```

默认不能推出：

```text
X 不存在
```

只有当 coverage 足够完整时，negative closure 才成立。

否则：

```text
indeterminate
```

### P6. Proof-carrying derivation

所有 derived fact 必须可以回答：

```text
这个结论来自哪里？
```

例如：

```text
mechanicallyOperable(button)
    ↓
Rule R17
    ↓
enabled=true
visible=true
identity=current
version=compatible
    ↓
GroundingRef A/B/C
```

---

## 5. 目标架构

```text
                    ┌──────────────────┐
                    │       LLM        │
                    │ semantic choice  │
                    └────────┬─────────┘
                             │
                 minimal semantic request
                             │
                             ▼
                 ┌─────────────────────┐
                 │ SMC Model Surface   │
                 │ observe / hydrate   │
                 │ wait / operate      │
                 └─────────┬───────────┘
                           │
                           ▼
            ┌───────────────────────────┐
            │ Semantic Compiler         │
            │                           │
            │ Fact Projector            │
            │ Rule Engine               │
            │ Semantic Closure          │
            │ Proof / Provenance        │
            └─────────────┬─────────────┘
                          │
             canonical mechanical contract
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
      Browser            FS               API
      Adapter          Adapter           Adapter
         │                │                │
         └────────────────┼────────────────┘
                          ▼
                     Physical World
```

---

## 6. 核心数据层需求

### R1. Semantic Fact

定义统一内部 Fact：

```text
subject
predicate
object/value

source
scope_ref
observed_version
grounding_ref

completeness
confidence_type
```

注意这里不建议引入自由浮动的模型 confidence。

第一阶段主要是：

```text
observed
mechanically_derived
unknown
conflict
```

---

## 7. Context / Graph 需求

支持类似 N3 quoted graph 的概念：

```text
Graph(snapshot_101) {
    button enabled true
    button visible true
}
```

而：

```text
Graph(snapshot_102) {
    button enabled false
}
```

两者同时有效。

不能把 102 回写覆盖 101。

这与现有 GroundingRef immutable semantics 对齐。

---

## 8. RulePack 体系

RulePack 分两层。

### 8.1 SMC Core RulePack

跨 domain 通用：

#### Identity Rules

```text
GroundingRef
→ SemanticObject ID
→ scope_ref
→ observed_version
```

#### Scope Rules

```text
object
→ belongsTo scope

frame
→ parent document

document
→ parent page
```

#### Completeness Rules

```text
negative observation
+
complete relevant coverage
→ mechanical negative

negative observation
+
partial coverage
→ indeterminate
```

#### Conflict Rules

```text
source A says X=true
source B says X=false

且无预声明 deterministic resolver

→ canonical X=null
→ conflict=true
```

#### Version Rules

```text
expected object generation
!=
current physical identity generation

→ stale
```

#### Receipt Rules

```text
same action_id

receipt_seq(n+1) > receipt_seq(n)
```

禁止覆盖旧 receipt。

### 8.2 Domain RulePack

Browser：

```text
DOM
AX
Vision
page
document
frame
navigate
click
fill
```

Filesystem：

```text
path
snapshot
hash
mtime
inode
expected_snapshot
```

未来：

```text
API
Database
GUI
Game World
Robot
```

---

## 9. Semantic Compiler

这是第一阶段最具有现实价值的组件。

当前模型可能需要提交：

```text
schema
domain
scope_ref
target
property
operator
value
```

未来：

```text
object_ref
property
operator
value
```

Semantic Compiler 自动推出：

```text
schema
domain
SemanticObject.id
scope_ref
observed_version
```

同理：

```text
operate(
    grounding_ref,
    verb,
    semantic_args
)
```

机械推出：

```text
target_id
scope_ref
expected_version
version_scope
operation_class
idempotency_class
atomicity_class
action_id mechanics
```

模型不再维护这些重复关系。

---

## 10. C28 多传感器语义推理

现有：

```text
DOM = true
AX  = false
```

升级为统一 source-qualified semantic fact：

```text
DOM graph:
{ button enabled true }

AX graph:
{ button enabled false }
```

Rule Layer：

```text
conflicting declared observations
+
no deterministic resolution rule

=>

canonical.enabled = null
conflict = unresolved
```

必须保存：

```text
source
value
grounding_ref
```

---

## 11. Predicate Layer

当前 typed Predicate 保留。

第一阶段不急于把 Predicate 完全改成 N3 query language。

先实现：

```text
Predicate
    ↓
Semantic Compiler
    ↓
canonical fact query
    ↓
satisfied
unsatisfied
indeterminate
```

第二阶段才研究：

```text
AND
OR
NOT
relation
existence
quantifier
```

并评估是否仍保持 typed DSL，而不是把完整 N3 暴露给模型。

---

## 12. Action Precondition Layer

SemanticAction dispatch 前形成：

```text
ActionIntent
      │
      ▼
Semantic Closure
      │
      ├── identity current?
      ├── scope current?
      ├── version compatible?
      ├── grounding valid?
      ├── operation supported?
      └── action_id unused?
      │
      ▼
Mechanical Precondition Result
```

只有 mechanical PASS 才进入 Runtime dispatch。

但是：

> Rule Layer 不负责决定该动作是否值得执行。

---

## 13. Proof / Provenance Layer

增加内部：

```text
DerivationRecord
```

至少包含：

```text
derived_fact
rule_id
rule_version
input_fact_refs
grounding_refs
snapshot/version
result
```

例如：

```text
fact:
button.mechanically_operable=true

derived_by:
browser-operability-r3

because:
enabled=true @ grounding_17
visible=true @ grounding_19
version_match=true @ version_check_22
```

这为未来形成：

# Proof-carrying Semantic Manipulation

---

## 14. Shadow-first 实施策略

这是整个项目最重要的安全原则。

第一阶段：

```text
Current Python Semantics
          │
          ├──────────────► Production Result
          │
          ▼
Semantic Logic Shadow
          │
          ▼
Shadow Result
```

Shadow Result：

**不参与：**

```text
routing
dispatch
retry
authority
completion
provider-visible response
```

只进行：

```text
comparison
logging
qualification
```

---

## 15. 第一批 Shadow Gate

优先只验证已经拥有 deterministic oracle 的五类问题。

### Gate S1 — Grounding Closure

输入：

```text
GroundingRef
```

必须 100% 推导出当前 Python 相同的：

```text
SemanticObject.id
scope_ref
observed_version
```

### Gate S2 — C28 Conflict

```text
DOM=true
AX=false
```

必须得到：

```text
canonical=null
conflict=unresolved
```

且 source-grounding 完整保留。

### Gate S3 — Predicate Honesty

```text
not found
+
partial coverage
```

必须：

```text
indeterminate
```

不能得到 false/not-exists。

### Gate S4 — Version/Stale

旧 GroundingRef + 新 object generation：

必须得到与现有 Python identical 的：

```text
stale
reason
version relation
```

### Gate S5 — Receipt Monotonicity

必须证明：

```text
running receipt
terminal receipt
```

是 append-only revision，而不是覆盖。

---

## 16. Phase Roadmap

### P0 — Semantic Logic Specification

**只做 docs/schema，不改 production。**

产物：

```text
SMC-SEMANTIC-LOGIC-v0.1.md
SMC-RULE-AUTHORITY-v0.1.md
SMC-FACT-PROVENANCE-v0.1.md
```

冻结：

- Fact model；
- graph/context semantics；
- RulePack authority；
- derivation/proof；
- open-world semantics；
- shadow boundary；
- model/runtime/logic/adapter authority matrix。

#### Gate

纸面 adversarial review PASS。

### P1 — N3-compatible Shadow Representation

实现：

```text
SMC object
→ Semantic Fact Graph
```

暂时可以采用：

> **N3-compatible internal IR**

而不是马上把生产强绑定到某个完整 N3 runtime。

同时提供：

```text
IR → N3 serialization
```

供调试/研究/对照。

#### Gate

现有 frozen fixtures 100% projection deterministic。

### P2 — Core Rule Engine

实现五组规则：

1. Grounding；
2. scope；
3. completeness/conflict；
4. Predicate；
5. version/receipt。

#### Gate

当前 Python canonical result 与 Rule Engine：

```text
semantic equivalence = 100%
```

任何 mismatch 都属于 RED。

### P3 — Shadow Qualification

对 Browser Phase 1 现有 deterministic corpus 全量 replay。

至少覆盖：

```text
reorder
replacement
duplicate identity
navigation
frame generation
DOM/AX conflict
virtualized list
partial coverage
stale ref
version mismatch
non-idempotent mutation
receipt revision
```

指标：

```text
false closure = 0
silent rebind = 0
unknown→false collapse = 0
proof coverage = 100%
```

此阶段仍无 production authority。

### P4 — Semantic Compiler A/B

开始减少 model-facing 冗余字段。

A：

```text
当前 surface
```

B：

```text
minimal semantic surface
+
Semantic Compiler
```

重点测试目前真实出现过的问题：

```text
grounding_ref 错塞 snapshot
target_ref / resource_ref 混用
scope_ref mismatch
version_scope 猜错
navigate/object args 交叉
```

主要 KPI：

#### First-call-ready

不是“规则运行了多少次”。

测：

```text
首次 semantic call 结构合法率
cross-binding error
tool failure
schema reread
rounds
tokens
task result
```

### P5 — Selective Authority Cutover

不得一次性替换。

建议顺序：

#### 5A Read-only mechanical derivation

先接：

```text
Grounding closure
scope closure
Predicate identity compiler
```

#### 5B Conflict / completeness

再接：

```text
C28
negative honesty
```

#### 5C Version derivation

再接：

```text
expected/current version relation
```

#### 5D Mutation precondition

最后才允许 semantic rule output 进入 mutation guard。

每一层必须：

```text
independent qualification
rollback switch
dual-compute comparison
```

### P6 — 第二 Domain 验证

不能只证明 Browser 有效。

推荐第二 domain：

# Filesystem

因为 FS 已天然存在：

```text
path
snapshot
version
hash
GroundingRef
expected snapshot
mutation receipt
```

如果 Browser + FS 可以共用同一套：

```text
Grounding
Version
Completeness
Predicate
Receipt
Provenance
```

那么才证明这是：

> **SMC Semantic Logic**

而不是 Browser-specific abstraction。

---

## 17. Model-facing 最终目标

今天：

```text
model
需要理解大量 contract plumbing
```

最终：

```text
Model:
    what
    which object
    which condition
    which action
    semantic args

Logic:
    relation closure

Runtime:
    execution safety
```

例如最终 Browser surface 可以趋近：

```text
observe(...)
hydrate(ref)

wait(
    ref,
    property,
    operator,
    value
)

operate(
    ref,
    verb,
    args
)
```

而不是让模型自行维护：

```text
schema
domain
scope
target
version
version_scope
operation_class
idempotency_class
atomicity_class
```

---

## 18. Authority Matrix

| 能力 | LLM | Semantic Logic | Adapter | Runtime |
|---|---:|---:|---:|---:|
| 选择目标 | ✅ | ❌ | ❌ | ❌ |
| 判断任务意义 | ✅ | ❌ | ❌ | ❌ |
| 选择动作 | ✅ | ❌ | ❌ | ❌ |
| Grounding→scope | ❌ | ✅ | 提供事实 | ❌ |
| conflict closure | ❌ | ✅ | 提供事实 | ❌ |
| negative completeness | ❌ | ✅ | 提供 coverage | ❌ |
| 版本关系 | ❌ | ✅ | 提供 observation | ✅ fence |
| 物理操作 | ❌ | ❌ | ✅ | ✅授权 |
| idempotency enforcement | ❌ | 说明合同 | ❌ | ✅ |
| receipt durability | ❌ | derivation | observation | ✅ |
| task complete | ✅ | ❌ | ❌ | ❌ |

---

## 19. Rule 生命周期

生产 Rule 必须具有：

```text
rule_id
version
domain
authority_class
inputs
outputs
source
tests
hash
status
```

生命周期：

```text
candidate
→ deterministic_tested
→ shadow_qualified
→ active
→ superseded / retired
```

模型生成的 Rule：

```text
永远从 candidate 开始
```

不得直接 active。

---

## 20. 性能要求

Semantic Logic 不能制造新的 Agent latency bottleneck。

第一阶段要求：

```text
无额外 LLM round
无额外 provider request
无网络依赖
deterministic local execution
bounded inference
```

性能 Gate 不建议现在写死绝对毫秒值。

采用相对指标：

```text
Semantic Logic p95
<
对应 physical observation/action latency 的 5%
```

并单独测：

```text
100 facts
1K facts
10K facts
```

防止 rule closure 出现非线性爆炸。

---

## 21. 安全要求

必须 fail-closed 的包括：

```text
unknown rule version
unknown GroundingRef
ambiguous identity
rule recursion overflow
unbounded derivation
conflicting authority facts
expired grounding
rulepack hash mismatch
```

但 fail-closed 仅作用于：

> 机械执行资格。

不能演变为：

> 程序认为用户任务不能完成。

---

## 22. 关键 KPI

第一阶段成功不看“N3 使用率”。

真正 KPI：

### Semantic correctness

```text
Python ↔ Logic equivalence = 100%
```

### Epistemic honesty

```text
unknown incorrectly collapsed to false = 0
conflict silently resolved = 0
```

### Identity safety

```text
silent rebind = 0
```

### Execution safety

```text
duplicate physical dispatch = 0
stale accepted = 0
```

### Proof

```text
derived mechanical facts with derivation provenance = 100%
```

### Model ergonomics

A/B 后测：

```text
first-call-ready ↑
cross-binding error ↓
schema reread ↓
tool failure ↓
round count 不恶化
task success 不恶化
```

---

## 23. 当前最值得优先解决的问题

结合现有 SMC 实测，我建议优先级是：

### Priority 1 — GroundingRef Semantic Closure

先让：

```text
GroundingRef
→ object
→ scope
→ version
→ valid operations
```

成为统一机械关系。

这是当前收益最大、风险最低的部分。

### Priority 2 — Source-qualified Fact + C28

把：

```text
DOM / AX / Vision
```

从字段拼装升级成真正 source-qualified facts。

### Priority 3 — Predicate Semantic Closure

统一：

```text
coverage
negative
unknown
conflict
```

减少各 adapter 重复逻辑。

### Priority 4 — Proof-carrying Action Precondition

把：

```text
为什么允许/拒绝执行
```

变成可追溯 derivation。

### Priority 5 — Model Surface Reduction

只有前四项证明稳定后，再减少模型参数。

不能倒过来为了缩 schema 而先改 contract。

---

## 24. 与当前 Perceive / Operate Routing 专项的关系

N3 / Semantic Logic **不解决模型选择 Perceive 还是 Operate 的语义问题**。

这个选择仍由 LLM 完成。

但一旦模型选择了：

```text
Perceive(ref)
```

或：

```text
Operate(ref, verb)
```

Semantic Logic 可以消除：

```text
tool-name 对了但参数 template 用错
grounding_ref / target_ref 混用
scope/version 交叉绑定错误
```

因此它主要改善的是：

# selection 之后的 synthesis correctness

而不是接管 selection。

这保持了现有 Routing 专项的裁决边界。

---

## 25. 推荐下一阶段正式任务

建议下一阶段不要立即写 N3 production code。

先执行：

# SMC Semantic Logic P0 — Read-only Architecture & Rule Audit

范围严格限定：

1. 把当前 SMC Python 中所有机械 semantic invariants 列出来；
2. 分类：
   - core invariant；
   - Browser-specific；
   - model-owned；
   - runtime authority；
3. 找出重复实现；
4. 为五个首批 Shadow Gate 建立 frozen fixture；
5. 定义 N3-compatible Fact / Rule / Derivation schema；
6. 输出 P0 design；
7. 不修改现有 Browser production behavior；
8. 不增加模型 tool；
9. 不改变 provider-visible schema；
10. 不进入 mutation authority。

P0 完成以后再裁决：

```text
P1-A
自研 typed semantic-rule IR

vs

P1-B
直接采用现成 N3 reasoner

vs

Hybrid
内部 typed IR + N3 import/export/qualification
```

当前推荐：

# Hybrid

即：

> **生产内部首先使用强类型、受限、可验证的 Semantic Rule IR；N3 作为表达、交换、研究和独立推理验证语言。**

这样可以获得 N3 最重要的思想和形式能力，又不会过早把 SMC 生产 runtime 绑定到一个外部推理生态。

---

## 26. 一句话路线图

```text
现有 SMC
    ↓
Fact Graph
    ↓
N3-compatible Semantic Rules
    ↓
Shadow semantic closure
    ↓
Python ↔ Logic equivalence
    ↓
Proof-carrying derivation
    ↓
Semantic Compiler
    ↓
更小、更可靠的 model surface
    ↓
Browser + FS 跨域验证
    ↓
Selective production authority
```

最终目标不是“SMC 支持 N3”。

而是：

> **让 SMC 从一套语义数据合同，升级成一套具有 Grounding、Context、Rules、Proof 和 Execution 的完整 Semantic Manipulation Runtime。**

同时继续保持最重要的 LFL 原则：

> **模型负责理解与选择；语义逻辑层负责可证明的机械关系；Adapter 负责感知和执行；Runtime 负责硬边界。**
