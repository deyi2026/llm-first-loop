# LFL 修复与优化总书：LLM Agency First（模型能力优先）

> 状态：**R8 / P1-A + P1-B + P1-C 已验证完成**（修订记录见附录 A）
> 日期：2026-09-03
> 适用范围：LFL 的工具发现与投影、工具执行循环、停滞/熔断、任务恢复授权、Prompt Eligibility、动态注入、错误回执、本地/远程模型工具路由，以及后续所有修复、优化、功能新增。
> 核心裁决：**程序的职责是提供能力、事实、边界和可恢复性，不是替模型做推理，不是用规则替代模型判断，也不能以“稳定/省 token/防犯错”为由制造模型无法完成任务的结构性障碍。**
> 本文是后续相关设计与代码评审的上位原则。与旧规则冲突时，旧规则必须重新证明必要性；不能证明则修改、降级为观测或删除。
> 当前修订：**R8 Runtime Identity Boundary**——R7 的诚实感官与连续性继续有效；新增“运维调用方环境不是 LFL 运行身份”边界：MCP Console、IDE、CI 或其它 operator 通道可以为自己的执行使用沙箱 HOME/TMPDIR/PATH，但常驻 LFL Web/Feishu 服务不得被动继承这些临时身份。服务启动必须恢复宿主账户运行身份，再由 LFL 自身的 CatastrophicGuard / EXEC_MODE / approval / EXEC_SANDBOX / workspace scope 独立实施安全边界；DSH 等子系统可另有显式、可审计的专用数据根。该边界不扩大模型权限，只消除“由谁重启服务决定模型看到哪个 HOME/PATH”的非确定性。

---

## 0.0 2026-09-04 P1-B 当前运行时契约（覆盖旧 Promotion/Eligibility 方案）

P1-B 已把“工具可达性”从第二套程序决策系统收敛为机械事实：

```text
provider callable tools
= registered schemas
- runtime-unhealthy tools
- explicit delegated-scope exclusions
```

当前权威语义：

- **健康的已注册工具默认全部可调用**；用户关键词、当前/历史任务文本、active protocol、typed recovery、模型类型、Capability Requirement、HandleCollector 等均不得决定 provider 工具面。
- **runtime health** 只表达真实依赖/运行环境不可用；stale direct call 仍在执行边界再次校验，属于机械能力事实。
- **显式 delegation scope**（如子代理继承的 `current_tool_discovery_scope`）继续作为真实执行域边界；它不是任务语义分类。
- `get_tool_schema` 只负责目录/搜索/完整 Schema 发现；exact lookup **不再生成 promotion、TTL、grant 或后续可达性状态**。
- ToolResult 的 `capability_requirements` 仅作为 producer 事实 metadata 保留；若其中指名的能力当前确实 runtime-unhealthy，可在所属当前 human turn 渲染 `[能力边界事实]`，但该 metadata **不再选入、隐藏或提升任何工具**。
- `TOOL_ELIGIBILITY_MODE` / `TOOL_PROMOTION_MODE` / `CAPABILITY_REQUIREMENTS_MODE` 及对应 Settings/runtime state 已退役；不保留 shadow/enforce 双轨。
- `PREFIX_LAYERED` / CORE9 + keyword→full-schema 的分层 selector 同步退役；稳定 `schemas(lazy=True)` 仍保留首调所需 `type/enum/properties/items/required`，因此只压缩说明文本，不改变工具可调用能力。
- Reachability telemetry 仅记录 `registered / final_provider_callable / quarantined / model emissions / executed receipts`，不再计算 hypothetical `would_select`、promotion、rule-review 或 capability-auditor 结果。
- 普通用户文本中的“取消/停止任务”等语义不再由程序关键词映射为 `job_kill` 工具选择；工具已在稳定工具面中，由模型判断是否调用。

因此，本文后续 4.x 中关于 Promotion TTL/预算、旧 Phase 1、旧 G1 promotion 指标等内容均标记为**历史方案**；它们解释事故与演进过程，但不得据此恢复运行时 selector。

## 0.1 2026-09-04 P1-C 当前 Prompt Authority 契约

P1-C 将“自动 program prompt 的语义排序/分档”从运行时移除，当前契约为：

- `PROMPT_DYNAMIC_PRODUCER_SLOTS = frozenset()`；未知/未批准 producer deny-by-default。
- persisted memory/program-control/legacy recovery 在 downstream Cognitive 阶段之前即退出 provider view；durable storage/event truth 不删除。
- `InjectionProfile` / `injection.profile.shadow` **不再产生新的 runtime recommendation/event**；历史 event schema 仅为 append-only 旧日志读取兼容。
- `InjectionBudget` / `INJECTION_BUDGET_CHARS` / program block priority keep-drop **不再是生产运行时机制**；程序不得以“recovery/status/reference 谁更重要”替模型做语义裁决。
- Cognitive state/packet 仍可做 prompt-neutral observability；P1-C 不扩大为 Cognitive Runtime 退役。
- 物理 `history/context window`、provider context limit、output reserve、overflow、compaction、tool/schema 实际资源计量继续属于程序机械资源职责。

一句话边界：**程序可以裁决“物理上装不下”，不能裁决“哪条语义更值得进入 prompt”。**

---

## 0. 为什么需要这份总书

近期连续出现同一类症状：模型已经知道目标动作、甚至已经持有目标工具参数，但真正发射时连续调用 `get_tool_schema`，无法触达 `submit_evolution` / `save_experience` 等目标工具；随后程序又通过停滞提醒、熔断、提示词、工具投影等机制继续干预，最终形成“工具很多、规则很多、模型却做不了已经决定要做的动作”的悖论。

独立代码审查已经确认：这不是单纯的“模型不听话”或“推理错误”，至少存在一个程序结构性根因：

1. `get_tool_schema(X)` 成功后只把 X 的完整 schema 放进 ToolResult 文本；
2. 下一轮 `project_tool_schemas()` 的 protocol 恢复只识别真实调用过的工具名，因此只看见 `get_tool_schema`，不会把被查询的 X 提升为 provider callable tool；
3. 当新一轮用户输入只是“继续”等弱关键词时，词法任务路由也不会重新选中 X；
4. 于是模型“知道 X 怎么调用”，但 provider 实际可调用集合里仍没有 X；
5. `get_tool_schema` 又固定在 CORE，模型最容易、甚至只能继续查 schema；
6. 后加的全局同指纹第 3 次拦截可以止血，但不能让 X 变得可调用。

因此本轮不再把问题简化成“加一个更强熔断器”。本设计从根上重审所有可能阻碍模型发挥的规则与程序。

---

# 1. 总原则：LLM Agency First

## 1.1 一句话原则

**默认允许模型使用已注册、健康、授权范围内的能力；程序只有在存在可证明的安全、授权、数据完整性、协议正确性或资源失控风险时，才可以限制模型行为，而且限制必须是最窄、可解释、可观测、可回滚的。**

## 1.2 程序应该做什么

程序应该承担以下职责：

- 提供真实、完整、可调用的能力；
- 提供结构化事实，不伪造、不隐藏关键失败；
- 维护安全、权限、数据完整性和副作用边界；
- 让模型能够发现能力，并在发现后真正调用；
- 在模型失败后提供**可恢复的状态**，而不是替模型规划下一步；
- 维护上下文、缓存、工具 schema 的工程效率，但不能牺牲任务可达性；
- 防止确定性的无限空转、重复副作用和资源失控；
- 记录观测事实，供模型或运维检索，而不是把大量观测自动塞回 prompt。

## 1.3 程序不应该做什么

以下行为默认视为反模式，除非有独立证据证明必要：

- 因为“模型可能用错”就把合法工具藏到无法调用；
- 用关键词表决定模型**能不能**调用工具；
- schema 已查询成功，但目标工具仍不可调用；
- 把“相同调用”直接等价成“无进展”；
- 用程序生成的建议、技巧、经验、恢复提示持续引导模型推理；
- 对已经 resolved/consumed 的内容反复自动注入；
- 用 prompt 文案代替真正的权限控制；
- 让模型自己填写 `confirm=true`，然后把它当成“用户真的确认过”；
- 把内部错误伪装成参数错误、未命中或成功；
- 为了 cache/token 省一点成本，破坏工具可达性或让模型陷入额外工具调用；
- 用全局、一刀切规则治理本质不同的工具类别；
- 规则已经证明误伤正常能力后仍因“已经做了很多”而保留。

## 1.4 与灾难性安全硬约束的优先序

本原则约束的是“能力可达性”，不是“无条件放行”。以下硬约束**优先于本文一切条款**，不得引用本文来论证削弱：

- 破坏性命令硬阻断与人工审批边界；
- 生产部署/制品发布/强推/环境销毁的人工审批；
- 数据完整性（会话/记忆/审计记录不可删除、不可篡改）；
- 协议硬约束（tool_call 配对、回执真实性）；
- 真实用户授权（尤其外发副作用与历史任务恢复）。

当“模型能力”与上述硬约束冲突时，正确解法是**给模型更准确的事实与更窄的合法通道**（例如 program-issued authorization），而不是降低硬约束，也不是让模型自证。

## 1.5 认识论诚实：判断权属于模型，但当前事实必须接地

LLM Agency First 不是“模型可以凭自己记得的内容把任何判断都说成当前事实”。模型拥有理解、推理、策略与完成裁决权；**程序负责把模型接到真实世界，模型负责诚实地区分它知道什么、核实了什么、推断了什么。**

### 1.5.1 当前可核事实：训练先验不是证据

当结论涉及下列**当前可核事实**，且该事实会影响回答、行动或完成判断时，模型应先取得与当前对象对应的工具/文件/运行态证据，再作确定性陈述：

- 当前代码、函数、文件内容、路径、行号、Git 分支/提交/dirty 状态；
- 当前版本、配置、启动参数、进程、端口、运行服务是否已加载某次修改；
- 当前 provider/model/tool/schema/Skill 的实际可用性与接口契约；
- 当前外部系统、网页/API、CI、远端仓库、任务状态或执行回执；
- 当前写入、提交、推送、部署、发送等动作是否真正完成。

模型参数内知识、训练知识、过去会话、旧文档、旧 Experience/Method/Rule 可以用于**提出假设、解释背景、缩小搜索范围或选择下一步取证方式**，但不能冒充“刚刚核对过的当前事实”。如果当前证据无法取得，应明确表述为“未核验 / 当前证据不足 / 推断 / 存在不确定性”，而不是用精确路径、行号、版本、运行状态等措辞制造已经核验的印象。

### 1.5.2 证据必须匹配所声称的层级

“调过工具”本身不等于诚实，**证据对象、版本、时间和运行层必须支持所声称的结论**。典型边界：

- 读到 `pyproject.toml` 的新版本，只能证明源码/配置文件当前写着什么，**不能单独证明运行中的 Web 已加载该版本**；运行态结论还需要进程/manifest/health 等运行证据。
- 在 `.backup/.worktrees/.tmp-ci` 旧副本中找到函数，不能冒充当前 workspace 的实现；默认发现面应优先当前工作区，审历史副本时显式指定范围。
- 旧 Experience 记录曾经成功，只能说明过去的已验证路径；当前 schema/provider/runtime 已变化时，仍需核适用性。
- 工具返回 failure/error/timeout/blocked 时，不得把“尝试过”改写成“已完成”；执行完成以真实成功回执或等价的当前状态证据为准。

### 1.5.3 核验不是仪式，也不是新的 Program Authority

认识论诚实要求**证据与结论匹配**，不要求固定步骤、固定工具、固定来源数或“每个事实都查两遍”。模型仍自主判断什么证据足够、何时需要交叉核验、何时一个强证据已经足够。

因此禁止把本原则实现成新的程序语义控制器，例如：

- 所有回答一律强制工具调用；
- 所有当前事实固定查 N 个来源；
- 程序用关键词决定哪些陈述“必须查”；
- 因没有满足某个固定核验仪式而阻断模型正常回答；
- 把“诚实”扩张成程序替模型判断任务质量、相关性或完成条件。

程序应做的是：提供可发现、可调用、可追溯的感官与回执，保留必要的 provenance / version / runtime identity / execution status，让模型能够接地；只有安全、授权、数据完整性、协议和物理资源等不可移交边界继续由程序硬执行。

### 1.5.4 Provider-agnostic：没有“弱模型专用诚实规则”

本原则属于 **LFL 公共架构层**，不是针对本地小模型的补丁。Ornith、Qwen 等本地模型，以及 GLM、MiniMax、DeepSeek 和后续任何网络 API/provider 接入模型，均应通过同一 Common Governance、tool/schema、Skill/evidence 与当前事实契约获得能力。Provider adapter 只处理 wire protocol、reasoning control、transport、计费/资源事实等 provider 差异，**不得为云端强模型绕过当前事实诚实，也不得为本地模型另建一套程序替它判断的语义控制面。**

这条原则与 `RULE-AI-01` 的关系是：本文定义**架构权责与设计边界**，`docs/ai_rules.md` 定义模型可发现的规则 SoT，`src/llm_loop/core/prompt.py` 只保留极短的通用运行契约。三者语义必须一致，但不得把整份架构文档重新注入普通 prompt。

## 1.6 诚实感官的四个机械推论（R7）

R6 规定“模型的当前事实必须接地”，R7 进一步规定：**程序交付给模型的感官事实本身也必须诚实、可归因、可连续恢复，而且不能在事实回执里夹带程序替模型做的策略。** 2026-09-11 的真实 GLM 长会话事故证明，云端强模型同样会被错误的感官契约带偏，因此以下边界属于 LFL 公共架构层，不按模型大小/provider 分叉。

### 1.6.1 失败回执是事实，不是修复计划

工具 failure/error/timeout/blocked 回执应提供当前可机械证明的状态、原因、能力边界与调用契约，例如：可执行文件当前不可发现、合法 enum/范围、权限不足、资源上限、退出码/timeout。**不得把安装依赖、切换工具/模型、重试、修改任务方案等策略写成程序默认“下一步”。** 模型可依据事实自行选择修复、绕行、报告阻断或改变计划。

这不禁止机器 Schema 告知“什么参数合法”，也不禁止安全/授权边界明确说明“什么动作不允许”；前者是协议事实，后者是不可移交硬约束。禁止的是把可选策略伪装成工具失败契约的一部分，使模型把程序建议误当成任务授权或必要路径。

### 1.6.2 观测必须保留主体 provenance；默认当前 session

会话级诊断/恢复工具读取共享 workspace 审计流时，每条事实必须保留其 `session_id`（以及已有时间/stream/source 等 provenance）。默认模型视图应限定当前 session；只有模型或用户**显式请求 workspace-wide audit** 时才允许混合多个 session，而且混合结果仍必须逐条标明 session provenance。

因此，“同一工作区同时发生”不等于“当前会话做过”。程序不得为了构造统一 event stream 而丢弃主体标识，导致模型把并发 release、测试、子任务或另一会话的动作归到自己身上。

### 1.6.3 历史分叉 fail-open，但 active continuity 不得归零

event log 与 live session 前缀不一致时，程序不得猜测哪条旧历史应覆盖另一条；**拒绝自动合并仍是正确的数据完整性边界**。但“不能安全合并旧历史”不等于“当前 active turn 没有任何可恢复状态”。

当最近一轮在 tool chain 中被取消/中断且新的真实用户输入已经到达，程序可以从**当前 live session 本身**机械提取有来源的最近模型可见文本与终态 tool receipt，作为一次性的 provider-only continuity fact；不得恢复隐藏 reasoning、不得执行半截 tool draft、不得把旧程序占位消息冒充模型回答。新的真实用户消息始终位于连续性事实之后，继续作为当前授权真值。

### 1.6.4 Working-set 收敛是表示/资源机制，不是证据价值裁决

在一个长 active episode 中，已经被后续模型轮次看过、且拥有稳定 EvidenceRef/可恢复来源的旧 tool result，可以机械替换为 protocol-preserving receipt；原始证据仍可精确水合。最新未暴露/未决 tool chain 保持原文，不可恢复的 failure/error/timeout 事实也不得为了省 token 直接丢弃。

折叠必须兼顾 provider 前缀稳定：禁止恢复已被实测否决的“每轮一暴露就重写旧前缀”方案。当前边界采用**粗字节批次 + 已暴露 pending-result 数量上限**双机械阈值；两者只回答“表示层积压是否过大”，不回答“哪条证据重要/是否足够/任务是否完成”。模型仍拥有证据相关性、充分性和收口判断权。

## 1.7 运维沙箱不是 LFL Runtime 身份（R8）

LFL 的 operator/维护通道与 LFL 常驻 runtime 是两个不同安全域。MCP Console、IDE agent、CI runner 或其它维护工具可以为了保护自己的执行过程设置临时 `HOME`、`TMPDIR`、`PATH` 或其它沙箱环境；**这些值不得因为一次 restart/deploy 动作而无意变成 Web/Feishu 等常驻 LFL 服务的运行身份。**

服务启动器必须机械恢复当前 Unix 服务账户的真实 `HOME` 与平台原生临时目录，并显式构造运行所需 `PATH`/`PYTHONPATH`/数据根。之后的工具执行安全继续由 LFL 自己负责：灾难性操作由 CatastrophicGuard 硬阻断，`EXEC_MODE`/approval 负责授权分级，`EXEC_SANDBOX` 若显式启用则负责命令沙箱，文件/证据工具继续遵守 workspace scope。**不能用 operator 的临时沙箱替代这些 LFL 安全机制，也不能因为恢复宿主 HOME 就绕过它们。**

DSH 等外部执行子系统可以使用独立、显式、可审计的数据根。例如镜像运行时固定 `DSH_HOME=<mirror>/data/dsh-home`，用于隔离 profile/session；二进制发现则使用宿主账户已安装的 `~/.local/dsh/bin`。这类显式子系统隔离与把整个 LFL runtime 偶然塞进 operator sandbox 是两回事。

2026-09-11 事故证据：由 MCP Console 调用 `restart_mirror.sh` 后，8903 曾实际继承 `HOME=<mcp-console>/home`、`TMPDIR=<mcp-console>/tmp`，且 `_prep_dsh_env()` 先 export 镜像 `DSH_HOME` 又在同函数中 unset，最终 `dsh_task` 将真实已安装的 DSH 误报为 unavailable。修复后 8903 的 `HOME` 恢复宿主账户、`TMPDIR` 恢复 macOS user temp，`DSH_HOME` 保持镜像专用目录，PATH 可发现宿主 DSH；LFL 自身安全策略不变。

---

# 2. 所有限制必须通过“必要性六问”

以后新增或保留任何模型限制，设计与代码评审必须逐项回答以下六问。任何一问回答不清，默认不能进入 enforce。

## N1：风险是否真实存在？

必须有至少一种证据：

- 可重复事故；
- 可构造的确定性失败；
- 安全/权限边界要求；
- 明确的数据破坏或副作用风险；
- 可量化资源失控。

不能仅用“模型有可能”“理论上也许”作为硬限制依据。

## N2：为什么必须由程序限制，而不是让模型判断？

适合程序硬限制的典型场景：

- 权限/身份/用户授权；
- destructive side effect；
- 数据一致性；
- 协议不变量；
- 确定性的无限循环；
- 超出系统物理/资源上限。

不适合程序硬限制的典型场景：

- “这个工具可能不是最佳选择”；
- “模型应该先查另一个工具”；
- “我们觉得这一步没必要”；
- “可能浪费一点 token”；
- “多数时候不会用到”。

## N3：是否已经做到最窄？

限制必须尽可能绑定：

`风险对象 + 风险状态 + 作用时刻 + 作用范围`

而不是绑定“大类工具”“整个会话”“所有第三次调用”。

例如：

- 正确：`同一 immutable schema 查询 + 相同 schema digest + 目标已 callable + 无新 user intent` 才判无进展；
- 错误：任意 `tool_name+args` 第三次一律 BLOCK。

## N4：是否存在不限制模型的替代方案？

优先级：

1. 提供更准确能力；
2. 提供结构化状态；
3. 改善可发现性/可调用性；
4. 增加观测；
5. 最后才是限制。

如果“让工具真正可调用”能解决问题，就不应该先教模型“不要再查 schema”。

## N5：限制是否可证明没有误伤？

必须有：

- 正常路径正例；
- 合法重复调用正例；
- 多模型/本地模型至少一种验证；
- 新 user turn 边界验证；
- shadow 指标或 AB 证据。

## N6：限制何时自动退出？

每个限制必须定义：

- reset 条件；
- TTL；
- override/授权条件；
- 回滚开关；
- 删除标准。

**永久化规则必须比临时修复拥有更高证据门槛。**

---

# 3. 当前机制的重新裁决：保留、改造、删除

| 当前机制 | 裁决 | 原因 |
|---|---|---|
| `get_tool_schema` | **保留并升级** | 发现工具是必要能力；问题不是它存在，而是“发现后不可调用” |
| `CORE_TOOL_ORDER` | **保留为稳定起始集，不得充当权限门** | 有利于前缀稳定，但 CORE 之外必须一跳可达 |
| `TOOL_TASK_KEYWORDS` | **降级为预取/排序 hint** | 关键词可以帮助省 token，但不能决定最终 callability |
| `project_tool_schemas()` eligibility | **重构为 capability projection，而非隐藏门** | 必须消费 schema promotion / active protocol / authorization |
| local `LOCAL_TOOL_NAMES` 硬白名单 | **取消“硬 gate”语义** | 当前会让本地模型发现工具后仍可能调用不到；可保留为初始预算 seed |
| prefix dynamic layer | **保留追加式缓存优化，但接入 promotion** | 缓存稳定可保留，不能阻止目标工具尾部追加 |
| 全局 `partition_stagnation_block`：同 call 第 3 次硬拦 | **当前语义应退出** | “相同调用 != 无进展”；会误伤合法 read/status/poll/recheck |
| `stagnation_carry_fp/count` | **退役跨-run策略状态** | P2-A：重复/空结果只保留当前 run 事实 telemetry；不恢复 blocked/prewarm/no-progress carry |
| `task_update(confirm=true)` | **保留为显式机械动作位，不作为程序自证授权** | P1-A/RULE-AI-23：模型依据当前真实用户指令判断是否授权重开；程序只校验显式位，不解析“继续/重做”等措辞 |
| resolved/history 自动注入 | **继续退出 prompt，保留索引检索** | resolved is retrievable, not injectable |
| memory/experience tips 自动推送 | **默认退出，显式检索优先** | 避免程序替模型选经验、污染当前推理 |
| 失败后的“建议下一工具” prose | **默认移除或变结构化 metadata** | 程序只陈述事实与约束，选择交给模型 |
| runtime health quarantine | **保留，但必须事实化、可恢复** | 真缺依赖/不可用属于能力事实，不是推理干预 |
| safety/权限/destructive guard | **保留并强化为程序态授权** | 这是程序应该负责的硬边界 |

## 3.1 现行成文规则的衔接与退场映射

本总书落地时，现行规则文档（docs/ai_rules.lite.md v8 及超集 docs/ai_rules.md）受影响条目的映射：

| 现行条目 | 处置 | 说明 |
|---|---|---|
| R3 停滞调整（重复动作/无进展即调整） | **P2-A 收正** | 程序只记录精确重复调用/连续空搜索事实；“是否无进展、是否继续”归模型判断，物理资源边界另行硬保留 |
| R21 程序反馈语义（runtime notice 非模型回答） | 保留为过渡保护 | 与 5.5 / 第 9 节事实化回执互补；删除条件继续挂 R8.24-B/C 验收，不受本文影响 |
| R6 演进审批（Web 面板优先） | 不变 | 属真实人工审批硬边界；与普通任务语义判断分离，不再作为通用 Task Authorization Context 的来源 |
| R8.24-A 过渡条款 | 不变 | 本文不改变其删除条件；新机制落地时同步更新映射，避免双轨 |
| 各类“建议下一工具/恢复提示”类 prompt 注入 | **已退出当前主链** | P1-C/P2-A 后不再保留 `PROGRAM_ADVICE_MODE` 这类 dormant 策略开关；历史文本仅作演进证据 |

规则文档随对应 Gate 通过而同版本修订受影响条目，不允许“代码已换、规则未换”或反向的长期漂移。

**边界豁免（协议与数据层硬约束，Phase 6 不得触及）**：tool_call_id 声明↔回执配对；携带 tool_calls 的 assistant 消息必须回传 reasoning_content（M20）；会话/记忆/审计数据完整性（不删除、不修改）；破坏性命令硬阻断与人工审批边界。本总书治理的是 prompt/投影/熔断/授权语义层，不裁决协议与数据层不变量。

---

# 4. P0 根因：Tool Discovery → Callability 断链

## 4.1 当前失败状态机

```text
registered(X)
   ↓
hidden from provider
   ↓
get_tool_schema(X) is callable
   ↓
model receives X schema as text
   ↓
NO capability promotion state
   ↓
next round projection sees only get_tool_schema
   ↓
X remains hidden
   ↓
model queries get_tool_schema(X) again
```

这是结构性不可达，不应该归责为模型“明知故犯”。

## 4.2 目标状态机

```text
REGISTERED
   ↓
DISCOVERABLE
   ↓ exact get_tool_schema(X) success
PROMOTED(ttl / reason / session / run)
   ↓
CALLABLE in provider tools
   ↓ real tool call
EXECUTED
   ↓
CONSUMED / TTL expiry / new task boundary
   ↓
DEMOTED to discoverable
```

**硬不变量：任何对模型宣称“可用/已注册/可发现”的工具，在成功完成一次精确 schema discovery 后，必须在下一轮成为真正 callable，除非存在明确的安全、权限或 runtime-health 阻断。**

这条称为：

> **One-Hop Capability Reachability（一跳能力可达性）**

## 4.3 Promotion 必须是结构化状态，不是提示词

推荐内部概念：

```text
ToolPromotion
- tool_name
- session_id
- source = exact_schema_lookup | protocol | user_explicit | recovery
- issued_round
- expires_round / ttl
- consumed
- schema_digest
- blocked_reason (optional)
```

不要求把这些字段暴露给模型；但必须由程序投影层真实消费。

### exact lookup

`get_tool_schema("submit_evolution")` 成功：

- 返回 schema；
- 同时产生 `promotion(target=submit_evolution, ttl=2 rounds)`；
- 下一轮 provider tools 必含 `submit_evolution` 完整 schema；
- 若 runtime health / auth 不允许，必须明确返回 `not_callable + reason`，不能继续宣称普通“完整 schema 已获取”；
- 若目标本轮已 promoted/callable，exact lookup **短路**：直接返回缓存 schema + `already_callable=true` 事实，不再生成新 promotion（这是消解 schema-loop 的第一杠杆，优先于任何 breaker）；
- promotion 生成必须按 `schema_digest` 去重：同 digest 的 active promotion 不重复创建。

### directory/search lookup

`get_tool_schema("*")` / `?keyword`：

- 只负责目录发现；
- 不应把几十个工具全部 promote；
- 模型需要目标后再做一次 exact lookup，或者在搜索结果唯一且模型明确选定时 promote 一个目标。

## 4.4 Promotion 的优先级必须高于 token 优化

工具最终 callability 的优先级建议：

1. safety/runtime-health hard deny；
2. explicit user authorization / program-issued permission；
3. active exact promotion；
4. active protocol required tool；
5. explicit current user intent；
6. stable CORE；
7. task keyword prefetch；
8. budget optimization。

**budget/profile/cache 只能决定“还额外放哪些工具”，不能推翻前 1-5 层。**

## 4.5 Prefix layer 与 promotion

追加式 prefix 机制可以保留：

- 锚层保持稳定；
- promotion 工具以“动态尾部 full schema”追加；
- 同一个 session/run 已追加的不删除，直到定义好的 task/run boundary；
- 新增只发生在尾部，不改前缀字节。

这同时满足：

- cache 稳定；
- 目标能力可达；
- 不需要重新发全量 40+ schema。

## 4.6 本地模型工具白名单必须改语义

当前 local allowlist 如果作为硬过滤，会产生：

> schema 可发现，但目标永远进不了 provider tools。

因此 `LOCAL_TOOL_NAMES` 最多只能表示：

> **initial preferred tool set / token-budget seed**

不得表示：

> **permanent callable allowlist**

本地模型也必须服从 One-Hop Capability Reachability：exact discovery/promoted tool 可以突破 initial seed；真正禁止的工具只来自 safety/auth/runtime-health。

## 4.7 TTL 与“追加即承诺”的一致性语义

`promotion(ttl)` 与 4.5 的“已追加不删除”必须统一为下述语义，否则会出现“schema 还在 prompt 里、工具已不可调用”的新断链：

- TTL 只约束**尚未追加的 promotion**：过期未消费即失效，不得据此撤销已追加能力；
- full schema 一旦进入动态尾部，即构成对模型的**可达性承诺**：在当前 task/run boundary 前保持 callable；
- demotion 只发生在 boundary：随动态尾部整体重置，不在 run 中途静默摘除 callable；
- 若因 runtime-health/权限在 run 中途失去 callable，必须回执事实化（`no_longer_callable + reason`），不得静默。

## 4.8 Promotion 预算与裁剪次序

无约束的 exact-lookup promotion 会让 provider tools / 动态尾部膨胀。约束：

- 每 run active promotions 设上限（建议 ≤8 或等价 token 预算，可配置）；
- 同 `schema_digest` 去重；已 callable 目标短路（见 4.3）；
- 超限时按 4.4 优先级自低位裁剪，**1-5 层禁止裁剪**；
- 发生裁剪必须输出事实（如 `promoted_tools_dropped=[...]`），不得静默；
- 若按次序裁剪后仍超出 provider 硬上限（受保护层 1-5 不可裁剪而预算仍溢出）：不得静默摘除受保护工具，必须返回结构化降级事实（如 `tools_budget_violation=true`、`protected_tools=[...]`）并把该 run 标记 degraded；该情况连续出现视为预算配置缺陷（观测告警），不归责模型。

---

# 5. 历史设计：从“重复调用熔断”到“无进展熔断”（P2-A 已 supersede）

> **2026-09-04 P2-A Rule-first 裁决：本节以下 No-Progress breaker/classifier/threshold 方案仅保留为历史设计证据，不再是生产契约。** 当前生产只记录“精确完整参数调用连续出现次数”和“连续空搜索回执次数”等事实；程序不据此 block 工具、不生成 blocked receipt、不跨 run prewarm deny state、不终止任务。副作用重复安全归工具级幂等/WAL/冲突/授权边界；无限资源风险归 max-iterations/context/time/resource 等机械上限。

## 5.1 当前规则为什么不合适

当前逻辑大致是：

```text
same tool_name + same arguments
连续第 3 次
→ BLOCK
```

它错误地假设：

> same call == same information == no progress

实际并不成立。

合法重复示例：

- `job_output(job_id=X)`：状态在变化；
- `architecture_status(...)`：系统状态在变化；
- `read_file(path=X)`：文件可能被另一个 actor 修改；
- `search_records(query=X)`：索引可能新增；
- `get_goal()`：task/goal 状态可能变化；
- 网络/外部服务轮询：同参数返回不同事实。

因此当前全局 blocker 只能视为 emergency containment，不能永久化为最终判定。

## 5.2 新定义：No-Progress Streak

真正应计数的是：

```text
same_call_fingerprint
AND same_result_fingerprint
AND no_state_change_since_last
AND no_new_user_intent_boundary
AND no_explicit_retry_authorization
```

只有全部成立，才增加 no-progress streak。

### 推荐状态

```text
NoProgressState
- call_fp
- result_fp
- count
- last_user_turn_id
- state_epoch
- last_successful_effect_epoch
- reason_class
```

## 5.3 工具分类治理，禁止一刀切

### A. Immutable introspection

例如：精确 `get_tool_schema(X)`，且 registry/schema digest 未变化。

特点：同参数正常情况下结果确定。

策略：

- 允许更强的 no-progress 检测；
- 如果 X 已 promoted+callable，重复 exact schema 查询可以在 2-3 次后硬阻断；
- 若 X 尚不可调用，则**不能怪模型重复查**，应先判 capability projection bug。

### B. Mutable observation

例如：`read_file`、`job_output`、`architecture_status`、`search_records`。

策略：

- 必须计算 result fingerprint；
- 结果变化即 count reset；
- 新 user turn reset；
- state-changing tool 成功后 reset/epoch++；
- 不允许只凭 args 硬拦。

### C. Effectful tools

例如写文件、发消息、任务状态更新、演进登记等。

关注点不是“重复查询”，而是重复副作用。

策略：

- 依赖 idempotency key / conflict detection / user authorization；
- 已成功执行后再次相同调用应返回“已执行/冲突/幂等结果”的事实；
- 不应该用通用 stagnation breaker 代替副作用幂等设计。

## 5.4 Reset 边界

以下任一发生必须重置或分叉 no-progress streak：

- 新的用户消息；
- 用户明确“再试一次/重新检查”；
- 工具结果 fingerprint 变化；
- 任一 effectful tool 成功；
- 外部事件/任务状态 epoch 变化；
- 模型切换（默认 reset，除非有明确跨模型 no-progress 证据）；
- task/goal scope 变化。

尤其：**跨 run carry 不能无条件跨 user intent 延续。**

同时：模型在自身推理中自述“我要重试/这是新的一次尝试”**不构成** reset 边界（防自我解锁）；reset 只能由 user turn、result fingerprint 变化、state epoch 变化或 effectful 成功触发。

## 5.5 熔断回执只陈述事实

BLOCKED 回执应保持事实化：

- 什么调用；
- 已连续得到几次等价结果；
- 本次是否执行；
- 阻断的程序原因码。

不要写：

- “请换工具”；
- “建议你……”；
- “应该联系……”；
- “下一步使用 X”。

恢复策略由模型根据事实自行决定。

## 5.6 No-Progress 的工程落地要求

`NoProgressState` 能否成立取决于关键字段的真实来源，必须与 Phase 2 一并落地：

- `result_fp` 由工具执行层在回执中结构化给出（receipt 携带 `result_fingerprint` / `receipt_id`），不得由 prose 推断；截断/分页结果以 `evidence_ref` 为指纹基准；
- `state_epoch` 由真实状态变化源推进（task store、外部 job 状态、文件 hash/mtime、新 user turn）；
- fingerprint 必须稳定（同内容同指纹），并容忍无害抖动（时间戳、随机 id），归一化规则写入实现规约；
- streak 绑定 `(call_fp, task_scope)`，禁止升级为全局会话级封锁；
- user-intent boundary 的弱关键词判定（如“继续”）本身须经 N1-N6 审查：最小封闭集合、shadow 期统计误判率；误判即回退为“任何新 user turn 均重置”的保守语义。

---

# 6. P1-A（2026-09-04 收正）：当前任务语义归模型，程序只守机械重开边界

> **本节覆盖 2026-09-03 初稿中的 Authorization Context 方案。** RULE-AI-23 v12 已把“当前用户指令是任务授权真值、短回复最近绑定、历史提议不得自我授权”提升为模型侧规则，因此运行时不再维护第二套 `continue/resume_unfinished/reopen_done` 语义授权分类器。

## 6.1 权威边界

程序保留并提供可验证事实：

- 当前输入是否为 genuine human ingress、session/user-turn provenance；
- Goal/Task 当前状态、合法状态转移、done/premise_stale 等账本事实；
- 显式 `/continue` 控制命令自己的 UI/票据协议；
- 安全、身份、不可重复副作用等真正机械授权边界。

程序**不再**：

- 从“继续/恢复/重做/重开”等自然语言关键词生成授权 token；
- 将历史 unfinished/done 状态升级成当前任务；
- 用 shadow/enforce TaskAuth 状态替模型解释当前用户意图。

## 6.2 `task_update(confirm=true)` 的新语义

`confirm` 只用于 `done -> 非 done` 的显式重开动作位：

- `confirm` 缺失/false：TaskStore 机械拒绝隐式重开；
- `confirm=true`：表示**模型已依据当前真实用户指令**判断本次重开获得授权，并显式选择该动作；
- 程序不从用户措辞代填 `confirm`，也不生成/消费 AuthorizationContext；
- 该参数不是安全身份凭据，不能越过真正的权限/审批/副作用硬边界。

这与普通工具参数相同：模型负责语义判断，程序负责动作结构和账本不变量。

## 6.3 历史任务状态只提供事实，不自动恢复

### current-turn task

当前用户指令及本轮模型创建的子任务按正常模型决策执行，无额外程序授权分类。

### historical unfinished task

旧 Goal/Task/checkpoint 仅是可查询事实。是否恢复由模型根据当前用户指令与最近交互判断；程序不得因账本仍 unfinished 自动启动。

### done task reopen

TaskStore 保留 `done -> 非 done` 的显式 `confirm=true` 机械门，防止普通状态更新误触重开；“用户是否明确要求重开”由模型判断。

### scheduler/system/background resume

后台 continuation 只能使用其已有明确机械授权/调度契约，不得把程序生成 wake 文本重新解释成新用户授权。

## 6.4 `/continue` 是显式控制协议，不是自然语言分类器

飞书 `/continue` 保留独立控制入口：

- 可读取当前 Goal 状态并在已开始未完成时生成 scoped confirmation frame；
- pending frame 的“同意/拒绝”仅消费该既存票据；批准后执行原先排队的真实 `/continue` 命令，不把“同意”本身作为无 referent 的模型任务文本；
- 普通自然语言“继续”“重跑这个任务”等不再进入 RestartGuard，原样交给模型；
- `/continue` 不能授权任意历史 done task。

---

# 7. Prompt Eligibility：减少程序干预，不是减少模型能力

## 7.1 总原则

Prompt Eligibility 的目标不是“尽量少给模型信息”，而是：

> **只把当前推理真正需要的状态放入 prompt；其它信息保持可检索、可发现、可水合。**

减少注入和保障能力不是冲突关系。

## 7.2 默认不应自动注入的内容

- 已解决的原始用户问题；
- 已消费的工具回执；
- resolved Q&A/tool chain 全文；
- 普通 memory 全文；
- experience tip；
- 失败工具的冗长教学；
- observability report；
- 重复架构状态；
- 工具 schema 查询历史正文；
- “建议下一步”的 program prose。

这些内容应该：

```text
index → search → explicit hydrate
```

而不是自动回流 prompt。

## 7.3 可以注入的最小状态

只有当前轮必须的状态，例如：

- 当前用户输入；
- 当前 active task 的最小执行游标；
- 未消费的授权状态；
- 当前工具调用需要的 schema；
- 必须维持协议正确性的极小状态；
- 尚未解决且当前仍直接相关的失败事实。

## 7.4 程序 prose 治理

程序生成文字应分为：

### Fact

允许：

- tool unavailable；
- permission missing；
- action blocked；
- result truncated；
- evidence ref；
- partial/degraded；
- duplicate effect conflict。

### Advice

默认禁止自动注入模型上下文。

如果确实需要机器可恢复信息，改成 metadata：

```text
reason_code
available_tools
blocked_capability
promotion_target
retryable
```

由模型自行解释。

metadata 以结构化尾块附着在当轮 ToolResult/回执内：不进入 prefix 锚层、不自动回流历史消息，字段集合有界；需要原文时经 evidence_ref 显式水合。

---

# 8. 工具系统目标架构：Availability / Discoverability / Callability 分离但闭环

工具应明确四个不同概念：

## 8.1 Registered

程序注册表存在工具。

## 8.2 Healthy

当前 runtime 能否执行。

## 8.3 Discoverable

模型是否能知道该能力存在、查看 schema。

## 8.4 Callable

当前 provider 本轮是否真的接收到完整 callable schema。

过去的问题在于：

> discoverable 被误当成 callable 的替代品。

新不变量：

> **Discoverable 必须拥有有界、确定的一跳路径进入 Callable。**

如果做不到，就不应对模型宣称“这个工具可用”。

---

# 9. 错误与结果必须保持“事实语义”

工具系统至少区分：

- SUCCESS：动作真实完成；
- NOT_FOUND：真实检索完成但无结果；
- PARTIAL/DEGRADED：动作完成但结果不完整；
- BLOCKED：程序边界阻止，未执行；
- UNAVAILABLE：runtime capability 不可用；
- UNAUTHORIZED：缺真实用户/系统授权；
- FAILURE：内部执行失败；
- CANCELLED：执行未完成；
- CONFLICT/ALREADY_DONE：副作用幂等/冲突事实。

禁止：

- 内部异常 → “参数错误”；
- 扫描失败 → “未找到”；
- 被 BLOCK → 看起来像成功；
- 已执行但 projection 失败 → 让模型以为未执行；
- tool hidden → 让模型以为不存在。

---

# 10. Safety / Authorization：哪些硬边界必须保留

“模型能力优先”不等于删除所有 guard。

以下类型属于必要硬边界：

1. **用户权限**：外发消息、重启历史任务、敏感副作用等需要真实授权；
2. **数据完整性**：路径安全、并发覆盖、重复 destructive effect；
3. **安全策略**：法律/安全限制；
4. **协议正确性**：tool call/result pairing、必填格式、事务不变量；
5. **资源硬上限**：真正会导致 OOM/无限循环/系统不可用的边界；
6. **运行时不可用**：缺依赖、服务不可达、工具被 quarantine。

但即使这些边界也必须：

- 在最靠近风险源的位置执行；
- 不通过 prompt 劝模型自律来代替；
- 不扩大到无关工具/无关 session；
- 输出结构化事实；
- 有明确恢复条件。

---

# 11. Cache / Token 优化的优先级重新排序

以后优化优先级固定为：

1. 正确性；
2. 任务可达性；
3. 用户授权与数据安全；
4. 模型自主推理空间；
5. 可恢复性；
6. cache/token/latency 成本。

不能为了第 6 项破坏前 1-5。

因此：

- CORE + 动态尾部是好方向；
- 隐藏 40+ 工具减少 schema token 也是合理方向；
- 但必须保证 promotion 一跳可达；
- 如果一次 schema 查询 + 一次目标调用比全量 schema 更省，这是有效优化；
- 如果 schema 查询后目标仍不可调用，导致 7 次 schema loop，则该“优化”实际同时恶化 token、latency 和成功率，应直接回退。

---

# 12. 建议实施阶段（后续编码路线，不在本轮执行）

## Phase 0：冻结证据与行为基线

目标：先证明真实问题，不再靠描述猜测。

需要新增/固定观测：

- provider 最终发送的 callable tool names；
- 模型原始返回 tool call；
- parser 后 ToolCall；
- tool projection reason；
- schema lookup target；
- promotion state；
- block reason；
- result fingerprint；
- user intent boundary id。

验收：可以回答：

> “模型原始发的是 get_tool_schema，还是程序把 submit_evolution 改成 get_tool_schema？”

在没有 raw emission 对账前，不再写“发射层替换”这种超出证据的结论。

## Phase 1：One-Hop Tool Promotion（P0）

目标：修 schema-loop 根因。

实现方向：

1. exact `get_tool_schema(X)` success 生成 promotion；
2. 下一轮 eligibility 强制包含 X full schema；
3. local budget filter 不能删掉 active promotion；
4. promotion TTL 1-2 round；
5. X 成功调用后 consume；
6. 未消费 promotion 按 TTL 自动清理；已追加能力只在 new task boundary 随动态尾部重置（见 4.7）；
7. blocked/unhealthy X 明确返回不可调用原因；
8. 已 callable 目标 exact lookup 短路（`already_callable` 事实，见 4.3）；
9. promotion 去重 + 每 run 预算（见 4.8）。

必须测试：

- hidden `submit_evolution` → exact schema → 下一轮 callable → 真执行；
- hidden `save_experience` 同路径；
- 用户下一轮只有“继续”仍可执行；
- local/remote 各一条；
- promotion 不永久膨胀 tool set；
- `?keyword` 不批量 promote；
- exact lookup 不存在的工具：返回 NOT_FOUND 事实，不产生 promotion；
- promoted schema 被 provider 拒绝（schema 非法/超上下文）：返回结构化失败事实并保留 promotion 现场供诊断，不静默丢弃。

## Phase 2：Stagnation 重新定义为 No-Progress（P0）

目标：去掉误伤模型的“第 3 次相同调用”规则。

动作：

- 全局 args-only block 退出；
- exact immutable schema loop 可以保留专用 breaker；
- mutable observation 用 call+result+epoch+user_turn；
- effectful tool 用 idempotency/authorization；
- carry 遇新 user turn 重置。

Shadow 指标：

- would_block_count；
- actual_result_changed_after_same_call；
- false-positive candidate rate。

达到证据门后再 enforce。

## Phase 3：Task Authority 收正（P1-A，2026-09-04）

目标：消除运行时与 RULE-AI-23 争夺用户语义解释权的第二套 TaskAuth 系统，同时保留 Task 账本机械边界。

动作：

- 退役 input-side `AuthorizationContext` 与 continue/resume/reopen 关键词分类；
- genuine user ingress/provenance 与 Task/Goal 状态继续作为事实；
- 普通自然语言不经历史 Goal restart semantic gate；
- done→非done 仅保留模型显式 `confirm=true` 的结构门；
- `/continue` 保留为显式控制命令及 scoped pending-frame 协议；
- 用 RULE-AI-23 三模型 canary + focused/full regression 验证，不增加替代 classifier。

## Phase 4：Prompt/Feedback 去程序化（P1）

目标：程序只给事实，不指导模型思考。

动作：

- 清查所有 `[建议]`、`preferred_next` prose、experience tip、recovery tip；
- 需要机器恢复的改 metadata；
- resolved/history 改 index-first；
- 自动 experience/memory 注入默认关闭；
- 只有用户显式提及或模型检索时 hydrate。

## Phase 5：统一 Local / Remote Capability Projection（P1）

目标：不同 provider 只在“表达格式/预算”上不同，不在“能否完成任务”上不同。

动作：

- local allowlist 改 initial seed；
- promotion/protocol/auth tool 永远优先；
- 本地文本工具协议和 function-call provider 都遵守同一 capability state machine；
- provider 特例只能影响序列化，不得暗中改能力语义。

## Phase 6：删除旧债务（P1/P2）

只有新路径验证后再删除：

- 全局 args-only `partition_stagnation_block`；
- 无 user-intent reset 的 carry；
- 模型自报 `confirm`；
- 重复 kind/tool allowlist；
- program advice prose；
- 已被 promotion 替代的 schema retry guidance；
- 无消费方的 dead state/提示。

不要为了“兼容旧逻辑”永久双轨；双轨只能有明确迁移期。

---

# 13. 强制验收矩阵

## 13.1 Tool Reachability

| 场景 | 必须结果 |
|---|---|
| X 在 registry、未在 CORE | 模型能发现 X |
| exact schema(X) 成功 | 下一轮 X callable |
| user turn = “继续” | promotion 不丢 |
| local provider | X 仍 callable |
| remote provider | X callable |
| X unhealthy | schema 回执明确 unavailable，不伪装可用 |
| promotion consumed | 不再续期；已追加能力在当前 boundary 内保持 callable，boundary 时随动态尾部重置，不永久膨胀 |
| 同目标重复 exact lookup（已 callable） | 短路返回缓存 schema + `already_callable`，不产生新 promotion |

## 13.2 Stagnation

| 场景 | 必须结果 |
|---|---|
| 同 read_file args，内容变化 | 不 block，count reset |
| 同 job_output，状态变化 | 不 block |
| 同 schema exact，digest 相同，目标已 callable，连续重复 | 可 block |
| 同 call 两次后新 user turn | streak reset |
| effectful tool 成功后同 args 再来 | 由幂等/冲突处理，不由通用 stagnation 猜测 |
| schema 查询重复但目标仍不可 callable | 判 projection defect，不判模型停滞 |

## 13.3 Task Authorization

| 场景 | 必须结果 |
|---|---|
| 本轮用户要求做任务，模型拆子任务 | 正常执行，不重复问 |
| 历史 pending 自动恢复，无本轮授权 | 不启动 |
| 用户明确“继续上次任务” | 明确 scope 可执行 |
| 多个历史任务 + “继续”歧义 | 不自动猜范围 |
| done task 程序自行 reopen | 拒绝 |
| 用户明确要求重做 done task | 允许指定 scope |
| 模型私自传 boolean confirm | 不能构成授权事实 |

## 13.4 Prompt Freedom

- 无自动重复原问题；
- 无 resolved episode 全文常驻；
- 无普通 experience tip 自动注入；
- 无程序“建议换工具”的强引导；
- 模型仍可通过 search/hydrate 查回全部必要信息；
- prompt chars 减少不能伴随 task success rate 下降。

## 13.5 分阶段验收门（Gates：未达标不得进入下一阶段）

- **G0**（Phase 0）：raw emission 对账可回答 4.1 之问；观测字段齐全且有留存样本。
- **G1**（Phase 1 enforce 门）：连续 ≥3 个真实 run `promotion_next_round_callable_rate = 100%`；`hidden_tool_unreachable_count = 0`；run 末动态尾部有界（promotion 预算生效）；其中至少 1 个 run 为 local provider，至少 1 个 run 的下一轮用户输入仅为弱关键词（如“继续”）。
- **G2**（Phase 2 enforce 门）：shadow 期 would-block 样本中 `actual_result_changed_after_same_call` 占比显著（建议 ≥30%，按 G0 基线校准），证明旧规则在误伤；新 breaker 误伤候选率低于旧规则；达标后旧 args-only blocker 进 Phase 6 删除清单。
- **G3**（Phase 3 / P1-A）：无 TaskAuth 语义分类器/事件/运行态；普通自然语言直达模型；done→reopen 无 `confirm=true` 时机械拒绝；RULE-AI-23 canary 与全量回归通过。
- **G4**（Phase 4/5）：13.4 达标且 task success rate 不降；local/remote 通过 13.1 全行。

Gate 未达标：停留在 shadow/观测，不得 enforce，不得提前删除旧路径。

---

# 14. 关键指标：以后不能只看“测试绿”

必须建立行为指标。

## 14.1 Capability

- `schema_lookup_exact_total`
- `schema_lookup_to_target_call_rate`
- `promotion_created / consumed / expired`
- `promotion_next_round_callable_rate`，目标必须接近 100%
- `hidden_tool_unreachable_count`，目标 0
- `promotion_budget_dropped_count`，应趋近 0（持续 >0 说明预算常满，需复核预算或模型行为）
- `schema_lookup_short_circuit_rate`（已 callable 目标的重复 exact lookup 被短路占比），上升即说明模型侧循环在减少

## 14.2 Model friction

- `repeated_same_schema_lookup_rate`
- `user_intervention_to_unstick_rate`
- `tool_not_visible_after_discovery_count`
- `program_block_count`
- `block_false_positive_rate`

## 14.3 Prompt/cache

- stable prefix chars；
- dynamic schema tail chars；
- cache hit；
- tool schema tokens；
- schema discovery extra rounds。

必须联合看：

> 如果 cache hit 提升但任务成功率下降 / schema loop 增加，优化判失败。

## 14.4 Task correctness

- historical task auto-start count，目标 0；
- unauthorized reopen count，目标 0；
- duplicate user confirmation count，应下降；
- current-turn task blocked by historical guard count，目标 0。

---

# 15. 回滚策略

每阶段必须独立可回滚，但**退役后的第二决策系统不得为了“方便回滚”永久留一套 shadow/enforce 双轨**。

P1-B 后：

- `TOOL_ELIGIBILITY_MODE` / `TOOL_PROMOTION_MODE` / `CAPABILITY_REQUIREMENTS_MODE` / local hard-filter selector 已删除；需要回滚时依赖版本控制与验证证据，不在生产 runtime 保留 dormant selector。
- P2-A 后 `LFL_DUPLICATE_GUARD_MODE` / duplicate prewarm / `NO_PROGRESS_BREAKER_MODE` / `PROGRAM_ADVICE_MODE` 及对应 semantic breaker/classifier 也已删除；回滚同样依赖版本控制，不在 runtime 养 shadow/enforce 双轨。
- 事实 telemetry 可以长期存在，但不得拥有 block/terminate/promotion/authorization 等策略权。

---

# 16. 对当前五个提交的处置建议

## `4d0b0ab` loopbreaker

**保留作为紧急止血证据和实现基础，但不得把当前 args-only 全局拦截视为最终行为。**

后续：

- schema immutable 专用部分可复用；
- 历史上曾建议以 no-progress breaker 替代 args-only blocker；P2-A 进一步裁决为**不保留通用语义 breaker**；
- 不建立 cross-run carry deny state；只保留当前 run 的精确事实 telemetry。

## `2fe3ef1` task restart guard

**P1-A 已收正：保留 Task 状态与显式 `/continue` 控制协议，退役普通自然语言 TaskAuth 分类。**

当前契约：

- `done -> 非 done` 仍要求模型显式 `confirm=true`，仅作为结构动作位；
- 程序不从“继续/重做”等文本生成授权事实；
- historical unfinished/done 账本仅提供事实，不自动成为当前任务；
- 普通飞书文本不再由 RestartGuard 先行解释；只有显式 `/continue` pending frame 应答继续走一次性票据。

## `b539cb0`

per-session RunState 与授权轮 next-step 思路可保留；但 next-step 只能是状态锚，不得自动演化成程序命令或历史任务自启动依据。

## `c89d580`

Feishu `/continue` 可以成为真实 user authorization source；但必须有 scope，不得作为“任意历史任务恢复”的万能许可。

## `66e4195`

docs/skills 可以保留“快速止损”方向；后续所有文档证据必须区分当前可验证事实、外部证据与推测，日期/测试数/环境声明必须可追溯。

---

# 17. 后续代码评审必须逐项回答的 Checklist

任何修复、更新、功能添加，PR/设计评审必须回答：

1. 这个改动是否减少模型可用能力？
2. 如果减少，风险证据是什么？
3. 能否改成观测、结构化事实或软排序，而不是 hard gate？
4. 工具如果可发现，是否能一跳变 callable？
5. 是否新增 program prose 干预模型？为什么不能用 metadata？
6. 是否把“相同动作”误判为“无进展”？
7. 是否跨 user turn 延续了本应重置的状态？
8. 是否让模型自己声明授权/安全事实？
9. 是否把 cache/token 优化放到了任务可达性前面？
10. 是否把 resolved/consumed 信息重新自动注入？
11. 是否为 local/remote 制造了能力语义差异？
12. 是否有合法重复、模型自主换路、多模型正例测试？
13. 是否定义 shadow 指标、回滚和删除旧逻辑的时间点？
14. 如果删掉这个规则，真实最坏后果是什么？是否其实可接受？
15. 如果保留这个规则，模型可能失去什么能力？
16. 是否为 promotion / no-progress 定义了预算、去重与 reset 边界？
17. provider 工具数/上下文超限时，裁剪是否按 4.4 次序执行并输出事实，而非静默？
18. 是否把削弱安全硬约束包装成“能力优化”？

**第 14/15 问是强制反向审查。不要默认“已有规则就是安全资产”。旧规则同样必须持续证明自己值得存在。**

---

# 18. 明确禁止的未来做法

后续不再接受以下方案作为正式修复：

- “模型重复了，所以再加一句提示让它别重复”；
- “模型调用错工具，所以隐藏更多工具”；
- “工具太多，所以 local 永久只允许固定 10 个”；
- “查过 schema 但调用不到，再加熔断”；
- “用户授权不好判断，于是程序再做关键词分类并生成第二套授权 token”；
- “为了不崩，把异常吞掉返回空结果”；
- “为了 cache 稳定，不允许本轮新增必要工具 schema”；
- “某规则有误伤，但暂时先保留因为测试已经很多”；
- “旧逻辑和新逻辑都留着最安全”；
- “靠 program-final / program advice 替代能力修复”。

---

# 19. 最终目标状态

完成本路线后，LFL 应表现为：

1. **模型能看到足够少但真正有用的初始工具。**
2. **不知道的工具可以查。**
3. **查到后下一轮一定能调用。**
4. **程序不会因关键词、模型类型或 cache 优化把已经选定的能力再次藏掉。**
5. **正常重复检查不被误伤；程序只报告重复/结果/状态事实，是否无进展与是否继续由模型判断；资源耗尽由机械上限截断。**
6. **历史任务不会自行复活，但本轮用户已授权的正常任务不会被反复确认拖慢。**
7. **程序只提供事实、授权、边界和索引，不持续给模型塞建议。**
8. **resolved 信息可以随时检索，但不会因为“可能有用”而永久注入。**
9. **本地模型与远程模型能力语义一致，只在协议和预算表达上不同。**
10. **所有限制都有证据、最窄边界、观测、reset、回滚和最终删除标准。**

这才是 LFL 的目标：

> **不是让程序替 LLM 做更多，而是让程序成为可靠的执行环境，使 LLM 能把自身推理能力真正转化为动作。**

---

# 20. 当前裁决与下一步

2026-09-04 Rule-first Program Authority Audit 当前进度：

1. **P1-A：已完成**——TaskAuth 语义分类器退役；保留 provenance/Task 状态/显式 `/continue` 控制协议。
2. **P1-B：已验证完成**——Tool Eligibility / Promotion / Capability selection plane 及 `PREFIX_LAYERED` keyword/index selector 的策略性权力退役；保留 runtime health、注册表事实、显式 delegation scope 与 factual receipt metadata。验证证据：focused/邻域回归全绿，最终 full pytest **REAL_EXIT:0**；GLM-5.3 / DeepSeek V4 Flash / MiniMax-M3 live canary **3/3 PASS**，三模型均可在未查 schema 前直接调用原 CORE9 外的 `model_catalog`，exact schema lookup 前后 provider callable surface 不变，selector/promotion/capability-declare 事件为 0。当前镜像运行环境注册 62 工具、机械可用 60，唯一 quarantine 为缺 Python runtime dependency 的 `playwright_test` / `playwright_exec`。证据：`data/audit/p1b_tool_authority_live_canary_20260904.json`。
3. **P1-C：已验证完成**——zero-producer fixed point 已证明；runtime Injection Profile / semantic Injection Budget 已退役；focused **58/58 PASS**、physical-budget/ERR1210/fallback/config 等邻域 **289/289 PASS**、最终 full pytest **100% / 0 failure**；GLM-5.3 / DeepSeek V4 Flash / MiniMax-M3 live prompt-authority canary **3/3 PASS**，每模型 6 个 provider attempts 保持 62 registered / 60 runtime-callable（仅真实缺 Playwright dependency 的 2 工具 quarantine），且新 `injection.profile.shadow=0`、`action.injection_budget=0`；RULE-AI-23 多选“继续” live canary **3/3 PASS / 0 tools**。证据：`data/audit/p1c_prompt_authority_live_canary_20260904.json`、`data/audit/p1c_rule_ai23_multichoice_canary_20260904.json`。
4. **P2-A：已验证完成**——DuplicateGuard enforce/prewarm/blocked receipt/escalation 与 NoProgress classifier/threshold/terminate 已从生产主链退役；相关 duplicate allowlist、rollout/advice switch 与历史 enforce tests 同步退役。重复调用改为 exact-all-args `tool.repeat_observed` 事实事件，空搜索改为 `tool.empty_search_observed`；empty-search→`path_registry` missing 语义升级删除，并清理历史 `tool:search` 伪 path facts **56/200**，保留 144 条真实 tool/stat/read 来源。验证：focused **99/99 PASS**、邻域 **264/264 PASS**、最终 full pytest **100% / REAL_EXIT:0**、production breaker authority scan=0、Ruff PASS、`git diff --check` PASS。镜像 live canary：GLM-5.3 / DeepSeek V4 Flash / MiniMax-M3 **3/3 PASS**，每模型在一个 run 内真实执行 `model_catalog ×3`（4 rounds），恰 1 条 `tool.repeat_observed`，0 duplicate/no_progress/stagnation.break；每个 provider attempt 保持 62 registered / 60 callable。证据：`data/audit/p2a_progress_authority_live_canary_20260904.json`、`data/audit/p2a_path_registry_cleanup_20260904.json`。
5. **P2-B：已验证完成 / CLOSE**——Fallback/Recovery 收敛为机械 availability/wire recovery，不再承担模型质量与任务策略判断。退役 `LFL_FALLBACK_FLOOR` / capability-tier 候选过滤、WIP/tool-receipt 驱动 same-model retry、fallback system notice + 24h stamp 状态机，以及 ERR1210 blind resend / prompt strip / defer / replay / runtime rebuild / injection-slot parser 等旧控制面；`MODEL_FALLBACKS` 仅保留 operator 明确配置的默认模型 availability failover，候选只做注册表/凭据/规范化/去重并排除当前默认模型自身，显式 model override 继续 strict。ERR1210 仅保留已实证的 tail consecutive-user 无损聚合：payload 未变化时 0 次额外请求，变化后最多重试 1 次。验证：邻域回归 **100% / REAL_EXIT:0**、最终 full pytest **100% / REAL_EXIT:0**、Ruff PASS、`git diff --check` PASS、production retired-authority scan=0。镜像 8903 live strict-override smoke：GLM-5.3 / DeepSeek V4 Flash / MiniMax-M3 **3/3 PASS**，均 1 round、`model_used` 精确匹配请求、`fallback_receipt=null`；受控生产类机械 canary **3/3 PASS**：默认模型自身从 fallback 候选机械去重，429 primary 1 次 + fallback 1 次并仅以结构化 `fallback_receipt` 告知当前用户、Prompt notice=0；单-user 1210 provider_calls=1/aggregate_retry=0；连续 user 1210 无损聚合后恰 1 次重试并恢复。证据：`data/audit/p2b_fallback_recovery_live_canary_20260904.json`。**P2-B 正式 CLOSE；后续 cache/performance 残余控制面审计尚未启动。**

旧 P0-1/P0-2/P0-3 路线作为历史设计证据保留，不再是当前实施权威。

在 P0-1 完成前，不应把重复 `get_tool_schema` 继续归咎于模型，也不应再通过增加 schema-loop 提示或扩大熔断范围“修”这个问题。

---

# 附录 A：修订记录

- **R0（2026-09-03）**：初稿（原状态“设计冻结前评审稿”）。
- **R1（评审修订，先于本记录建立，内容以正文为准）**：新增/强化 3.1 现行成文规则映射、4.7 TTL 与“追加即承诺”一致性、4.8 Promotion 预算与裁剪次序、5.6 NoProgressState 工程落地、13.1 短路/消费场景行、13.5 分阶段验收门 G0-G4、14.1 预算/短路指标、Checklist 16-18 问等。
- **R3（2026-09-04 Rule-first 收正）**：P1-A 退役 Task Authorization Context/自然语言 restart semantic gate；当前用户语义归 RULE-AI-23 模型判断；`confirm=true` 改为 done→reopen 显式机械动作位；`/continue` 保留 scoped 控制协议。
- **R4（2026-09-04 P1-B Rule-first 收正）**：退役 CORE/keyword/protocol/recovery eligibility selector、`PREFIX_LAYERED` keyword/index selector、Tool Promotion TTL/budget、Capability Requirement Registry/HandleCollector/ReachabilityAuditor 与 cancel-intent→tool selection；provider 工具面收敛为“registered − runtime-unhealthy − explicit delegation scope”；schema lookup 变为纯 discovery；capability requirement 保留 factual metadata；历史 R8.7/Promotion/CORE9 A/B 章节降级为演进证据。
- **R5（2026-09-04 P1-C Rule-first 收正）**：证明 dynamic producer registry 空集与 program-origin pre-budget filtering fixed point；退役 runtime `InjectionProfile`、per-attempt `injection.profile.shadow` emitter、`InjectionBudget` / `INJECTION_BUDGET_CHARS` / semantic priority keep-drop；保留 Prompt Eligibility deny-by-default、历史 event schema 读兼容、Cognitive prompt-neutral observability 与物理 context/window/overflow/compaction 资源边界。
- **R6（2026-09-04 P2-A Rule-first 收正）**：退役 `DuplicateGuard` enforce/prewarm/blocked receipt/escalation、`NoProgressService` classifier/threshold/terminate、duplicate allowlist 与相关 rollout/advice 开关；重复/空搜索改为纯事实 telemetry；搜索 miss 不再写入 `path_registry` 负帧，并清理 56 条历史 `tool:search` 伪 path facts；副作用安全继续由 WAL/idempotency/conflict/authorization 机械边界承担。focused 99/99、邻域 264/264、full pytest 100% `REAL_EXIT:0`。
- **R7（2026-09-04 P2-B Rule-first 收正）**：退役 fallback capability floor / quality-tier 候选裁决、WIP 驱动 same-model outer retry、fallback notice/stamp prompt 状态机，以及 ERR1210 blind/strip/defer/replay/rebuild/injection-slot 旧恢复控制面；保留 operator-defined default-model availability failover、低层无输出 transport retry、跨-provider wire/reasoning replay 重建、strict explicit override，以及 exact 1210 changed-payload tail-user normalization 单次机械重试。full pytest 100% `REAL_EXIT:0`；镜像三模型 strict-override live smoke 3/3 PASS；受控 fallback/1210 mechanical canary 3/3 PASS。证据：`data/audit/p2b_fallback_recovery_live_canary_20260904.json`。
- **R2（本轮评审补遗）**：
  1. 状态更新为“评审修订稿 R2”，建立本修订记录；
  2. 4.8 补受保护层超限时的结构化降级事实（不静默摘除受保护工具）；
  3. 5.4 补“模型自述重试不构成 reset”（防自我解锁）；
  4. 5.6 补 user-intent 弱关键词判定自身的 N1-N6 审查要求；
  5. 6.2 补授权凭据字段（scope_text / evidence_ref / audit_ref）；新增 6.5 歧义与拒绝事实化、6.6 授权记录完整性与隐私；
  6. 7.4 补 metadata 载体边界（结构化尾块、不进锚层、字段有界）；
  7. Phase 1 补负例测试（NOT_FOUND 不 promote；provider 拒绝 promoted schema 的事实化处理）；G1 补 local run 与弱关键词 run 覆盖；
  8. 3.1 补协议与数据层硬约束边界豁免（tool_call_id 配对 / M20 / 数据完整性 / 破坏性命令硬阻断不在退场范围）。
