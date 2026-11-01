# E2 · spawn_subagent / subagent_result / subagent_lease / subagent_topology 可观测性缺口调查

- 性质：只读调查报告（未修改 src/ tests/ docs/，无 git 写操作，未遍历 data/ .releases/ runs/）
- 方法论检索：本环境无 search_records 工具，按"不适用"直接开始
- 行号基于当前工作区快照（runner.py snapshot_ref=artifact://v1/340d39e581794a03be5acb438f4512eb）

## 1. model 缺省时的子代理模型决定路径

结论：缺省（不传 model）时机械继承"父 run 当前实际模型标签"，在 runner.py:1623 生效、1625 解析。

- 工具面入口：src/llm_loop/tools/builtin/spawn_subagent.py:255 —— model = str(kwargs.get("model", "") or "").strip()（缺省=空串），:344-360 以 model=model 传入 runner.start(...)。
- 异步路径 SubAgentRunner.start()：src/llm_loop/subagent/runner.py:1617-1625
  - 1617 requested_model = str(model or "").strip()
  - 1619 inherited_model = str(current_model_label.get() or "").strip() ← 继承源
  - 1620 （仅当 self._llm_resolver is not None；否则空串）
  - 1623 child_model_ref = requested_model or inherited_model ← 生效点
  - 1625 child_llm, child_model_label = self._resolve_child_llm(child_model_ref)
- 继承源 current_model_label 由父引擎在 run 绑定时设置：src/llm_loop/core/loop/lifecycle.py:199（model_token = _current_model_label.set(run_model_label)）；子代理线程内再被子自身标签覆盖（runner.py:1201，_run_reserved_child 内 current_model_label.set(model_label)），供递归 spawn 链式继承。
- 解析器 _resolve_child_llm：runner.py:364-372 —— ref 为空返回 (self.llm, "")（fallback 到 runner 构造默认 client，标签空串）；ref 非空走 self._llm_resolver(ref)，无 resolver 抛 ValueError。
- 同族解析点（同一 requested/inherited 模式）：同步 run() runner.py:2464-2472（docstring :2450 明言"省略时机械继承父 run 当前模型"）；followup_current runner.py:2326-2332；Host 预算预检 child_input_budget_chars runner.py:2739-2744；canary 校验消费该结果 runner.py:1653。

## 2. spawn 回执字段：回显了 model，未回显来源

- 成功回执 dict 构造：runner.py:1953-1971，全部字段：accepted、child_id、state、depth、model(:1958 = child_model_label)、tool_scope(:1959-1963)、write_scope_command_guard(:1964-1968 条件携带)、worktree(:1969)、detail(:1970)。
- 拒绝回执 dict：runner.py:1526-1532（_start_failure_result）：accepted/child_id/state/depth/detail（模型不可用分支另带 model :1632）。
- 工具面渲染：spawn_subagent.py:383-401，其中 :385 —— f"... model={started.get('model', '') or 'legacy_default'}"
- 缺口：回执有 model= 但没有"来源"字段（inherited vs explicit vs legacy_default 三态只在 runner.py:1617-1623 内部存在，未外显）。legacy_default 仅在解析后标签为空（resolver 缺失/空继承）时出现——把"回退默认"与"继承成功"混在同一展示位，父代理无法区分。

## 3. 终止路径可观测性（cancel / 超时 / 停滞）

outcome 枚举：runner.py:213 —— completed/failed/cancelled/truncated/refused。

cancel 的三处收口（构造点）：
- 轮首检查：runner.py:3000-3009（"[状态: cancelled] …未继续执行后续动作"）
- LLM 响应返回后：runner.py:3255-3262
- 工具执行后：runner.py:3496-3504
- 取消触发面：cancel_parent runner.py:821-892（父 Stop 经 spawn_subagent.py:240-242 terminate_session 传入）；in-memory 标志写入点 :878 handle.cancel_requested = True（:882 同时 set activity_event）；durable 写入点 :866-872 → src/llm_loop/core/subagent_delivery.py:449-459 追加 subagent.cancel_requested 事件（reason 固定 parent_lifecycle_cancel，全仓唯一调用点）。

"超时"类：
- 启动握手超时：runner.py:1936-1944（startup_event.wait(timeout=2.0)，失败=state failed，不是 child 终态）。
- fleet 租约 TTL 过期/被接管：runner.py:3015 _renew_fleet_run 每轮心跳 → :3016-3029 _fleet_fence_lost 为真即返回 outcome="refused"（"fleet lease 权威已失效…"）。注意：仅 fleet 配置时存在；且只在轮边界判定——LLM HTTP 挂起/单工具长跑不触发。
- 轮数超限截断：runner.py:3529-3543 outcome="truncated"。

停滞（长时间无工具调用）：无 stall watchdog（已核实）。activity_event（runner.py:255）只是 threading.Event 唤醒器（:2031 clear / :2065 wait≤30s / :1172 set），不记录时间戳；result_current 的 wait_seconds 上限 30s（runner.py:2063）超时后只如实返回 running。

父会话经 subagent_result 能拿到的字段（快照构造 result_current runner.py:2004-2115；渲染 src/llm_loop/tools/builtin/subagent_result.py）：
- 快照字段：child_id/parent_id/generation/result_id/state/depth/cancel_requested/reports/result/local_active（local 路径 :2081-2094；durable 路径 :2050-2061、:2104-2115）。
- running/orphaned 分支渲染：subagent_result.py:74-88 —— child_state/child_id/depth/cancel_requested + 最近 5 条中途报告（各截 300 字符）。
- terminal 分支渲染：subagent_result.py:105-163 —— child_state/child_outcome/depth/rounds/tools(条数)/tokens_in/tokens_out + 报告 + 工具轨迹头 10 条（:118-125，仅 name:status，轨迹源头 runner.py:3464 tool_trace.append("name": call.name, "status": result.status.value)）+ final_answer + verification_receipts + settlement binding（:126-143）。durable 不可确认时显式 [持久化未确认] result_durability=local_only（:144-153）。
- 缺口：terminal 分支不显示 cancel_requested/取消原因（快照里有 flag :2090/:2057/:2111 但 :105-155 未渲染）；无"子代理停在什么状态/改了什么文件的摘要"——工具轨迹无路径/无 args、无 effect 汇总（effect 事实在 tool.execution.effect_prepared/observed 事件与 journal sidecar 中，未投影到回执）；无 model 字段。
- 其他只读面：delivery_snapshot（runner.py:546-591）有 cancel_reason；topology_snapshot（:423-484）有 outcome/settlement_state。

## 4. lease 磁盘结构与 subagent_lease 暴露面

- WorkerLease：src/llm_loop/fleet/store.py:77-87 字段：lease_id/project_id/workspace_id/worker_id/generation/owner_id/acquired_at/state(active|superseded|settled)/expires_at（None=永不过期）。没有 last_heartbeat / last_activity 独立字段——心跳即续租：renew 在 store.py:397-398（raw["expires_at"] = now + extend_seconds）；由 runner.py:945-967 _renew_fleet_run（经 src/llm_loop/fleet/coordinator.py:141 renew_run）在每轮边界调用（runner.py:3015），TTL 默认 900s（runner.py:303/346）。
  - 可推导"最后活动"：expires_at − ttl ≈ 最后一次成功心跳时刻，但每轮粒度且未在任何工具面回显。
- recover() 视图：src/llm_loop/fleet/coordinator.py:201-253 —— lease 块含 expires_at/expired/remaining_seconds(:231-239)，settlement 块含 result（含 outcome）(:241-247)，facts_summary{run_started,run_settled,last_parent_session_id}(:248-252)。
- subagent_lease 工具暴露：src/llm_loop/tools/builtin/subagent_lease.py:44-74 —— workspace_id + lease 行 lease_id/generation/worker_id/owner_id/state/expires_at/expired（:51-61）+ settlement 行 outcome/worker_id（:68-73）。不含 acquired_at/remaining_seconds/最后心跳推导值。
- subagent_topology 工具的租约行：src/llm_loop/tools/builtin/subagent_topology.py:52-69 —— state/generation/expires_at/expired + facts 汇总行。

## 5. 子代理生命周期事件记录点（现有可复用）

事件类型登记：src/llm_loop/event_log/model.py:50-57 —— subagent.linked / subagent.generation.started / subagent.generation.released / subagent.terminal / subagent.mailbox.queued / subagent.report.queued / subagent.result.available / subagent.cancel_requested。Event 自带 ts（ISO UTC，model.py:82-90），落盘经 EventStore.append（store.py:325-340，会话级 flock + 单调 seq）。

- TopologyJournal（src/llm_loop/core/subagent_topology.py，_append:47-53）：
  - linked() :155-172；generation_started() :174-198；generation_released() :200-229（含 reason）；terminal() :231-256（含 outcome）。
  - runner 调用点：runner.py:1239-1244（linked）、:1245-1251（generation_started）、:1339-1346（released，reason="worker_exit"）、:1138-1144（terminal，_finalize_child 内）。
  - payload 仅 child_id/parent_id/generation/owner_id/depth/(reason|outcome)——无 model。
- DeliveryJournal（src/llm_loop/core/subagent_delivery.py）：
  - queue_mailbox() :292-334；queue_report() :336-374；result_available() :376-424（payload=result dict :402-413）；cancel_requested() :426-469。
  - runner 调用点：:706-711（report）、:732（mailbox）、:609-615（result，经 _persist_terminal_result :593-616，payload=_result_payload :499-511）、:867-872（cancel）。
- ToolExecutionJournal（src/llm_loop/core/tool_execution_journal.py，child 循环内逐工具调用）：
  - declared() :337-361；started() :363-378；finished() :738-786（含 result_state_sha256/status）；receipt_committed() :805-847；另 mark_effect_fence_lost() :541、effect_context() :380+（lease_fence 注入）。
  - child 循环调用点：runner.py:3371（declared）、:3413（started）、:3442-3449（effect_context + fleet fence）、:3475（finished）、:3487（receipt_committed）。
  - 每步活动时间戳已存在于子会话事件流（tool.execution.* 的 ts）——"最后活动时间"可由子会话最后一条事件 ts 推导，当前无人消费。
- fleet facts 流：coordinator.run_fact()（coordinator.py:135），runner 写入 run_started（runner.py:933-942，含 depth/runner_owner/parent_session_id）与 run_settled（:1077-1091，含 outcome/depth/parent_session_id）；recover 按 event 名精确过滤计数（coordinator.py:211-212），新增事件名不破坏汇总。

## 设计可用挂点（最小侵入）

1. spawn 回执加 model_source：runner.py:1953-1971（成功 dict，紧邻 :1958 model）+ 渲染 spawn_subagent.py:383-385。三态 explicit/inherited/legacy_default 的判定数据已存在于 :1617-1623，只需把 requested_model 是否非空随 dict 带出。影响面：仅回执文案与 dict 新键；拒绝路径 :1526-1532 可不动。
2. generation_started payload 加 model/model_source：subagent_topology.py:174-198 + 调用方 runner.py:1245-1251。fold()(:56-148) 按事件类型匹配、忽略未知 payload 键，SubAgentTopologyState 不必扩字段（recover 兼容旧事件）。影响面：子会话事件流新增键，durable 只读面零变化。
3. 每轮心跳落一条 fleet fact：runner.py:3015（_renew_fleet_run 调用点）或 _renew_fleet_run 内 :960-962 续租成功后 run_fact(lease, "event": "round_heartbeat")；recover 的 facts_summary（coordinator.py:248-252）按名过滤不受影响，可在 subagent_lease.py:44-74 增一行"最后心跳=facts 末条 round_heartbeat 时刻"。影响面：仅 fleet 配置时多一条/轮 fact；粒度=轮，不能替代 stall watchdog。
4. result_current 快照加 last_activity（+model）：runner.py:2081-2094（local）/ :2050-2061、:2104-2115（durable）。last_activity 取子会话事件流最后一条事件 ts（EventStore 已有，model.py:90），fleet 场景可用 expires_at − ttl 兜底；消费点仅 subagent_result.py:74-77（running 分支加一行）。影响面：快照 dict 独占消费方是 subagent_result 工具，纯增量。
5. SubAgentResult 加 model 与富化工具轨迹：dataclass runner.py:208-237 + _result_payload :499-511 + _result_from_payload :513-544（宽容读旧 payload）→ subagent.result.available 事件（delivery :402-413 原样透传 dict）与 subagent_result.py:108-111 头行自动获得 model；轨迹源头 :3464 目前仅 name/status，可增量加 args_sha256（tool journal :356 已算好）作为"改了什么文件摘要"的最小底座。影响面：事件 payload 新键、旧载荷默认值；terminal 渲染加 1-2 字段。

## 验收对照

1. 每条结论均带 文件:行号 ✅
2. model 缺省继承路径 = runner.py:1619-1623（生效 :1623，异步）/2464-2472（同步），继承源 lifecycle.py:199；回执回显 model（runner.py:1958 / spawn_subagent.py:385）但不回显来源 ✅
3. cancelled/timeout/停滞时父会话可得字段：§3 列全（快照 runner.py:2081-2094/2050-2061/2104-2115；渲染 subagent_result.py:74-88/105-163；取消 durable 事件 subagent_delivery.py:449-459；无 stall watchdog；无停态/文件改动摘要）✅
4. 未修改 src/tests/docs，无 git 写操作 ✅
