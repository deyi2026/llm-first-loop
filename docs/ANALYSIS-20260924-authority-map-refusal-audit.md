# 拒收分布与双权威疑点审计（authority-map 判据对照）

日期: 2026-09-24 · 性质: 纯读代码审计（审计级先行，结果决定后续 evolution 设计形态）

## 0. 判据来源与转述声明

对照文档为 authority-map（外部对照文档，前一会话轮次全文读取；本会话证据库无可水合原文 ref）。
本文引用其要点为**转述**，非逐字引用。核心判据（§四 四分类）：

| 类别 | 正确处理 | 例子 |
|---|---|---|
| 非法业务操作 | 工具入口拒绝 | 模型冒充人作审批、没有判据就交付 |
| 已经发生的运行失败 | **必须允许记录** | 评估者崩溃、落盘失败、子任务被打断 |
| 历史记录自相矛盾 | 报告诊断，保留原始记录 | 引用不存在的步骤 |
| 无法证明的业务判断 | 标为未知，交给评估者 | 两条读数是否可比 |

配套警告: "拒收一条已发生的失败，本身就是一次不实陈述。"

## 1. 审计项①: BLOCKED/拒收分布是否"拒掉已发生失败" —— 结论: PASS（无违例）

逐条代码证据（src/ 前缀省略）:

| 拒绝路径 | 拒的是什么 | 记录是否保留 |
|---|---|---|
| convergence_boundary（工具面收窄） | 下一轮**执行**（WAL 不 start、不 mutate state） | ✅ 合成 `executed=false; reason_code=convergence_boundary` BLOCKED 回执配对入历史（tool_cycle.py:384-409）；octet 观测恰好一次、status 原值透传+reason_code（tool_cycle.py:661-670, M4-R0 冻结映射） |
| missing_tool_call_id | 执行 | ✅ 协议回执 + action 记录 + `record_tool_octet(status="blocked")`（tool_cycle.py:300-336） |
| 客户端断流/取消（GeneratorExit、runner cancelled） | 执行 | ✅ 合成"已取消"回执+落盘，对账不变量"声明数=结果数+取消数"（tool_cycle.py:341-383, 410-420） |

正面设计（对应 §四第二类"子任务被打断必须允许记录/等待"）:
- `outstanding_async_obligations > 0` → 不 arm boundary（convergence_boundary.py:35-36；tool_cycle.py:817）: 未结算异步义务存在时不得收窄。
- 决策工具（convergence_decide）缺失时自动解除 boundary，"must never dead-end the run"（tool_cycle.py:934-937）。
- arm 探测失败 fail-open: registry/async_obligations 异常→不 arm（tool_cycle.py:814-819）；goal-frontier probe 失败→(None,None)→goal_frontier_closed 理由不会误触发（tool_cycle.py:784-807）。
- boundary 模块 docstring 明写 "never decides that the user's task is complete"，无消息注入、无程序策略 prose 持久化（convergence_boundary.py:1-9）。

## 2. 审计项②: 双权威 / 伴生解释器疑点 —— 结论: PASS ×2

### ②a runtime_tool_health 不是伴生解释器
- 唯一判定 = `importlib.util.find_spec("playwright")` 环境机械事实（eligibility.py:33-46）。
- P1-B（2026-09-04）已退役 R8.7 语义选择面: 用户/任务关键词、协议历史、恢复提示、promotion 状态、能力要求**永不**决定工具可见性（eligibility.py:1-7 docstring）。
- `_project_tool_schemas_for_round` 中 planned_label/user_text/session_messages 被 `del`，零权威（tool_cycle.py:904-921）。
- 判定性质属"宿主不变量"（环境可用性），非对历史/任务语义的第二套解释。

### ②b tool_history 是投影，不构成重复权威
- 写入: `ToolHistoryItem(name, status, summary[:120], duration_ms)`，arguments 丢弃，内存环形缓冲 `[-200:]`（tool_cycle.py:879-889；status.py:260-265）。
- 消费点: SelfEvaluator 效率指标（evaluator.py:226-250，source="tool_history"）+ architecture_status 只读展示；**无阻断消费**。
- 权威记录 = messages + message 事件 + WAL octet（args 全量、status 原值、reason_code、sha）。两者是"权威+有界投影"关系，与 `_resp_summary`"仅审计展示，不作为阻断依据"同款纪律（tool_cycle.py:867-877）。

## 3. 对 evolution 设计形态的输入

1. "证据等级→终局裁决书写权"硬门可复用既有形态: BLOCKED + 配对回执 + octet reason_code（本审计已验证该形态不吞记录、无死锁、fail-open）。
2. 书写权判定必须挂唯一权威面（octet/事件），不得挂 tool_history 投影。
3. 现存轴可复用: service_control.evidence_level（E1/E2/E3）、task_update 的 evidence_required/evidence_refs 参数化门；Goal 层（update_goal complete）是否程序级强制未查，属 evolution 范围。

## 4. 附录: LFL 侧"观察→正确理解"表（对应 authority-map §一六行表精神；按 LFL 实例重构，非原文抄录）

| 观察 | 正确理解 | 证据 |
|---|---|---|
| boundary BLOCKED（executed=false） | 拒的是下一轮执行，不是记录；回执与 octet 均在 | tool_cycle.py:384-409, 661-670 |
| job_output 长时间 0 行 | ≠僵死；以 interop 通知 completed 事件为准 | EXPERIENCE-20260829-dsh-dsh-home ⑤ |
| 子代理租约 expires_at/expired | 磁盘事实视图，不含接管语义 | subagent_lease 工具契约（只读） |
| 父会话回合结束 | 只证明父回合结束；child completed 才是结算 | subagent_result 工具契约 |
| goal frontier total>0 且 open==0 | 机械前沿闭合信号，非任务完成判定；程序永不断言任务完成 | convergence_boundary.py:45-50 及模块 docstring |
| octet status 原值 + reason_code | 权威观测恰好一次；BLOCKED 也是已发生事实，不可拒收 | tool_cycle.py:661-670（M4-R0） |
