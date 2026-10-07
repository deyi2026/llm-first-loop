# AUDIT 2026-10-07: P0 Architecture Gap Audit（针对当前 main）

- 审计对象：`main` @ 0.6.26（399 文件 / 146,959 行 / 测试 744 文件；全量回归 7,508 passed / 3 failed（known-red safety 环境）/ 116 skipped）
- 输入：① 外部 GPT 审查（评分/竞品部分未核验，不作为依据）② 本次对仓库当前事实的逐项核验
- 性质：纯文档分析，未改任何产品代码
- 结论级别标注：[事实]=仓库当前可核验；[推断]=基于事实的判断；[未核验]=本轮无证据
- **rev 2（2026-10-07 22:5x）**：修正 rev 1 自身的 currentness 错误——rev 1 依据 10-07 上午的 CHANGES 文档断言"B 面尾注已实现待部署"，但 `af480f80d`（同日 14:16）已按用户指令删除 B 面自动尾注，且生产 web 已运行 gen 195 @ `54fc378c4`（含该删除）。受影响：§0 G3、§1 末行、§4、§5 P0-1；详见 §4.4 preflight 与 §6 方法记录。

## 0. 一页结论

外部审查最大的战略判断（"能力增速超过收敛速度"）成立，但它给出的 P0 序列中 **第 2 项（Invocation Journal）已过时**：P0-2 provider-settlement 覆盖已于 2026-10-02 全相位实现并提交（A2/B1/B2/B3/C1），P0-3 strict durability 同日落地。真正仍然打开的缺口是四个：

| # | 缺口 | 一句话现状 |
|---|---|---|
| G1 | Kernel 无显式边界契约 | 事实 kernel 分散在 core/loop + event_log + resources + runtime，六面是操作模型不是代码结构；机械守卫只有局部（local-import ratchet + 函数尺寸 only-decrease） |
| G2 | durability 基座分散 | 每个 Incident 新增一套专属持久化（最新：schedule 私有签名账本），无统一 Durable Run Contract |
| G3 | method 消费闭环缺 T0 基线 | **[rev 2 修正]** B 面自动尾注已按用户指令删除（`af480f80d`）；A 面/pull-mode 已在生产 gen 195 生效；真正缺的是按实际机制起算的 T0 观察窗；消费率 6/677 ≈ 0.9% |
| G4 | 横向扩张仍在进行 | 10-07 当天仍有新能力合入 main（browser target_id 换绑等）；"冻结"是策略决策，目前无机械执行 |

## 1. 对外部审查的逐项裁决修正

| 外部审查主张 | 本轮核验 | 裁决 |
|---|---|---|
| P0 序列：冻结扩张 → Invocation Journal → ExecutionRuntime → Durable Run Contract → trace/benchmark | P0-1 审计（AUDIT-20261001）已冻结；P0-2 五提交 `3c9b0d52e`/`d005f275a`/`518441614`/`52496d327`/`25b737ce3` 全部在 git；`deepseek_web.py`/`chatgpt_web.py` 均含 `transport_observer`（L119-122/144/248） | **第 2 项过时**：Invocation Journal 已实现。剩余残留仅 §1.1 |
| "最大风险是能力增速超过收敛速度" | §3.3 证据：单日 4 个 schedule durability 补丁；673 卡 vs 6 条消费 | 同意 |
| "673 卡供给远超消费" | `data/methods/` 677 目录（rev 2 重数）；`usage.jsonl` 6 条（含今日补记 1 条） | 属实，且根因不只是检索质量——T0 观察窗尚未按实际机制起算（§4.3） |
| 评分 79/92.3、OpenAI Agents API/OpenHands/Letta 现状 | web_search 无有效命中 | 未核验，不采用 |
| "method 消费闭环未开始" | CHANGES-20261007（上午）：A 面锚点 + B 面尾注已实现 | **rev 2 再修正**：rev 1 只读 CHANGES 未做 symbol survival check——B 面尾注当日 14:16 被 `af480f80d` 按用户指令删除；A 面/pull-mode 已在生产 gen 195 生效（§4.4） |

### 1.1 P0-2 惟一残留 [事实]
Web 路径断言依赖真实流量出现后才生效（conditional assertions）。低风险，等待流量即可，不需要工程动作。

## 2. Kernel v1 边界审计（G1）

### 2.1 当前结构事实 [事实]
26 个顶层包按 LOC 排序（源 src/llm_loop；另有 6 个顶层能力模块由 P0-3 guard 单独登记）：

| LOC | 文件数 | 包 | 六面归属 |
|---|---|---|---|
| 30,515 | 89 | core/ | 跨面聚合根（见 2.2） |
| 16,814 | 55 | tools/ | Action |
| 14,100 | 51 | introspection/ | Epistemic |
| 9,884 | 18 | web/ | 交付面（六面外） |
| 9,348 | 17 | llm/ | kernel 候选（transport 适配） |
| 8,654 | 18 | runtime/ | kernel 候选（服务控制/因果/配置） |
| 8,071 | 15 | memory/ | Context |
| 6,421 | 12 | browser/ | Action |
| 6,073 | 18 | resources/ | kernel 候选（provider 结算/evidence store） |
| 5,555 | 14 | feishu/ | Action（outbound） |
| 3,843 | 13 | event_log/ | kernel 候选（事件事实源） |
| 3,448 | 4 | semantic_logic/ | 跨面（语义权威） |
| 2,570 | 5 | methods/ | Learning（pull-mode 检索消费） |
| 2,414 | **2** | subagent/ | Mission（2 文件巨石） |
| 2,194/2,158/2,000 | 9/7/12 | task_quality/ workspace/ codearts/ | Evaluation / 跨面 / Action |
| ≤1,566 | ≤6 | cognitive feedback fleet experiences eval cache_guard recovery skills knowledge | Evaluation / Reasoning 辅助 / Mission / Learning / Learning / Epistemic / Context 辅助 |

六面（ARCHITECTURE-ai-operating-v1 §4-13+）：Mission / Epistemic / Context / Reasoning / Action / Evaluation。

### 2.2 无法归面的模块 [事实]
- `web/`（9.9k LOC）：交付/呈现面，六面无此面。架构文档未覆盖"对用户的交付"。
- `semantic_logic/`：SMC 语义权威，横切所有面。
- `core/session.py`（109KB 单文件）、`core/history.py`（97KB）、`episode_history.py`（75KB）：会话/历史聚合根，天然跨面。
- `methods/`：被检索消费（pull-mode，Epistemic）且 `introspection/registry_introspection.py` + `tools/registry.py` 提供工具面锚点（A 面，Reasoning）；B 面自动尾注已删除（`af480f80d`）。

### 2.3 事实 kernel 与其边界现状 [事实+推断]
- 事实 kernel = `core/loop/`（engine + 20 个 engine_services：convergence/termination/recovery/routing/token_budget/method_injection…）+ `event_log/` + `resources/` + `runtime/` + `llm/` transport。
- **不存在名为 kernel 的模块；不存在 kernel 边界契约文档。**
- 机械守卫已存在但局部：`tests/unit/test_arch_guards.py`（local-import ratchet）+ `tests/guards/function_size_baseline.json`（schema 2，`only-decrease`，含 `function_lines` 与 `legacy_super_functions` 两组基线）。
- [推断] 外部审查的 "Kernel v1" 建议方向正确，但其前提（六面=代码结构）不准确：六面是**操作模型**，代码按子系统分包。收敛动作应是"给事实 kernel 写显式契约 + 扩 import ratchet"，而非重构为 kernel/planes 目录。

### 2.4 巨石热点 [事实]
`session.py` 109KB / `history.py` 97KB / `episode_history.py` 75KB / `cache_health.py` 54KB / `tool_execution_journal.py` 39KB / `scheduler.py` 36KB；`subagent/` 2 文件 2,414 LOC；`legacy_super_functions` 基线含 `build.py::_build_llm_messages` 199 行、`engine_services/fallback.py::_try_fallback_chain` 235 行。

## 3. Durability 分散热点（G2）

### 3.1 Incident 样本：schedule 唤醒四连补丁 [事实]
10-07 单日：`06e6a587c`（one-shot 唤醒改为在实际 run 受理时消耗）→ `ee75b861d`（跨混合版本写入者的唤醒权威）→ `a829e254a`（due 声索前恢复被代理 owner）→ `54fc378c4`（grant_lost_owner_dead 确定性降级）。
根因（docs/schedule-wake-restart-recovery.md）：restart 丢失 in-process wake grant → 指数退避；`session_busy` 在受理前误写 `wake_started_at`。
修复引入**独立私有签名账本**：0600 权限、fsync、原子替换、目录 fsync、跨进程锁、tombstone 与 entry 分离。
[推断] 修复本身质量高（受理→后台→run lease 三段消耗语义清晰），但这是第 N 套按事故新增的持久化机制。

### 3.2 持久化基座清单（已核验，非穷举）[事实]
1. EventStore JSONL（append-only 事件事实）
2. Provider settlement journal（P0-2 已收敛入 EventStore 语义）
3. Schedule 子系统包含两个不同持久化 surface：
   - `ScheduleStore` 主状态文件：flock + 锁内重读合并，但仍以裸 `write_text` 覆写，写失败 fail-open；
   - `WakeAuthorizationStore` 私有签名账本：0600 + flock + tmp + file fsync + `os.replace` + directory fsync，已具备强 T2 原子持久化语义。
4. service_control desired-state / generation CAS
5. Evidence blob store + ledger（evidence://）
6. `data/methods/usage.jsonl` + 各卡 `qualification.jsonl`
7. experiences / episodes 存储

### 3.3 收敛方向（决策待做，不写实现）[推断]
选项 A：Durable Run Contract——定义统一"持久化语义接口"（单写者/原子性/恢复钩子/idempotency key），现有基座逐个声明符合或迁移；ScheduleStore 主状态文件为第一个迁移 client，已具备强原子性的 WakeAuthorizationStore 不重复建设。
选项 B：维持分立但建立 durability 清单与一致性测试矩阵（成本最低，风险是第 N+1 套仍会出现）。
推荐 A，理由：GPT 与本次审计共同指向的"分散 durability"是复发模式，B 不改变生成机制。

## 4. Method 消费闭环（G3）

### 4.1 当前生效机制 [事实，rev 2 重核]
- A 面（Reasoning）：`tools/registry.py` + `introspection/registry_introspection.py`——5 个具体触发域 + 行为触发。
- pull-mode（Epistemic）：`search_records(kind=method)` 词法检索路径（`introspection/search.py::_search_method`）恒可用；`SEMANTIC_METHOD_ENABLED=0`（.env:268）仅关闭语义 RRF 扩展层（L762-768），不阻断词法发现。
- `method_manage` 生命周期工具；Learning reflection 中的 related-method advisory。
- **B 面（已删除）**：rev 1 记载的 `RecordSearcher.search() → _maybe_collect_related_methods → tools_status.py::_format_related_methods_hint`（尾注，`method_related_hint_enabled`）链路——`6dddb6962` 引入，线上观测补丁 `7e4cee69a`/`8ce30c626`，用户否决后由 `af480f80d`（10-07 14:16）删除；三符号当前 `grep --include="*.py"` 零命中。

### 4.2 rev 1 的错误与更正 [事实]
- rev 1 断言"A/B 面已实现、未 publish/restart"——两半都不成立：B 面当日已被用户指令删除；A 面/pull-mode 无"待部署"增量（见 4.4）。
- 错误根因：只读 CHANGES 文档（上午版本）即写入结论，未做 HEAD 上的 symbol survival check——本审计自己犯了它要求外部审查过的错（§6）。

### 4.3 消费率断点排序 [推断，rev 2 修订]
1. T0 观察窗从未按实际机制起算——无数据支持任何归因。
2. usage 记录依赖手动/补办（usage.jsonl 6 条含补记）。
3. 677 卡中必然存在低触发域覆盖卡（A 面锚点仅 5 域）；语义扩展层关闭进一步限制召回宽度。

### 4.4 currentness preflight [事实，2026-10-07 22:5x]
- 生产 web：generation 195 @ `54fc378c4`，22:09:02 启动，matches_desired=true，restart_required=false。
- HEAD `4bd0b9356` 与生产的产品代码差 = `git diff --stat` 仅本审计文档；**当前 main 不存在"已实现未部署"的 Method 消费改动**。
- B 面删除（`af480f80d`）早于生产代 `54fc378c4` → 生产代码不含 B 面，无复活风险。
- T0 基线（实际机制指标，非尾注计数）：method 卡 677；usage.jsonl 6；`kind=method` 检索调用历史累计 24（T0 后 0）；`method_manage.record_use` 调用累计 1（T0 后 0）。
- **T0 = 2026-10-07 22:09:02（gen 195 启动时刻）**；T+7d 指标：kind=method 调用增量、record_use 增量、usage.jsonl 增量。

## 5. 可执行任务清单

> 纯增量动作，均不与已完成项重复。每条含验收标准。P0=本周，P1=两周内，P2=决策后。

### P0-1 【观测】method 消费闭环 T0 起算（rev 2 改写；原"部署"前提已被 preflight 否证）
- rev 1 原文（publish + restart + 统计尾注次数）**作废**：§4.4 证明生产 gen 195 已含全部现行机制，无待部署增量；尾注载体已被用户否决删除，重统计它无意义。
- 动作：以 T0 = 2026-10-07 22:09:02（gen 195 启动）落观测基线文档；T+7d 检查点统计 `kind=method` 调用增量、`method_manage.record_use` 增量、usage.jsonl 增量。
- 验收：基线文档落 docs/（含 677 卡 / 6 usage / 24 次历史检索的起点值与采集命令）；T+7d 有一次复查记录。
- 依赖：无。**不做 publish/restart**（无产品代码增量，重启纯风险）。

### P0-2 【决策】Durable Run Contract 立项决策（先文档后代码）
- 动作：按 §3.3 选项 A 写 DESIGN 文档：接口语义（单写者/原子性/恢复钩子/idempotency）、现有 7 基座符合性矩阵、schedule 私有账本作为首个迁移 client
- 验收：DESIGN 文档落 docs/ 且列出每个基座的"符合/迁移/豁免"结论；无代码变更
- 依赖：无

### P0-3 【策略+机械】横向扩张冻结的执行机制
- 动作：把"新能力合入需声明归属面/或显式豁免"写进 CHANGE 纪律；扩展 test_arch_guards：新顶层子包/新工具文件需在基线中登记
- 验收：guards 测试在未登记新增包/文件时 fail；现有 26 包 + 6 顶层能力模块全部登记
- 依赖：无

### P1-4 【契约】Kernel v1 边界契约文档 + import ratchet 扩展
- 动作：定义 kernel = {core/loop, event_log, resources, runtime, llm}；写"kernel 不 import 面、面可 import kernel 公共 API"规则；用 test_arch_guards 机械化
- 验收：契约文档落 docs/；ratchet 测试覆盖 kernel→面方向的非法 import；全量回归绿
- 依赖：P0-3（登记机制先行）

### P1-5 【偿还】巨石拆分 ratchet 加速
- 动作：`legacy_super_functions` 基线目标本季度 -50%（`_build_llm_messages` 199 行、`_try_fallback_chain` 235 行、`session.py`/`history.py` 拆分启动）
- 验收：基线数值单调下降且回归绿
- 依赖：无（可与 P1-4 并行）

### P1-6 【收尾】P0-2 web 真实流量断言激活
- 动作：等首个真实 web 流量后确认 conditional assertions 生效
- 验收：AUDIT-20261001 §6 该项标记完成
- 依赖：流量事件（被动）

### P2-7 【基线】run-level benchmark
- 动作：定义收敛步数/工具调用数/token 三指标基线，tests/perf 已有基础
- 验收：benchmark 脚本 + 首份基线数据落盘
- 依赖：P1-4（指标定义依赖 kernel 契约）

### P2-8 【文档】六面文档补"代码映射"章节
- 动作：把 §2.1-2.2 映射表回写进 ARCHITECTURE-ai-operating-v1，并补"交付面"（web/）定义
- 验收：文档含映射表且与 test_arch_guards 登记一致
- 依赖：P0-3、P1-4

## 6. 本审计自身的方法记录
- 关键修正：外部审查基于的材料落后于 main 约 5 天（10-02 的 P0-2/3 落地未被其覆盖）。任何外部评审结论进入任务清单前必须先过"是否已被 main 落地"这一关。
- rev 2 追加（本审计自身犯错后的机械规则）：**任务清单引用的任何 capability，必须先在 HEAD 上做 symbol/commit survival check（`grep` 关键符号 + `git log` 确认引用提交仍是 HEAD 祖先），只读 CHANGES 文档不构成充分证据。** 本审计 rev 1 引用"B 面尾注已实现"仅依据当日上午 CHANGES，未察觉同日 14:16 的删除提交 `af480f80d` 与 22:09 的 gen 195 部署——与外部审查落后 5 天是同型错误，落后 8 小时也是落后。此规则同样适用于部署状态断言：声称"未 publish/restart"前必须先查 service 状态的当前 generation 与 git_head。
- rev 3 追加：P0-3 机械扫描确认 `src/llm_loop` 当前是 **26 个顶层包 + 6 个顶层能力模块**；rev 2 的"27 个子包"为统计口径错误。Durability 计数也改为"7 个子系统、至少 8 个持久化 surface"：ScheduleStore 主状态与 WakeAuthorizationStore 私有授权账本必须分开判断。后续任何新增持久化 surface 都必须先声明 Durable tier（T1/T2/T3）或显式豁免，再进入实现评审。
