# DESIGN-20261009: GLM-5.3 Provider/Tool 执行预算与权限边界 v1

> 状态：**DRAFT / DESIGN REVIEW ONLY / NO ENFORCEMENT AUTHORIZATION**（2026-10-09）
>
> 基线：本地 main = 7bdccc3c4b2ee02a4c6569714448a09aacc3846d；
> 生产 Web = gen206 / da8629b0b66be5eba214b1490daefcf0cccaa306，
> Knowledge Advisor = Shadow；Feishu/Learning = gen204。上述是文档立项时的
> 已核事实，不是未来部署授权。Canary = HOLD。
>
> 本阶段**只交付需求、执行设计、反例和验收规约**；不改变 src/、生产配置、
> Web/Feishu/Learning 进程，不接真实 GLM、不重做失控烟雾测试，不推送远端。

## 0. 先裁决：我们到底在修什么

先前独立 Web 烟雾任务（归档会话 8040dc96-b886-4c1c-9ec4-718baa958b66）
以模糊输入启动真实 GLM-5.3，却没有工程级工具或资源隔离。事件账本表明：

1. 首次用户入口是 web；Run 1 执行了 20 轮；
2. Run 1 第 223–227 号事件中，schedule 工具成功注册 wake=true 的
   **同会话自动续跑**（不是单纯发通知）；
3. 第二条独立消息的入口为 scheduled:schedule_wake，携带有效 delegated ingress，
   启动 Run 2（16 轮）；**不能**把它归因于同步 HTTP 超时自动重试；
4. 两 Run 合计 38 次 provider.call.opened/settled、35 次 tool.execution.started/
   finished、763,950 输入 tokens、7,505 输出 tokens，均因取消结束；
5. Shadow 只产生 knowledge.discovery，knowledge.reference_prepared=0，
   knowledge.method_declaration=0；没有证据证明 Shadow 引发模型行为失控。

本事故的可靠根因是：**将常规生产工具权限赋予了测试任务，只有提示词承诺而无
Provider/Tool/派生续跑的强制成本与权限边界。** 需要防止“一个小测试”演变成多个
LLM transport、工程副作用和未来 Run，不应据此更改正常 Schedule 的授权语义。

### 0.1 已有能力和真实缺口（按源码核验）

| 系统/权威入口 | 已有事实 | 本设计不能冒充的能力 |
| --- | --- | --- |
| ResourceGovernor / resources/provider_calls.py | RG-1/2 可按已确认的本地 runtime 并发事实控制租约，云端缺资格时不作本地 RG-2 适用推断 | 不是云端 GLM 的账户、费用、token 或跨 Run 硬预算 |
| RG-3C provider_settlement.py | 记录 logical provider call、physical transport attempt、opened/settled、retry、usage 已知字段和缺失事实 | 记录事实不是调用前原子扣额；open/settled 事件不能当作实时停止令牌 |
| RG-3D ledger projection | EventStore 是权威，SQLite 作为投影；known sum、coverage、unknown 分开 | 投影只观察，不授予预算，不阻断、重路由或自动撤销 |
| RG-3E vendor/product facts | GLM Coding Plan/public quota 不是可直接换算的 exact account quota；GLM product/account 绑定未资格化 | 不能把“约 N prompts”换算成准确定额；不能借 cost_tier 猜价格 |
| core/loop/engine.py | 有 max_iterations、请求投影/overflows、tool trace、Run 终态、cancel 观察点 | 最大轮数不自动限制单轮多次 transport retry、tool 副作用或 schedule_wake 新 Run |
| llm/client.py | GLM 接口支持 provider max_tokens 可配置；流式有独立总时长保护（读间 timeout 不是总时长）及有界空响应/网络重试 | 单次 HTTP timeout、max_tokens 或近似字符估算不是全任务绝对 token/cost 硬上限 |
| tools/registry.py & tools/pipeline.py | 真正工具执行入口有预检、执行流水线、工具超时和部分破坏性工具 EXEC_MODE/单调权限 | EXEC_MODE=blocked 只保护指定变更类工具；不能默认视为 schedule(wake=true)、其他非破坏类及后台派生工作也被禁止 |
| web/routes.py & core/loop/runner.py | 同步 Web /api/v1/chat 串行入口、Runner 取消、同步 Run 活动登记、会话级工具取消 | HTTP 客户端 155s 超时不等于服务端停止；cancelled=true 先代表请求被登记，非物理副作用全部终止 |
| core/scheduler.py & tools/builtin/schedule.py | wake=true 需要当前真实 user-ingress 同会话授权，scheduled:schedule_wake 是委派来源；持久化/去重/re-arm 有独立生命周期 | 用户身份授权不等于“可无限消费下游预算”；跨 Run 派生必须有单独资源预算归属 |
| scripts/shadow_smoke_offline.py | 完全离线 FakeLLM、零工具、1 次调用/1 轮、有限合成 token、外层 20s 进程组超时；6/6 PASS | 这是**测试端**能力，无法自动保护线上真实 GLM 与 Web 任务 |

RG-3C/3D/E 的“shadow-only/no enforcement”是其各自已冻结的正确事实边界。
本设计提出独立的 TaskBudget Authority；**不能偷偷把 RG-3D 投影改成云配额执行器**。

### 0.2 不做什么

- 不改变正常任务的模型语义决策、方法选择、知识检索结果、会话原文保存或 Provider 的工具协议；
- 不凭模型说“简单任务”/“只读”就放宽权限，也不靠提示词判定能否执行；
- 不假设 GLM-5.3 Coding Plan 的账户产品、定价、余额或某个 tokenizer 已有 exact 绑定；
- 不把成功写入取消请求、发出 SIGTERM、HTTP 断连、工具 timeout 一概标记“物理执行停止”；
- 不默认对所有正常业务开启新的低限额；先封闭**隔离烟雾执行 profile**，之后经独立资格和授权扩面；
- 不因跨 Run 的 schedule_wake 是模型创建就否认已有 ingress/delegation 权威；为预算隔离建立**另一个正交授权条件**。

## 1. 需求和硬不变量

### 1.1 安全第一的最小可用目标

**P0-A 不触云端**：只要是隔离 smoke profile，未经明确 live-profile 签发，
所有 provider transport 都要在**真实网络调用前**返回 typed BLOCKED，
不是仅删工具 schema 或换一个无效 URL。Fake Provider 不能通过动态路由旁路。

**P0-B 零工具执行**：smoke profile 的可执行工具集合必须为空，包括
schedule、schedule_cancel、execute_command、read_file、web_fetch、MCP
工具、子代理、Learning 与复合工具；模型伪造 tool_call、旧会话 replay、
工具别名、get_tool_schema、registry.execute_many 并发、嵌套执行都不能绕过。
既要在模型可见 tools 中不发布，也要在最终物理执行边界阻断并留下 typed 回执。

**P0-C 无自动续跑**：smoke profile 不允许创建任何 wake=true 或重复 schedule。
普通用户业务 profile 的 schedule 授权可以保持不变；但派生唤醒若属于受约束
预算族，必须继承父 profile 的剩余额度/截止时间，不因产生新的 run_generation
而得到另一套完整预算。预算撤销后所有尚未消费 wake 必须不能继续执行。

**P0-D 多维硬限制**：对 exact、有权威计量支持的维度强制 admission；
对 unavailable/unknown 的物理/token/美元精确值如实报告 unknown。
不得用提示词、字符数或供应商含糊宣传值宣称“精确消费硬上限”。

**P0-E 全链路停止**：预算到界时禁止后续 provider/tool admission；对已在途
provider 发起取消/关流；对子进程、长工具按原工具协议终止、等待结算。
没有终止确认则 outcome=STOP_REQUESTED 或 COMMIT_UNCERTAIN，不得伪报“清场成功”。

**P0-F 未更改默认业务面**：新机制 default=off、精确匹配测试身份并仅 Web
可激活；Feishu/Learning、正常人类会话、Learning Plane 的行为与安全边界
保持现状。正式发布/重启/线上 live 实验分别经后续明确授权。

### 1.2 成功定义分三层

1. **机制资格**：离线真实执行路径证明无非法物理 side effect、预算数值不被越过、
   retry/fallback/wake 完整归属、取消后无未知继续运行；这是 P0 退出必需。
2. **Provider 资格**：在有真实 GLM-5.3 精确请求/消费证据及隔离账目之后，
   才能区分“可严格保证的 Provider 请求上限”和“只能估算/观察的 token/费用上限”。
   未验证前标签必须是 UNKNOWN/HOLD。
3. **知识收益资格**：冻结 OFF/SHADOW 对照样本、工具权限/上下文/模型身份等价，
   独立验证正确率、重试、FCR、whole-run wire/cost。不能用机制 PASS 代替收益 PASS。

## 2. TaskBudget Authority：独立于知识、模型和 RG-3D 的授权

### 2.1 对象、身份和作用域

引入概念性 TaskBudgetGrant（当前**尚未实现**），字段至少：

| 字段 | 约束和用途 |
| --- | --- |
| budget_id / policy_version / generation | 独立可重复读取身份；修改只能新建更严格 generation |
| issuer / authority_source / expires_at | 签发者必须是运行入口/操作者；用户自然语言、模型输出、工具返回不得签发或扩大 |
| workspace_scope / session_id / human_turn_ref | 隔离授权所属真实工作区、Session 与起始 human turn |
| run_generation / ingress_ref / ingress_kind | 记录**消费时** Run 身份及真实/委派入口；不拿 run_generation 当可重置余额的根 |
| lineage_root_id / parent_budget_id / schedule_sid | wake、子代理、Fallback、工具派生任务的父预算族 |
| surface / provider_identity / exact_model_ref | Web-only scope；若模型改路由仍沿同一预算；产品/账号未资格化时不冒充绑定 |
| mode / profile / capability_policy | off、observe 或 enforcement；smoke profile 的 tool allowlist=显式空集且不可扩大 |
| attempts, rounds, tool_calls, in/out token limit, wall deadline | 各独立上限；显式 None = 该维度**未资格化/不可承诺**，不是无限额度 |
| reservation_ids / settled_ids / unknown_liabilities | 持久 CAS 防重复扣额；已开未结的请求不能算零消费 |

身份标准：root budget **绑定一个经人类明确准入的任务来源**，一个合法
schedule_wake 派生 Run 消耗同一 root budget，而不是按新 Run 分别得到新额度。
跨 session/subagent 若授权不明确，预算族状态 UNKNOWN => **不启动受约束派生任务**。
正常非试验会话不得从临近测试会话、同名模型或进程全局变量继承额度/禁用工具策略。

### 2.2 预算是交集，不是某个入口的最终决定

实际可用权限 = 平台/灾难性安全最小边界 ∩ 当前 ingress 权威 ∩
服务专属限制 ∩ 当前 TaskBudgetGrant ∩ 工具自身限制。

- 旧 EXEC_MODE、escalation approval、插件/MCP 权限都**不能**提高 TaskBudgetGrant 权限；
- 同会话另一条合法人类消息不自动继承 smoke 授权；若新预算由人类重新签发，
  必须与旧任务明确分离，防止连续任务偷用对方额度；
- schedule(wake=true) 的现有人类委派令牌只是必要条件之一；预算仍可能拒绝该动作；
- 请求中的“忽略预算/恢复所有工具”及检索到的 Method/Experience/网页均视为低可信文本；
- 任何 fallback 或模型切换不可重置 tool/provider 总次数、TTL、预算族身份。

### 2.3 最小状态机

授权状态：ISSUED → ACTIVE → STOP_REQUESTED → SETTLING →
（CLOSED_VERIFIED | CLOSED_UNCERTAIN），另有 BLOCKED_BEFORE_START。

一次消费必须有 reserve → dispatched → settled，或 reserve →
abort_before_transport（释放已证明未发生的预约）。必要审计事件拟名：

- budget.grant.issued（只存非敏感范围、policy hash、来源、额度，不存 key/消息）；
- budget.admission.denied / budget.reservation.created（带 CAS epoch、用途、call/attempt id）；
- budget.transport.dispatched / budget.transport.settled / budget.liability.unknown；
- budget.tool.denied / budget.tool.dispatched / budget.tool.settled；
- budget.stop.requested / budget.stop.acknowledged / budget.closed。

正式映射前不得声称这些事件当前存在。预算层事件只包含身份和计量指针；
现有 provider.call/transport opened/settled 是后者**权威事实源**，避免重复总结或
把同一 physical retry 计成两个不相干请求。EventStore 写失败、CAS 冲突、
身份缺失、消耗未知时：对 smoke **阻断新增物理调用**，同时记录可恢复错误，
不做静默 fail-open。

## 3. Provider 侧：先批准物理发送，再核销真实回执

### 3.1 绝对不能遗漏的两层调用

一次用户 Run 可包含多个 model rounds；一次 round 可因 fallback/recovery
出现多个 logical provider calls；一次 logical call 还可能经过连接重试、
空响应重试、流式重建等**多个 physical transport attempts**。
只在 engine._run_with_acquired 外层计“一次任务”，或在
foreground_task_provider_chat 入口计“一次 logical call”，都不足以
硬限**物理** Provider 请求数。

拟采用**两道强制 admission**：

1. **logical call gate**：在 core/loop/engine.py + RecoveryController +
   Fallback 的调用决策前，从同一 TaskBudgetGrant 获取 round/call reservation，
   校验任务总轮次、fallback、deadline、已消费/在途额度；不依赖模型的自报；
2. **physical attempt gate**：在 llm/client.py 的真实 HTTP/WebSocket transport
   发起前（包括内部空响应重试、连接重试以及协议分支），核验
   provider-attempt reservation。请求目标切换不能逃逸该栅栏；GLM 正常路径、
   OpenAI-compatible 与 future adapter 必须全部证明入口覆盖。

transport attempt 的 idempotency key 由 root budget + call_id +
attempt_id + epoch 派生，必须与 RG-3C ProviderCallSite、transport_retry_index
和 provider.transport.* 关联。一个失败后自动重试也是**新的物理预算消费单位**；
不允许在 retry 递归里自增未记账的内计数。

#### Admission 伪代码（设计，不是已实现行为）

    grant = budget_authority.lookup(exact_signed_ingress_scope)
    budget_authority.require_active(grant, wall_deadline, generation)
    call_reservation = budget_authority.reserve_logical_call(grant, stable_call_id)
    for candidate_attempt in provider_transport_attempts:
        attempt_reservation = budget_authority.reserve_physical_attempt(
            grant, call_reservation, provider_target, attempt_id,
            projected_request_size, qualified_output_cap
        )
        if attempt_reservation.denied:
            return BLOCKED_BEFORE_TRANSPORT_WITH_REASON
        try:
            response = send_with_checked_deadline_and_cancellable_transport()
        finally:
            settle_or_mark_unknown(attempt_id, RG3C_actual_evidence)

逻辑/物理限制不能串成“任一通过即放行”；任何已启用的硬维度未满足都 DENY。
资格不足的 provider 缺失精确 usage 时，仍可精确限制**请求次数和时长**，
但不能声称已严格限制 token 或账单金额。

### 3.2 Token：区分请求侧保证、事后计量、估算

| 维度 | 能作为什么 | 不应做什么 |
| --- | --- | --- |
| UTF-8 provider payload bytes | 物理硬边界；精确读取最终构造出的请求 bytes（包括 tools/schema/reasoning/projection） | 不按固定 chars/token 换算声称精确 token |
| request input tokens | 仅当已资格化**模型精确 tokenizer / Provider 预检计数**且覆盖 role、tools、缓存及 multimodal 时，才可在发送前硬阻断 | 不把提示字符数、历史缓存估计、另一模型 tokenizer 作为精确 GLM 事实 |
| output tokens | 在模型/产品确认 max_tokens 含义后，可把 Provider 接受的 request cap 与流式限制组合 | 不把本地 max_tokens 字段存在等同于真实 Billing 上限，尤其 thinking/reasoning 输出 |
| post-response usage | RG-3C 的 per-physical-attempt provider usage，可作已知消费的会计事实 | 不把缺报/空响应/中断当作零成本；不对同一 stream snapshot 累加 |
| cached input/reasoning tokens | 按 Provider 明确回报字段单独追踪，避免以 cache hit 当作免费 input | 不凭 pricing tier/推测将 cached tokens 从 billable tokens 中扣除 |
| 货币费用 | 必须具备 exact provider/product/model/price/time/units 身份后才能计算并封顶 | 当前 GLM RG-3E 产品绑定不成立，不得凭 marketing quote 做“人民币硬限” |

如供应商可能在响应结束后才返回精确 input/output usage：
先作最坏情形 reservation（只有可证明的上界才可使用）；无法证明时将该
维度标为 unknown，并对要求此维度必须 exact 的 profile **拒绝进入 live**。
若仅启用物理请求次数/轮次/时长/工具禁用，允许将 tokens 标注
OBSERVED_ONLY，但用户/报告不能再宣称“硬 token 限额已满足”。

即使请求中发送 max_tokens，也要确认服务端是否保留超出参数的 reasoning、
错误返还、部分流、自动兼容改写。是否支持 stop/cancel 及何时停止计费，
必须从当前 GLM 实际适配器资格获取，不复用其他 Provider 结论。

### 3.3 拨号、回退、重试、停止

- 对路由标签和**实际 transport target** 双重记录；没有 exact product/account
  不做账号配额合并，却仍按 task-root 统计**所有** Provider 物理尝试。
- 超时后的未知 attempt 标记 in-flight liability，不能立即返还 quota；
  以后通过 authoritative settlement/reconciliation 证明未发生发送时才能释放。
- Provider 400/429/5xx、SSL EOF、空输出等分支不能绕过 gate；已有重试机制
  必须先重新 reserve，剩额不足返回 budget_exhausted，不再走 fallback。
- client disconnect 后若后台工作继续，budget 仍在服务端生效；不要把客户端
  read timeout 当作 cancel authorization。若收到取消：先撤销**新调用准入**，
  再关闭 transport，观察 settled/orphaned，不允许无界等待。
- 工程故障下保存完整 provider 响应/部分推理的现有安全策略不变；预算层只
  存 token/attempt/身份摘要，不保存密钥、原始提示、reasoning、HTTP 头。

## 4. Tool 侧：真实执行点必须与模型可见面双重一致

### 4.1 能力策略，不是字符串黑名单

提议 CapabilityPolicy 的核心是**默认拒绝的显式正向集合**：
allowed_tool_ids、allow_side_effects、allow_delegated_wake、allow_subagents、
allow_background_jobs、max_physical_invocations；所有字段只允许
签发者收紧，不接受模型输出加权限。

“空 allowlist”与“未设置 allowlist”不同：

- smoke profile：allowlist 明确为空，强制 max_tool_invocations=0，
  并禁止 schedule/wake、复合工具、插件、MCP、隐藏通道；
- normal profile：未设置时沿用当前既有权限边界，**不是**默认禁用所有工具；
- 若工具 schema 出现别名或工具注册集动态变化，以真实 ToolRegistry 的
  tool identity + 策略绑定核实，无法证明身份时拒绝而非按名字相似放行。

### 4.2 两阶段拒绝与并行 CAS

**展示门**：core/loop/engine_services/tool_cycle.py 的
_project_tool_schemas_for_round，对受约束的测试 Run 不广告任何可调用 schema。
禁止调用 get_tool_schema 来把不允许工具“拿回来”；模型自行猜测工具名时仍拒绝。

**执行门**：tools/registry.py 的 ToolRegistry.execute（及 execute_many 分派到
物理执行前）按 budget/ingress/generation 再检一次。
工具调用经过现有 safety、escalation、MonotonicGuard、effect-binding 后，
不得通过测试预算禁令获得任何额外授权。准入必须早于 tool.execute 和 side effects；
在 on_result/post hook 才发现违法太晚。

同轮多个只读工具会在 execute_many 并发运行。预算的 max_tool_calls 必须用
跨线程原子 reserve：若只剩 1 次额度，同时声明 2 次只可有 1 次 admitted，
另一次需生成绑定原 tool_call_id 的结构化 BLOCKED receipt，不能部分掉结果、
不能以异常使已授权的另一个调用失去终态结算。

### 4.3 线程超时不等于工具退出

tools/registry.py 已说明 ThreadPoolExecutor future timeout 可能使非 daemon
线程继续运行；会尽力 revoke effect binding、future.cancel、调用 terminate hook。
因此只能在明确工具支持并验证了 kill/revoke/physical-commit 屏障后，
才声称已阻止剩余副作用。

对独立子进程的 smoke 限界应在独立进程组/sandbox worker 完成；没有进程隔离的
工具超时只能进入 cancel_requested / worker_unconfirmed，
上游任务不能因线程返回 TIMEOUT 就宣布安全结束并释放预算。任何已经开始的
物理提交如果结果未知，保留 COMMIT_UNCERTAIN，必须由原业务日志/receipt reconcile。

### 4.4 schedule 是未来执行能力

正常 schedule(wake=true) 的当前 user ingress 委托机制保持原样。
新的预算门至少核验：

1. 当前 budget profile 是否允许 schedule 和 wake；
2. schedule_sid 对应的**父任务预算族**和 policy_generation 是否有持久签发权；
3. 到点 claim 后再次验 budget 状态/剩额/截止时间/会话身份；
4. restart recovery、grant re-arm、Goal generation 变化或旧 session 复用
   不能让未来任务获得一份全新的预算；
5. 取消根预算后，子 schedule 按既有投递语义留下
   budget_denied / cancelled 可审计状态，而不是悄悄丢失；
6. 通知型 schedule(wake=false) 需要区分纯通知与外部副作用；
   smoke profile 两者都禁止，正常任务须按独立通知能力授权。

用户对模型的普遍工具授权不自动等价于一次具体的预算续期承诺。
若未来业务允许循环长期运行，必须以**新的人类批准或运维策略签发**
追加预算，而非模型自己创建任意多次 wake。

## 5. 时间、停止、重启后的复原

### 5.1 三个不同时间维度

1. socket read/connect timeout：网络每阶段行为，不代表任务生命周期；
2. provider stream total deadline：单个 stream 的上限，当前 llm/client.py
   使用 effective timeout 的倍数；不覆盖所有工具和后续 schedule_wake；
3. **TaskBudget root wall deadline**：必须由服务端签发单调 deadline，
   在新调用 admission、流式读循环、工具执行前和定时唤醒 claim 时生效。

持久化中同时存 wall deadline、签发时刻、时钟不确定标志。进程重启后的
monotonic epoch 不可直接复用；若时钟回拨/漂移无法证明，不得借重启续出
新的完整有效期。用户侧 HTTP 超时不自动创建新 Run，也不自动删除已运行子任务。

### 5.2 Stop 不是一个布尔值

拟定义可验证阶段：

    REJECT_NEW_WORK → REQUEST_CANCEL_IN_FLIGHT
      → TERMINATE_SUPPORTED_CHILDREN → RECONCILE_PROVIDER_AND_TOOL_RECEIPTS
      → CLOSED_VERIFIED / CLOSED_UNCERTAIN

- 新工具和新 Provider 请求必须同步阻断，不需等现有 task 自然退出；
- 精确 run_generation 对应的取消登记是控制事实，不等同于 Provider HTTP ACK；
- 跑在独立进程组的 Job 要验证整个可归属进程组的终止，不可 kill 任意同名 pytest；
- 外部 API 副作用若没有 cancel 能力，只能声明不能保证 rollback；
- 正常已授权任务若只触发预算暂停，不得擅自清理用户文件/关闭其他 session；
- 若事件日志不可写或账本状态无法恢复，smoke 将停止新副作用，恢复时
  通过稳定 action/call/attempt ID 去重与 reconcile；不得忽略 UNKNOWN。

### 5.3 对现有 Web 同步和后台双入口的要求

Web /api/v1/chat 当前直接进入 engine._run_with_acquired；
/api/v1/chat/cancel 经 Runner.cancel 支持后台及同步活动登记。
但 cancel 返回 True 只说明取消请求被接受，不能代替真实 run.end、
provider.transport.settled、tool.execution.finished 和剩余子进程清单。
测试工具应带**exact session + run_generation**，只取消自己拥有的任务；
同步 HTTP 客户端断线以后不再默认沿同一会话补一条 user 输入来“确认完成”。

实际实现之前要对非流式 Web、SSE/WebSocket、Feishu、Learning、
SubAgent 和 detached schedule wake 逐一列出 call-site 覆盖矩阵。
若某条路径尚未接入预算栅栏，smoke profile 应明确判为 unsupported
并拒绝启用该路径，而不是“部分 enforce”。

## 6. 配置提案、现网隔离和迁移路线

### 6.1 配置不可以先于 schema 实现

以下为**拟议接口，不是当前支持的字段**（值仅表示 smoke v0 离线初始冻结线）：

| Proposed field | smoke_offline/v0 | 生产资格说明 |
| --- | --- | --- |
| task_budget.mode | off / offline_enforce | 默认 off；正式线上 enforce 必须独立签发和放行 |
| task_budget.surfaces | [offline_test] | Web-only live scope 尚未实现；Feishu/Learning 不默认接入 |
| max_logical_calls / max_physical_attempts | 1 / 1 | 不能只限制 logical；所有 retry/fallback 都算 attempt |
| max_rounds | 1 | 目前离线 1 轮；不映射全局普通任务 max_iterations |
| max_tool_invocations | 0 | 物理执行入口必须 deny，无 schema 并不足够 |
| allowed_tools / allow_wake | [] / false | “显式空集”是 deny-all，不能等价 None |
| max_input_tokens / max_output_tokens | 2000 / 128 | **仅 FakeLLM 合成 usage** 已可检；真实 GLM exact=HOLD |
| max_provider_payload_bytes | 80,000 | 必须在最终 provider wire 构造后计 bytes |
| task_wall_seconds | 20 | 当前离线父进程组物理约束；Web live timeout/cancel 尚未资格化 |
| on_unknown_usage | deny_if_exact_required | 缺失/不完整 usage 不是免费额度 |

任何生产配置应先在 runtime/resolver.py closed schema 注册，明确 Web-only
source precedence、合法取值、旧版 Feishu/Learning 的兼容性。不能直接把未注册
的 [task_budget.web] 写入共享 runtime.toml（旧解析器可能启动时报未知字段）。
具体 TOML/env 名称需在实现阶段重新冻结，**不能把上表当可直接填入线上配置的指南**。

### 6.2 渐进部署，不把实验条件扩给其他服务

1. **D0 需求评审**：本 MD + 逐条源码引用与反例确认；仅文档修改，生产 gen206
   Shadow 保留、Canary HOLD。
2. **D1 Off + offline enforcement**：独立分支接真实 engine/provider/tool/scheduler
   hook，但 production default off；FakeLLM、失败注入及崩溃恢复测试先过。
3. **D2 Shadow accounting**：只计算 would_block/usage gaps，不阻断正常业务，
   比对旧 RG-3C/3D 事实与新预算账本，保留原始调用行为。
4. **D3 Controlled smoke**：另行人类授权后，先选可证明零工具/单物理调用
   的 Web-only 隔离 profile，并对 GLM 当前产品/adapter 做 provider budget
   能力探测；不达标即回退离线，不尝试“凑够 1 次真实 GLM”。
5. **D4 结果与推广**：冻结随机化 OFF/SHADOW 对照；将测试安全 PASS 与
   Method/Experience 提效 PASS 分开批准。Canary 仍需单独审批。

Production default off 不允许因为环境变量继承或会话设置自动变成 enforce。
任一范围扩展必须原子签发、记录 policy generation 并提供**可验证**的撤销路径。
部署/重启均须按 service_control release identity、CAS、idle barrier、健康和
回滚基线执行，不能直接 kill Web 逃逸 Gate。

## 7. 验收矩阵：每条都必须产生可审计的反证能力

下面的测试 ID 为**将来应新增的测试**，不是声称已完成。优先在真实
LoopEngine/ToolRegistry 与 FakeLLM/无网络 transport 上运行；失败用例必须
证明实际调用数、子进程数、事件数量和 side-effect count，而非只比对错误字符串。

| ID | 故障注入/输入 | 必须出现的可观测结果 |
| --- | --- | --- |
| A01 | offline profile 直接 FakeLLM 正常回复 | 1 轮、1 次 fake 调用、0 物理 tool，Run 终态；会话没有测试参考注入 |
| A02 | Fake 模型返回 schedule(wake=true) 伪造 tool_call | Provider 结果可审计，但真实 schedule add=0，工具 BLOCKED，未来 wake=0 |
| A03 | provider 返回工具 alias / get_tool_schema 试探 | 未在显式 allowlist 的真实注册 id 不可执行，零物理 side effect |
| A04 | 不公告 schema，却直接调用 ToolRegistry.execute/execute_many | 同 budget 身份在物理边界拒绝，证明只隐藏 schema 不足够 |
| A05 | 允许 1 tool，2 个只读调用同一批并发 | CAS 最多 1 次 dispatched；另外 1 次原 tool_call_id 绑定 BLOCKED |
| A06 | 允许 1 provider physical attempt，内部连接重试 2 次 | 第 2 次必须在网络前拒绝；不能把一次 logical call 当作一次物理网络请求 |
| A07 | 空响应后客户端自动重试 | 重新尝试要独立 attempt reservation；无法在余额耗尽时再次发送 |
| A08 | Overflow/recovery/fallback 更换 provider/model | 同 root 额度不重置；路由目标变化与 RG-3C 实际 attempt 身份相符 |
| A09 | 前次 transport 已打开但超时/未结算 | in-flight liability 保留；不能把未知 usage 计 0 并允许下一次占额 |
| A10 | EventStore 确认“阻断在 send 前”，实际 HTTP 计数器为 0 | BLOCKED_BEFORE_TRANSPORT 与 RG-3C 事件保持一致，不生成伪 settlement |
| A11 | 真实 tokenizer 未资格化，profile 要求 exact input tokens | 拒绝 live 准入，报 token_authority_unknown；不拿字符预算代替 |
| A12 | provider 回报 input=unknown / cached=unknown / reasoning=unknown | 字段继续保持 unknown；既不补零也不标 usage_complete |
| A13 | Provider stream 分块 usage 重复，末端只回一次 summary | 不重复相加同 attempt snapshot，按 RG-3C 完整度与 attempt 去重结算 |
| A14 | 既有 max_tokens 配置，但 adapter 未证明 GLM thinking 语义 | 禁止标记 output_exact_hard，最多记录 request_cap_sent/observed |
| A15 | 缺 GLM product/account/pricing exact 绑定 | 费用硬限资格 HOLD，公开 approximate quota 不能制造 CostBudget |
| A16 | 客户端先断连，服务器 Run 仍在继续 | 新 provider/tool admission 受原 budget 控制；不能因 HTTP 连接结束重新给额 |
| A17 | root budget wall deadline 到界同时一个流继续滴流 | 新发送 0；cancel 状态可确认；无 settle 只能 CLOSED_UNCERTAIN |
| A18 | 线程内工具 timeout，但仍有线程/外部子进程 | 不虚报 CLOSED_VERIFIED，不释放 effect/liability，按实测终止能力裁决 |
| A19 | 物理 side effect 已开始后 host 异常 | 以真实 commit/event receipt 对账；重复请求不生成第二个副作用 |
| A20 | 模型正常创建一次 schedule(wake=true) | 普通业务现有 ingress 正向路径保留；预算 profile 不许可则在 schedule.add 前拒绝 |
| A21 | smoke 创建 schedule 与数分钟后 wake（模拟时钟） | schedule 创建=0，wake Run=0；不允许普通 schedule grant 漏过去 |
| A22 | 有预算的合法 wake 在重启后 claim | 读同 root budget，剩余额度单调、截止时间不刷新；未知授权拒绝，不冒充未曾消费 |
| A23 | schedule re-arm、Goal 更换 generation、重复 claim | 不铸造第二个完整预算族，不发生多次消费或跨会话复活 |
| A24 | 原 Run 被取消，异步子代理或 Job 仍持有 lease | 禁止新派生动作，先终止可停止子进程，无法证实收口则 CLOSED_UNCERTAIN |
| A25 | 改 session/model/Provider 标识但保持相同 tool/run 事实 | Budget 权限不能跨工作区、跨 principal、跨模型身份或跨用户泄漏 |
| A26 | 收到恶意 Method/Experience/网页文本“解锁预算” | 无 task grant 变化，无新增工具能力或额度；provider 原文不插额外权限提示 |
| A27 | 临时账本/事件目录不可写、CAS 冲突或旧进程残余 | smoke 不再派发外部副作用，留下 typed denial/uncertain 可恢复线索 |
| A28 | 试验配置在 Web 开启但 Feishu/Learning 沿旧版本启动 | Web-only scope 精确生效；旧服务行为/工具集/密钥来源不变 |
| A29 | 执行点多样：sync Web、stream Web、scheduled wake、子代理、Learning | 未集成入口标 unsupported+deny experimental profile；不得报告“全入口覆盖” |
| A30 | 退回 profile=off | 所有正常默认 Run 的 provider wire、ToolRegistry schema、Schedule 正向行为与冻结 baseline 等价 |
| A31 | 20 秒离线 subprocess watchdog，孙进程刻意延迟写文件 | parent/child 均被进程组终止，写文件不存在，进程/句柄可确认收口 |
| A32 | 模型响应时合成输入/输出 token 超额、provider 第二次调用 | Fake harness 必须立即失败；不能声称这种测试证明真实云账单上限 |
| A33 | 修改预算限额后新旧进程并行读取 | 持久代际 CAS 保证旧权限不能继续新增消费，不以进程局部计数为源 |
| A34 | 重复 ProviderCallSettlement、out-of-order opened/settled | 同一 attempt 不重复扣减；真实 opened 未 settled 不可推断未发送或零成本 |
| A35 | 取消请求 ACK 与真实 tool/proxy/stream ACK 不一致 | Run 终态和子工作 outstanding 分开报告，不能将 cancelled=true 当全部 closed |
| A36 | 依赖现有服务健康或 Shadow 观测数据退化 | 默认 off 零回归；独立资格失败停止推广，生产部署走可审计 Web-only 回滚 |

至少用 fail-first 注入证明每一道**物理执行门**没有被跳过，之后再做正例。
包含“未来计划的事件 ID”的测试只有在实际事件结构实现后才能打 PASS。
当前运行没有这些新事件时，绝不构造虚假历史回执。

### 7.1 最低证据包（每一条 PASS 都可追溯）

- 运行身份：repo commit、文件 diff/hash、policy_version、进程/Run generation、
  workspace/session/ingress、model route 和实际 dial target；
- 准入证明：provider-call/transport attempt 预算 reserve/deny 的顺序和
  **真实 HTTP mock 发送次数**，与 RG-3C opened/settled 一一核对；
- 工具证明：真正 ToolRegistry 前置 deny、物理 tool.execute 次数、
  side-effect commit receipt、Job pid/pgid 和 parent 子进程终态；
- 持久证明：budget reservation/reconcile、schedule_sid/goal lineage、
  重启恢复不重置数值，unknown 和 unfinished 并非 0；
- 指标：provider calls/physical attempts、rounds、工具次数、known/unknown
  token usage、wall time、后续 wake 次数、真实 retry/FCR；
- 反证：若能力不在实现覆盖表或权威账本不完整，验收只能是
  BLOCKED/UNKNOWN/HOLD，不能“部分通过”替代生产资格。

## 8. 十八项设计拷问：尚未回答清楚之前禁止 live

| # | 问题 | 现有事实/待补证据 | 未通过时的裁决 |
| --- | --- | --- | --- |
| Q01 | 哪一处是**真正拨号前**最后不可旁路的拦截点？ | 需逐协议跟踪 llm/client.py、Fallback、Recovery、内嵌重试 | PHYSICAL_ATTEMPT_HOLD |
| Q02 | LLM 内部 empty-response 重试也占实际预算吗？ | 当前有内部有界重试；必须能注入并实数网络动作 | RETRY_COVERAGE_HOLD |
| Q03 | 物理请求已发、回包失联时如何结算？ | RG-3C 有 transport opened/settled；未知消耗需债务态 | USAGE_UNCERTAIN |
| Q04 | 谁证实 GLM-5.3 input tokenizer 精确？ | 当前未核验 exact 等价关系，包括 tools 和 multimodal | INPUT_TOKEN_HARD_HOLD |
| Q05 | GLM max_tokens 包不包括 reasoning 和隐藏开销？ | 必须基于当前 provider/product 回执独立验证 | OUTPUT_TOKEN_HARD_HOLD |
| Q06 | GLM Coding Plan 与当前 route/key 是否同一资源产品？ | RG-3E 未资格化账户产品绑定，不能用 marketing quotas | MONEY_HARD_HOLD |
| Q07 | 是否能在停止 stream 后证明 Provider 不再计费？ | 关流/取消能力与实际计费确认是不同事实 | COST_STOP_UNCONFIRMED |
| Q08 | Worker 超时返回后还会有 side effect 吗？ | ThreadPoolExecutor 自身不能 kill 线程；需真实进程/commit fence 证据 | PHYSICAL_STOP_HOLD |
| Q09 | 零工具 profile 有没有所有注册入口的最终 deny？ | Tool schema 与 ToolRegistry.execute、MCP、SubAgent 必须同时覆盖 | TOOL_ZERO_HOLD |
| Q10 | 能否阻止 model-created schedule(wake=true)？ | 上次事故已证明当前 human grant 下 model 能注册自动续跑 | DERIVATION_HOLD |
| Q11 | wake/new Run 能否得到全新的预算？ | 必须持久记录 root lineage，禁止按 run_generation 重置 | TASK_LINEAGE_HOLD |
| Q12 | 同一 Session 不同真人任务互相借额度怎么办？ | root 人类入口与 workspace/principal 分离；共享 session 不是同一 budget | SCOPE_HOLD |
| Q13 | 并发只读工具会不会同时透支最后一份额度？ | execute_many 并行线程必须在执行前 CAS reservation | CONCURRENCY_HOLD |
| Q14 | EventStore 不可写、SQLite projection 落后时信谁？ | EventStore 为 provider usage 事实，预算应有独立同步 CAS 源；投影不是授权 | LEDGER_UNCERTAIN |
| Q15 | HTTP timeout、SSE 断连、Runner.cancel 谁保证真正停止？ | 按 generation 追 cancel/transport/tool terminal，不能只看 client ACK | CANCEL_HOLD |
| Q16 | mixed-gen Feishu/Learning 会不会误采 Web 的实验配置？ | 必须使用 Resolver closed schema + 版本兼容测试 | SCOPE_LEAK_HOLD |
| Q17 | 对照组是否真的有等价模型、工具和成本口径？ | frozen manifest + 每行 exact call/attempt 和 user task success | EFFICACY_HOLD |
| Q18 | 用户为什么要相信“没有发生第二次任务”？ | 须完整覆盖 schedule wake、subagent、job、retry 和未知 orphaned；负证据需完整观察窗口 | CLOSURE_UNPROVEN |

每一问只有权威证据和**对照反例**才能变更状态；不能通过扩大测试阈值、
减少测试用例、依赖模型声明或改用 DeepSeek 假装 GLM-5.3 合格。

## 9. 建议实现单元与明确停机线（待后续授权）

以下是实施次序，**不是本轮执行授权**。

| 阶段 | 范围 | 独立停机线 |
| --- | --- | --- |
| I0 contract freeze | 明确 TaskBudgetGrant/Reservation/Settlement/CapabilityPolicy 字段、责任层、case A01-A36 的操作回执 | Q01/Q09/Q11/Q14 未裁决，不进入代码 |
| I1 pure store + CAS | 独立任务预算账本、跨 Run lineage、重入恢复、unknown liability、版本隔离 | 重启/并发重复扣额或更新不确定，停止 |
| I2 provider gate | logical 和 **每次 physical transport** admission、模型协议兼容、retry/fallback 全覆盖 | 任一路径未收口或真实发送次数与 reservation 不符，停止 |
| I3 tool gate | ToolRegistry 真实物理门、explicit zero allowlist、schedule/wake/嵌套子代理继承 | 只靠 schema 隐藏或 tool timeout 有残余可执行，停止 |
| I4 cancellation | 绝对 wall deadline、同步/异步取消、进程组收口与 commit uncertainty 对账 | cancelled 被假报 CLOSED_VERIFIED，停止 |
| I5 offline qualification | Fake Provider + 模拟 transport/worker/时钟 + 原平台 full CI/R9，不触真实模型 | 任何 A01-A36 FAIL、不具备未支持路径负例，停止 |
| I6 managed OFF rollout | 另行审批默认 OFF 代码部署，校验 release 代际、Service scope、回滚 | 启用测试 profile 于非目标服务或现网用户，回滚 |
| I7 provider capability | 经授权 GLM-5.3 确认可执行硬限制的维度及其未知 | 如果 exact token/cost 不明，只批准 calls/rounds/wall/tool，不宣称全面硬预算 |
| I8 bounded real test | 新一次独立授权，工具禁用与线前拒绝已被强证据证明后才允实网 | 任一未知费用/意外 schedule/失控进程/中断不结算，立刻停止 |
| I9 controlled comparison | 预注册 OFF/SHADOW 任务/环境、FCR、whole-run wire、成本 | 效果或负例阈值不达标，Canary HOLD |

建议新增中性运行层模块（名称仅为提案）：
resources/task_budget_contracts.py、resources/task_budget_store.py、
resources/task_budget_authority.py；不要放入 Web 包或 RG-3D projection；
Web、Feishu、Learning、SubAgent 仅是入口适配器。
执行门放在真实 Provider 网络 transport 与 ToolRegistry 的物理执行边界，
Schedule 消费 Root lineage 的独立预算引用。Resolver、EventStore、ResourceGovernor、
ProviderCallCoordinator 与现有 Session/Run 继续保持各自权威，不以影子账本
替代用户消息和模型语义。

## 10. Review outcome / 需要新的实施授权

**本设计已经确定：**

1. 事故第二 Run 由成功的 schedule(wake=true) 触发，而不是 HTTP 隐形 retry；
2. 当前 RG-3C/3D/E 不提供可直接拿来用于云端 GLM 的 exact cost/token 硬预算；
3. 真正的 hard deny 必须两层落地——物理 provider attempt 和物理 tool.execute，
   同时必须覆盖 schedule wake 的持久预算族；
4. 模型决策自由与工具权限是两件事；预算程序只裁事实、权限、数字与截止时间，
   不自动给模型做 Method 适用性或任务完成的语义判断；
5. 离线 6/6 仅证明测试装置安全，不能代替真实 GLM provider/token/cost 的资格；
6. D0 退出可以是“哪些事实仍 UNKNOWN”；不得为了上线给未知编造肯定结论。

**仍然未授权：** 编写/启用生产 budget gate、调整任何原有工具权限、绑定
GLM 账户/价格、做 live GLM smoke、修改生产配置、publish/restart/push、
开启知识 Canary 或将实验额度扩展给 Feishu/Learning。

评审通过本 MD 后，下一步只建议批准 I0/I1 的纯 offline contract +
原子账本实现与 fail-first 测试，**先不连 Provider、不接工具副作用**。
只有 Q01/Q09/Q11/Q14 等单元级关键权威问题有代码证据后，再申请 I2/I3。

### 10.1 文档事实参考（本地可复核）

- docs/DEVELOPMENT_REPAIR_SAFETY.md：真实 provider-view、权限和可恢复性边界；
- docs/RESULT-20261009-shadow-smoke-incident.md：双 Run 原始事件与 smoke 失控；
- docs/DESIGN-20260910-resource-governor-rg3c-provider-call-settlement.md：logical/physical settlement；
- docs/DESIGN-20260910-resource-governor-rg3d-ledger-projection.md：EventStore vs projection；
- docs/DESIGN-20260910-resource-governor-rg3e-authoritative-adapters.md：GLM product/account UNKNOWN；
- docs/DESIGN-20261008-execution-knowledge-consumption-v1.md：Web-only Shadow/Canary 权限及零提示注入；
- src/llm_loop/resources/provider_calls.py、provider_settlement.py、governor.py；
- src/llm_loop/core/loop/engine.py、engine_services/fallback.py、
  engine_services/recovery_controller.py、runner.py；
- src/llm_loop/llm/client.py、src/llm_loop/tools/registry.py、
  tools/pipeline.py、tools/builtin/schedule.py、core/scheduler.py；
- src/llm_loop/web/routes.py、src/llm_loop/runtime/resolver.py；
- scripts/shadow_smoke_offline.py 和 tests/unit/test_shadow_bounded_smoke.py。

验收口径：该文档是**设计与尚待验证的反证清单**，不是 API 合同已经合入的声明。
