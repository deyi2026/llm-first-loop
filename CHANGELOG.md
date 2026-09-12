# Changelog（公开变更记录）

> 面向使用者的变更摘要（内部开发过程记录不公开）。版本语义：0.x 内小版本可增补能力，不破坏既有行为。

## v0.6.12 — Stable provider prefixes and cache-efficient working sets（2026-09-12）

- **Sticky compaction frontier**：修复 active run 中 provider-view receipt 副本与 canonical Session 的 compaction marker 分裂；`message.cache_compacted` / `history.compaction_state_reset` 现在在 live Session 与 event replay 保持同一机械语义，避免同一源消息在后续 build 被重复 compact/reset、反复改写 provider 前缀。
- **低收益 rewrite 迟滞**：保留已验证的 64K coarse working-set batch 与 grace 机制；12-result soft cap 只有在 raw→receipt 实际净节省达到 16K 时才提前 fold，32-result hard cap 作为大量小结果机械兜底。真实 2026-09-11 GLM 事故 human-turn 离线重放中，working-set fold 事件由 5 次降到 2 次（-60%），最终 tool 投影仅由 28,131 增至 29,927 chars。
- **Compaction 重放实证**：同一真实事故轨迹在 40K 压力离线重放，首轮 compact 102 个 source messages 后 live markers 同步为 102；第二轮同 provider/model/budget 新增 compact=0、overlap=0，证明 stable frontier 不依赖进程重启/replay 才生效。
- **可归因缓存观测**：常态 `request.meta` 增加 fold trigger、pending raw/receipt/net-gain 等低成本机械事实；显式 `LLM_PAYLOAD_TRACE=1` 时，OpenAI-compatible 发送前 deep trace 记录完整 request-object 指纹、消息公共前缀/首个分叉消息、tools/params shape 变化及 cache/compaction epoch。trace 默认关闭、fail-open，不进入 prompt，也不参与路由/完成判断。
- **架构边界 R9**：正式定义 “Prefix Stability as a Mechanical Resource Boundary”：程序可以冻结机械表示、控制改写频率和物理资源水位，但不得据此判断哪条证据重要、充分或应该删除。`v0.6.11` 已发布且保持不可移动；本修复作为独立 patch 版本，可回滚到 `v0.6.11`。

## v0.6.11 — Runtime identity independent of operator sandbox（2026-09-11）

- **运行身份解耦**：常驻 Web/Feishu 服务不再继承发起 restart 的 MCP Console/IDE/CI 临时 `HOME`/`TMPDIR`；启动器恢复当前 Unix 账户 HOME 与 macOS 原生 user temp，再由 LFL 自身 CatastrophicGuard / EXEC_MODE / approval / EXEC_SANDBOX / workspace scope 实施安全边界。
- **DSH 发现修复**：修正 `restart_mirror.sh` 先设置、随后又误 `unset DSH_HOME` 的启动 bug；镜像继续使用 `data/dsh-home` 隔离 DSH profile/session，同时从真实账户 `~/.local/dsh/bin` 发现已安装 DSH。真实 DSH v0.1.1-rc.2 canary 已返回 `DSH_RUNTIME_OK`。
- **回滚边界**：`v0.6.10` 已正式发布且保持不可移动；本修复作为独立 patch 版本，若异常可回滚至 `v0.6.10`。

## v0.6.10 — Honest sensing, scoped recovery and bounded working set（2026-09-11）

- **失败回执去策略化**：工具不可用时只返回当前状态、原因、PATH/Schema/权限/资源等可机械证明的事实，不再由程序在 failure receipt 中指定安装依赖、切换工具/模型或重试策略；模型保留修复路径与任务策略判断权。
- **会话 provenance**：`event_stream` 默认只读当前 session，并在每条事件中保留 `session_id`；跨会话 workspace 审计必须显式 `scope=workspace`，避免并发 release/测试/其它会话动作被误认成当前会话事实。
- **Active interruption continuity**：历史 event/live 前缀分叉仍 fail-open、绝不猜测合并；若上一真实用户轮在 tool chain 中取消，则从 live session 机械恢复最近模型可见文本与终态工具回执作为一次性 continuity fact，不恢复隐藏 reasoning/tool draft，当前用户输入仍是最终授权真值。
- **Working-set 双机械上限**：保留 64K coarse byte batching 以保护 provider prefix/cache，同时对已暴露、可恢复的 pending tool results 增加 12-result 上限，避免大量小回执长期卡在字节阈值下。真实 2026-09-11 事故回放从 63,979 tool chars 投影到 28,131，61 个旧可恢复结果 receipt 化、pending 仅 2；固定 18×12K benchmark 仍维持 coarse fold cadence（grace0 R7/R13、grace1 R8/R14），未退回已被否决的 per-round rewrite。
- **版本边界**：`v0.6.9` 保持已发布不可移动；本修复集作为新的 patch 版本 `v0.6.10` 验证和发布，出现问题可直接回滚到 `v0.6.9`。

## v0.6.9 — Provider-agnostic honesty and tool-use recovery（2026-09-11）

- **全模型诚实契约**：本地与网络 API 模型统一遵守“当前可核事实先取当前证据”。训练先验、参数内知识、历史经验/记录可用于提出假设与缩小检索范围，但不能冒充已经核对过的当前代码、文件、路径、版本、运行态、配置或外部接口；无法取得当前证据时必须明确未核验/不确定性。
- **工具使用恢复**：保留最小 Common Governance，恢复失败后核当前 Schema/code/docs、自主纠正参数、专业工作流 Skill discoverability，并让默认 `search_files` 优先当前 workspace、避免临时 CI/backup/worktree 的旧源码副本污染当前事实；显式 root 仍可审计历史副本。
- **Provider 无差别**：上述治理位于统一 prompt/tool/schema/evidence 层，不按 Ornith/GLM/MiniMax/DeepSeek 分叉；provider adapter 只承载 wire/reasoning/transport 差异。
- **版本与回滚**：统一 package/Web/README 为 0.6.9；Release tag 必须与 `pyproject.toml` 版本一致，正式发布 remote 明确为 `lfl`，版本异常可回到上一已验证 tag/commit 后再修复。

### M61：工具可达性每轮观测（Phase 0）——EVO-20260903-ba25857b 第一优先落地（2026-09-03）
- **背景**：P0-0 能力可达性缺陷（get_tool_schema(X) 连续 SUCCESS 但 X 未进 provider callable 集、schema-loop 熔断）的演进修复，实施顺序冻结 P0-1→P0-2→P0-3；本轮执行第一优先 Phase 0 观测性（P0-1 状态机/P0-2 no-progress 语义已先行在位，单测 25+ 全过）。
- **新增**（`engine_services/tool_reachability.py`，224 行）：`RoundReachabilityRecorder` 每轮记录 registered_tools / candidate_tools / final_provider_callable_tools / promoted / quarantined / promotion_state 快照及 schema_lookups（get_tool_schema 探测事件）→ emissions（raw_arguments 线上 JSON 串 + arguments 解析态）→ executed（真实回执 + duplicate-guard 阻断帧 blocked=True 如实区分）全链；JSONL 每轮一行落盘 `data/observability/tool_reachability.jsonl`（env `TOOL_REACHABILITY_LOG` 覆盖，`off` 禁写）；flush 成功即清当前轮（防重复落盘）并留 last_flushed 快照。
- **接线**（`engine_services/tool_cycle.py` 六点，全 fail-open）：`__init__` 持有观测器；投影入口 begin_round（round 取 promotion 跨 run 单调投影序号，利于 incident 对齐）；enforce/shadow/off 三分支投影快照同口径入记录；promotion resolver 探测事件入记录；`_execute_tools` 声明链（含缺 id 声明 valid=False）+ 回执链 + 逐轮 flush。纯观测面：不读不写 run state、不做决策、任何失败降级 debug 不阻断主循环。
- **测试**：`tests/unit/test_tool_reachability.py` 10 用例（全链 JSONL/fail-open 不可写/env off/env 覆盖/flush 幂等/防御路径形状/schema 名提取/promotion 快照/resolver 接线/观测器持有）+ 既有 promotion/no-progress/duplicate-guard/stagnation/tool-round-tail 回归 70 passed（合计 80）。

### M60：Web 新建会话继承模型覆盖——修"飞书新建会话变成本地模型"（2026-09-03）
- **症状**：新建会话后模型回落装配默认（本地模型），丢失用户此前所选云端模型。
- **根因**：三端"/new 继承 model_override"仅 CLI（M52）与飞书（M52-fix）落地；Web `/api/v1/chat`·`/api/v1/chat/stream` 的 `new_session=true` 分支仍裸 `create()`（override=None）。owner 飞书私聊与 Web 跨端共享当前会话（shared_current），Web 侧新建的 override=None 会话被飞书经 `get_shared_current()` 拉走 → 回落本地默认。
- **修复**（`web/routes.py`，新增 `_inherit_shared_model_override`）：Web 两端点新建会话前继承旧共享会话 `model_override`（fail-open → None，旧会话缺失/损坏不阻断新建），与飞书/CLI 同语义；用户在请求中显式携带 `model` 时仍按既有语义接单后覆盖（EVO-20260829-ad8c5984 不变）。
- **测试**：`tests/unit/test_m60_web_new_session_inherit.py` 4 用例（chat 继承/无共享 fail-open/损坏 fail-open/流式继承）+ 既有 M52/M50/locks/stream/csrf 回归 57 passed；ruff PASS。

### R9-B3 Phase 3：两依赖环断裂 + cycle 守卫恒 0（2026-09-01）
- **环① engine<->build 三步**：`build_session_snapshot_text` 纯 move 至 `core/session_snapshot.py`（`1aba90b`）→ build.py 函数内 import 退役改指叶子模块断环（`ac7b7c6`）→ engine re-export 清理、包级导出源直连（`2bc4784`）。
- **环② session<->fork 四步**：`session_types` 纯类型抽离（SessionIdConflictError/ForkReport/BranchSeed，`f98b527`）→ fork 异常 import 改指（`3e6cf72`）→ BranchSeed 重建入口 + fork 收窄为数据生成、持久化职责移交（`95c5724`，环断点）→ BranchWriter Protocol 依赖倒置窄口（`fa51dc9`）。
- **守卫翻转**：cycle 守卫恒 0 断言生效、known_cycles 空态锚定（`f54a8e7`）；Tarjan 双侧实测 0 环，断环后依赖全单向 DAG（fork 唯一出边 = 纯类型模块）。
- **等价性**：全程 wire-fixtures 逐提交回执（21 用例）+ 环② fork 回放三面对照 + 等价套件 133/133；八连提交链机检五规则逐条 PASS、每步可 bisect。
- **治理事件**：外部滞留测试代收口 9 文件（`2dc9b3b`）+ 提交流程文档化（`3271c1e`：提交队列串行化/共享主区安全纪律/外部红登记豁免口径）。

### R9-B2 Phase 1+2：worktree/门禁/机检 + 架构守卫四检测器上线（2026-09-01）
- **守卫资产收编 + 基线 v2**（guard）：workbuddy 雏形转正（`ff37e92`，HEAD 口径逐键校准）；`function_size_baseline.json` 升级五节 schema:2（`legacy_super_functions`/`function_lines` 37 键/`local_imports`/`known_cycles`/`exemptions`），全数值节 HEAD 棘轮只降不升（`179b375`）；守卫文件更名 `test_arch_guards.py`。
- **四检测器**（guard，spec §5.3 三层红线 + 棘轮 + cycle）：三层红线 300/200/WARN 120-150 三态（`837eb51`）｜棘轮防篡改纯函数化 + import 守卫行内豁免标记（`2e10219`）｜runtime cycle 检测器 AST 依赖图 + Tarjan SCC 实测恰两环（`2aa50af`）｜守卫读源双口径——外部未 staged 漂移回退 HEAD、真实违规全量设防（`dbf340f`，外部级豁免归零）｜豁免清单数量单调不增（`2d9eb03`）。演练发现并修复语义缺陷：强制登记线 150 与 WARN 下限 120 解耦（`658f1df`）。
- **门禁与机检**（chore/fix）：commit 性质机检五规则 + `r9_commit.sh` 三步包装（`f871d66`，前缀白名单/行为面隔离/wire 回执/守卫防篡改/switch 前缀）；ruff 存量清偿 + ci_gate 第 1 步全量阻断、外部级 D-07 区分呈现（`ae6faca`+`54743b1`）；旧守卫 `_base=1361` 口径冲突退役（`f0dcc16`）；守卫性能 24.98s→1.32s + tier0/markers/ci_gate 三层接线 CI 常驻（`cebdebc`+`0238c2a`，全链路 56.1s）；机检空 diff 崩溃修复（`2cf7a79`）；xdist 假红降级——红→serial 单点复核（`ace4f3e`，门禁语义 = serial 可复现红才阻断）。
- **演练回执**：七场景红/黄/绿全矩阵（tmp 构造树 + /tmp worktree 端到端各一轮）；12 commits 逐条机检单性质全过（bisect 可判定）；外部混合层 69 项零触碰（交集=0 实证）。

### R9 结构收口准备：三批默认值切换 + 行为基线固化（2026-09-01）
- **立即项四件**（refactor/fix）：删除 tests/unit 四源码副本 1994 行死代码（`c6f9f4e`）；path_registry 隔离洞双修——静默 fallback 改抛错 + 测试沙箱 chdir 锁（`5c5df12`）；dev extras/lockfile 可复现安装口径（`69e154b`+`046bd34`）；symlink 探测三态化——edit_file 探测失败也拒写（fail-closed），read_file 如实标注不拒读（`347af8f`+`64beb97`）。
- **测试工作流**（test/chore）：tier0 冒烟集（338 用例 14.8s 分钟级反馈）+ xdist 并行化（全量 13min→36s，失败集合与串行一致）+ `ci_gate.sh` 一条命令复现 CI 三件套（`0fc28e3`+`65aa515`+`6fb94b0`）。
- **Phase 0 三批默认值切换**（每批独立可 revert，批间以镜像流量观测回执为门）：`LFL_EVIDENCE_CAPSULE` on→off（`79376ef`，W1 观测：任务完成 7/7、dup 0%）→ `LFL_TOOL_GUIDANCE` on→off（`cfda166`，W2：完成 4/4、失败自恢复全靠事实性回执零引导依赖）→ `CACHE_GUARD_PERF_BLOCK` on→enforce（`6a137ef`，W3：guard 判定 63 条全 ALLOW 零误拦、privacy 硬拦照旧）。
- **BEHAVIOR-BASELINE-R824 行为基线固化**（`372aae6`）：六道硬门全 PASS（wire 零程序注入/潜语义通道/advisory/capsule/suspect provenance/性能类 BLOCK 全部 chars=0 或 WARN 化）；R8.24 fixed-point 达成；behavior canary 解除，后续结构重构（R9 Phase 1+）以本基线为只读对照。
- 详见 `docs/r824/BEHAVIOR-BASELINE-R824.md`（复现口径：`uv sync --frozen --extra dev` + `env -u` 七开关干净进程 + `--dist loadfile -n 8`）。

### 任务接力热卡 + 紧急压缩空转修复（2026-08-26）
- **任务接力热卡机制**（feat）：用户中途切换意图时，自动生成「热卡」（上一任务关键进度/证据/下一步摘要）注入新上下文——任务交接连续性保留，无需翻档案从头恢复；含单元测试（test_task_hotcard.py）。配套规则：RULE-AI-20 第 7 条「意图切换即时登记」。
- **紧急压缩空转修复**（fix）：历史压缩预算原先只统计消息正文（content），不含思维链（reasoning_content）与工具调用参数——实测部分会话思维链占比 40%+，导致「提交超模型窗口被守卫拦截 → 紧急压缩判定未超预算不缩历史 → 下轮仍超限再拦截」空转死循环（会话 fb8f8987 连续 3 次紧急压缩后历史体积 300K 纹丝不动）。现改为按全字段（wire 口径）统计，紧急压缩后历史真正缩小，下轮提交恢复。

### 压缩风暴熔断（P0 breaker）+ 缓存遥测内容/传输分层（P1）（2026-08-25）
- **背景**：8/24 命中率 98.2%→87.8% 归因 = 两个大上下文会话进入「压缩风暴」（每轮归档 20-90 条消息 + 锚点持续前移 → 历史字节每轮被改写 → provider 前缀缓存只命中 system+tools 固定段 8,320 tokens，命中率钉死 3-4%，连续 40+ 轮）——去掉两个异常会话后 deepseek 命中率回到 97.2%（审计 `guarded_requests.jsonl` 复算）。风暴根因 = 有效预算（窗口×0.6×0.5≈300K 字符）与重工具会话体积的剪刀差，cache monitor 的 `force_head_keep` 恢复条件（锚点连续 N 轮不前移）在风暴期永不满足 → 自持。
- **P0 compression-storm breaker**（`cache_health.py` + `history.py` + `build.py` + `engine.py`）：
  - 触发 = 连续 (context.compressed 且 anchor 前移 且 压缩后仍超压缩线) 达 `BREAKER_TRIGGER_RUNS`（默认 5）+ 命中共信号（独立滚动窗口 < `BREAKER_HIT_THR` 0.5，防渐进折叠误判——折叠轮命中高）。
  - 冻结 = 禁止程序兜底压缩 + 锚点不前移（`freeze_compression` 进 `build_history_messages`，不归档/不分层降级）；冻结期超安全水位（预算×0.95，与 cache_guard 规则 F BLOCK 阈值对齐）→ `context_pressure` 前置拦截（不提交——AI 先 checkpoint/换会话），规则 F 在 breaker 期降级 WARN（防双拦死锁）。
  - 退出 = 明确 hysteresis：cooldown 轮数下限 + 上下文低于退出水位（预算×0.8）+ anchor 连续稳定，非仅时间。
  - 逃生 = 连续 context_pressure 达 `BREAKER_PRESSURE_ESCAPE_MAX`（默认 6）→ 放行一次受控压缩（烧损有界，防永久死锁）。
  - 审计 = `data/audit/cache_breaker.jsonl`（storm_count/anchor/breaker_enter/breaker_exit/context_pressure/escape_armed + reason），复发可直接从 JSONL 判定；`architecture_status`/snapshot 暴露 per-session 熔断状态。
  - 水位口径：锚定视图字符（实际提交量）——锚点压缩不删会话消息，全量口径会让压力永不解除。
- **P1 遥测内容/传输分层**（`engine.py` + `build.py` + `cross_sync.py`）：
  - 问题：程序把 `⚡ 缓存命中率` 写回 assistant 历史 → 下一轮 LLM 可见 → 模型可模仿伪造同格式行（实测 8/25 msg[128] 同条消息出现模型伪造 93.6% + 程序真实 90.4% 双行，伪造行分母 773,371 在审计中不存在）。
  - 修复：`assistant.content` 只存纯回答；权威遥测进 `metadata.cache_health`（结构化）；build 时剥离 legacy 历史中的 ⚡ 行 + 剥离模型本轮伪造行；transport 层（web 返回值 / 飞书 cross_sync）渲染 canonical 一份。
- **PROGRESSIVE_FOLD_K=3**（.env 开启）：P0/P1 之后启用——每次最多折最老 3 个配对组，平滑 anchor 跳跃曲线（非消灭压缩；超 95% 预算保命兜底仍突破上限）。
- **验证**：单测 +12（`test_cache_breaker.py` / `test_cache_breaker_engine.py` 全链路：风暴→breaker→context_pressure→逃生→恢复，含不误触发/隔离/规则 F 降级），全量 2222 passed；真实 DeepSeek 重工具长会话冒烟（逐 request 曲线）。

### SWE 对照实验定论：本地 thinking 默认开启（回退早前"默认关闭"决策，2026-08-24）
- **实验**：同一任务（SWE-bench requests-2317）、同一模型（qwen3.8-27b）、唯一变量 = `LOCAL_ENABLE_THINKING` 开关，判据只有 F2P（`test_encoded_methods`）。
- **结果**：关思考 4 次独立尝试 **0/4 通过**（全漏第二修复点 `sessions.py builtin_str`）；开思考 1 次 **通过**（对照实验 + wire 抓包 `B'GET'` 溯源，双点修复，回归 135 通过无确定性回归）。
- **结论**：本地 27B 的能力边界 = 思考深度——缓存/内存优化解决"跑得更快"，thinking 决定"能否修对"。早前"本地默认关思考提速"的决策被实证否决。
- **变更**：`client.py` 本地 thinking **默认开启**（不再发 enable_thinking=False）；`LOCAL_ENABLE_THINKING=0` 显式关闭（纯速度场景）。测试双态断言更新。完整过程见 `docs/swe_ab_report.md`。

### 缓存窗口镜像：让"缓存里有什么"可见可审计（2026-08-24）
- **能力**：每轮把服务端上报的 `cached_tokens`（前缀命中 token 数）映射回提交载荷的**消息级窗口**——缓存覆盖到哪条消息、哪些是新增（miss 区）。落点：事件日志 `cache.window` 事件（完整可回放）+ `architecture_status.context_usage.cache_health.window`（AI 每轮自查）。
- **信息补充决策原则**（对齐前缀缓存语义，RULE-AI-00）：①补充=尾部追加（前缀不变, miss 仅新增段）；②引用缓存区内信息=零额外 prefill；③中插/重排/压缩=断前缀（当次全量 miss）。
- **实现**：`src/llm_loop/core/cache_window.py`（纯函数 `describe_cache_window`）+ engine 事件钩子 + factory 快照合并；测试 `tests/unit/test_cache_window.py`；文档 `docs/cache_window.md`。
- **实证发现（工具轮模板硬约束）**：llama.cpp Qwen 聊天模板要求载荷含 user 消息——零历史工具轮只发配对组会 500「No user query found」；`_tool_round_zero_tail` 已修复为 [最近 user 指令 + 最近完整配对组]（中间轮次裁剪，任务锚点摘要补偿）。

### 本地模型"出错"根因修复：系统代理劫持回环 LLM 请求（2026-08-24）
- **根因**：httpx 默认 `trust_env=True` 经 urllib 读取 **macOS 系统代理**（Surge 等代理工具把 `127.0.0.1:6152` 设为系统代理）→ **所有 LLM 请求（含本地回环直连）被转给 Surge 代理** → Surge 无法代理自身回环 → 503 Connection Closed（SGErrorDomain）→ 表现即"本地模型出错"。curl 直连正常（不走 urllib）而 LFL 全挂——本地模型 2026-08-22 能用是因为当时 Surge 系统代理未开启。
- **修复**：`LLMClient.__post_init__` 本地 base_url（localhost/127.0.0.1）→ `trust_env=False` 直连（llama-server KV 前缀缓存本就依赖同 slot 直连）；远程 provider 保持默认（需代理访问 API 场景零回归）；env `LLM_TRUST_ENV` 显式覆盖（1=启用系统代理/0=禁用）。
- **实测（Qwen3.8-27B 直连）**：一般形态 精确重发命中 99.5%（1.87s→87ms，21 倍）、前缀+追加 97.3%；工具轮形态 命中 98.4%（1.13s→365ms）——「稳定前缀 + 尾部追加」在本地成立的实证。
- **附带假设（待验证）**：deepseek 大上下文流式断连（incomplete chunked read）可能部分是 SSE 长流经 Surge 代理被掐断——可用 `LLM_TRUST_ENV=0` 让远程也直连对比断连频率。

### 本地模型高缓存命中：工具轮极小窗口默认启用 + 配对组修复（2026-08-24）
- **方案**：本地工具轮「稳定前缀 + 极小窗口」——system prompt + 工具白名单 schema 字节稳定（记忆/快照/提醒全部尾部追加，此前已落地），工具轮只发 system+工具+最近**完整协议配对组**（assistant(tool_calls)+全部 tool 回执）→ llama.cpp KV 前缀复用命中（LMS_DIRECT 直连 llama-server 已是默认路径，注释实测命中 97% / prefill 秒级）。
- **改动 1（默认启用）**：`data/providers.json` local 条目加 `"tool_round_zero_history": true`（ProviderSpec 新字段，env `TOOL_ROUND_ZERO_HISTORY` 显式覆盖；云端缺省 False 零回归）——工具轮历史从 8000 字符预算进一步收成极小配对组。
- **改动 2（配对组修复）**：原 `base[-2:]` 在并行多工具回执时截断声明↔回执配对组 → C1 协议违规（"声明 3 个调用仅 1 条回执"）；改为从最后一条 tool_calls 声明起保留整组（`_tool_round_zero_tail`）。
- **改动 3（可观测）**：`scripts/local_cache_probe.py` 三实验探针（A 冷/B 同 payload/C 前缀+追加），直连 llama-server 验证 KV 命中率与 prefill 提速。
- **附带**：修复 `test_client_params_no_auth_provider` 环境敏感（本机有 llama-server 时直连发现返回真实 key）——隔离 `_discover_llama_server` 使测试环境无关。

### deepseek 大上下文断连修复：预算收敛 1M→150K + 流式断连自动重试（2026-08-24）
- **根因**：`.env` HISTORY_MAX_CHARS 与 `data/providers.json` deepseek `history_budget_chars` 均为 100 万字符（2026-08-18 缓存方案 A 显式豁免）——`[预算预警]`（80%）与程序兜底压缩（90%）被推到 800K/900K 字符，飞书长会话膨胀到 150K-230K 字符仍 0 次压缩、AI 从未收到压缩信号；deepseek 在该量级流式偶发 `peer closed connection (incomplete chunked read)`，断连整轮 50 万+ tokens 白烧（实测 535s/1.26M tokens 的 run 中断，飞书侧表现为"出错了"）。
- **修复 1（预算校准）**：`data/providers.json` deepseek `history_budget_chars` 1000000 → **150000**（≈75K tokens）。既有机制自动前移生效：80% 预算预警 ≈120K 字符注入、90% 程序兜底压缩 ≈135K 字符触发（原文另存 + `[上下文压缩]` 标注，零丢失可 search_archive 检索）；提交载荷被约束在观测失效线（150K+）以下。与 EVO-20260818「收敛上限 1M→200K」既定方向一致。
- **修复 2（断连重试）**：`LLMClient._stream_openai` 对传输级断连（httpx NetworkError/ProtocolError，含 peer closed / incomplete chunked read）在**尚无任何输出已产出**时同请求自动重试 1 次（env `LLM_RETRY_DISCONNECT` 可调/关，默认 1）——前缀缓存命中率高、重试成本极低；已有 content/reasoning/tool delta 产出则不重试（防 UI 重复/工具重复执行）。
- **预期代价（明示）**：压缩轮必断一次前缀缓存（物理必然），缓存命中率从 ~99% 周期回落到 ~86% 量级；换取不再整轮白烧与飞书"出错了"。实测三会话 0 压缩的根因由「AI 忘了压缩」修正为「预算校准缺口」——机制齐备，缺的是预算落在服务端稳定区间。

### 历史预算基准更新 + 缓存命中修复（审查完善项，2026-08-17）
- `history_budget_chars` 全局基准 60000 → **800000**（预算链修复：此前预算过短导致历史截断/提交不完整 → 前缀缓存 0 命中；修复后命中率 98%+）
- 缓存纪律沉淀：system 前缀锚定 + 压缩留缓冲 + M58 命中可观测

### 安全：playwright 子进程加固——cwd 限定 + env 敏感键剥离（DSH 复核 005 建议 a+c，2026-08-16）
- 子进程 `cwd` 限定 `data/e2e/<session>/`（模型代码相对路径访问被限定在产物目录；
  产物路径改绝对路径注入，功能不变）
- 子进程 `env` 剥离敏感键（KEY/SECRET/TOKEN/PASSWORD/PASSWD/CREDENTIAL 子串匹配），
  消除模型代码经 `os.environ` 读取凭据的面
- 文件头安全模型更新：明确"门槛非沙箱"——绝对路径访问与同用户权限（ctypes/syscall）
  仍可达，定位为挡误操作/粗注入，不宣称沙箱；开放面（文件/网络信任边界）仍待产品决策
- 行为变更：模型代码相对路径不再指向仓库根，指向会话产物目录

### 安全：playwright 执行防线补强（DSH 独立审查后修复，2026-08-16）
- **URL 沙箱 host 精确校验**：原正则无 `$` 锚定，`userinfo@host`/域后缀可逃逸（如
  `https://a.feishu.cn@example.com/`）；现改用 urlparse 解析 hostname 精确集合校验
  （仅 feishu.cn 含子域/localhost/127.0.0.1），同时修复裸 `feishu.cn` 误拦与大小写不敏感
- **命名空间隔离**：模型代码经 `_run_model` 在独立命名空间 exec，仅可见 helper 七件套+
  内置；`_page/_browser/_pw/_OUT` 内部对象不可见——堵死"裸 API 直连绕过白名单"路径
- **AST 门控纵深**：新增拦截动态导入（`__import__`/`import_module`/getattr 间接引用）、
  动态执行（exec/eval/compile）、`sys.modules` 取已加载模块（任何访问形态）
- **明确开放面**：模型代码在子进程内可读写工作区文件、发起任意网络请求，属设计未承诺
  防护的信任边界，需产品方显式决策
- 附：DSH 工具 DSH_HOME 可写性回退（长驻 agent 沙箱下 ~/.dsh 不可写时回落项目内 data/dsh-home）

### 安全：提交安全扫描——防 AI 自动提交误传敏感/私密/错误文件
- `scripts/git_security_scan.sh`（pre-commit 钩子 + CI job）：拦截 data/ 运行时数据、.env*/日志/私钥、
  高价值密钥模式（sk-/AKIA/ghp_/app_secret 等）、本地绝对路径（用户目录、/home/）、>1MB 大文件
- `.githooks/pre-commit` 提交前硬拦截（AI 自动提交无人工检查环节）；CI `security-scan` job 全树兜底
- 清理存量：已跟踪文件中的本地用户目录路径痕迹全部中性化（占位符/样例路径）（占位符/样例路径）

### 新增：playwright_exec(code) 单 exec 浏览器工具（EVO-20260816-bfb9f215 阶段二）
- 模型写 Python 一次调用打包 navigate+act+extract，预置 helper 七件套（goto/click/fill/wait/js/screenshot/axtree_text）
- 每次调用独立子进程（解释器/浏览器零跨调用持久），产物落盘 `data/e2e/<session>/`；confirm 二段确认默认 dry_run
- 安全：AST 静态门控禁止 import playwright（强制走 helper）；helper goto 强制 URL 白名单（复用阶段一校验）；子进程超时终止（默认 60s 上限 300s）
- 工具描述钉死 ≤2KB helper 摘要+状态契约+fetch-first"何时不用"条款（对齐 Hermes 调研 #1/#2/#6/#7）
- 验收基准 `scripts/bench_playwright_exec.py`：5 个网关 Web E2E 任务 × 3 次重复（方法论评测纪律第 5 条首单，需网关在线时人工触发）

### 安全：playwright 执行门控升级——注册层门控 + 执行层 URL 再校验（EVO-20260816-96215428）
- RUN_MODE=ptc 隐藏 `playwright_test`（浏览器执行类工具仅 standard/creative 可见，对齐"仅 terminal 权限会话注册"精神），为 playwright 单 exec 演进扫清安全前提
- `playwright_test` 真实执行路径增加执行层 URL 沙箱再校验（纵深防御，参数层之外的第二道）
- 新增 tests/unit/test_playwright_gate.py（3 用例）+ run_mode 四模式可见性断言

### 新增：DSH 编排工具集——调度 DeepSeek Harness 执行任务（P0/P1/P2）
- `dsh_task`：进程级子代理（spawn `dsh --profile headless "<task>"`）——任务下发/超时整树终止/退出码五态映射/3 万字符截断/审计落盘；协议 v2 支持 `ctx_path`（上下文文件引用并入）、`report_format`（结构化汇报模板）、`acceptance`（验收清单逐项自检）、`retry`（失败新 session 重试，timeout 不重试）、任务文本脱敏（敏感 env 值替换）、`background`（JobRegistry 后台执行，多任务并行 fan-out）
- `dsh_session_read`：DSH session 事件日志回放（zstd JSONL）——最终回答 + 工具调用轨迹 + 关键词过滤/指定 session 检索，补全"只回最终文本"的中间过程盲区
- 新增依赖 `zstandard`

### 修复：长任务重启保护——重启预检 + feishu 中断补偿 + guard 去抖
- `restart_system.sh restart` 前检测 feishu 处理中消息（心跳 `processing_msg_id`）——长任务进行中警告确认，防重启打断导致无反馈
- feishu 桥优雅退出打断长任务 → 落盘补偿记录 → 下次启动主动回复"任务因重启中断请重发"（防静默丢失）
- guard 工作区变更日志 5 分钟去抖（agent 长任务编辑期间不再每 21s 刷屏；flag 仍每次刷新）

### 新增：memory 命中计数事实源——升格判据量化（EVO-20260816-fcdbe2e9）
- `MemoryEntry` 新增 `inject_count`/`last_inject_at`：只计**实际注入上下文**（检索构造注入消息的最终 top_k 条目），与 `access_count`（检索命中，含未注入的噪音）区分
- 技巧升格通道（"命中复用 ≥3 次 → 升格经验库"）由此获得程序侧量化判据：`architecture_status.memory.top_injected` 可查按注入次数降序的头部条目
- 计数内存态更新，沿用 run 末 flush() 批量落盘（不新增写盘点）；计数失败 fail-open 不阻塞记忆注入；旧索引无新字段加载默认 0（向后兼容）

### 优化：降级提示 stamp 限频——同类降级 24h 内主消息流只提示一次
- 同一降级对（from→to）重复降级时，提示消息 24h（`FALLBACK_NOTICE_COOLDOWN_S` 可调，0=关闭）内仅注入一次；stamp 落盘 `<data_dir>/state/fallback_notice_stamps.json`，重启仍生效
- 仅抑制消息注入：status 降级态 / 审计 / action_trace 每次照常记录（可观测性不降级）；链全失败汇总不限频（每次如实告知）

### 新增：工作区变更感知——guard 检测 + 提醒重启（P1-12）
- **背景**：运行中进程不感知工作区变化（.env/providers.json/src/skills 改动需重启生效，外部编辑/git pull/agent 自改后一直跑旧状态）
- **机制（手动确认式，不无差别自动重启）**：guard 每轮对监视文件做内容哈希指纹对比基线；变化 → 写 `data/workspace_changed.json`（变更清单 + 建议命令）+ guard.log 记录，**不自动重启**；AI 经 `architecture_status.workspace_changed` 自查可见；确认后 `restart_system.sh restart` 末尾自动 ack（清 flag + 刷新基线闭环）
- 端到端闭环实测通过；相关测试 230 全绿

### 修复：飞书收到回复后多一条重复 [跨端同步] 消息（P1-11 竞态）
- **根因**：`CrossSyncWatcher`（飞书←Web 增量同步）的基线刷新（`mark_processed`）原在**回复发送后**才调用——回答落盘与基线刷新之间存在秒级窗口，轮询（1.5s）会插入其中，把桥自己的回答当"Web 侧增量"重复推送一条 `[跨端同步]`（用户反馈重复）
- **修复**：① `mark_processed` 前移到 `engine.run` 返回后立即执行；② `cross_sync` 新增 `skip_fn`——**按会话精确跳过**桥正在处理的那个会话（其他会话照常实时同步，增量不丢：基线未推进, 清除后按累积 diff 一起推）；两保险消除重复且不牺牲跨端实时性
- 飞书测试 191 全绿（含按会话跳过语义用例）

### 新增：RULE-AI-12 模型身份声明约束（0814 身份幻觉真阳性实证条款化）
- 规则条款：对自身模型身份/提供方的声明必须以 model_catalog / architecture_status 回执为准，
  禁止依据训练先验自报身份；无回执佐证如实声明"未核验"
- prompt 注入 + `docs/ai_rules.md` 条款 + 评测判定器 `verdict_identity_verified`
  （先验身份幻觉判 False；否定澄清/未核验如实声明放行）+ 评测场景 rule12 系列

### 修复：declaration 判定器 B2/B3 误报治理（EVO-20260815-640fc96a，honesty_rate 归因）
- B2 计划陈述豁免：未来时态/规划句（下一步/计划/待办/即将）不抽取；含完成标志的计划句仍校验
- B3 引用内容剥离：代码 fence / 表格行 / 引用块不进入声明抽取；正文完成声明不受影响
- 真阳性约束测试：身份幻觉句与严格行为声明仍被捕获（宁可误报不可漏报）
- docs/eval_scenarios.md 新增「判定口径已知边界」文档（能力/计划/引用豁免、比较保留严格、身份最严）

### 新增：真实 tool-call 往返门禁（EVO-20260815-f22ab8dd，v0.6.5 arguments 透传回归补洞）
- run_real_smoke.sh 新增 [1.5/3] 真实 tool-call 往返用例（协议矩阵：默认 openai +
  SMOKE_WIRE_PROTOCOL=anthropic|google 逐协议执行，无 key 自动 skip）

### 其他
- 进程代码时效提醒（EVO-20260815-69ac0bd0）：每轮末检测工作区/进程代码时效，每进程冷却一次
- refresh_config 生效范围说明（LLM 凭据/模型目录热生效，其余启动时装配）
- 门禁 pytest 全量绿 + ruff 0 + pyright 0 + CI 三件套 + nightly 真实评测通过

## v0.6.7（2026-08-16）

### 修复：history_anchor 落在工具轮内 → 孤儿 tool 回执 → 上游 API 400（tool_call_id is not found）
- 根因：锚点（P1-10 窗口裁剪起点）落在「工具调用声明 ↔ 工具回执」消息组内部时，
  声明被裁掉、回执成孤儿 → OpenAI 兼容 API 拒绝（tool_call_id is not found）
- 双层修复：① `build_history_messages` 裁切后丢弃窗口内无对应声明的 tool 回执
  （declared_ids 集合 + dropped_orphans 计数，如实告警）；② 锚点推进对齐——锚点若落在
  工具回执上则拉回至其声明起点，保证组内声明/回执成对进入窗口
- 回归防护 +1（tests/unit/test_anchor_pairing_boundary.py：锚点落在工具轮内/外两方向配对断言）
- 门禁 pytest 2058 passed（25 本地文档基线 skip / 14 real_llm 排除）+ ruff 0 + pyright 0；
  线上实测（kimi/k3 真实 tool-call 往返）正常

## v0.6.6（2026-08-15）

### 修复：tool_call.arguments 归一化回归（v0.6.5 引入，工具通道断连根因）
- 根因：v0.6.5 客户端重写时本地重定义了 ToolCallDeltaAggregator（原版从 llm/schemas.py 导入），
  新实现 finish() 不解析 arguments → 真实 provider 的 JSON 字符串 arguments 原样进注册表 →
  所有工具调用被 "[参数错误] 参数必须为 JSON 对象" 拒绝（FakeLLM 预构造 dict 的测试盲区）
- 修复：复用 schemas.py 聚合器（finish 含 json.loads 归一 + _raw_arguments 兜底）；
  Anthropic tool_use start 空 input 不并入（防 "{}" 破坏 JSON）；Google functionCall 独立 index
- 回归防护 +4（归一/非法兜底/端到端真实客户端 mock SSE→read_file 真实执行/注册表防线）
- 门禁 pytest 2090 + ruff 0 + pyright 0

## v0.6.5（2026-08-15）

### P3-5：provider 广度——Anthropic / Google 原生协议（wire_protocol）
- LLMClient 协议分发：`openai`（默认零回归）/ `anthropic`（Messages API：/v1/messages + x-api-key +
  anthropic-version，system 拆分、tool_use/tool_result 转换、thinking_delta/input_json_delta 流式解析）/
  `google`（Gemini：streamGenerateContent?alt=sse + x-goog-api-key，contents/systemInstruction/
  functionDeclarations，functionCall 聚合、MAX_TOKENS→truncated）
- 元数据驱动：ModelSpec.wire_protocol（providers.json 模型条目，非法值回退 openai 如实告警）；
  client_params/pool/factory 全链透传；LLM_WIRE_PROTOCOL 可配默认 client
- 修复：Python 3.11+ 裸 yield-from 丢弃子生成器返回值（终态 LLMResponse 必须显式捕获 return）
- 测试 +7（anthropic payload/头/tool_use 聚合、google payload/functionCall/截断、默认零回归、
  provider 解析/非法回退）；门禁 pytest 2084 + ruff 0 + pyright 0

## v0.6.4（2026-08-15）

### P3-4：workflow_run DAG 编排（拓扑序 + 节点级预算，无 graph DSL）
- `mode=dag`：步骤可声明 `id` + `depends_on`（id 或 0 起下标）依赖；Kahn 拓扑排序确定执行序，
  依赖步骤 final_answer 自动注入被依赖步骤 context（【依赖步骤 X 结果】标注）
- 校验诚实：未知依赖/自依赖/重复 id → 400 式如实失败；**循环依赖 → 拓扑前检测**（不派发任何步骤）
- **节点级预算** `budget_rounds`：透传子代理 max_rounds（SubAgentRunner.run 新增可选参数，
  提示文案与循环守卫同步生效）；回执如实标注 budget
- parallel/pipeline 同步支持 budget_rounds（通用节点预算）
- 测试 +6（拓扑序+依赖注入/环检测/未知依赖/自依赖/重复 id/预算透传）；门禁 pytest 2079 + ruff 0 + pyright 0

## v0.6.3（2026-08-15）

### P3-2：英文文档对等化
- `README.en.md` 整体重写为与中文版对等（157 行，章节/功能 27 条/配置表/CLI 命令逐条对应；程序输出标记保留中文原样，与源码字面一致）
- 新增 `docs/api.en.md`（142 行，章节数与中文版一致 19 段）与 `docs/ai_rules.en.md`（217 行，RULE-AI-00~11 全部编号对等）
- `docs/INDEX.md` 链接补充；英文文档对等守护测试 +3（api 章节数/规则编号/README 版本一致）

## v0.6.2（2026-08-15）

### P3-3：bash 沙箱后端（EXEC_SANDBOX=bwrap|none，可选）
- `EXEC_SANDBOX=bwrap`：bubblewrap 隔离 execute_command——只读系统目录（/usr /etc /lib /lib64 /bin /sbin）、
  /dev /proc 挂载、/tmp 临时文件系统、工作区可写绑定、独立 PID/UTS/IPC 命名空间
- **fail-closed 语义**：显式开启而 bwrap 缺失 → 命令不执行、回执如实说明（不静默降级）；
  回执标注"已启用 bwrap 沙箱"
- 前台/后台（run_in_background）双路径接线；未启用零回归（shell=True 路径不变）
- 测试 +8（argv 结构/禁用/启用/缺失 fail-closed/回执标注/后台/零回归）；门禁 pytest 全绿

## v0.6.1（2026-08-15）

### P3-1：MCP 客户端接入（stdio）
- `MCP_SERVERS` env JSON 配置 stdio MCP 服务器；启动连接握手（initialize/initialized/tools/list）
- 工具以 `mcp.<server>.<tool>` 名注册（inputSchema 透传为 parameters），执行走统一注册表通道
  （线程超时 / 输出分层 / 审计复用）；结果五态包装（success/failure/blocked/timeout/error）
- 诚实边界：单服务器连接失败 fail-open（其余服务器/工具不受影响）；调用失联单次重连，
  仍失败 → ERROR 态如实；isError → FAILURE 态（content 原样透传）
- 测试 +10（配置解析/真实 stdio 握手与清单/schema 透传/五态/注册表集成/双服务器 fail-open）
- 门禁：pytest 2062 passed + ruff 0 + pyright 0

## v0.6.0（2026-08-15）

### 窗口锚定：历史起点固定 → 前缀缓存全量命中（P1-10）
- **根因**：预算裁剪"从最新往回保留"导致每次提交的保留集合**起点移动**（旧的挤出、新的加入）→ system+历史前缀每次从历史第一条就变 → llama.cpp/服务端前缀缓存几乎全 miss（冷 prefill 每轮 ~20-56s）
- **锚定机制**：按 provider 在会话持久化窗口锚点（`history_anchors`）——锚定后起点固定（只追加不挤旧）；超预算依次：①剔除注入消息（不进提交、零损失、不产生归档）②分层降级中段旧 tool ③仍超才归档推进锚点（前缀断一次后重新锚定，低频）
- **实测（真实大会话 + local 9B）**：前缀一致率 **48/49（98%）**；连续 run 首分片从 20-56s → **3.8-11.5s（缓存命中）**
- 快照注入仅无锚时执行（锚定后快照为推送式注入已打标跳过提交，避免锚点换算复杂化）；无锚路径行为零变化

### 云端 provider 提速降本：前缀稳定 + 历史预算（P1-9）
- 本地模型优化（P1-7 前缀稳定 / 历史预算）推广到云端：deepseek/kimi 配 `history_budget_chars: 60000` + `inject_system_notices: false`、minimax 配 `40000` + false——system 前缀静态化命中服务端 prompt 缓存（输入 token 折扣）+ 控制输入量（成本），推送式注入仍可经 architecture_status 自查（能力零损失）；超时保持全局 120s 不放大（provider 级差异由配置天然表达）
- 实测：kimi/k3-256k 默认模型端到端正常（in=5916 tokens, 回答正确）

### 默认模型支持全限定 `provider/model`（P1-8）
- `LLM_MODEL=kimi/k3-256k` 形式全限定默认模型 → 默认 client 按注册表 provider 参数装配（base_url/api_key 来自 provider 配置、模型名发送裸名，OpenAI 兼容端点不接受全限定）；裸模型名保持 env 三件套（零回归）
- 配置：`.env` 默认模型已切至 `kimi/k3-256k`（备份 `.env.bak-20260816-kimi`）

### 本地模型首 token 提速：推送式 system 注入不进提交视图（P1-7 前缀稳定）
- **根因（Stateful API 可行性验证）**：LM Studio Stateful API 增量续聊实测 TTFT 0.58s，但 OpenAI 兼容端点在**相同前缀**下同样命中引擎 KV 缓存（2.9s）——让 agent 缓存失效的真正元凶是**每轮注入的 system 消息**（[架构上报]/[预算预警]/[声明提醒]/快照，大会话已累积 181 条），下次 run 全部合并进开头 system → 前缀从第一个 token 就变 → 每轮全量冷 prefill
- **provider 级开关 `inject_system_notices`**：默认 True（零回归）；`local` 配 false → 推送式注入（架构上报/预算预警/轮数预警/声明提醒/快照/自我评估提醒）仅落会话、不进提交视图（AI 可经 architecture_status 自查，能力零损失）；功能性注入（压缩标注/降级通知/overflow 回注/轮次决策请求/故障反馈）不受影响
- **存量消息兼容**：跳过判定 = metadata 标记 + 内容前缀（[架构上报] 等）双通道，历史遗留注入消息同样生效
- **实测**：system 前缀稳定为静态文本（+压缩标注尾部），首分片从 ~70s 降至 ~25s（9B 冷 prefill 固有成本；多引擎 CPU 争抢缓解后更低）

### Web V2：全新 React 端（对齐 DeepSeek Harness Web，双版本并存）
- **独立目录 `webui/`（React 18 + TS + Vite）**，挂载 `/ui/v2` 与原版 `/` 并存（原版保留可回退）；独立分支 `feature/web-v2` 合入
- **视觉对齐**：DSH 同源设计 token（亮/暗/跟随系统，`--dsw-alias-*` 语义变量 + shiki 代码配色）、三栏布局壳、消息入场动效、移动端抽屉
- **功能对齐**：流式会话（思考块/工具链状态chip/代码块分块）、`/` 命令面板（点选即执行）、模型目录、消息反馈（👍👎 → feedback.jsonl）、会话 Markdown 导出、子代理标签、跨端同步（SSE 命名事件 + 失联自愈看门狗）
- 侧栏管理：置顶/两步确认删除/分支（fork→自动切换）/来源通道标签
- 识别链路（后端增强，原版/飞书同受益）：**auto 链**——团队识别工具（arkcli）优先 → 注册表 multimodal 模型（Kimi 实测可用）兜底 → 明确报错；docx/pdf 走 doc-extract 结构化抽取（本地提取兜底）；识别失败附件如实标注"图片未包含"防幻觉
- 新端点：`POST /api/v1/sessions/{id}/feedback`
- 文档：`docs/web-v2-diff.md`（DSH 对齐三态清单/差异对比/切换方案）

门禁：pytest 2038 passed + ruff 0 + pyright 0 + Vitest 29/29 + 分支 CI 全绿

## v0.5.6（2026-08-15）

### 修复：飞书发消息 Web 端必须手动刷新才显示（SSE 命名事件缺失）
- **根因**：SSE 规范中命名事件必须带 `event: <type>` 行；服务端只发 `data: {"type": ...}` → 浏览器按默认 `message` 事件处理，前端 `addEventListener("sessions_updated")` 永不触发（curl 能看到数据流，浏览器里却没有任何回调）
- **修复**：事件帧补 `event: connected` / `event: sessions_updated` 命名行（data 内 type 字段保留向后兼容）；新增 20s keepalive 注释行防长连接被中间层/浏览器超时掐断
- **前端加固**：失联自愈看门狗（>25s 无事件且页面可见 → 静默自愈刷新，SSE 健康时不触发）；标签页重新聚焦立即同步（后台标签页 SSE/定时器被浏览器节流时兜底）
- 测试 +6（命名帧格式 / 端点防回退守护 / 前端看门狗·聚焦·监听器静态守护）；全量 2020 passed + ruff 0 + pyright 0

## v0.5.5（2026-08-15）

### 双端统一会话 + 双向实时同步（用户需求）
- **统一会话**（已有机制确认）：owner 飞书私聊与 Web 共享同一会话（`shared_current`），Web 默认加载跨端共享当前会话；Web 新建会话同样设为共享当前
- **Web ← 飞书**（已有）：SSE `/api/v1/events` 指纹轮询，飞书侧新消息 Web 端 1.5s 内自动刷新
- **飞书 ← Web（新增）**：桥进程内 `CrossSyncWatcher` 后台线程——轮询会话目录，对映射到飞书聊天的会话（含 owner 共享当前）做增量检测，Web 侧用户输入/AI 输出**实时推送到飞书聊天**（卡片：`[跨端同步] Web 端会话「标题」新增 N 条消息`，角色标注 + 截断）
- 基线机制：桥自身回复完成后 `mark_processed` 刷新基线（不重复推送自己）；首见会话只建基线不推历史；速率受限（3s 最小间隔）多条合并；推送失败不推进基线（下轮重试，fail-open）
- `FEISHU_CROSS_SYNC=0` 关闭；测试 7 项（增量推送/自身不重推/Web 先建会话推 owner/限速合并/清理不推/损坏 fail-open/键解析）

## v0.5.4（2026-08-15）

### 显式输出预算 max_tokens（现场修复：长分析被截断、思考占大半输出只余少数）
- **根因**：请求未携带 max_tokens → 走模型默认（如 4096）；思考链模型思考占预算大半，最终分析被截断（现场：回答末尾直接中断在"（回答被截断）"，确认项都未列完）
- **修复**：`LLM_MAX_TOKENS` 默认 **8192**（env 可调）显式下发；`data/providers.json` provider 条目支持 `"max_tokens"` 覆盖（local/minimax 已设 16384）；pool 继承链路（provider 优先 → 默认 client）与客户端 payload 全链路接通
- 测试：payload 携带/缺省/配置默认/factory 装配/provider 解析与回退（+11 项）；FakeLLM 桩对齐新字段
- 配置文档补 `LLM_MAX_TOKENS` 行

## v0.5.3（2026-08-15）

### 消息响应提速：事件日志 O(n²) 续号修复（agent 通用路径，本地/云端同受益）
- **根因（用户反馈"发消息 1 分钟模型才有反应"）**：大会话（如 654 条）压缩归档时对每条消息单独写一条事件日志，而 `EventStore.append` 为求最大 seq **每次全文件扫描**——625 次连续 append 总耗时 O(n²)，实测 62s 阻塞在主循环（LLM 调用之前）；云端 80K 预算归档同样多，故本地/云端一样慢
- **修复**：seq 续号改**尾部读取**（append-only 文件最大 seq 必在尾部，反向读最后一条事件，O(1)；含损坏行容错与多段归档段取大）；`last_seq()` 同口径；`_resolve_msg_seq` 优先用 run 中内存会话（P0-5 绑定表），避免每次归档都读盘
- **实测（真实 654 消息会话 + 9B）**：run 97s → 37s，其中 LLM 固有 prefill+生成 35.7s（cProfile 实证），**agent 管线 63s → 1.3s**
- 事件日志语义零变化（seq 单调、损坏行容错、flock 并发安全、滚动兼容），相关测试全绿


### 本地大模型接入：provider 级超时（修复 LLM 请求超时 120s）
- **根因**：本地大模型（LM Studio 27B 量化实测 ~5s/千字 prefill）在 120s 全局超时内完不成首 token——40K 字上下文实测 208s 才出首字节，大上下文会话（几十万字符）必然超时报 `LLMTimeoutError: LLM 请求超时（120.0s）`
- **provider 级 `timeout_s`**：`data/providers.json` 每个 provider 可配 `"timeout_s": 600`（本地慢模型放大，云端保持全局默认零回归）；`model_catalog` 目录标注 provider 超时
- **调用语义修正**：`timeout_s` 未被 `adjust_strategy` 显式调整时，循环不再下发 per-call 覆盖，让 client 自身超时（provider 级优先、全局兜底）生效——此前 provider 配再大也会被循环的 120s 覆盖
- **配置**：`data/providers.json` 的 `local` 已配 `"timeout_s": 600`；`docs/configuration.md` 常见坑新增本地模型超时排查三步（调超时/控上下文/换轻模型）

### 本地大模型接入：provider 级历史预算（agent 发给本地模型的上下文过长问题）
- **根因（用户指出）**：agent 每轮发给本地模型的历史按全局 `HISTORY_MAX_CHARS`（80K 字符 ≈ 56K tokens）构建，本地模型 prefill 随上下文线性涨——80K 字符在 CPU 级 27B 上首 token 要 7-10 分钟，即使窗口装得下也慢得不可用；实际有用的近期内容远小于全量历史
- **provider 级 `history_budget_chars`**：`data/providers.json` 每个 provider 可配历史注入预算（字符），`_effective_history_budget` 取 min(全局, 窗口折算, provider 预算)——`local` 已配 `"history_budget_chars": 12000`（≈9K tokens），实测真实会话发送载荷 69,697 → 13,510 字符（5 倍缩小），27B 首 token 缩到 1-2 分钟、9B 10-20 秒；旧历史照常压缩归档可检索（信息零丢失，RULE-AI-00 不变）
- **`[预算预警]`/context_usage 占用率口径修正**：改为统计**实际发送载荷**（构建后消息），不再把已压缩归档的原始会话算进"当前占用"——旧口径在收紧预算后会虚高数十倍（实测 440K vs 实际 70K），误导 AI 压缩决策；`architecture_status.context_usage.breakdown` 同步如实
- **配置**：`data/providers.json` 的 `local` 已配 `"history_budget_chars": 12000`；云端 provider 不配则完全零回归

## v0.5.3（2026-08-15）

### 现场修复：代理假 IP 段（198.18/15）误拦 web_fetch（本地大模型接入用户现场）
- **背景**：Surge/Clash fake-ip 模式下代理 DNS 把目标域名解析为 198.18.0.0/15 假地址；Python `is_private` 将该段判为私网 → SSRF 防护误杀代理环境下全部外网抓取（`[内网拦截] 目标地址属于私网/保留地址段（198.18.x.x）`），既有测试被迫 `WEB_FETCH_BLOCK_PRIVATE=0` 绕过
- **修复**：全部解析地址落在 198.18/15（代理假 IP）→ 默认放行 + 回执如实标注「已按代理通道放行」；`WEB_FETCH_BLOCK_FAKE_IP=1` 恢复严格拦截；真实私网/回环/链路本地/保留段拦截语义不变（P0 不回归）；连接后对端复核（TUN 假 IP）同步放行
- **测试**：新增 `test_web_fetch_fake_ip.py`（8 项）；撤销 m48/paging/builtin 中 17 处"关拦截"绕过（修复后拦截开启下通过）
- **对端复核容错**：透明代理转发（Surge pf 重定向，对端为本机回环）放行 + logger 留痕——per-hop 预检查已把关目标，真实私网对端仍丢弃（P0-3 主体不变）；端到端实测 `example.com` 经代理通道抓取成功且回执如实标注

## v0.5.2（2026-08-15）

### 回复展示：不折叠，过长分块输出（用户需求批次）
- **Web**：回复正文折叠整体移除（消息体级 2000 字摘要折叠 + 「展开全文」按钮删除）；超长代码块（>200 行）由折叠摘要改为**顺序分段全量展示**（每段 ≤200 行、段首标注「第 i/N 段 · 共 X 行（自动分块，未折叠）」、逐段语法高亮与复制按钮保留）
- **飞书**：长回复默认**不折叠全量分段推送**（markdown 感知分段既有能力）；`FEISHU_FOLD_LONG_REPLY=1` 选择加入旧折叠行为（摘要卡 + 「展开全文」取回，命令保留向后兼容）
- 折叠实现（collapseUnit/折叠样式类）整体移除，防复活守护测试改写

## v0.5.1（2026-08-15）

### 截断信号与轮次耗尽强化（用户需求批次）
- **放大字数**：`TOOL_SUMMARY_THRESHOLD` 默认 5000 → 12000；输出分层首尾窗口 600/600 → 2500/2500——截断/摘要发生更晚、可见内容更多（硬上限 100K 安全阀不变，信息零丢失语义不变）
- **截断信号行动指引**：`[输出摘要]` 与 `[结果超长，已截断]` 回执附统一指引——继续推理前先把可见要点与待核实缺口提炼记录（推理链或 [[memory]] 记忆块），最终总结纳入；程序只发信号不替 AI 摘要（RULE-AI-00）
- **轮次耗尽决策轮**：耗尽不再直接罐装终止——注入一次 `[轮次决策请求]` 请 AI 归因：① 工具使用错误/空转 → 如实归因 + 正确做法 + 当前结论收尾；② 正常推进 → adjust_strategy 调大 max_iterations（≤500）续跑。决策轮仅一次（per-session 标志）；AI 未调大仍耗竭 → 回到罐装如实终止（程序兜底边界不变）
- **RULE-AI-11 新规则**：截断提炼与轮次耗尽自主归因写入规则真相源（`docs/ai_rules.md`）+ system prompt 嵌入（同步漂移测试覆盖）

## v0.5.0（2026-08-15）

> 安全深化 + 正确性修复批次（代码审计 18 项发现的完整闭环；审计报告与修复计划为本地过程文档不入库）。

### 安全修复（P0）
- **灾难性命令硬阻断 Guard（P0-1/审计发现 #1/#4）**：execute_command 危险命令检测重写为"全串正则层 + shlex 分段子命令层"双扫描——管道/拼接/`rm -rf` 聚合 flag/`find -delete|-exec rm`/`sh -c` 内嵌/`python -c` 载荷（rmtree/unlink/os.remove 等）此前可绕过的形态全部闭合；命中硬阻断 + 审计落盘 `data/audit/safety_blocks.jsonl`（fail-open）。模块职责如实标注为"已知模式硬阻断+审计，非完备沙箱"
- **web_fetch SSRF 重定向逐跳检查（P0-2/审计发现 #2）**：301/302 跳转此前不经私网校验（公网 URL 可跳板打内网）——curl/httpx 双路径改手工逐跳循环，每跳目的 IP 均过内网拦截，超 5 跳如实报 FAIL
- **web_fetch DNS 钉 IP（P0-3/审计发现 #3）**：解析→连接之间的 DNS 重绑定窗口闭合——curl `--resolve` 钉死已校验 IP；httpx 建连后核验对端地址（不符即断连丢弃，GET 请求行已发出的残余如实标注：保护的是回读数据）
- **会话存储跨进程写互斥（P0-4/审计发现 #5/#6）**：Session 保存此前仅进程内锁——CLI/Web/飞书多进程并存可写穿 JSON。现每会话 `<sid>.lock` flock 覆盖"读-改-写"临界区（含 load→append→save 全链），锁不可用如实降级告警
- **引擎跨会话可重入（P0-5/审计发现 #7）**：停滞指纹/overflow 计数/预算预警/快照节流等运行态此前挂在引擎单例上——同引擎多会话并发 run 互相污染（状态串台/停滞误判）。改为 `contextvars` 会话定位 + per-session 状态桶（SSE/ASGI 跨 Context 驱动用值快照还原），registry 双层线程池均做上下文传播

### 正确性修复（P1）与工程补强（P2）
- **子代理会话泄漏（P1-5/审计发现 #10）**：SubAgentRunner 执行前切到子会话但从不恢复——父级后续超长工具结果归档/变更日志归错子会话（串台）。改为 try/finally 保存并恢复注册表会话（显式字段 + `current_session_id` ContextVar 值快照还原，成功/异常/截断路径全覆盖）
- **工具超时线程/子进程泄漏（P1-5/审计发现 #11）**：`_run_with_timeout` 超时后 `with ThreadPoolExecutor` 退出会 `shutdown(wait=True)` 卡到工具自行结束（超时名存实亡），且 execute_command 的 shell 子进程不被终止。修复：超时路径 `cancel()` + 调用工具 `terminate()` 钩子 + `shutdown(wait=False)` 立即返回；execute_command 前台改 `Popen`+`communicate`（独立进程组 + `terminate()` 整树 SIGKILL），超时后 shell 及其孙进程不再残留孤儿（残余无钩子工具的工作线程如实标注：最多存活到工具自身超时/结束）
- **事件日志滚动未接线生产（P1-1/审计发现 #9）**：RotateManager 此前只有 CLI 读段清单在用，`check_and_rotate` 生产无人调用（事件日志永不滚动），且多段迁移检查在锁外有竞态、迁移后追加 seq 从 1 重启。修复：RotateManager 接线进 EventStore.append（大小触发每次查、天数触发 30s 节流）+ 会话级稳定锁 `<sid>.lock` 覆盖"检查+迁移+追加"临界区 + 多段 seq 全局续号 + 引擎 run 末 `check_rotate` 钩子（均 fail-open；未接线存储零回归）
- **fork 工具轮边界对齐（P1-6/审计发现 #15）**：fork 点切在 assistant(tool_calls) 与其回执之间 → 分支继承孤儿声明，下次运行被配对修复伪造 `[程序异常]` 回执。修复：fork 点自动向前对齐到完整工具轮边界，`ForkReport.snapped_fork_point` 如实报告实际生效点
- **tool_calls 配对漏计空 id 回执（P1-6/审计发现 #16）**：配对自检/补齐按"回执 id 非空"计数，存量会话的空 tool_call_id 回执被漏计 → 多补占位（额外 tool 消息无声明 → API 400）。修复：按 id 精确配对 + 空 id 位置兜底，自检与补齐共用同一缺口函数
- **流式断连会话漂移（P1-6/审计发现 #17）**：`run_stream` LLM 流式中客户端断连（GeneratorExit）跳过 loop 末保存 → 事件日志已追加而 session JSON 未保存。修复：部分回答如实落会话（中断标注不伪装完整）+ 事件双轨同步 + 立即保存
- **retire 指引如实化（P1-2/审计发现 #8）**：`read_path_switched` 字段名暗示已切换（实际只写切换指引）。改名 `read_path_ready_to_switch` + 新增 `switch_instructions`（READ_PATH_SOURCE 修改 + 重启两步指引），CLI 打印与回滚提示同步如实（程序不代写用户 .env）
- **providers 配置解析加固（P1-3/审计发现 #12）**：能力标志严格布尔解析（白名单字符串/非法值 warning + 回退默认，不再静默 `bool()`）；context 缺失回退 131072 与 ModelSpec 默认一致；provider/模型双层 try/except——单条非法跳过该条并如实告警，不再拖垮整个注册表
- **模型解析失败可感知（P1-4/审计发现 #13）**：`switch_model` 目标解析 ValueError 不再静默吞掉——warning 含配置模型名与失败原因；`config_status` 新增 `model_registry_resolved` 维度，AI 可感知"模型配置未生效"
- **鉴权 fail-closed + 跨站写防护（P2-1）**：`WEB_AUTH_REQUIRE=1` 未配置 `WEB_API_KEY` 旧实现静默放行（等于无鉴权）——现启动拒绝（对齐远程绑定校验语义）+ 请求期 503 如实报错；回环豁免部署的 mutating 端点新增 Origin 头校验（非回环来源 POST/PUT/DELETE/PATCH → 403，防浏览器跨站打 127.0.0.1；无 Origin 的 curl/脚本不受影响）
- **upload 体积前置检查（P2-2）**：base64 体积先查字符串长度（≈4/3 原始体积）再解码，超限直接 413——大 payload 不再先吃解码内存/CPU
- **会话锁表无界增长 + 首聊竞态（P2-3）**：`session_locks` 改 LRU 上限 1024（淘汰最旧空闲锁，持锁不淘汰防互斥失效）；无 session_id 并发首聊的"取共享→建会话→设共享"收进同一模块级 guard——不再双建孤儿会话
- **LLM 连接泄漏（P2-4）**：`LLMClient.close()` 此前无人调用。新增 `ModelClientPool.close()`（default+缓存全关，幂等）与 `LoopEngine.close()`；`clear_cache()` 热重载路径改为先关旧 client 再清空；CLI 主返回路径、web 退出、飞书停机均接线关闭
- **eval 管道验证补强（P2-5）**：wilson_ci docstring 漂移修复（k=0 正常计算真实区间如 (0.0, 0.562]，仅 n≤0/k<0 返回 (0,0)）；dry 模式新增注入可见性自检（真实状态追踪器注入 FAILURE → architecture_status 快照路径断言可见，不可见即管道失效如实报错）
- **fallback 引擎级集成测试（P2-6）**：真实 `_try_fallback_chain` 触发路径（主模型 500 → 降级链成功）——断言回答来自降级模型、`[模型降级]` 回执注入、architecture_status 降级态与 `model_fallbacks_count` 配置计数可见；4xx 不降级与链全失败汇总两条零回归路径同测

## v0.4.0（2026-08-15）

### 新能力
- **孤儿 tool_calls 合成回执（HARNESS-01）**：`run_stream` 客户端中断（close）时自动写「已取消」合成回执并立即保存——不再产生「有声明无回执」的孤儿声明（严格 FC 协议 400 根源），对账不变量「声明数 = 结果数 + 取消数」
- **`request.meta` 事件（HARNESS-02）**：每轮 LLM 请求快照入事件日志（round/model/thinking/reasoning_effort/tools_count/history_chars/budget），回放可确知"当时用的哪个模型/挂了哪些工具/预算多少"
- **web_fetch SSRF 内网拦截（HARNESS-03）**：`WEB_FETCH_BLOCK_PRIVATE`（默认开）拦截私网/环回/链路本地/保留段地址（IP 字面量 + DNS 解析双路径），命中返回 BLOCKED `[内网拦截]`——防云元数据（169.254.169.254）等内网探测
- **上下文预算预警（HARNESS-04）**：上下文占用率 ≥80% 预算时注入一次 `[预算预警]`（含占用率/字符数），"压缩/收尾"决策归 AI——程序不自动压缩（RULE-AI-00）
- **程序故障指标（R2/A6）**：`architecture_status` 上报程序故障计数（event_write/memory/llm_call/session_persist 等 fail-open 点），AI 可感知"程序故障率"并应对
- **archive-index 存量段索引重建（R3）**：`archive-index` 命令幂等重建历史段检索索引（存量无索引段全文扫描兜底升级为索引检索）
- **飞书显示批次**：超长行零宽空格折行（fence 内不折）+ 分段字节预算（50000→30000 防物理上限）+ 表格降级增强（来源标注/列数提示）+ 摘要卡交互化（「展开全文」命令，消息条数收敛）+ 状态卡 1s 节流 + 发送最小间隔 300ms + 渲染支持矩阵 `docs/feishu_render_matrix.md`
- **本地真实回归脚本**：`scripts/run_real_smoke.sh`（冒烟 + 评测集，key 从 env/.env 读取，`--quick` 模式）——key 不上传策略下的 CI 补位

### 改进
- **工具重名去噪（R1）**：同一对象重复注册静默跳过（修复 `RUN_MODE=minimal` 过滤失效），工具面更干净
- **评测 token 开销指标（A2）**：场景级 tokens_in/tokens_out 聚合 + 报告渲染（`scripts/run_eval.py`）
- **run_mode 文档化（A1）**：`docs/configuration.md` 补 standard/ptc/minimal/creative 模式说明
- **开发方法论公开（B10）**：`docs/development_methodology.md`（SoT 先行/如实记录/零回归/评测纪律）

### 修复
- **上报冷却首调误拦截（HARNESS-05）**：`EventReporter.should_report` 首次调用 last 取 0.0、`time.monotonic()` 从系统启动起算——CI 全新 runner 启动 <60s 时首次上报被误判"冷却中"拒绝，致自我评估/演进提醒偶发不注入（本地系统启动久无法复现，CI 复现；回归测试模拟系统启动 5s 场景）
- **CI nightly 无 key 跳过失效**：`exit 0` 只放行当前 step，后续 real_llm/评测 steps 无 key 时仍执行致 exit 2——改为 GITHUB_OUTPUT 条件门（workflow_dispatch 实测修复）

### 文档
- 飞书渲染支持矩阵（`docs/feishu_render_matrix.md`）+ 开发方法论（`docs/development_methodology.md`）

### 框架化批次（2026-08-15 追加）
- **headless 服务模式（B5）**：`examples/04_headless_service.py`（无 UI 纯 API 嵌入——`build_engine` 单实例 + 同步/流式对话端点约 20 行）
- **LLM 错误注入矩阵（A4）**：网络/超时/HTTP 4xx/HTTP 5xx/协议五类错误各注入引擎循环，断言 `[LLM 调用异常]` 三件套如实呈现 + 类型名不吞并 + 不抛穿
- **发布节奏制度化（B11）**：Release Drafter（PR 标题自动归类 changelog 草稿）+ tag 触发门禁复核 + Release 草稿生成 + CONTRIBUTING 发布流程
- **多 provider 成本路由增强（B6）**：`switch_model` 成功回执注入目标模型成本档 + 能力语义 + 上下文窗口（元数据缺失如实标注，判断归 AI）
- **插件化 Skill 可演示化（B3）**：仓库自带示例技能（`skills/`）入库，真实装配端到端测试
- **评测集贡献指南（B7）**：`docs/eval_scenarios.md`（schema + 判定注册 + 30 分钟新增路径 + PR 验收）
- **API 契约稳定化（B5）**：公共签名快照测试（build_engine/LoopEngine/SessionStore/ToolRegistry 参数锁定）+ api.md §1 装配链路可执行验证

## v0.3.0（2026-08-14）

### 新能力
- **插件化 Skill 加载**：`skills/<name>/SKILL.md` 目录自动扫描，AI 经 `skill_list`/`skill_load` 发现并加载外部技能执行（`SKILLS_DIR`，默认 `./skills`）——外部扩展零代码
- **动作状态条（H-UI）**：引擎动作观察者（thinking/tool_call/tool_result/answer/done 事件）+ 飞书状态卡实时更新（💭 思考中 / 🔧 正在调用工具 / ✅ 完成 / ✍️ 生成回答）；Web 流式本就支持（思考 + 工具进度链）
- **人工审批流**：EXEC_MODE 拦截项可在 CLI 交互模式终端确认（`set_approval_callback`，无终端 fail-closed 拒绝），审批审计落盘
- **symlink 写防护**：edit_file 写路径含符号链接拒绝（防越界写）；read_file 读 symlink 如实标注
- **评测体系**：固定评测集（6 场景）+ 运行器（`scripts/run_eval.py`，真实 LLM / `--dry`），Wilson CI 统计约束，CI nightly 自动运行
- **`LoopEngine.run_single`**：一次性便捷入口（自动建会话）

### 改进
- `LLM_MAX_ITERATIONS` 默认 20 → **40**（多步任务不再轻易触顶）；达 80% 注入 `[轮数预警]`，AI 可经 adjust_strategy 调大（硬上限 500）
- `HISTORY_MAX_CHARS` 默认收敛统一为 **100K**（1M 曾致上下文撑爆）
- 档案分片 + sidecar 检索索引（100MB 开新段，检索跨段最近优先，存量无索引全文扫描兜底）
- 飞书心跳历史轮转（`FEISHU_HEARTBEAT_HISTORY_MAX_MB`）
- HashEmbedder v2（2+3-gram）+ embedding 缓存版本化
- `model_catalog` 选型指引（成本/能力语义 + switch_model 引导）
- CI：GitHub Actions 三件套门禁（pytest/ruff/pyright）+ nightly 真实评测

### 文档
- 公共 API 参考（`docs/api.md`，含稳定 API 声明）+ 3 个示例（`examples/`）
- 配置参考（`docs/configuration.md`，分组配置表 + 常见坑速查）
- 事件溯源设计（`docs/event_sourcing.md`）+ 评测集扩展指南（`tests/eval_sets/README.md`）
- 英文 README（`README.en.md`）+ 贡献指南（`CONTRIBUTING.md`）

### 修复
- `maybe_trigger` 首次触发平台 bug（容器 monotonic 从 0 开始误判冷却，提取静默失效）
- pyright 1.1.411 兼容（divider 类型）、CI 环境兼容（测试自足）

## v0.2.0（2026-08-14）

- D1 事件溯源单一真相源（5 类事件 + 回放/对账/迁移/回滚/退役/会话 fork/过滤钩子）
- 实时停滞检测（连续同指纹 3 提醒 / 5 熔断）+ edit_file 换行归一化 + mtime 基线防并发
- 开源发布（Apache-2.0 + 公开面精简）
