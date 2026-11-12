# M0 Delta 审计：Task Intelligence Execution（2026-11-12）

- 基线：`feat/task-intelligence-execution-20261112` @ `0e933d6d88adb52168c07879e6c7e30db530f16c`（= origin/main 冻结点）
- 方法：3 个并行只读子代理（glm/glm-5.3，程序级只读白名单）分域审计 + 父代理独立交叉核对（6/6 承重结论复核通过）+ 复用既有报告（不重复 census）
- 证据：域1 `evidence://v1/f6affc292fa1...`（child subagent_84861f7d8059）；域2 `evidence://v1/faabe7396f12...`（subagent_6034cdb58586）；域3 `evidence://v1/9e664ac72f8e...`（subagent_1d3fbd232ac3）。行号均为基线版本。
- 纪律：本文只登记已核代码事实（带 file:symbol）与显式标注的推测/未核项；不引用未实测的 provider 字节或收益数字。

## 0. 结论速览

| 域 | v2 设计前提 | M0 裁决 | 真实缺口（已核） |
|---|---|---|---|
| Goal/Task/Continuity | 状态已持久化、无需新 schema | **成立**：全部需求字段已存在；journal/claims/CAS 齐 | 读侧：单任务明细/checkpoint 四要素/blocked_reason 全文**无任何工具出口**；非 overflow 中断零任务投影；overflow wire 无 blocked 维度 |
| Execution/Side-effect | journal+registry 已承担，禁建第二状态机 | **成立且无需修复**：journal 是唯一生命周期 WAL（unknown 三分支恢复、永不自动重执行）；registry/gate 非第二状态机 | 覆盖面：仅 3/45 工具有副作用登记；browser_action 与语义封装登记断层；`side_effect_kind` 类属性机制仅存在于 docstring（0 声明）；registry 登记自身无 WAL（fail-open） |
| Prompt/Knowledge/Eval | 管道存在、provider 证据非字节级 | **成立**：discovery→exact hydration→version_scope→use ledger 全链路有代码+测试 | eval：run_eval.py **无 seed/temperature、无噪声地板臂、无 B′ 重复臂**——任何 A/B 收益声称前必须先补；常驻 prompt 规模为估算非实测 |

**一句话**：设计的三条 P0 担忧在基线代码层面均**不构成需要修复的重复建设**；真实缺陷收敛为两个——①任务状态「聚合可见、明细不可见」的读侧盲区（域1），②副作用登记覆盖缺口（域2，行为面广、非本次最小修复对象）。

## 1. 旧报告继承/推翻表（P1-5，不重复 census）

| 旧报告 | 关键主张 | M0 处置 |
|---|---|---|
| ANALYSIS-20261111-memory-consolidation-gap（v2 设计 §1.2 引用） | Method 2,025 / Experience 946 / 96.8% candidate / 评分覆盖 10.9% | **继承为历史口径**。该文档**不在冻结基线**（0e933d6d8 中 missing，仅存在于 dirty 主树）；基线实测 `data/methods` 2,040 张 METHOD.md（git-tracked 2,185 文件）、`experiences` 952 张。两者为不同时点/树的事实，不得混用 |
| ASSESS-20261021-method-pool-funnel-census | 三段流水线几乎不相交（交集 7 张；92.1% 未评估未使用）；not_evaluated=证据等级字段非"没评估" | **继承**；域3证实管道机制仍在原位（search.py:304 分发 / store.py record_use / use_ledger.py 幂等）。分布未复测，明确不复算 |
| learning-queue-cluster-verdict-20261105 | longrun_continuity 由 49a85d52f 引入，218 行测试 | **继承**；域1补充实测行为：仅 overflow/projection_cannot_fit 触发（run_finalizer.py:312-341）、仅接受紧邻占位符（engine.py:769-785）、wire ≤12,000 字符、frontier 快照只含 ready/in_progress 的 id 列表（≤12 each）、**不含 blocked/标题/acceptance**（longrun_continuity.py:36-88） |
| RESULT-20261006-method-binding-v3 | Method binding 确证实验未达预注册阈值，不推广 | **继承**；与域3「eval 无 seed/B′/噪声地板」互证：实验纪律短板是横切面 |
| REVIEW-20261112-deepseek-v4-flash P0-2 | 防止第二套幂等/unknown 状态机 | **担忧在基线不成立**（域2排查：peer 幂等分类/browser manifest/ReconcileOutcome 均为领域内分类，非生命周期复制）；真实缺口是登记覆盖面，不是重复建设 |
| REVIEW-20261112-deepseek-v4-flash P0-3 | version_scope/content_hash 修订致前后不可比 | **机制面已有对策**：usage_net 双口径（current_version_only vs all_v2_heads_no_current_version_match，methods/store.py:1575-1588）如实披露；实测修订链行为未核（域3未核项） |

## 2. 域1：Goal/Task/Continuity（child subagent_84861f7d8059）

### 2.1 字段与读取面（已核）

- **全部需求字段已存在**：Goal（objective/status/checkpoints 四要素/blocked_reason/version-CAS，`introspection/goal.py:67-82,150-213`）；Task（acceptance/done_when/evidence_refs/evidence_verification_status/blocked_reason/dependencies/owner，`introspection/task_store.py:86-101`）；Claim（token/holder/ttl，`task_claim.py`，经 tools_task.py:379-543 写入）。**无需新建 schema**。
- 模型可读工具（均已注册，factory.py:2424-2435/1600）：`get_goal`（最近 3 条 checkpoint 仅 ts+what[:80]，tools_goal.py:533-535）、`task_frontier`（blocked reason[:50]、无标题/acceptance，task_store.py:757-805）、`coordination_status`（workspace 级聚合）、`task_state`（session 账本）。写侧 `_require_active_goal` 严格（tools_task.py:160-187）。

### 2.2 真实盲区（按影响排序，均为已核代码事实）

1. **单任务明细无读取工具**：`TaskStore.get` 存在（task_store.py:294-297）但无工具包装；acceptance/done_when/evidence_refs 全量、blocked_reason>50 字符、claim 持有者不可按需读取。
2. **checkpoint 四要素无常规读取入口**：evidence/path/next 仅出现在 overflow wire（最新 1 条）与 cognitive/state.py:342-373（仅 what+next）。
3. **非 overflow 中断零任务投影**：provider 截断走 `_last_interrupted`+text_tail（run_finalizer.py:256-301），模型看不到 frontier/blocked/next，全靠自发调用工具。
4. **overflow wire 缺 blocked 维度**（longrun_continuity.py:72-85）。
5. **跨会话隐式不可见**：get_goal/task_frontier 默认 strict-session（tools_status.py:295-307 fail-closed），新会话需 coordination_status 或显式 goal_id。
6. 反例测试存在：test_task_active_authorization.py:108-119 断言任务 id 不出现在 wire——**现状是"零自动注入"的刻意设计**，修复方向必须是按需读取，不是注入。

### 2.3 未核项（移交）

cognitive/state.py 消费点是否进 prompt；system prompt 对续接工具调用的引导；CLAIMS_DIRNAME 细节；非 overflow 中断后模型是否"知道"要调 get_goal（推测：取决于 prompt 引导，未核）。

## 3. 域2：Execution/Side-effect（child subagent_6034cdb58586）

### 3.1 状态机事实（已核）

- **journal 是唯一完整生命周期 WAL**：declared→started→finished→receipt_committed（tool_execution_journal.py:337-820）；恢复三分支（recover，journal.py:849-1017）：started 无 finished→`started_outcome_unknown`（error 回执+effect_snapshot，`causation_proven` 恒 False）／finished sidecar 丢→`finished_result_unavailable`／仅 declared→`declared_not_started`；**auto_reexecuted 恒 false，永不自动重执行**；主 loop 与子代理 runner 均接线（events.py:1122-1203、subagent/runner.py:473）。
- **registry/gate 非第二状态机**：SideEffectRegistry（side_effects.py:60）是外部副作用观测面（flock+tempfile 原子写，登记失败 fail-open 返回 None，:233-235）；realtime gate 的 ReconcileOutcome/UnresolvedReconciler **未接线**（src 内 0 引用，仅单测）。

### 3.2 覆盖矩阵（45 工具，抽样方法见证据原文）

- journal 全覆盖（loop 统一包裹，tool_cycle.py:341/383）✅；字节级 effect WAL 仅 edit_file（file_replace）；超时围栏（revoke 后提交 fail-closed）覆盖 execute_command/dsh_task/browser 两族 ✅。
- **副作用登记仅 3 处**：process_bg（execute_command.py:921-928，revocable=True）、dsh_bg（dsh_task.py:311-318，True）、browser_mutation（browser_semantic_operation.py:1489-1496，False）。
- **断层**：browser_action（底层原语）无登记，其语义封装登记 browser_mutation——engine.py:342-371 的"未结算非可撤销副作用禁止打断"门对 browser_action 路径失明。
- `side_effect_kind` 类属性 opt-in 机制**仅存在于 docstring**（side_effects.py:13，全 src 无工具声明，父侧复核 ✓）。
- 未发现非幂等被误标可重试（peer non_idempotent⇒supervised_only；journal 永不重执行；browser unknown 走 mismatch 拒绝）。
- 深读 4/45 工具源码+局部 2，其余 39 为清单+grep 级（子代理已如实标注）。

## 4. 域3：Prompt/Knowledge/Eval（child subagent_1d3fbd232ac3）

### 4.1 已核机制

- 常驻 prompt = `_SOUL_BLOCK`+契约段+installation_briefing（`core/prompt.py:build_system_prompt`，extra 显式 del）；briefing ≤4,000 字符（截断可见标记，runtime/briefing.py:399-400）：规则索引 ≤40、方法名索引 ≤8、skills ≤12、知识结算概况（TTL 7 天）。规模 ~1.0-5.0K 字符为**估算**。
- provider 请求证据：指纹级（LLM_PAYLOAD_TRACE=1 → payload_trace.jsonl，sha256 分段指纹），代码诚实标注"not a claim about HTTP bytes"（client.py:803-809）。
- Method/Experience 五环节全在：discovery（search.py:304/932，短卡 projection_complete:False+task_applicability:not_evaluated）、exact hydration（method: 前缀，search.py:941-957）、version_scope 双口径（store.py:1575-1588）、content_hash（store.py:652）、use ledger（record_use+use_ledger.py 幂等 dedupe，"只落账不证明收益"）。heldout 读侧过滤防题面回流。
- **eval 缺口**：run_eval.py **无 seed/temperature 控制、无噪声地板臂、无 B′ 重复臂**（父侧 grep 复核 ✓，全文零命中）；wilson_ci"CI 重叠即不显著"是既有纪律；cache guardrail 在运行时（cache_guard/guard.py）不在 eval 脚本内。

### 4.2 历史声称 vs 已核（显式分离）

已核=file:symbol 机制与测试锁定行为；历史声称=「96%→2% 前缀断点归因」（ingress_resolution.py:225 注释）、「深读率 10.5%/53%」（store.py:408）、deepseek_cache_probe 三实验（合成 payload）、evals/*/results/* 登记数字。**全部未在本轮复测**。

## 5. 父代理交叉核对记录（不照抄子代理自报）

| # | 承重结论 | 核对方法 | 结果 |
|---|---|---|---|
| X1 | 无 task_get 工具 | grep task_get src/ 零命中 | ✓ |
| X2 | get_goal checkpoint 仅 what[:80] | sed tools_goal.py:525-540 | ✓ |
| X3 | side_effect_kind 0 声明 | grep 全 src，仅 side_effects.py:13 docstring | ✓ |
| X4 | register 恰 3 处硬编码 | grep builtin/*.py | ✓（execute_command:921/dsh_task:311/browser_semantic_operation:1489） |
| X5 | run_eval 无 seed/temperature | grep -i 零命中 | ✓ |
| X6 | browser_action 无登记 | grep browser_action.py 零命中 | ✓ |

## 6. 并行协调复盘（实测与局限）

### 6.1 指标

| child | 域 | rounds/tools | tokens_in/out | 终态 |
|---|---|---|---|---|
| subagent_84861f7d8059 | Goal/Task | 34/61 | 2,014,896 / 11,885 | completed ~23:29 |
| subagent_6034cdb58586 | Execution | 9/36 | 240,658 / 16,803 | completed ~23:29 |
| subagent_1d3fbd232ac3 | Prompt/Eval | 38/67 | 1,252,704 / 11,125 | completed ~23:29 |

- spawn ~23:23:47（三回执 23:24:13-14）→ 全部终态 ≤23:29:18；**墙钟 ≤5.5 分钟**，三 child 均在 60 轮预算内（余量 26/51/22）。
- 父侧等待期间完成：RULE-AI-24 水合、基线来源存在性核验、旧报告结论提取、交叉核对锚点采集、R9 命令确认——**父侧无空转**。
- **无同口径串行对照，不声称 speedup**（委派要求）。
- 重复/冲突：三域零重叠冲突；域1/域3在工具注册面轻度交叠但视角不同（读触发条件 vs prompt 注入），无矛盾结论。
- 终态/证据格式问题：三份回执均被截断（result_truncated），需父侧 read_evidence 补全——**子代理最终答复超长是普遍现象，下轮任务书应把报告压到 2,500 字内或要求分节**。

### 6.2 适用性结论（下次优化）

- **适合并行**：互不依赖的只读分域审计；父侧交叉核对锚点采集。本轮 3 域切分按模块边界（introspection/core-loop/工具面），冲突面为零。
- **必须串行**：M1 修复实现（单点）；冻结候选后的独立审查（依赖候选定稿）；最终测试/集成（父代理独占）。
- 协调成本实测：父侧轮询 3 次×30s×3 child ≈90s 纯等待 + 报告补全 3 次 read_evidence；子代理上下文累积成本高（tokens_in 为逐轮累计重发，34 轮即 2M）——**下轮应明确"每读一个文件即提炼、不全文驻留"的纪律**。
- tokens 统计口径说明：tokens_in 为运行时累计值（含逐轮上下文重发），非增量；记录为 unavailable 的项：无（本表全量来自工具回执）。

## 7. M1 裁决：选「单任务明细无按需读取出口」（域1-缺口1）

**裁决依据**（对照委派红线）：

1. **M0 证实的真实缺陷**：acceptance/done_when/evidence_refs 全量、blocked_reason>50 字符经任何既有工具不可达（X1-X2 复核）；这正是 v2 设计核心假设「状态已持久化但模型看不到」的精确实证。
2. **最小纵向修复**：新增 `task_get` 只读工具包装既有 `TaskStore.get`（task_store.py:294-297），复用 task_frontier 同款 strict-session/goal_id 解析；零注入（不触碰 wire/常驻 prompt，符合 P1-3/Q2/Q5 与 test_task_active_authorization 的零注入反例）；无 schema 变更、无新状态机、无分类器。
3. **收益面**：长任务中断续接时模型可按需取回任务验收标准/证据/阻塞原因全文——续接盲区的最高频场景；简单任务零成本（不调用即零开销）。
4. **拒绝的替代**：
   - 域2 副作用登记扩展：行为面变更（revocable=False 会触发禁止打断门），需逐工具风险分析，非"一个问题族"；登记为后续候选。
   - 域3 eval seed/B′：无已承诺的 A/B 实验，先建基础设施属投机；登记为**任何未来 A/B 的前置硬条件**。
   - checkpoint 四要素读取（域1-缺口2）：另一读出面，频率低于任务明细；后续可搭车。
   - overflow wire blocked 维度（域1-缺口4）：触碰 wire 投影（缓存敏感）， defer。

**M1 验收（预注册）**：① 红测先行——存在工具能取回 200 字符 blocked_reason 全文（修复前红）；② 正测——task_get 返回 acceptance/done_when/evidence_refs+verification/blocked_reason 全文、strict-session 默认、显式 goal_id 可跨会话；③ 反例测试——不自动注入（wire 无新增任务内容）、无写参数、未知 task_id 确定性报错、既有工具回执字节不变；④ 目标测试全绿 + 独立 GLM-5.3 Reviewer 对冻结候选真实 PASS。

## 8. 未核项移交清单（供后续批次）

- 域1：cognitive/state 消费点、prompt 对续接工具的引导、claims 读面。
- 域2：39 个 grep 级工具的源码级核实；UnresolvedReconciler 接线决策；registry WAL 化。
- 域3：实际部署 briefing 字节数（LLM_PAYLOAD_TRACE 实测）、semantic RRF 召回质量、修订链 version_scope 实测行为。
- 任何 A/B 实验：先补 seed/temperature/B′ 噪声地板（本审计登记为硬前置）。

## 9. M1 实施记录（task_get，2026-11-12）

**冻结候选（未提交）**：

| 文件 | 状态 | SHA256 |
|---|---|---|
| src/llm_loop/introspection/tools_task.py | M（+98/-2） | `3a2aa27269c3cfcdc749133d211762f3d45a9f87a743e02667ee6b8e5df39594` |
| src/llm_loop/introspection/registry_task.py | M（+6/-2） | `03d5097b5bfa4d85c33f6aac34d16a8ced642081ad7c3b1b21adc83ecc7b8aca` |
| tests/unit/test_task_get_tool.py | 新增 168 行 | `d77650f474af71c2275e1ca50c69ad09a923521fe1c8baf7dcea4de1cb286da0` |

diff 合计 102 insertions / 2 deletions（2 行为 docstring 同步）。无其他文件触碰（git status 核对）。

**实现要点**：TASK_GET_TOOL_DEF（schema 仅 goal_id 可选 + task_id 必填，无写参数）；run_task_get 复用 frontier 同款 goal 解析（current/active 别名→bound_session_id→strict_session=True，GoalStoreCorruptionError 容错一致）；TaskStore.get 只读包装；全文渲染 acceptance/done_when/blocked_reason/evidence_refs+verification/依赖/owner/期限/acceptance_revised/premise_stale；注册经既有 _REGISTRIES 通道（corrections.py 无改动）。

**测试证据（真实命令与 exit code）**：
- `PYTHONPATH=$ROOT/src $ROOT/../../.venv/bin/python -m pytest tests/unit/test_task_get_tool.py tests/unit/test_task_cross_goal_dependency.py tests/unit/test_task_active_authorization.py tests/unit/test_task_store.py -q` → **42 passed, exit 0**
- 扩面 `-k "introspection or goal or task or frontier or registry or correction"` → **999 passed, 8 skipped, 0 failed, exit 0**（56.20s）
- `ruff check` 三文件 → All checks passed, exit 0
- 一次红→绿迭代记录：首版 test_evidence_and_flags_rendered 用 done+evidence_refs 触发存储层 evidence 校验（TaskStore.update 仅 done 态强制 verify，无 verifier 报错）——改为 in_progress 附加 refs（verification=not_checked 如实渲染），符合"测试反映真实语义"而非绕过。

**预注册验收对照**：①盲区闭合测试（全文可达+frontier 截断行为不变对照）✓；②正测三件（全文/strict-session/显式 goal_id）✓；③反例四件（无写参数/未知 id 确定性失败/零副作用幂等/注册分派）✓；④独立审查与全量 R9 由父代理门禁执行（本代理不自行合并/推送/重启）。

**独立审查（已闭合）**：GLM-5.3 Reviewer（child `subagent_4661f51f5357`，只读白名单，rounds=6/tools=21/tokens 182,135 in+13,497 out，~23:40-23:47）对冻结候选完成七维审查——**verdict: PASS，P0=0，P1=0，P2=4**。

- 七维全过：正确性（与 frontier 解析逐行同构）/只读边界（无写路径，schema 无写参）/安全语义（strict-session fail-closed 与显式 goal_id 既有语义一致，非新后门）/零注入（全 worktree 42 命中仅注册+测试+文档+陈旧缓存，无 wire/prompt/engine 路径）/防退化（frontier 50 字符截断与 test_task_active_authorization 零注入断言原样成立）/测试充分性（预注册项全覆盖）/工程质量（ToolResult 契约与错误确定性一致）。
- P2（非阻断，移交后续）：①测试计数口径应为 9 个（非 10，预注册项无遗漏）；②零副作用断言未覆盖 TaskStore 既有锁文件机制（首读可能建空 .lock，属既有行为非本次引入）；③新文件未自带 wire 零注入断言（依赖既有全局反例+grep，frontier 侧有 current 别名专属测试可仿）；④evidence_verified_at/evidence_refs_digest 未渲染（预注册未要求）。
- 漂移核验：审查后父代理 shasum 复核三候选文件，与审查对象字节一致（零漂移）；审查员"基线=仓库根 checkout"的保留项由父代理 git diff（对 worktree HEAD 0e933d6d8）闭合。
