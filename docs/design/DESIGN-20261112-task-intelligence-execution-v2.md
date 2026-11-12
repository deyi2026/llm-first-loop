# LFL 任务智能与执行能力提升需求及实现设计书

- **文档 ID**：DESIGN-20261112-task-intelligence-execution-v2
- **日期**：2026-11-12
- **状态**：DeepSeek-v4-flash 独立审查后 v2 设计提案；未实施、未授权生产变更
- **范围**：Task Plane、Deliberation、Knowledge/Memory、Tool Execution、SubAgent、Learning、Qualification/Evaluation
- **原则**：LLM-first；程序最小化；当前事实与证据优先；渐进验证；不以流程复杂度代替智能

> 基线声明：本轮读取的 macOS 工作区为 main@594a3bce，本地领先 origin 3、落后 19，且存在未提交/未跟踪变更；远端 main 检查时已到 0e933d6d8。因此本文不把本地快照等同远端或 Deepin 生产，也不授权代码修改、合并、push、发布或重启。

---

## 0. 独立拷问审查与修订裁决

**审查来源**：LFL Web 独立会话 `a2b6e90b-e91e-452f-ad74-2b61eaed75ca`；HTTP 回执 `model_used=deepseek/deepseek-v4-flash`，17 轮，设计审查 Verdict=`PASS_WITH_IMPROVEMENTS`。这仅证明 LFL 会话路由的模型身份，不证明远端底层权重身份；亦非代码审查 PASS 或生产发布资格。完整长审查答复的 LFL 本机证据路径为 `data/audit/long_answers/a2b6e90b-e91e-452f-ad74-2b61eaed75ca/8f05f06ef6af3da2.md`。

**审查分级**：P0=3 / P1=5 / P2=3（这里的 P0 是**设计实施前的必要纠偏**，不是生产故障等级）。本版采取以下裁决：

| 编号 | 审查发现 | v2 处置 |
|---|---|---|
| P0-1 | 新任务 YAML 复制现有 Goal/Task 状态，可能制造平行事实源 | **接受**：删除新持久化状态 schema，改既有字段映射与按需派生投影 |
| P0-2 | 执行前后状态/幂等层重复既有 Journal/SideEffectRegistry | **接受**：先做现有工具覆盖矩阵，只补被复现的缺口 |
| P0-3 | Method 修订改变 content_hash 与 version_scope，使前后收益不可比 | **接受**：加入整理前快照冻结、版本同一性与 `incompatible` 禁止比较 |
| P1-1 | 10–15% 等目标缺样本量/置信区间，不能当统计结论 | **接受**：仅为规划愿景，实验门槛由预注册与样本量决策 |
| P1-2 | C 臂无同配置重复臂，缺模型随机波动噪声地板 | **接受**：增加 B′ 重复基线与逐 cell 参数冻结；区分探索性试验与确证实验 |
| P1-3 | “继续”若程序强制核 Goal，会覆盖自然语义 | **接受**：按需取事实、由模型决定；普通轮次零强制注入 |
| P1-4 | 只看成功率/重试次数会漏缓存成本、漏掉应重试而未重试 | **接受**：增加双向 guardrail、LCP/cache/有效成本 |
| P1-5 | 重写三份审计文档会与既有报告重复 | **接受**：合并为一份 delta 审计与结论继承表 |
| P2-1 | 按年龄/数量批量归档可能丢唯一学习记录 | **接受**：仅有负证据、可逆且抽样验证时才处置 |
| P2-2 | dirty main 及新旧 SHA 可能令审查和测试错位 | **接受**：隔离候选、精确 SHA、变更范围与回执绑定 |
| P2-3 | “建议深思”式工具能力注入会诱导模型被动服从 | **接受**：只提供数值、来源、能力事实，不给程序化语义建议 |

**重要限定**：本次审查者只读核对的是本地 `main@594a3bcec`，不是最新远端或 Deepin 生产；部分符号/行号的准确性需在 M0 对最新候选复核。审查者自述未跑测试、未核真实 provider-visible 注入、未核实验温度/seed、未查最新生产代际。本文不把这些未知当成已验证事实。

---

## 0. 执行摘要

### 0.1 目标

LFL 已有多 Provider、推理强度配置、工具调用、任务续接、Goal/Task、Method/Experience、语义检索、多代理、反思学习、资格验证、自评和演进机制。下一阶段的主要问题不是“再增加一个 Agent 功能”，而是这些能力是否能在真实任务中形成低摩擦、可观测、可验证的闭环。

目标定义：

> 在模型本身不变的条件下，使同一模型借助 LFL 获得更好的任务理解、证据、推理资源、工具行动、错误反馈和跨任务经验；以真实任务完成率、结果质量、可靠性及全程成本证明提升。

### 0.2 拷问后的关键裁决

1. **不另造总控 Planner。** 模型是语义规划者；LFL 提供当前事实、能力目录、资源预算、持久状态和工具。程序只硬执行协议、安全、授权、资源与副作用边界。
2. **不硬编码简单/复杂任务流程。** 可提供轻量能力/预算建议，但路径、是否深思、检索、委派由模型判断。
3. **不以知识卡数量代表学习成果。** 重点是召回质量、准确水合、使用决策、独立验证和跨任务净收益。
4. **不把工具调用成功当任务成功。** 完成必须回到用户目标和可观察证据；不可核验时标记未验证。
5. **不把每次失败变成新流程或重试。** 先归因，再选最小恢复动作；同一根因重复失败时停止无效循环。
6. **不默认所有任务使用多代理/强推理。** 必须证明质量收益大于延迟、token 与协调成本。
7. **不立即启动全库自动整理。** 先只读 dry-run、抽样验证、可逆修订，再决定是否低频调度。

### 0.3 推荐顺序

先建立真实任务基线与轨迹归因；再做“工作状态与任务结算”和“失败反馈”最小闭环；接着改善知识调用与资格验证；最后试验自适应推理、模型路由和多代理协作。

---

## 1. 现状与证据边界

### 1.1 已有基础

| 能力 | 已存在基础 | 不重复建设 |
|---|---|---|
| 模型 | Provider、model_catalog、switch_model、thinking_mode、reasoning_effort、窗口/预算适配 | 不另建模型注册中心 |
| 任务循环 | LoopEngine、严格 function calling、工具执行记录、run/session 生命周期 | 不另造主循环 |
| 上下文 | 历史预算、压缩/归档、精确证据引用、长任务续接 | 不全量注入历史 |
| 知识 | search_records、Method/Experience、exact hydration、usage、Learning Plane | 不新建平行知识库 |
| 多代理 | SubAgent 生命周期、模型来源、预算/结算、Reviewer | 不默认拆分所有任务 |
| 长任务 | Goal、Task、Checkpoint、恢复与事件记录 | 不另建重叠任务数据库 |
| 学习演进 | Reflection、候选 Method、Qualification、self_evaluate、submit_evolution | 不让自评直接晋级 |
| 执行工具 | 文件、命令、浏览器、桌面、服务管理及权限边界 | 不以智能为由扩大权限 |

### 1.2 已读取的关键证据

- README.md：消息进→理解→行动→真诚回答→记住；程序负责感知、执行、协议、安全、持久化和恢复，模型负责语义决策。
- docs/DESIGN-20260910-adaptive-reasoning-learning-architecture.zh.md：已有 Task / Deliberation / Learning / Qualification 四平面及 Meta-Learning 总体设计。
- docs/PLAN-20261014-architecture-agency-refactor.md：稳定核心原则最小常驻；长知识按需 discovery→exact hydration；调用记录不等于有效收益。
- docs/ANALYSIS-20261111-memory-consolidation-gap.md：11 月 11 日快照记载 Method 2,025 张、Experience 946 张；Method candidate 1,960 张（96.8%）；评分 sidecar 覆盖 220/2,025（约 10.9%）。注入实际条数/字节数未核，不能把候选池比例直接解释为 prompt 噪声。
- docs/RESULT-20261006-method-binding-v3.md：Method Subject-Binding 确证实验未达到预注册推广阈值，未授权生产推广；“看起来有用”不能代替独立任务收益证据。
- docs/ASSESS-20261021-method-pool-funnel-census.md：历史快照显示生成、评估、使用流水线曾脱节；属于 10 月 21 日数据，不作为当前计数。
- docs/analysis/learning-queue-cluster-verdict-20261105.md：历史队列曾出现 dead jobs 阻塞健康任务，后续有终态化修复；不能据此声称当前仍有同样问题。

### 1.3 事实、假设、未知分离

| 类型 | 内容 | 处理 |
|---|---|---|
| 已有事实 | 组件和工具存在，部分设计/实验报告存在 | 复用 |
| 历史事实 | 曾有队列阻塞、Method 评测停滞、续接故障 | 作为回归案例，核最新版本 |
| 待核假设 | 重复检索、路由不佳、知识召回盲区 | 先采集真实轨迹 |
| 待核假设 | provider-visible 上下文有效信息密度不足 | 必须抓真实请求证据 |
| 待核假设 | 自适应路由能提升任务表现 | 冻结任务集做对照 |
| 禁止推断 | 本地 main 等于远端 main 或生产 live | 每次核 SHA、版本、代际、进程和回执 |

---

## 2. 目标、非目标与成功定义

### 2.1 目标

- **G1 任务理解**：识别最终结果、范围、约束、完成条件和授权；歧义时只问最关键问题。
- **G2 模型能力发挥**：提供准确事实、可用工具/模型能力、上下文余量和执行反馈；不替模型做语义判断。
- **G3 可靠执行**：行动后观察，失败后归因，修复后验证；副作用动作不重复执行。
- **G4 知识复用**：相关知识能被发现、精确水合、判断适用性并记录结果；候选/旧经验不能伪装成权威。
- **G5 长任务连续性**：中断后从可验证工作状态继续，不重做已完成工作，不依赖旧对话猜当前事实。
- **G6 持续测量**：同模型、同任务、同预算下比较基线和候选，确认收益与代价。

### 2.2 非目标

- 不训练/微调底层模型权重。
- 不改造成固定 DAG/工作流引擎，不强迫每个请求建立计划表。
- 不默认引入新向量库、图数据库、消息总线、后台常驻 Agent。
- 不全量注入 Method/Experience/历史。
- 不让 LLM 自授权限、改安全边界或批准生产副作用。
- 不以调用次数、卡片产量、token 减少单独代表智能提升。
- 不为指标好看放宽评测判据或门禁。

### 2.3 成功定义

改进须同时满足：
1. 目标任务成功率/结果质量有可复现改善，或可靠性显著提高；
2. 无新增安全、数据完整性、隐私或授权风险；
3. 全程成本没有不合理恶化；
4. 失败能准确识别，不伪报成功；
5. 对弱模型有明确收益，或对强模型有质量/效率收益；
6. 独立 holdout 可复现，不只在开发样本有效。

---

## 3. 设计原则：拷问与裁决

### Q1：是否应由程序判断简单/复杂并固定流程？

**反方质疑：** 分类器容易错分；硬编码“代码任务必规划、网页任务必多代理”会削弱模型判断并形成流程债。

**裁决：** 不做强制任务分类器。提供模型、推理档位、上下文预算、工具、权限和成本事实。模型自主决定深思、检索、委派或切换模型。程序只硬执行资源、安全、协议和副作用边界。

**验收：** 冻结任务集中，模型能自选路径；简单任务无明显额外轮次/延迟，困难任务成功率或质量提升。

### Q2：为何不把更多规则、Method、Experience 直接注入 prompt？

**反方质疑：** 信息多不等于有用。已有无条件 Method 附录干扰弱模型工具选择的历史实验。全量注入会降低注意力密度、破坏缓存、增加成本并让旧事实误导。

**裁决：** “核心认知最小常驻 + 任务知识按需发现 + 精确引用水合”。核心层只放少量稳定且验证过的 LFL 原则；其他知识 compact discovery，模型判断适用性后 exact hydrate。不得静默截断，完整源必须可恢复。

**验收：** provider-visible payload 可复现；注入大小受控；相关知识召回改善；无关知识干扰不增加。

### Q3：2,025 张 Method 是否说明知识系统失控？

**反方质疑：** 96.8% candidate 不直接证明检索污染，候选可能仅在主动检索时出现；10.9% 评分覆盖也不说明其余卡片质量差。

**裁决：** 先只读盘点生成→检索曝光→exact hydration→使用声明→独立资格→任务净收益。区分“可发现”和“默认注入”。抽样核重复、过期、矛盾、无来源卡；先可逆 archive/supersede，不删除、不批量改写。

**验收：** 每项有文件级/事件级口径；曝光、精确水合、有效使用、独立验证、过期/冲突分开报告。

### Q4：record_use 是否证明 Method 有效？

**反方质疑：** record_use 是使用声明，不等于方法改变行为，更不等于提升成功率。

**裁决：** 区分发现、读取、声明、效果四层。只有独立任务证据支持 qualification；源 episode 不能给自己的 candidate 晋级。

**验收：** efficacy 报表不把 retrieved/hydrated/declared 当效果；holdout 任务冻结判据。

### Q5：是否每个任务都强制“计划—执行—复盘—验证”？

**反方质疑：** 简单问题过度规划会增加成本，让模型忙于维护计划。

**裁决：** 不强制显式计划。模型按不确定性、跨度、副作用风险和失败反馈决定何时外显计划。长任务复用 Goal/Task/Checkpoint，短任务不必创建。

**验收：** 简单任务无明显额外开销；复杂任务中断后可恢复且不重复副作用。

### Q6：工具失败后是否自动重试？

**反方质疑：** 网络错误、权限拒绝、参数错误、业务拒绝、超时、执行状态未知是不同故障。统一重试可能重复发送/发布/写入。

**裁决：** Observe→Diagnose→Choose→Act→Verify。只对明确幂等、无副作用读取做有限重试；副作用动作先核状态/幂等键/回执，未知时停止，不盲目重发。

**验收：** 每类错误有恢复策略和“不应重试”反例；超时能区分未执行、已执行、未知。

### Q7：是否所有工作都用强模型/独立 Reviewer？

**反方质疑：** 多模型增加费用、等待和冲突，Reviewer 也可能有共享盲点。

**裁决：** 按风险和不确定性由模型选择升级审查。高风险代码、架构、发布、生产变更可用独立 Reviewer；普通只读任务不强制。Reviewer 审冻结候选和完整证据。

**验收：** 统计有效缺陷、误报、耗时和逃逸率，证明净风险下降。

### Q8：模型路由是否由程序自动决定？

**反方质疑：** 能力标签可能不准；不同 Provider 的 high/max 参数不等价；错误切换会丢上下文并增加成本。

**裁决：** 程序提供实测画像，模型决定 switch_model。切换保留目标、状态、证据锚点；Provider 参数按自身契约，不假定等价。用户显式选择不得静默降级。

**验收：** 记录选择来源、理由、切换前后结果与全程成本。

### Q9：如何防止长任务“看似工作”却停滞？

**反方质疑：** token、工具调用、进程存活都不等于进展；自动 kill 可能丢半成品；重复 Goal 会碎片化。

**裁决：** 观察最后有意义状态变化、阻塞、完成证据、下一动作。提醒模型诊断，不自动 kill；恢复时核当前事实，不照抄旧 checkpoint。

**验收：** 模拟 timeout、子代理失败、Host 中断、重复唤醒、lease 过期；恢复无重复副作用、无孤儿任务。

### Q10：是否立即启用 nightly dreaming/自动整理？

**反方质疑：** 未验证流程常驻化会制造周期成本和错误归档；历史模板改写曾造成重复污染。

**裁决：** 先手动 dry-run，只读扫描；模型提出逐条修订候选，人工/既有规则裁决。识别准确率稳定后再考虑低频抽样，不做全库 nightly rewrite。

**验收：** dry-run 不改源；候选有来源/反证；归档可逆；抽样 precision 达预设门槛才调度。

### Q11：如何证明 LFL 变聪明而非模型随机波动？

**反方质疑：** 单次演示、少量成功、调用减少或回答更长都不能证明提升。

**裁决：** 预注册 A/B：同模型、任务、输入、工具权限、预算、环境；冻结 holdout；报告成功率、质量、安全、token、时间、人工介入。强/弱模型分层，尽可能盲评。

**验收：** 有 run IDs、输入/环境指纹、模型/参数身份、工具轨迹、最终证据和全程成本。

### Q12：是否立即拆 engine.py 或建新智能中枢？

**反方质疑：** 大规模重构不等于能力提升，会扩大回归面并延迟收益。

**裁决：** 先做纵向切片：选高价值任务族，从输入到完成、失败到恢复、经验到复用贯通。只有真实模块边界阻碍时才最小拆分。

**验收：** 每个代码变更对应可复现行为问题；保持 wire/event/history 兼容，不增加无收益层次。

---

## 4. 目标架构：模型主导的自适应任务闭环

```text
User Goal / Current Request
        |
        v
Task Understanding (LLM-owned semantics)
  - desired outcome / constraints / ambiguity
  - authorization scope / completion criteria
        |
        v
Current-State & Capability Perception (runtime facts)
  - current model / reasoning capability / context budget
  - available tools / permissions / active run / goal state
  - current source / deployment / external state when relevant
        |
        v
LLM Deliberation (LLM-owned decisions)
  - answer / retrieve / plan / use tools
  - choose reasoning depth / model / subagents when justified
        |
        v
Action -> Observation -> Diagnosis -> Next Action
  - tool journal / exact outputs / errors
  - idempotency and side-effect settlement
  - model-controlled recovery within authorization
        |
        v
Outcome Verification
  - compare actual state against user's goal
  - success / partial / blocked / unknown
  - durable evidence refs
        |
        +--------------------------+
        |                          |
        v                          v
Task Closeout                 Async Learning
  - truthful answer            - episode reflection
  - completed / remaining      - candidate knowledge
  - next action if blocked     - independent qualification
                                 - measured future reuse
```

| 平面 | 模型负责 | 程序负责 | 不允许 |
|---|---|---|---|
| Task | 理解目标、策略、完成语义 | 保存目标/任务状态、事实和证据引用 | 程序猜用户意图 |
| Deliberation | 推理深度、工具/模型/代理选择 | 提供能力/预算/上下文事实 | 固定流程替代语义决策 |
| Execution | 选择动作、解释观察、选择恢复 | 协议、权限、幂等、持久化、执行和回执 | 工具成功即宣称任务成功 |
| Knowledge | 判断相关性、适用性、是否使用 | 检索、水合、来源和账本 | 程序强迫模型用某卡 |
| Learning | 反思、抽象、提出修订 | 异步队列、来源冻结、资格记录 | 自评自证 |
| Evaluation | 解释结果与失败族 | 冻结任务、记录身份/成本、统计 | 事后放宽判据 |

### 4.1 既有任务状态权威映射（不新建 schema）

**禁止**创建第二个 `task_state.json`、独立 `completed/remaining` 状态仓库或平行终态枚举。既有 `Goal`、`Task`、事件日志、ToolExecutionJournal 是状态权威；模型看到的是当前任务所需的、只读的 **derived view**，不是需要双写的新事实源。

| 需求字段 | 既有来源/审查线索 | 待核缺口与最小处理 |
|---|---|---|
| user_goal/status | `src/llm_loop/introspection/goal.py` 中 `Goal.objective/status` | 核当前源、权限与状态新鲜度，不复制存储 |
| completion criteria | `src/llm_loop/introspection/task_store.py` 的 `Task.acceptance/done_when` | 核判据覆盖是否充分；不足时扩既有 Task 字段 |
| evidence_refs / verified | `Task.evidence_refs/evidence_verification_status` | 核引用是否真实可恢复，不能凭模型自述变已验证 |
| blocked/remaining | `Task.blocked_reason`、任务状态/依赖、Goal checkpoints | 仅派生状态；版本冲突时展示冲突并重新查询，不擅自择一 |
| next_action | `Goal.checkpoints[what,evidence,path,next]` 与当前用户要求 | 历史 next 为线索，当前选择仍归模型 |
| longrun continuity | `src/llm_loop/core/longrun_continuity.py` | 延续既有非权威历史投影；验证续接当前性 |
| constraints / authorization | 当前用户明示授权、现有授权/权限事实 | 不从旧 Goal 推导新授权；不足标 `unavailable` |
| last meaningful progress | 现有事件日志和 Task/Goal 时间戳 | 先定义事件级派生指标，未经证据不得新增持久字段 |

**注入规则**：普通任务不得每轮常驻 Goal/frontier；只有模型主动工具查询，或明确相关的长任务续接场景，才给有界、只读、来源可追踪的 tail 事实。纯事实字段不得带“你应该换路”“请继续推进”之类语义指令。先核现有 `longrun_continuity` 是否已经覆盖，不重复搭桥。

**验收**：同一任务的派生视图与原始权威状态一致；一条跨会话续接轨迹二次重放结果一致；简单任务首轮注入为零；用户新指令不被旧 Goal 覆盖；没有第二个持久化状态文件。

---

## 5. 六个能力工作流

### A. 任务理解与轻量工作状态

**需求：** 识别最终结果、范围、约束、交付形式、完成判据与授权。短任务不强制建 Goal；跨会话、多步骤任务复用 Goal/Task。用户说“继续”时核验最近相关目标状态，不创建重复 Goal。重要状态变化更新 checkpoint。

**最小实现：**
1. 盘点 Goal/Task/Checkpoint 在 Web、CLI、Feishu 的真实路径。
2. 选择跨会话任务端到端 trace：消息→恢复→执行→结算→再续接。
3. 只修复复现的重复立项、旧状态误用、进度不可见或完成判据丢失。
4. UI 仅呈现已完成、进行中、阻塞、下一步，不将内部推理轨迹冒充进度。

**验收：** 续接不无故重复建 Goal；重启/切会话可恢复 remaining/blocked/evidence refs；新指令覆盖旧计划；外部动作有真实回执。

### B. 执行反馈与自主纠错（覆盖审计优先）

**前置拷问**：现有 `src/llm_loop/core/tool_execution_journal.py` 已包含 `declared → started → finished → receipt_committed` 和 `started_outcome_unknown` 的恢复语义；`src/llm_loop/core/loop/side_effects.py` 及逐工具 `idempotency_class` 也已有相关能力。不得把设计里的“执行前后状态/幂等标识”误写成待新建第二套系统。

**M0 只读审计**：机器枚举 `tools/builtin/*`，建立 `tool × side_effect_kind × idempotency_class × journal/recovery coverage × unknown handling × evidence` 矩阵；把缺失声明、没有 journal 的动作和危险的重复执行路径分开记录，必须用真实执行轨迹/回归验证，不凭 grep 推断全覆盖。

**只修缺口**：对确实缺失的工具补齐已有字段、真实结果回执、幂等/未知状态路径；不得新建 `unknown` 枚举或独立 journal。工具给模型：错误码、精确来源、stderr/stdout 摘要与完整引用、执行状态及是否能机械确认幂等。恢复策略由模型选择；对副作用 unknown 必须先核状态，不能重发。

**验收**：覆盖表可复现；每一处修复有“故障正例 + 不应重试反例”；重复副作用为零；合法瞬态失败“应重试却未重试导致失败”的数量不能上升；同一根因重复故障给事实计数而不是程序强制换策略。

### C. 知识发现、使用与资格闭环

**需求：** 核验 provider-visible prompt 中核心规则/知识入口的实际字节、条数、来源；分开统计 discovery、hydration、declaration、qualification、outcome；compact 搜索、exact ref 展开；时效/冲突/状态作为事实提供给模型。

**最小实现（内容哈希冻结是前置项）：**
0. 冻结每张参与评测卡的 `content_hash/read_version/version_scope` 与使用账本口径；整理前后仅允许对同版本集合比较；跨版本必须标为 `incompatible`，新版本重新积累独立证据。
1. 只读构建知识漏斗：卡片数、状态、来源、最后验证、重复簇、失效/冲突、评分覆盖。
2. 抓代表性请求实际 provider-visible payload。
3. 选 2–3 个高价值任务族做召回盲测。
4. 核 exact hydrate 的版本、来源和完整性。
5. 记录使用结果，但 efficacy 由独立资格评测决定。
6. 存量知识先 dry-run，提出 archive/supersede 候选；不删除、不批量改写。

**验收：** provider 输入有指纹/预算；召回提升、误召回受控；ref 可追溯；状态准确；报表包含 `content_hash/version_scope`，跨版本不可比时不宣称收益；holdout 净收益达预注册门槛才推广。

### D. 自适应推理与模型路由

**需求：** 模型感知当前模型、推理档位、上下文预算、工具、成本/延迟画像；可选择直接回答、工具辅助、深思、独立复核、子代理或模型切换。Provider 参数保持各自语义。

**最小实现：**
1. 核 model_catalog 元数据来源，缺失标 unavailable。
2. 建立任务族实测画像：成功率、错误率、P50/P95 latency、成本、上下文限制、工具兼容。
3. 提供轻量能力/预算事实，不建固定自动路由器。
4. 对照当前策略、同模型自主调整、允许模型切换三种方案。
5. 切换有 reason/审计，且保留目标、状态、证据。

**验收：** 简单任务无明显退化；困难任务质量/成功率提高；无隐式降级或状态丢失；统计全程成本。

### E. 多代理协作

**需求：** 主模型按任务差异决定委派；子代理目标窄、交付明确、预算/模型/写范围清楚；共享写入隔离或串行；Reviewer 审冻结候选；父代理取得真实终态、产物和未解决项。

**最小实现：**
1. 采样多代理任务，统计有效发现、重复工作、等待、失败、token 和冲突。
2. 单代理 vs 多代理任务族对照。
3. 定义最小输入和可验证交付物。
4. 仅在净收益任务族启用并行；高风险/高复杂度才独立审查。
5. 复用现有 SubAgent 生命周期，不新建 fleet。

**验收：** 终态可归因；无未经协调共享写冲突；质量/速度收益大于协调成本；Reviewer 有效发现和误报可量化。

### F. 反思、知识整理与持续学习

**需求：** 用户任务不等待 Learning；材料来自冻结 episode 与可追溯工具结果，不依赖 hidden CoT；学习产物是候选；独立任务验证后才 qualified；整理先只读巡检，修正保留历史。

**最小实现：**
1. 人工触发一次 consolidation dry-run。
2. 核同主题正文事实差异，不能只凭标题相似判断重复。
3. 抽样复核候选 precision/recall，记录误判。
4. 只有存在被反证、明确 superseded、确认无效等负证据，才逐条提出可逆 archive/supersede；不按年龄/数量批量归档。先冻结 content_hash 与 version_scope，记录恢复演练。
5. 再决定低频抽样复验，不先做全库 nightly rewrite。
6. 新 Method 使用独立任务集资格验证。

**验收：** dry-run 只读可重复；修订可逆、账本不断裂；学习不阻塞前台；合格方法未来复用有净收益。

---

## 6. 评测：用任务表现证明智能提升

### 6.1 任务族

至少覆盖：
1. 信息检索与证据核验；
2. 代码定位、最小修复、回归；
3. 浏览器/桌面多步骤操作；
4. 长任务跨会话恢复；
5. 工具失败诊断与安全恢复；
6. Method/Experience 召回与应用；
7. 多方案研究与决策；
8. 受控发布/服务状态核验（仅隔离测试环境）。

每项有期望结果、工具/权限、完成判据和失败边界。

### 6.2 对照组

| 组 | 配置 | 问题 |
|---|---|---|
| A | 同模型、基础工具 | 模型基线 |
| B | 当前 LFL | 当前 Harness 增益 |
| B′ | 与 B 完全相同配置、独立 session 复跑 | 同配置随机波动与环境噪声地板 |
| C1 | LFL + 工作状态/执行反馈 | 闭环/恢复是否有效 |
| C2 | LFL + 知识召回/资格优化 | 知识是否有净收益 |
| C3 | LFL + 模型自主自适应推理/路由 | 推理策略是否有收益 |
| C4 | 仅组合已证实有效能力 | 是否有协同/负交互 |

先 B/B′ 测噪声地板，再分项 C1/C2/C3，最后组合 C4，避免无法归因。对于模型随机性不能被固定 seed 消除的 Provider，要如实记录模型/参数指纹和重复次数；不得假定跨 Provider 参数等价。

### 6.3 指标

| 指标 | 定义 |
|---|---|
| Task Success Rate | 达到预定义完成判据比例 |
| Outcome Quality | 盲评正确性/完整性/实用性 |
| First-pass Completion | 无用户纠正、无失败重做完成比例 |
| Recovery Success | 失败后恢复并完成比例 |
| Duplicate Action Rate | 无效动作/副作用重复比例 |
| Evidence Integrity | 结论是否有正确、当前、可展开证据 |
| Knowledge Net Benefit | 用知识相对不用时的成功率/质量差 |
| Human Intervention | 用户介入次数及类型 |
| End-to-end Cost | 全程 token、工具耗时、等待、人工时间 |
| Safety Regression | 未授权动作、数据丢失、错误完成声明等 |
| Cache/Prefix Guardrail | 首轮 token、前缀 LCP/cache hit、缓存失效率、按缓存命中折算的单位成本 |
| Under-retry Guardrail | 明确应重试但未重试而导致任务失败的次数；与无效重试率成对统计 |
| Knowledge Version Compatibility | content_hash/read_version/version_scope；跨版本不兼容报告禁止比较 efficacy |

### 6.4 试验准入与判定（替换拍脑袋百分比目标）

历史建议的“成功率提升 10–15%”“无效动作下降 25–30%”“恢复 ≥95%”仅可留作方向性规划，**不能在无基线、样本量和置信区间时成为 PASS 门槛**。

必须先建立独立 prereg：

| 冻结字段 | 要求 |
|---|---|
| 任务族 | 明确定义纳入/排除条件、难度标注与外部依赖 |
| Baseline | B、B′ 同配置重复基线和不确定性估计 |
| 样本量/运行重复 | 基于预期效应与可接受误差确定；探索样本与确证样本分开 |
| 主要终点 | 任务完成质量/成功率、恢复成功率；预先指定首要指标 |
| 最小有价值效应 | 事先定义方向和最低改进幅度，禁止见结果后改变 |
| 不确定性 | 采用项目既有 Wilson/配对判断口径并完整报告；置信区间重叠不得宣称已证明差异，但不把“不重叠”误认为所有设计下唯一统计检验 |
| 反向 guardrail | 安全、重复副作用、首轮 token、LCP/cache 命中/单位成本、应重试未重试、简单任务退化 |
| 干预同一性 | 模型精确 id、参数、环境、权限、session/知识版本、工具快照与源 SHA |
| 无效/中止规则 | 超时、被截断、Provider 异常、模型漂移、数据污染/复用及费用/安全停止线 |

**探索性最小样本（例如每族每臂 n=3）只能用于验证机制可行、定位错误和估计方差，不足以证明 10–15% 任务成功率提升，更不能授权生产推广。** 确证试验需在估计基线与噪声后单独确定样本量、冻结 holdout 和判据；任何关键 guardrail 恶化都暂停默认推广。

### 6.5 实验纪律

预冻结任务、评分规则、样本量、最小效应、噪声地板、知识 content_hash/version_scope、排除与停止规则；各 cell 独立 session、隔离知识/记忆沙箱或保证来源不交叉污染。记录 run ID、模型/参数、prompt/request fingerprint、工具轨迹、证据 refs、环境 SHA、token、缓存/LCP、耗时和终态；失败/截断/超时不得静默剔除；尽可能盲评；不事后改阈值。

---

## 7. 实施阶段与门槛

### Stage 0 / M0：delta 审计（不改业务代码）

不再新建三份互相重复的“全量基线报告”。只建立**一份 delta 审计**，首页是既有报告的“继承/推翻/当前性”表：

1. 核最新 origin/main 和生产事实（如问题依赖生产），保护 dirty main；历史 snapshot 不能当最新真值。
2. Goal/Task/Checkpoint/longrun_continuity 现有字段 → 需求字段 → 未覆盖缺口；严格标明权威源。
3. 枚举逐工具 side-effect/idempotency/journal/unknown 覆盖矩阵，不新增执行状态机。
4. 抽取真实“继续”与工具 unknown 轨迹，核模型**当时实际看到**的状态；普通任务与长任务各一条。
5. 抓 provider-visible 请求，核常驻知识/规则的实际字节、来源、缓存前缀；核 Method/Experience 卡片哈希、usage/version_scope。
6. 定义一个最小、真实、可复现的续接任务族；准备 B/B′ 噪声地板预注册草案。

**退出条件**：同一事件轨迹两次派生结果一致；无新持久状态源；报告含 `source_sha`、证据引用、继承/推翻表、缺口排序；未核标 `unavailable`。M0 不能宣称能力提升。

### Stage 1 / M1：任务闭环最小纵切（只修证实存在的缺口）

优先选择 M0 已复现的**一个**长任务续接/执行反馈问题：如模型在恢复时看不到当前 Task frontier，而真实任务需要该信息。复用既有 Goal/Task/longrun_continuity，优先提供按需工具或有界 tail 事实投影；不得每轮强制预置、不得附语义命令、不另建存储。若 M0 证明已有路径足够，则 **不写代码**，改做回归测试与运用改进。

**M1 评测两层**：第一层探索性小样本验证“事实可见、恢复不重复动作、简单任务零注入、缓存不明显恶化”；第二层必须在冻结 baseline、B′ 噪声地板、样本量与独立 holdout 后才允许声明净收益。不得将 3×2×3 的冒烟矩阵当统计确证。

**退出条件**：受影响行为可复现、回归测试通过、目标/权限/证据同一性正确；未增加第二事实源；简单任务不强制计划、首轮 token/LCP/cache 与应重试未重试 guardrail 不劣化；若无真实缺口不实施。

### Stage 2：知识调用闭环

核真实注入/检索；小样本测召回、exact hydration、声明和独立效果；只读整理与小批量可逆清理；Method 资格试验预注册。

**退出条件：** 漏斗可复现；相关召回提高、误召回受控；不把声明当效果；不达标不推广。

### Stage 3：自适应推理/模型协同实验

提供真实能力/预算画像；模型自主选择档位、检索、切换或委派；对照简单/困难任务，统计质量和成本。

**退出条件：** 简单任务不过度复杂化；困难任务有独立收益；无隐式降级/上下文丢失；默认策略由实验决定。

### Stage 4：组合与推广

组合已证实有效能力；检查负交互；完成独立审查、原版完整 R9 和安全/架构门禁；隔离环境 canary，再按单独授权发布。

**退出条件：** 候选 SHA、审查范围、R9、wheel SHA、部署代际、live 身份一致；P0/P1=0；A/B 达预冻结门槛；有回滚和运行态核验。

---

## 8. 变更治理与安全边界

- 先核最新 main 与 dirty worktree；不得覆盖/清理他人变更。
- 在隔离 worktree/branch 实施；一次只处理一个可验证问题族。
- 每个修复对应可复现失败和回归测试；假设标为假设。
- 不扩大测试基线；不因门禁耗时跳过原版完整 R9。
- 增强 agency 的改动说明如何增加模型可见信息/行动/纠错能力。
- 新增硬控制须说明为何模型+现有工具不能判断，并提供可解释/否决路径。
- 代码改变后按既有流程完成独立 GLM-5.3 审查、P0/P1=0、原版完整 R9；审查与 R9 对应同一候选 SHA。
- 审查、R9、集成、push、发布、生产重启是不同阶段，不互相推断。
- 本设计不授权 main 合并、push、发布或生产重启。

### 安全授权

- 当前用户明确指令优先；“继续/按建议执行”不扩大最近授权范围。
- 文件系统外操作、凭据、外发、生产服务、发布、破坏性动作遵循既有审批。
- 工具失败不能伪造成功。
- 副作用工具须幂等或核验执行状态；未知状态不盲目重放。
- 子代理有明确 write scope、预算和目标；Reviewer 不与实现者共用未冻结可变候选。
- 日志/评测不记录 secrets、私钥或不必要个人数据。
- 学习不保存 raw hidden chain-of-thought；保存可验证工具轨迹、结论、证据与反馈。

---

## 9. 风险与反模式

| 反模式 | 风险 | 应对 |
|---|---|---|
| 规则膨胀 | 注意力被流程占用 | 核心最小常驻，长规则按需 |
| 知识全量注入 | 干扰、缓存成本、旧知识误导 | compact discovery + exact hydration |
| 自动任务分类器 | 错误分类导致错误路径 | 模型自主判断 |
| 过度规划 | 简单任务成本增加 | 模型按需外显计划 |
| 无差别重试 | 重复副作用/死循环 | 归因、幂等、状态核验 |
| 多代理滥用 | 协调成本超过收益 | 按净收益委派 |
| 自评晋级 | 自我证明循环 | 独立 holdout |
| 自动全库整理 | 错误归档与成本 | dry-run、抽样、可逆 |
| 只优化 token | 牺牲正确性 | 质量-成本联合指标 |
| 大规模重构先行 | 回归面大、收益不可归因 | 纵向切片 |
| 旧 checkpoint 当真值 | 状态漂移 | 核当前权威源 |
| 工具成功当任务成功 | 用户目标未达成 | outcome verification |

---

## 10. 第一批工作包（精简为三项）

| 顺序 | 工作包 | 产物 | 准入与退出条件 |
|---|---|---|---|
| **M0** | 一次 delta 事实/覆盖审计 | 一份审计：Goal/Task 字段映射、工具幂等矩阵、knowledge 版本快照、provider-visible 输入、继承/推翻表 | 仅只读；必须区分远端/本地/生产状态；重复提取一致 |
| **M1** | 一个有真实失败证据的任务闭环纵切 | 最小补修或“无需改动”结论、定向回归 | 不另建 Task/Journals；简单任务零强制注入；副作用/缓存/重试 guardrail 不退化 |
| **E1** | 知识与自适应能力探索/确证 | B/B′ 噪声地板、冻结 prereg、逐臂实验/独立 holdout | M0/M1 完成后依证据决定是否启动；仅有确证收益才考虑默认启用 |

**停止线**：M0 未查明问题不启动 M1；M1 尚未证明必要不启动多模型路由改造；若 E1 未达到预注册效应阈值或 guardrail 退化，实验停止于非默认配置，不追加“再试一次”式研发。

---

## 11. 最终建议

优先级：
1. **执行闭环与真实反馈**：先量化真实问题并复用既有 Goal/Task/Journal；减少反复“继续/完成了吗/是否生效”，让任务可靠做完。
2. **知识调用与资格验证**：释放现有知识价值，提高有效复用率，而不是继续只扩充数量。
3. **自适应深度推理**：复杂任务获得更多推理和验证，简单任务少走流程。
4. **离线知识整理**：先只读、抽样、可逆，验证收益后再调度。

LFL 不需要成为一个比模型更复杂的“总指挥”。它需要成为模型最可靠的感知器、记忆系统、工具箱、执行环境、证据系统和恢复机制。

**真正的 LFL 智能，不是程序替模型想得更多，而是让模型看见更准确的事实、调用更有效的知识、采取更合适的行动、及时发现错误，并在未来任务中复用经过验证的经验。**

### 首个实施范围建议

1. 对齐最新远端 main 和工作区/生产事实；
2. 只读完成**一份 delta 审计**（含现有字段/工具覆盖、知识版本与 provider 可见性），不重复造三份报告；
3. 仅当审计证明确有缺陷时，提交一个最小修复候选；
4. 定向测试与独立审查；
5. 完整 R9、集成、push、发布和重启分别遵循现有授权门槛。

---

## 附录 A：来源文件

- README.md
- AGENTS.md
- docs/DESIGN-20260910-adaptive-reasoning-learning-architecture.zh.md
- docs/PLAN-20261014-architecture-agency-refactor.md
- docs/ANALYSIS-20261111-memory-consolidation-gap.md
- docs/RESULT-20261006-method-binding-v3.md
- docs/ASSESS-20261021-method-pool-funnel-census.md
- docs/analysis/learning-queue-cluster-verdict-20261105.md
- docs/design/DESIGN-20261101-efficiency-hardening-v1.md

## 附录 B：本轮状态声明

本文为设计文档，不是实施完成报告。本轮未修改业务代码、测试、配置或生产服务；未创建/切换 Goal；未提交、合并、push、发布或重启。


## 附录 C：DeepSeek 审查前后差异与待证伪项

- **删**：§4.1 独立 YAML 状态模型；任何第二套 `unknown` 或幂等状态机。
- **改**：§5.B 从“建设执行前后状态”改为“复用既有 Journal 的工具覆盖矩阵”；§5.C/5.F 在知识变更前冻结 `content_hash/version_scope`。
- **改**：§6 增加 B′ 噪声臂、缓存成本和应重试却未重试的反向 guardrail、预注册样本量与显著性口径；历史百分比只保留为愿景。
- **并**：三份审计缩为一份 delta + 继承/推翻表；阶段工作包缩为 M0/M1/E1。
- **推迟**：默认启用多模型路由、多代理策略重写、全库自动整理、Meta-Learning 深度重构，直到独立任务证明净收益。
- **待核**：审查者引用的源码符号/行号需在最新候选复核；模型路由身份只确证到 LFL `model_used`；真实 provider 输入、生产代际、Learning 队列和实验方差尚未实测。
- **审查记录**：DeepSeek 反馈 P0=3、P1=5、P2=3；本版逐项接受为设计修订，但这些发现不等于已验证的生产缺陷。