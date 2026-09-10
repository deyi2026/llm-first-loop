# LFL 自适应推理与学习架构
## 最终设计——任务平面 / 深度推理平面 / 学习平面 / 资格验证平面 + 元学习

**日期：** 2026-09-10
**状态：** Architecture SoT（当前总设计基线）
**适用范围：** 本地模型、云端 API、自建推理服务
**适用对象：** GLM / MiniMax / DeepSeek / MLX / llama.cpp / vLLM / 未来其他 Provider

> 本文是 LFL 自适应推理与学习方向的总 Architecture SoT。它统领并高于
> `DESIGN-20260910-learning-plane.md`、`METHOD_LEARNING_V1.md` 等专项设计；专项文档仍作为
> 分阶段实现细则和历史证据保留，但不得与本文的四平面 + Meta-Learning 总边界冲突。

---

# 1. 最终裁决

LFL 不应该只从“带记忆的任务执行循环”继续演进，而应该进一步成为一个**能够持续积累、复用、质疑、验证并提升推理方法的自适应推理运行时**。

系统最终应该能够做到：

1. 完成当前任务；
2. 对困难、矛盾、不确定的问题，利用已经积累的方法和推理技能再次深度审视；
3. 在任务结束后进行反思，自主提炼可复用 Method；
4. 在独立任务与反例上验证这些 Method；
5. 在未来任务中重新调用经过验证的 Method；
6. 从多个 Method 中进一步抽象出更高级的 Meta-Method；
7. 持续测量系统是否真的变得更准确、更高效、更稳健。

最终能力循环不是：

```text
Task -> Answer -> Memory
```

也不只是：

```text
Episode -> Reflection -> Method
```

而是：

```text
Observe
  -> Reason
  -> Deliberate
  -> Act
  -> Answer
  -> Reflect
  -> Learn
  -> Qualify
  -> Reuse
  -> Meta-Learn
```

目标是在**不改变底层模型权重**的情况下，实现系统级能力持续增长。

LFL 的根本哲学保持不变：

> **程序负责提供能力、可观察事实、来源证明、资源边界、安全、持久化和恢复能力；模型负责语义理解、策略、适用性判断、推理、质疑、综合以及最终裁决。**

---

# 2. 为什么需要这套架构

即使底层模型本身很强，也可能反复出现同一类问题：

- 推理路径过长；
- 明明证据已经足够，却继续调用大量工具；
- 过度相信历史 Evidence；
- 混淆当前源码事实与旧 verdict；
- 在一次任务中学到教训，但下一次无法迁移；
- 某个好 Method 已经存在，却没有在恰当时机被调用；
- 对“看起来合理”的解释产生过高置信度；
- 用户纠正过一次后，系统仍无法将其沉淀为可复用方法。

普通 Memory 主要解决：

> “系统能不能找回以前发生过什么？”

这里要解决的是更难的问题：

> **“系统能不能从过去真正学会以后应该怎样更好地思考？”**

这要求把不同职责拆成多个独立平面，而不是继续把所有能力堆进主会话循环。

---

# 3. 最终架构：四平面 + Meta-Learning

```text
                         ┌──────────────────────┐
                         │      Task Plane      │
                         │   理解 / 行动 / 回答 │
                         └──────────┬───────────┘
                                    │
                         模型决定是否需要深思
                                    │
                                    ▼
                     ┌──────────────────────────┐
                     │    Deliberation Plane    │
                     │      Reasoning Lab       │
                     │ Method / Experience      │
                     │ Rule / Skill / Evidence  │
                     │ Counterexample           │
                     │ 探索 / 拷问 / 反证 / 综合 │
                     └────────────┬─────────────┘
                                  │
                           ReasoningBrief
                                  │
                                  ▼
                           Task Model 再判断
                                  │
                                  ▼
                              最终回答
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │      Learning Plane      │
                     │ Reflection / Self-Grill  │
                     │ Episode -> Method候选    │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │   Qualification Plane    │
                     │ 独立任务 / 反例验证      │
                     └────────────┬─────────────┘
                                  │
                        qualified / invalid
                                  │
                                  ▼
                          可复用 Method
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │       Meta-Learning      │
                     │ Methods -> Meta-Method   │
                     └──────────────────────────┘
```

这些平面必须在逻辑和运行时上保持清晰分离。

---

# 4. Task Plane / 任务平面

Task Plane 只负责用户当前任务：

```text
消息进入 -> 理解 -> 行动 -> 真诚回答 -> 持久化结果
```

它是系统最高优先级的前台工作负载。Task Plane 不应同步承担 post-task self-distillation、Method synthesis、qualification、Meta-Learning 或最终答案已经完成后的长时间自我批判。

正确关键路径：

```text
Task work
-> final answer
-> durable session / episode / run-end facts
-> LoopResult
-> SSE done / caller completion
```

Learning 必须发生在这条链之外。

---

# 5. Deliberation Plane / Reasoning Lab

## 5.1 目的

Reasoning Lab 是任务进行中的独立深度推理空间：

> **在最终裁决之前，利用已经积累的 Method、Skill、Experience、Rule、Evidence 和反例，对当前问题进行第二层深度思考。**

它不是 post-task Reflection，也不是普通用户 Session。

推荐运行时对象：

```text
DeliberationRun / ReasoningLabRun
```

建议字段：

```text
deliberation_run_id
source_session_id
source_episode_ref | active_task_ref
source_model
workspace_scope
trust_domain

current_problem
current_hypothesis
known_facts
uncertainties
candidate_method_refs
selected_skill_refs
evidence_refs

state
created_at
started_at
finished_at
reasoning_brief_ref
```

## 5.2 输入与检索

Reasoning Lab 可以按需读取：

```text
Method
Experience
Rule
Skill
Evidence
Counterexample
当前任务事实
```

但必须继续使用：

```text
compact discovery
-> stable exact ref
-> explicit hydration
-> 模型自行判断适用性
```

禁止把 Method / Experience 库大量自动注入 prompt。

## 5.3 三类认知能力

### Explorer

- 寻找其他可能解释；
- 发现遗漏维度；
- 扩展候选假设。

### Challenger

- 攻击当前假设；
- 找最强反例；
- 找未验证前提；
- 检查相关性/因果混淆；
- 检查过度置信。

### Synthesizer

- 比较相互竞争的解释；
- 整合 Evidence；
- 组合多个 Method；
- 形成更好的最终推理结构。

三者是能力，不是强制顺序或固定次数的多 Agent 流程。

## 5.4 推理 Skill

Reasoning Lab 可调用：

```text
adversarial-review
counterexample-search
root-cause-cross-examination
assumption-audit
evidence-conflict-resolution
first-principles
alternative-hypothesis
decision-pre-mortem
boundary-check
causal-vs-correlational-audit
```

Skill 表示“怎样审视问题”；Method 表示“过去真实任务中什么办法曾经有效”。二者可以与 Evidence 组合，但不得混为自动程序规则。

## 5.5 ReasoningBrief

Reasoning Lab 不保存 raw private chain-of-thought，而输出结构化 ReasoningBrief：

```text
problem
current_hypothesis
supporting_evidence
conflicting_evidence
applicable_methods
method_applicability_notes
assumptions
unknowns
alternative_explanations
strongest_challenge
counterexamples
recommended_reasoning_path
verification_needed
confidence_boundaries
method_refs
skill_refs
evidence_refs
```

Reasoning Lab 不拥有最终回答权。正确链路：

```text
Reasoning Lab -> ReasoningBrief -> Task Model -> final judgment
```

---

# 6. Learning Plane / 学习平面

Learning Plane 负责：

```text
Episode -> Reflection -> Method candidate
```

必须完全脱离 Task completion critical path。

Reflection 的 source of truth 必须是：

```text
source_episode_ref = episode:...
```

而不能是任意 `sess.messages[-N:]` Session 尾部切片。

Learning 可读取：

```text
source_episode_ref
真实 user 消息
可见 assistant 结果
tool observations / failures
重复工具调用事实
round 数
run_end_reason
用户明确反馈
source provider/model
本次使用过的 Method / Skill refs
```

禁止读取或持久化 raw hidden reasoning / reasoning_content replay。

推荐 ReflectionRun 字段：

```text
learning_job_id
reflection_run_id
source_episode_ref
source_session_id
source_model
source_provider
trigger_facts
feedback_refs
teacher_refs
state
attempt
candidate_ref
none_reason
failure_reason
created_at
started_at
finished_at
```

Candidate 输出采用 closed schema，程序只做机械结构验证，不判语义质量：

```text
decision: candidate | none
name
description
trigger
discriminator
short_path[]
stop_conditions[]
verification[]
counterexamples[]
program_boundaries[]
model_owned_judgments[]
```

---

# 7. Qualification Plane / 资格验证平面

Episode A 产生的 Method 不能再由 Episode A 自证。

```text
candidate
-> 独立任务验证
-> 反例验证
-> qualified
-> active
```

或：

```text
candidate -> transfer失败 -> hold / invalidated
```

Runtime 必须机械生成并证明：

```text
candidate.source_episode_ref
qualification.episode_ref
```

至少满足：

```text
qualification_episode_ref != source_episode_ref
```

必要时还要验证 lineage，避免 fork/replay 冒充独立验证。

模型仍然负责判断 Method 是否有帮助、是否引入偏差、是否可迁移、是否应该 refine，以及 verdict 是 pass/fail/mixed/insufficient。

---

# 8. Meta-Learning / 元学习

长期能力增长不能停在零散 Method。

```text
Method A
Method B
Method C
    ↓
重新抽象共同结构
    ↓
Meta-Method candidate
```

Meta-Method 必须记录：

```text
source_method_refs[]
source_qualification_refs[]
counterexample_refs[]
synthesis_run_ref
```

即使源 Method 都已 qualified，Meta-Method 也只能先成为 candidate，并必须接受独立 transfer qualification。

禁止 `if method_count >= N: synthesize()` 这种程序语义触发。Meta-Learning 由用户明确要求、模型自主选择，或作为低优先级学习任务调度；程序只能提供机械聚类/来源事实，不能判定多个 Method 在语义上“其实相同”。

---

# 9. 完整能力增长闭环

```text
Task
  ↓
必要时 Deliberation
  ↓
Answer
  ↓
Episode
  ↓
Reflection
  ↓
Method Candidate
  ↓
Independent Qualification
  ↓
Qualified Method
  ↓
未来 Reasoning Lab
  ↓
更好的 Task Performance
  ↓
更多 Episodes / Methods
  ↓
Meta-Learning
  ↓
Meta-Methods
  ↓
更高质量的未来推理
```

---

# 10. 模型主动 Deliberation，不建立程序语义触发器

禁止：

```text
if complexity_score > 0.8: run 3 critics
if confidence < 0.7: force reflection
if tool_count > 10: start Reasoning Lab
```

推荐：

```text
模型：“当前存在多组冲突证据，我需要进一步拷问。”
模型：“我需要寻找反例。”
模型：“这个问题似乎存在已学 Method，我先检索。”
用户：“用已积累的方法再深入审查一次。”
```

程序只负责创建隔离运行、提供检索、资源/权限边界、持久化 provenance 和返回 ReasoningBrief。

---

# 11. Unified Resource Governor / 统一资源治理

> RG-0 详细权力边界、数据契约与测试矩阵见 `docs/DESIGN-20260910-resource-governor-rg0.md`。RG-0 仅冻结 contract，不接管任何 runtime path。

RG-1 最小运行时与 Learning 迁移细则见 `docs/DESIGN-20260910-resource-governor-rg1.md`；RG-1 只拥有 lease/concurrency/service-order 机械权力，Task/SubAgent/provider rate/cost/trust/cancel 仍未接入。

RG-2 provider-call lease 与本地 runtime concurrency 细则见 `docs/DESIGN-20260910-resource-governor-rg2.md`；RG-2 只把已选择的 Task/SubAgent/Learning 本地 provider 调用接到同一机械 runtime lease，cloud rate/cost/trust/cancel 仍后移。

RG-3A cloud facts contract 见 `docs/DESIGN-20260910-resource-governor-rg3a-cloud-facts.md`；**RG-3A 仅冻结 cloud resource facts contract，不接 cloud enforcement**：显式区分 product/account identity、usage unknown vs zero、safe provider error/reset facts、quota、动态 pricing，以及 concurrency/rate/quota/cost 独立资源维度；TrustDomain/cancel 仍不接线。

RG-3B transport observation / shadow 见 `docs/DESIGN-20260910-resource-governor-rg3b-transport-shadow.md`；**RG-3B 只旁路捕获 typed provider transport facts**，admission/routing/fallback/enforcement 不消费 shadow；无法证明含义的 reset/rate 字段保持 unknown。

RG-3C unified provider-call settlement / shadow 见 `docs/DESIGN-20260910-resource-governor-rg3c-provider-call-settlement.md`；qualification 见 `docs/QUALIFICATION-20260910-resource-governor-rg3c.md`。**RG-3C 已 PASS/CLOSE：统一 logical call identity、每次真实 transport send 的 attempt lineage 与 durable/idempotent accounting**。已知 usage 求和与完整性分开表达；open/unsettled send 保持 unknown exposure；settlement 仍不参与 admission/routing/fallback/enforcement。

RG-3D global ledger projection / shadow admission facts 见 `docs/DESIGN-20260910-resource-governor-rg3d-ledger-projection.md`；qualification 见 `docs/QUALIFICATION-20260910-resource-governor-rg3d.md`。**RG-3D 已 PASS/CLOSE，且不把 per-call complete 外推为 account/window complete**：EventStore 继续是 SoT，SQLite 仅为可重建的跨 Session 派生索引；scope binding、exact window、fact validity/freshness、LFL source-set coverage 与 provider-global coverage 分离表达，provider-global 默认 unknown。真实 DeepSeek/GLM/MiniMax projection canary 3/3 PASS；RG-3D 仍不产生 admit/reject/defer，也不接 cloud enforcement。下一阶段为 RG-3E Authoritative Vendor/Product Adapters。

RG-3E authoritative vendor/product adapters 见 `docs/DESIGN-20260910-resource-governor-rg3e-authoritative-adapters.md`；qualification 见 `docs/QUALIFICATION-20260910-resource-governor-rg3e.md`。**RG-3E E0-E2 已 PASS，但整体 HOLD / 未完全 CLOSE**：PRODUCT resource scope、公开事实与 exact product/account/project truth 分层、显式 non-secret resource manifest 与三家 pure normalizer 已完成资格化；当前真实 routing targets 在无 resource manifest 时如实保持 product_unbound，未调用 product-specific control plane。E3/E4 必须等显式产品/账户绑定后再做 read-only schema/live fact qualification；RG-3F 不启动，RG-3E 仍不接 ResourceGovernor/admission。

这套架构必须同时适用于：

```text
本地 MLX
llama.cpp
vLLM
remote self-hosted
GLM
MiniMax
DeepSeek
未来其他云端 API
```

统一 Execution Class：

```text
FOREGROUND_TASK
SUBAGENT
DELIBERATION
BACKGROUND_LEARNING
QUALIFICATION
META_LEARNING
```

默认服务优先级：

```text
FOREGROUND_TASK
    >
SUBAGENT / 用户当前请求触发的 DELIBERATION
    >
BACKGROUND_LEARNING
    >
QUALIFICATION / META_LEARNING
```

如果 Deliberation 是当前用户任务的一部分，可以按前台工作处理。后台 Reflection 与 Meta-Learning 不能阻塞新用户请求。

ProviderResourceProfile 只暴露机械事实：

```text
runtime_type
max_concurrency
rpm_limit
tpm_limit
remaining_rate_budget
supports_cancel
supports_priority
supports_parallelism
local_memory_pressure
local_cache_slots
estimated_cost
trust_domain
```

程序只能依据这些事实进行 resource admission，不能把资源调度升级成语义策略裁判。

本地风险包括 GPU/统一内存竞争、prompt concurrency、KV/prompt cache、Prefill 与单 slot；云端风险包括 RPM/TPM、provider queue、限流、成本、quota、并发与 trust-domain。因此：

> **独立 Session ≠ 资源隔离。Resource Governor 是通用运行时能力，而不是 Method Learning 私有功能。**

---

# 12. Trust Domain 与隐私边界

不能因为某个 provider 空闲，就自动把当前任务内容发送过去。

必须经过：

```text
Episode / Task Material
    ↓
trust domain / data policy
    ↓
allowed execution providers
    ↓
resource admission
```

例如：

```text
local-only -> 只能本地推理 / 学习
cloud-approved -> 只能在批准 cloud provider 中运行
provider-restricted -> Deliberation 只能在原 provider
```

Runtime 负责机械边界；模型只能在授权范围内选择。

---

# 13. Reasoning Lab 工具边界

第一版默认只提供只读能力：

```text
method_search / method_get
experience_search / experience_get
rule_search / rule_get
skill_load
evidence_search / evidence_get
episode_get
```

默认不开放：

```text
edit_file
execute_command
deployment
send_message
delete
external mutation
```

除非用户明确委托的是需要副作用的独立子任务，而不是纯推理。

---

# 14. 保存推理产物，不保存隐藏思维链

持久化：

```text
hypotheses
evidence refs
counterevidence
assumptions
unknowns
alternatives
decision boundary
Method refs
Skill refs
verification plan
```

不持久化：

```text
token-by-token hidden reasoning
private reasoning_content replay
无限 scratchpad
```

此原则同时适用于 Deliberation / Reflection / Qualification / Meta-Learning。

---

# 15. Crash Recovery 与 Durable Learning Job

后台 Learning 不能只是 fire-and-forget thread。

使用持久 Learning Journal：

```text
queued
-> admitted
-> started
-> candidate_saved | none | failed | cancelled
```

每个 job 具有稳定 `learning_job_ref + source_episode_ref`。重启后 reconcile durable state；candidate 已存在则不得重复 Reflection；`none` 也必须持久化；避免同一 Episode 因重启生成多个措辞不同的 Candidate。

Meta-Learning Job 同样需要 durability。

---

# 16. Usage、成本与 Cache 分账

至少分开：

```text
foreground
deliberation
learning
qualification
meta_learning
```

分别统计：

```text
tokens_in
tokens_out
cache_hit_tokens
provider latency
queue delay
estimated API cost
local compute duration
```

目标是能回答：学习额外成本是否换来了未来前台任务更低成本和更高准确率。

本地后台 Learning 应优先 `low-priority / non-pin / transient`。必须测 foreground cache hit、TTFT、prefill latency、queue delay 和 learning occupancy；不能只看 WebUI done 是否及时就声称“零影响”。

---

# 17. 用户反馈作为 Learning Signal

可作为机械 friction fact 的信号：

```text
high rounds
many tools
tool failures
duplicate calls
stagnation
max_iterations
explicit negative feedback
```

`downvote + note` 是强机械信号。

自然语言纠正不能用“不对/错了/你应该”等关键词程序分类。程序只证明“这是 previous episode 后紧邻的真实 user followup”，然后由 Learning Model 判断它是纠正、补充、继续还是换任务。

---

# 18. 三个学习尺度

## L1 — Episode Learning

```text
Episode -> Reflection -> Method candidate
```

## L2 — Method Transfer

```text
New Task -> retrieve Method -> Deliberation -> apply / reject / modify
```

## L3 — Meta-Learning

```text
Method A/B/C
+ transfer results
+ failures
+ counterexamples
-> synthesis
-> Meta-Method candidate
```

三层 provenance 与 qualification 必须可追溯。

---

# 19. Method 生命周期与 Applicability

推荐生命周期：

```text
teacher
candidate
qualified
active
hold
invalidated
retired
```

约束：

- Teacher 不可修改；
- Candidate 不能直接 active；
- Candidate 不能用 source Episode 自我 qualification；
- Qualified 必须有独立 Evidence；
- Active 只是检索状态，不表示自动适用；
- Hold 保留不确定 Method；
- Invalidated 保留失败原因；
- Retired 退出普通 discovery，但 exact ref 可追溯。

即使 Method 已高度 qualified，检索仍应明确：

```text
task_applicability=not_evaluated
```

当前任务是否适用始终由模型判断。

---

# 20. Method 组合与防止“越拷问越差”

Reasoning Lab 可以动态组合多个 Method + Skill + Evidence，形成 task-local reasoning plan。只有 post-task Reflection 发现组合具有普适价值时，才沉淀成新 Method。

禁止固定 critic 次数，也不能要求 Challenger “必须找出错误”。允许合法结论：

```text
no_material_issue
current hypothesis survived challenge
```

原始 Evidence 必须保留，最终是否修改答案由 Task Model 决定。

---

# 21. 如何判断 LFL 是否真的越来越聪明

核心指标不是 Method 数量、Reflection 次数或库大小，而是：

> **积累的学习能力是否改善了从未见过的新任务？**

长期 capability benchmark 至少比较：

```text
A. Base model / normal LFL
B. + qualified Methods
C. + Methods + Reasoning Lab
D. + Methods + Reasoning Lab + challenge Skills
E. + Meta-Methods
```

测量：

```text
accuracy
task completion rate
tool calls
irrelevant exploration
evidence errors
unsupported inference
boundary overreach
recovery from wrong hypothesis
cross-task transfer
tokens
latency
cost
foreground cache hit
```

真正能力增长应表现为：

```text
accuracy ↑
transfer ↑
correction quality ↑
unnecessary tools ↓
unsupported confidence ↓
foreground cost per solved task ↓
```

Anti-Metrics：不要追求更多 Reflection、更多 Method、更长 reasoning、更多 Critic、更多 tool calls、更多 memory。

---

# 22. 推荐运行时组件

```text
TaskRunner

ReasoningLabCoordinator
DeliberationRunStore
ReasoningBriefStore

LearningCoordinator
LearningJobStore
ReflectionRunner

QualificationCoordinator
MetaLearningCoordinator

MethodStore
EpisodeStore
SkillStore / Skill Loader
EvidenceStore
ExperienceStore
RuleIndex

ResourceGovernor
TrustDomainPolicy
UsageAccounting
```

不要把这些职责重新塞回 `LoopEngine`。

---

# 23. Event Model

建议事实型事件：

```text
deliberation.queued
deliberation.started
deliberation.completed
deliberation.failed

learning.queued
learning.started
learning.candidate_saved
learning.none
learning.failed

qualification.started
qualification.recorded

meta_learning.started
meta_learning.candidate_saved
meta_learning.none

resource.admitted
resource.deferred

method.used
method.transfer_observed
```

Event 记录事实，不由程序写 `method_was_correct=true` 等语义结论；若存在此类评价，必须明确其模型来源与 provenance。

---

# 24. Priority Model

```text
P0 FOREGROUND_TASK
P1 用户当前请求触发的 DELIBERATION
P1 当前任务 SUBAGENT
P2 显式安排的后台 DELIBERATION
P3 LEARNING
P4 QUALIFICATION
P5 META_LEARNING
```

具体数值可配置，但 foreground 始终拥有最高服务优先级。

---

# 25. 推荐实施阶段

## Phase 0 — 冻结 Architecture SoT

锁定 Task / Deliberation / Learning / Qualification 权力边界、Episode identity、Method provenance、no-hidden-CoT、provider-independent resource class、trust-domain。

## Phase 1 — Learning Plane P0 收口

1. 把同步 Reflection 完全移出 Task completion critical path；
2. 用 exact Episode 作为 Learning SoT；
3. 修 production `current_episode_ref()` provenance 断点；
4. qualification Episode identity 改为 runtime-derived；
5. 建立真实 LearningPlane / SSE-done / foreground-priority tests；
6. `git diff --check` 全绿；
7. alternate Web port live qualification。

## Phase 2 — Unified Resource Governor

同时覆盖本地 + GLM / MiniMax / DeepSeek，不先做成本地专用。统一 execution class、priority、并发、RPM/TPM、成本、quota、trust-domain 等机械资源边界。

## Phase 3 — Reasoning Lab MVP

加入 `DeliberationRun`、只读 Method/Experience/Rule/Skill/Evidence 访问、`ReasoningBrief`；第一版只由用户显式调用或模型自主调用，不加入 complexity classifier。

## Phase 4 — Method Transfer Qualification

在独立 unseen-task A/B 中验证 Method/Reasoning Lab 是否真正改善 accuracy、tool waste、overreach、latency/cost。Telemetry 不自动决定 promotion。

## Phase 5 — Meta-Learning

只有 Phase 4 出现真实正向 transfer 证据后才进入。支持多个 Method synthesis -> Meta-Method candidate，并进行独立 qualification。

---

# 26. 必须覆盖的测试

## Task Completion Isolation

- slow Reflection 不延迟 LoopResult；
- SSE done 先于 Reflection 完成；
- Learning pending 时用户可以开始下一轮；
- Learning 不会让 source Session busy。

## Episode Isolation

- Reflection 只读取 exact Episode；
- 同 Session 前一个 task 不污染；
- hidden reasoning sentinel 不进入学习材料。

## Resource Isolation

- local foreground 优先于 queued learning；
- cloud RPM/TPM 为 foreground 保留；
- Learning 不能无限占用 provider concurrency；
- trust-domain 阻止未授权跨-provider Learning。

## Provenance

- candidate source Episode runtime-derived；
- source model/provider runtime-derived；
- qualification Episode runtime-derived；
- 同一 Episode 不能 self-qualify；
- lineage 不能轻易绕过 independence。

## Deliberation

- Reasoning Lab 不能修改 source Session；
- 默认 tools 全部只读；
- ReasoningBrief 不保存 hidden CoT；
- Task Model 可接受或拒绝 Lab 结果。

## Method Lifecycle / Crash / Meta-Learning

- candidate 不能直接 active；
- Teacher immutable；
- completed LearningJob 重启后不重复；
- candidate 已保存时 reconcile；
- `none` 不无限重跑；
- Meta-Method 记录 source Methods，且必须独立 qualification。

---

# 27. Live Qualification

真实端到端故意触发 Learning，测：

```text
T0 = final answer durable
T1 = SSE done
T2 = learning started
T3 = learning completed
```

要求：

```text
T1 - T0 ≈ immediate
```

然后在 Learning pending/running 时立刻发送第二个 foreground 请求，必须证明 foreground proceeds。

本地还要测 cache_hit_tokens / TTFT / prefill latency / queue delay；云端还要测 RPM / TPM / 429 / queue delay / foreground API latency / learning cost。

---

# 28. Architecture Invariants

**INV-1** 用户可见任务完成不依赖 post-task Learning 完成。
**INV-2** Reflection 来源必须是 Episode，不是任意 Session tail。
**INV-3** 隐藏 Chain-of-Thought 不能作为持久学习材料。
**INV-4** Learning 不能修改 source Task Session。
**INV-5** Foreground 始终优先于后台 Learning。
**INV-6** 资源治理必须 provider-agnostic，同时适用于 local 和 cloud。
**INV-7** 跨 provider Learning 必须服从 trust-domain。
**INV-8** Candidate provenance 必须 runtime-derived，模型不能伪造。
**INV-9** Method 不能使用 source Episode 自我 qualification。
**INV-10** Method applicability 永远由模型判断。
**INV-11** Reasoning Lab 只提供论证和结构化推理成果，不拥有最终裁决权。
**INV-12** 不得强制固定次数 self-critique。
**INV-13** Meta-Method 只能先成为 candidate，并需要独立验证。
**INV-14** 系统是否“变聪明”必须通过 unseen-task performance 判断，而不是 Method 数量。

---

# 29. 这套架构不是什么

它不是：

```text
越来越大的 prompt
自动注入全部 Method
第二套程序语义规则引擎
固定次数多 Agent Debate
隐藏 CoT 档案
关键词复杂度分类器
程序化 stopping oracle
只针对本地模型
只针对云端模型
```

---

# 30. 产品级最终定义

LFL 长期不应该只被定义为“有记忆的 Agent”。更准确的目标是：

> **一个能够积累可复用 Method、在当前任务中主动调用和质疑这些 Method、通过独立任务验证 Method，并长期形成更高阶推理方法的学习型 Agent Runtime。**

最终能力循环：

```text
Experience
   ↓
Method
   ↓
Deliberation
   ↓
Better decision
   ↓
New experience
   ↓
Better Method
   ↓
Meta-Method
   ↓
Better future reasoning
```

只有长期 Benchmark 证明 accuracy↑、evidence error↓、unnecessary exploration↓、correction ability↑、cross-task transfer↑、foreground cost per solved task↓，才可以合理地说 LFL 在系统层面真正变得更聪明。

---

# 31. 最终路线裁决

LFL 后续正式演进为：

> **Task Plane + Deliberation Plane + Learning Plane + Qualification Plane + Meta-Learning**

并共享 Provider-agnostic Resource Governor、Episode-level provenance、Trust-domain boundary 与 LLM-First authority。

实施顺序固定为：

1. 先冻结本总 Architecture SoT；
2. 完成 Learning Plane P0 收口；
3. 抽出统一 Resource Governor，一开始同时覆盖本地与云端；
4. 实现 Reasoning Lab MVP；
5. 通过独立 unseen-task transfer A/B 证明实际收益；
6. 只有正向 transfer 成立后才进入 Meta-Learning。

这个顺序的目标不是增加 Harness 控制，而是在保持 LLM-First 的前提下，让 LFL 真正具备持续积累和提升推理能力的可能。
