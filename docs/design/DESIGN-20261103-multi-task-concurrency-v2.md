# 多任务并发协调 需求实现设计 v2.7：从「归属正确」到「占用可见」

- 文档类型：design（需求 → 实现 → 验收）
- 日期：2026-11-03
- 版本：v2.7
- 状态：**PR-0 完成**。5 个裁决点已定（D1–D5，见 §12）；T-0.1 / T-0.2 / T-0.3 / T-0.4a / T-0.4b / T-0.5 / T-0.6 全部落地并有测试回执（§11.1）；下一步是 PR-0 观察期（空跑一周看「观测不阻断」）与 PR-1。
- 上游：`DESIGN-20261101-cross-session-coordination-v1.md`（四层已落地 v1.0）、`docs/analysis/2026-11-01-跨会话任务协调-分析与建议.md`（v2 拷问版）
- 关联规则：RULE-AI-01（事实/完成诚实）、RULE-AI-23（授权来源）、RULE-AI-24（防退化）、RULE-AI-35（守卫须实测）
- 方法：以 v1 **实施后**的代码为事实基线，用 45 问四轮拷问暴露 v1 未覆盖的层（v2.0 = Q1–Q22 搭骨架；v2.1 = Q23–Q32 以源码实测逐条纠错；v2.2 = Q33–Q39 用真实账本统计推翻三处语义前提；v2.3 = Q40–Q45 把观察期埋点与视图成本落到具体代码行，见 §4.4/§6.6/§6.7）。凡标「已核」者有源码定点依据；标「未实测」者不得作为实施完成判据；标「v2.0 表述有误」者已在 §2.1 勘误表登记。

---

## 0. 一页结论

1. **v1 做对了一半**：它关掉了"误写别人的 goal"这个真实危害面（L1 归属 + **goal 级** L4 版本 CAS 均已落地），但留下两个结构性空洞——**「谁在做」没有可信来源**、**「现在正在发生什么」是硬编码的 degraded**。
2. **状态 ≠ 占用**。`task.status = in_progress` 是任何人都能写的**描述**；`claim` 才是程序签发的**权利**。当前系统只有前者。这不是措辞问题：两个会话都可以把同一个 task 写成 in_progress，谁都不违法。
3. **状态迁移不能替代 claim**（v2.1 更正：不是"CAS 不能替代"）。`task_update` 只校验「这次迁移合法吗」，不校验「谁在做」；task 层**没有**版本 CAS（§2.1-E2），两次 `in_progress` 写入都会成功，两份劳动互相浪费。反过来 claim 也不防「基于陈旧视图的决策」——所以 claim 必须靠 generation fencing + 单一临界区兜住写入（§3.3）。二者不是替代关系。
4. **必须下沉到 task 级，不能复用 goal 级互斥**。一个 goal 下 5 个 task、父会话 + 3 个子代理并行推进，是**合法且应该鼓励的**并行；goal 级互斥会直接杀死的正是用户要的"同时推进"。claim 的并行度上界 = 不同 task 数，不是 1。
5. **不新建机制，只搬粒度**。`fleet/store.py` 已经证明「无后台回收线程的租约」在本仓库可落地（惰性过期 + flock 内 CAS + generation fencing + 过期不可自续），且有实测契约 `tests/unit/test_fleet_reclaim_race_and_ttl.py`。v1 §0.5 否决的是**回收器**，不是**租约**——本设计不违反该决策。**v2.2 更正**：本设计**不继承**其中的「过期不可自续」——fleet 的检查与提交跨 effect fence，本设计的 check+write 在同一临界区，时间不需承担安全职责（§2.1-E5 / Q33）。
6. **交付分三档**：**P0**（可见性接线，零破坏，1 个 PR）= 去掉三条硬编码 degraded；**P1** = claim 软接入 + 并发闸 + 路径重叠预检；**P2** = claim 强制（带开关）+ 拒绝契约全覆盖。
7. **第二轮实测推翻了 v2.0 的三处自述**（勘误见 §2.1）：(a) `spawn_subagent` **已有** 128 全局硬上限，不是"running 无上限"；(b) **task 级没有版本 CAS**，`Goal.version` 只管 goal 记录，claim 的 generation fencing 是 task 写入路径上**唯一**的并发控制；(c) `_SubAgentHandle` **没有** `expires_at` 字段（v2.0 伪代码引用了不存在的属性）。据此把 N4 从"新建闸"改判为"拆分既有闸的两种口径"，并新增四项实现约束：**锁序 claims→tasks 单向**、**校验与落笔同一临界区**、**holder 由程序注入**、**claims 文件名复用 goal 归一**。
8. **第三轮把「跑起来之后才会疼」的两件事提前到 P0**：`coordination_status` 用 `list(limit=200)` 硬截断（`goal_coordination.py:371`），真实账本 239 行 → **12 个 active goal 今天已不可见**（§2.1-E8）；窗口只认 `goal.updated_at`，而 task 写入从不触碰 goal 行（`task_store.update` 全程只写 tasks 账本），90 个 active goal 在默认 24h 窗口里剩 0 条（E9）；改用 `activity_at` 后**仍为 0**（E10），故空视图必须自证并给 `window_hours=0` 出口。T-0.1/T-0.2 已于 2026-11-03 落地（active 90/90 可见，回归测试 4 条）。观察期指标也从「只有名字」落到 3 个写入点（§6.6）。

---

## 1. 与 v1 的关系：做对了什么，留下了什么

### 1.1 v1 已闭环的部分（本设计不动）

| 层 | 机制 | 落地位置 | 状态 |
|---|---|---|---|
| L1 归属 | `resolve_write_permission` → allow / allow_annotated / deny | `introspection/goal_coordination.py` | 已核，A1/A2/A3/A5/A6 PASS |
| L2 视图 | `coordination_status` 只读快照（goals / sessions / tasks 计数） | 同上 + `tools_goal.py` | 已核，A12 只读性 PASS |
| L3 依赖 | `Task.blocked_by_goals` / `deadline_at` + 环检测 + frontier 求值 | `task_store.py`、`tools_task.py` | 已核，A8/A10 PASS |
| L4 并发 | `Goal.version` + `expected_version` flock 内 CAS（**仅 goal 级**） | `goal.py:188/:256` | 已核，A11 PASS；task 无版本 CAS（§2.1-E2） |

**v2 的立场：以上四层不重做、不改语义。** RULE-AI-24 优先于任何"顺手优化"的冲动。

### 1.2 v1 自己登记的三个残余（本设计的直接输入）

引自 `DESIGN-20261101` §12.4：

| v1 残余编号 | 原文 | v2 的处置 |
|---|---|---|
| §12.4-2 | 「L2 running/events 未接线 → 谁在跑什么仍只能从账本推断」 | **N1**（P0）——v2.5 接 running、v2.6 接 events |
| §12.4-3 | 「任务级归属未加：同一 goal 内的任务仍可被任意会话改」 | **N2/N3**（P1/P2） |
| §12.4-1 | 「无 binding 执行无法验证 owner → 只能标注放行」 | 不在本设计范围（需注入 session 身份，见 §10-R1） |

### 1.3 v1 未提出、但会阻塞用户诉求的两点

| 缺口 | 事实 | v2 的处置 |
|---|---|---|
| workflow 并行是伪并行 | `workflow.py:242` 注释自陈「registry 有状态故不真并发」，`parallel` 走 `_execute_linear` 顺序执行 | **N6**（P2，可诚实降级） |
| 子代理并发口径不可配（v2.0 误判为「无上限」，见 §2.1-E1） | `runner.py:1363-1372`：`_reserve_background_child` 在 `_children_guard` 内先 `_prune_handles_locked(reserve_slot=True)`（只淘汰非 running），随后 `if len(self._handles) >= self._max_handles: return None` → spawn 回执「后台子代理资源已达硬上限（128）」（文案 `runner.py:1670`）。上限**存在**，但 (a) 口径是全局句柄表占用（含未收集的 terminal），(b) 数值硬编码，(c) 128 对 LLM 并发成本过高 | **N4**（P1，改判为「拆分口径」） |

---

## 2. 实证基线（v2 重新核实，含与 v1 表述的差异）

| # | 事实 | 位置 | 状态 |
|---|---|---|---|
| 1 | `Task.owner` 是**死字段**：`from_dict`/`to_dict` 存取，但全库无任何判定消费者；注释指向未实现的「T3 subagent typed contract」 | `task_store.py:91/:124/:168/:228` | 已核（`grep -rn "\.owner\b"` 无命中；`tools_task.py` 无 `owner=` 传参） |
| 2 | `coordination_status` 的 running/events 是**硬编码空数组 + 三条固定 degraded 字符串** | `goal_coordination.py:414-421`、`:428` | 已核 |
| 3 | runner 有全局 `_handles: dict[child_sid, handle]`，但公开 API 只有 `active_children(parent)`（per-parent）与 `pending_obligations(parent)`；**无全局枚举** | `runner.py:359/:637/:647` | 已核 |
| 4 | spawn **已有**全局 128 硬上限：锁内 prune（只淘汰非 running）后判 `len(_handles) >= _max_handles` → 拒绝 | `runner.py:353/:1363-1372/:1670` | 已核（v2.1 更正 v2.0 的「无 running 上限」） |
| 5 | `JobRegistry` 是单例（`.instance()`），有全局 `active_count()`，但明细接口均按 `session_id` 过滤 | `job_registry.py:88/:116/:212/:222` | 已核 |
| 6 | `mask_session` 是**截断前 8 字符**（非哈希，可关联），已在协调视图使用 | `goal_coordination.py:43-47` | 已核 |
| 7 | fleet 租约**无后台回收线程**：`reclaim_if_expired` 是唯一时间授权接管路径，live/unexpired/expiry-free 一律 `LeaseActiveError` | `fleet/store.py:17-19/:402-442` | 已核 |
| 8 | fleet 有 `_require_current`（active + current generation + unexpired），**过期租约不能自续** | `fleet/store.py:387-388` | 已核 |
| 9 | fleet 竞态契约有实测：racing reclaims 序列化为 takeover chain，无 phantom active | `fleet/store.py:9-12`；`tests/unit/test_fleet_reclaim_race_and_ttl.py` 存在 | 已核（文件存在）；已实测 PASS：2026-11-03 `.venv` 运行 9 passed |
| 10 | `workflow_run` 的 `parallel` 走 `_execute_linear` 顺序执行 | `workflow.py:242` | 已核 |
| 11 | `transfer_goal` 未实现，仅存在于拒绝文案第 3 出口 | `goal_coordination.py:142` | 已核 |
| 12 | claim 落地后 `task_update` 的现有调用方数量 | `registry_task.py:22-25`（唯一分发入口）→ `tools_task.py:214`（唯一实现 `run_task_update`） | 已核（2026-11-03）：程序内调用方唯一；运行时调用方=模型工具调用，claim 采纳率由 §11 观察期统计 |

**与 v1 表述的三处修正**（v1 若被照抄会误导实现）：

1. v1 §0.5「不引入租约回收器」被后续读者可能误读为「不做租约」。**准确表述**：否决的是**回收器**（后台线程 + 僵尸清理），不是租约语义本身；fleet 是"无回收器的租约"的存在证明。
2. v1 §2 与 v2.0 §1.3 都误判了 `_max_handles`。**准确表述（v2.1 实测）**：spawn 有**硬拒绝**——`_reserve_background_child` 在 `_children_guard` 内 prune 后判 `len(self._handles) >= 128` 即返回失败回执。它是「全局句柄表占用上限」，不是「running 计数上限」（terminal 会被 prune，未收集的 terminal 仍占位）。v2.0 把 docstring 的「running 永不被静默丢弃」错读成「running 无上限」——后者从未成立。
3. v1 §12.4-3 说"任务级归属未加"，语气像"少写了一段校验"。**准确表述**：`Task.owner` 字段已存在但从未被消费，是**预留但未激活**的插槽。

### 2.1 v2.1 勘误表（第二轮拷问的实测结论）

| # | v2.0 表述 | 实测事实 | 影响 |
|---|---|---|---|
| E1 | 「子代理 running 数无上限，spawn 200 会真的起 200 个」 | `runner.py:1363-1372`：`_children_guard` 内 prune 后 `len(self._handles) >= 128` → 返回 None，spawn 失败 | N4 改判：全局 `max_handles`(128) 保留 + 新增 per-parent `max_running_children`(8) |
| E2 | 「L4 版本 CAS 均已落地」「CAS 是第二道闸：写入时若版本变了，拒绝」 | `TaskStore.update()` 无 `expected_version`（`task_store.py:240-252`）；`expected_version` 仅存在于 goal 层（`goal.py:188/:256`） | task 写入无 CAS → claim 的 generation 是唯一并发控制 → 必须「校验+落笔同临界区」（§6.2） |
| E3 | `_collect_running` 读 `h.expires_at`、`h.parent_id` | `_SubAgentHandle` 无 `expires_at`、无 `started_at`；实有 `child_id/parent_id/depth/generation/state/...`（`runner.py:84-99`） | running 段只出 `state/depth/generation`；要出「已运行时长」须先给 handle 加 `started_at`（列为 N1 可选项，不做则不显示时长） |
| E4 | §8-T1/T3/T4 与 §11 把 N1/N2 写反 | N1=可见性接线，N2=claim | 纯编号笔误，已改正（断言内容不变） |
| E5 | 「过期即失权」照抄 `fleet/store.py` 的 `_require_current`（TTL is authority，N2-A7/G4） | 该语义在 fleet 成立是因为**检查在锁内、副作用提交在锁外**（effect fence 之间有时间窗）；本设计的组合入口把 check+write 关进同一临界区，窗口已不存在。真实账本：531 次 `in_progress` 期间写间隔 p75=21min / p90=73min，ttl=30min 时有 **19.2%** 的写会在无人抢占的情况下被判过期 | 语义改为「过期=可被接管」，不是「过期=失权」（Q33）；D2 的 30min 从危险值降为零成本值 |
| E6 | §12-D3 把「worktree 隔离 vs claim 协调」当二选一 | `_DEFAULT_DATA_DIR = _CODE_ROOT/"data"`（`config.py:14-25`，注释自陈 split-brain 修复）→ **每个 checkout/worktree 自带 `data/audit`**（已核 `.worktrees/*/data/audit` 各自存在）。故 claims 账本天然按代码根隔离，默认不存在跨 worktree 冲突 | D3 从"取舍"降级为"配置声明"：claim 作用域 = 一个 `data_dir`，不跨区承诺（Q36） |
| E7 | §12-D4 / N4 读起来像「把既有 128 闸拆成两个口径，per-parent 只是加个默认值」 | `runner.py:353` 只有一个全局 `_max_handles=128`；`_children_by_parent`（初始化 `:349`）只用于枚举/登记（`:639/:721/:850/:903/:1375`），**没有任何 per-parent 计数与拒绝逻辑**；字典清理只在完成路径（`:1161-1166`），`_prune_handles_locked`（`:618-634`）淘汰 handle 时不清它 → 集合长度不能当在飞数 | per-parent 16 是**新增闸**：计数须读 `handle.state == "running"`（`pending_obligations` `:641-660` 已是该过滤式，可直接复用），与 depth/128 在同一 `_children_guard` 内判定，回执加 `reason_code`；风险集中在 `runner.py:1354-1373` 一个函数 |
| E8 | 「视图覆盖全库 goal；goal 到千级才需要考虑索引」 | `goal_coordination.py:371` 硬编码 `list(limit=200)`；`goal.py:362-379` 是「全读 → 状态过滤 → 取末 200 行」。真实账本 239 行 → 视图 200 条，**12 个 active goal 不可见**（78/90，实测 2026-11-03） | 不是规模问题，是截断缺陷；P0 一行修复 + `degraded` 显式化（D5）。同时推翻「千级需要索引」的前提：实测成本线性 ≈0.066ms/goal，1600 goal 全量 106.6ms（§6.7） |
| E9 | 「窗口 24h = 最近有活动」 | 窗口只比较 `goal.updated_at`（`goal_coordination.py:220-222`），而 `task_store.update`（`:240-300`）全程只写 tasks 账本、从不触碰 goal 行（已核：该函数体内无 `Goal`/goal 账本写入） | 实测 90 个 active goal 的 goal 行最新 `2026-11-02T12:07`、task 行最新 `2026-11-01T22:42`，均超 24h → 默认视图当天 0 条。口径应改为 `activity_at = max(goal.updated_at, max(task.updated_at))`；这是口径补强（未发生的数据不得说成 bug）。**但口径修正不产生数据**，见 E10 |
| E10 | 「改了 `activity_at` 口径，默认 24h 视图就有内容」 | T-0.2 落地后实测（2026-11-03）：按 `max(goal.updated_at, task.updated_at)` 计算，24h 内 active **仍为 0**（goal 最新 `11-02T12:07`、task 最新 `11-01T22:42`，均在窗外） | 口径补强只保证「不误判陈旧」，不制造活动。本仓库 goal 推进是周/月级，24h 是**热窗口**而非**可见窗口**。故空视图不能靠改口径救，必须两条一起：① `degraded` 出 `window_empty: …账本内仍有 N 个 active goal 未进入窗口`；② 回执给 `window_hours=0` 出口。默认 24h 保留（已有测试 `test_coordination_defaults_match_design` 锁定，且避免全量 frontier 常驻开销） |
| E11 | §6.4 参考实现里的 `from llm_loop.subagent import get_runner` / `JobRegistry.instance() + snapshots_for_session` 可直接取数 | 实测（2026-11-03）：`subagent/__init__.py` **没有** `get_runner`（无 runner 访问器）；`introspection` 层也没有 runner/job 句柄；`snapshots_for_session` 返回「本地 job + durable 非终态 orphan」混合体，**不是**纯在飞集合 | 接线改走装配点注入：`build_engine` 里 `correction_ctx.subagent_runner = subagent_runner`、`correction_ctx.job_registry = _job_registry`；jobs 侧新增 `JobRegistry.active_all()`（与 `active_for_session` 同口径）。代价：重启后未收口执行不进 running 段（§10-R4 残余） |
| E12 | `active_children()` 的 docstring「当前仍在运行」= 实现事实 | 实现是 `sorted(self._children_by_parent.get(parent))`，**不看 `handle.state`**；`_prune_handles_locked` 淘汰 handle 时不清该集合（与 E7 同一处）→ 成员资格 ≠ 在飞 | 新接口 `all_active_children()` 显式按 `state == "running"` 过滤，调用方另做一次视图侧过滤（宁可少报，不可伪报在飞）。**旧接口语义漂移未改**（避免动既有调用方），仅登记 |

> 方法论备注：E1/E2/E3 同源——**读 docstring 就推断行为**。docstring 说的是「不丢弃 running」，不是「不限制 running」；`Goal.version` 的存在不等于 `Task` 有版本。凡涉及行为判定，必须以调用链与分支条件为准，不以注释与字段存在性为准。

---

## 3. 架构定位：四类并发控制的正交性

### 3.1 总表（本设计的核心论点）

| 机制 | 语义 | 粒度 | 拦什么 | 不拦什么 | 现状 |
|---|---|---|---|---|---|
| `goal.session_id` | **静态归属**（地盘是谁的） | goal | 跨会话误写他人 goal | 同一 goal 内多执行者 | v1 已实现 |
| `write_scope` | **物理写权**（哪个路径能写） | 路径 | 越界写文件 | 语义重复劳动 | P0 已实现，P1/P2 未启动 |
| `Goal.version` CAS | **乐观并发**（写时检测覆盖） | record | 基于旧版本覆盖 | 两人做同一件事 | v1 已实现 |
| **`TaskClaim`（本设计）** | **动态占用**（现在谁在做） | task | 重复劳动 / 双写同一任务 | 不同 task 写同一文件 | **无** |

**一句话**：v1 解决了「写错人」与「写冲突」，v2 补「重复做」与「看不见」。

### 3.2 为什么「状态」不构成「占用」（关键论证）

`task_update` 的判定是「这次迁移合法吗」。它**只看目标状态能否从当前状态迁移**，不看此前是谁在做。构造反例：

```
t0  S1: task_frontier → 读到 task T 状态 pending
t1  S1: task_update(T, in_progress) → 成功（task 账本追加一行）
t2  S2: task_frontier → 读到 task T 状态 in_progress（这是最新状态，不是过期版本）
t3  S2: task_update(T, in_progress, title="补充说明") → 也成功
```

**两次写入都成功，没有任何机制知道「T 已经在被 S1 做」。** 需要特别指出（v2.1 更正）：`task_update` **没有** `expected_version` 参数——版本 CAS 只存在于 goal 层（`goal.py:188/:256`），而 t1/t3 都不改 goal 版本，所以「CAS 全绿」这个说法在 task 层无从谈起：**根本没有 CAS 可绿**。

claim 补的正是这一刀：**在 t1 之前就问「这个 task 有没有人正在做」**，有则 fail-closed。

### 3.3 task 级没有 CAS，所以 claim 必须自带 fencing

v2.0 曾写「claim 管能不能开始，CAS 管能不能落笔」。第二轮核实推翻了这个分工：`TaskStore.update()` 无 `expected_version`（`task_store.py:240-252`），**task 写入路径上不存在版本 CAS**。因此 claim 不能只做「入口检查」，否则就是 check-then-act 的 TOCTOU：

```
t0  S1 claim T（generation=1），开始实现
t1  S1 连续 40min 无 task 写入（在读代码 / 跑测试）
t2  ttl 到期，S2 的 claim_task 原子接手（generation=2）
t3  S1 回来 task_update → 若只查「t0 那一刻有效」，写入成功 → 覆盖 S2 的成果
```

正确的分工是三条，缺一条就有洞：

1. **generation 是写路径上的 fence**：每次写入都要求 `token.generation == 账本当前 generation`，落后即拒（不静默降级）。
2. **校验与落笔必须在同一个 claims 临界区内**（§6.2）：否则 t3 的「检查」与「写入」之间仍有窗口，边界竞态（F8）会重现。
3. **task 层不引入版本**：这是有意选择。给 task 加版本会与 frontier 求值、done→in_progress 重开级联、`no_change` 空写优化三处交织，收益小于风险；claim 的 generation 已承担「落笔被拒」的职责。

**代价（诚实登记）**：没有 task 版本意味着「基于陈旧 frontier 的决策」仍可能落到账本上（只要 claim 仍有效）。这由 §10-R12 登记，不由本设计掩盖。

### 3.4 为什么必须下沉到 task 级（不能复用 goal 级互斥）

用户诉求原文是「同时推进各项任务进行」。一个 goal 下常有 N 个可并行 task：

```
GOAL-xxx (owner = sess-A)
├── T1 抓取数据      ← 子代理 C1 做
├── T2 设计 schema   ← 子代理 C2 做
├── T3 写迁移脚本    ← 父会话做
└── T4 依赖 T2/T3    ← 等
```

若把 v1 的 L1 归属下沉成「goal 级互斥」，上面三条并行立刻变串行——**直接违背诉求**。所以互斥的粒度必须是 task。claim 的并行度上界是「不同 task 的数量」，这正是我们要的。

### 3.5 分工边界（防止实现越界）

| 问题 | 归属机制 | 本设计是否处理 |
|---|---|---|
| 别人正在做 T1，我想做 | **claim** | ✅ |
| 我 claim 了 T1，但想写 x.py，而别人在写 x.py | `write_scope` | ❌ 仅**预检警告**（N5） |
| 我 claim 了 T1，基于旧状态写 | `version` CAS | ❌ 已有，不动 |
| 别人在另一个 workspace 做同样的事 | 不支持 | ❌ 明确非目标 |
| 我的子代理在跑，我不知道 | **coordination_status**（N1） | ✅ |

> **硬边界**：claim **不授予**任何路径写权限、不提升工具权限、不跨 goal 越权。claim 只回答"这个 task 现在归谁推进"，其余一律照旧判定。任何"claim 了就都能写"的实现都是在复制 `DESIGN-20261030` 批判的"帮忙式越权"。

---

## 4. 拷问记录（四轮 Q1–Q45）

> 目的：把"看起来合理"的设计压到"能被证伪"的程度。每条必须给出**留下的残余**，没有残余的答案视为未想清楚。

### A 组：定位

**Q1：这套东西是不是"给不会协调的模型加复杂度"？v1 Q1 已经问过一次了。**
A：是，若它要求模型主动去查。所以 N1 的设计原则是「视图挂在默认回执尾部」，不是「多一个工具等人调用」。v2 与 v1 有个关键不同：v1 加的是**约束**（拒绝写），v2 的 N1 是**消除无知**（告诉它谁在跑）。消除无知不增加决策分支，只减少盲区。
**残余**：模型不看回执尾部的话，N1 收益趋零。这就是为什么 N1 必须同时挂到 `create_goal` / `task_create` / `task_frontier` 三处，而不是只做一个独立工具。

**Q2：为什么不直接用 git worktree？多任务并行不是有现成方案吗？**
A：worktree 解决的是"同一代码库两个分支互不干扰"。它解决不了：(1) 非代码任务（写文档、跑分析、抓数据）；(2) 共享资源（同一个 output 目录、同一个浏览器会话、同一个 job 注册表单例）；(3) 两个 agent 同时改同一个 goal 的 task 状态——那是**账本冲突**，不是文件冲突。
worktree 是文件系统隔离，claim 是语义占用。LFL 不是代码协同工具，任务主体不是 git 分支。
**残余**：若用户实际场景 90% 是代码改动，worktree 性价比更高。此点需用户确认（§12-D3）。

**Q3：为什么不用 DAG 调度器（Airflow / Celery）？**
A：三条否决：(1) 引入新进程 + 新存储，直接违反 v1 §1.3「不做常驻协调进程/队列/消息总线」；(2) 调度器假设"任务可被程序预先编排"，而 LFL 的推进者是 LLM，无法在事前声明准确时长与依赖；(3) `task_store` 已有依赖图 + frontier 求值，重建会双写。
**残余**：未来若需要"定时批量推进"，DAG 调度器是正确答案，但那不是当前诉求。

**Q4：已有 goal/task/CAS/write_scope 四套机制，再加 claim 是否抽象过载？能合并吗？**
A：不能合并，因为拦的失败模式不同（§3.1）。合并的信号是"两个机制拦同一个失败"，此处不存在。
但**能收敛**的是：claim 不新增存储引擎、不新增后台线程、不新增配置面——复用 flock + JSONL + 惰性过期。**概念 +1，机制 +0**。
**残余**：实现期若给 claim 加了独立锁服务或缓存层，就真的过载了。这是本设计最重要的实现纪律。

### B 组：claim 语义

**Q5：claim 和 `task.status=in_progress` 有什么本质区别？是不是同义词？**
A：三处区别：
1. **签发者不同**：status 由调用方写（模型说"我在做了"）；claim 由程序签发（程序说"归你做"）。
2. **可验证性不同**：status 无凭据，任何人可改；claim 有 `claim_id + generation`，写 task 时必须持有效 token。
3. **失效语义不同**：status 不会自己失效；claim 有 ttl，过期即失效，且**过期后不可自续**。
若实现成"status=in_progress 就等价于 claim"，这层白做。**必须有一个模型无法伪造的凭据。**
**残余**：凭据校验只在 `task_update` 一个入口做，其他写路径（如直接改 JSONL）不受约束——这是所有应用层机制的共同残余。

**Q6：两个会话同时 claim 同一个 task，谁赢？会不会双赢？**
A：flock 内串行。第一个追加成功拿 `generation=1`；第二个在锁内看到 active 且未过期 → `Conflict`（含 holder 脱敏、剩余窗口 `remaining_s`、`generation`）。**不会双赢**，因为判定与追加在同一临界区（`fleet/store.py:318` 的 `reclaim` 同构）。
**残余**：若两份 claims 文件因路径写法不同（相对 vs 绝对 vs symlink）被当成两个文件打开，flock 会失效。实现必须 `realpath` 归一。

**Q7：持有 claim 的会话崩溃了怎么办？**
A：ttl 兜底。过期后任何人可再次 `claim_task` 原子接手（回执 `reclaimed=true`），锁内只有一个赢家（与 fleet 同构）。崩溃者的记录保留为 `expired`，供审计，不删除。
**残余**：ttl 越长，僵死窗口越长。默认值需按"典型任务时长 + 裕量"定（§12-D2）。

**Q8：长任务要 3 小时，ttl 设多久？频繁续期是不是负担？**
A：两档：
- **短任务（默认）**：ttl 30 分钟，不续期，做完即 release。
- **长任务**：显式 `renew_claim(extend_seconds)`。**不做自动心跳**——心跳需要后台线程，正是 v1 否决的东西。
关键实现细节：`renew` 挂在「`task_update` 且 status 仍为 in_progress」时**顺带续期**（同步动作，零后台线程）。这样模型只要持续工作就自动续命，停止工作则自然过期。
**残余**：模型若长时间思考而不写任何 task 更新（例如一次 40 分钟的长推理），仍可能被抢。缓解是 ttl 默认值给足裕量。

**Q9：claim 过期后，原持有者仍在干活（只是网络慢），会不会"僵尸复活"写出脏数据？**
A：会，除非有 fencing。`task_update` 必须校验 token 的 `generation == 账本当前 generation`。被 reclaim 后账本变 N+1，旧 token 的写入一律 `claim_generation_stale` 拒绝。
**这是 fencing 的全部意义**：不是"阻止他写"，而是"让他的写可被识别为过期"。直接复用 `fleet/store.py:387` 的 `_require_current` 语义。
**残余**：claim 只管 task 状态写入，管不到他直接写文件（那是 write_scope 的领域）。

**Q10：claim 能不能跨 goal？一个子代理能否同时持两个 goal 的 task？**
A：能，且应该能——用户诉求正是"同时管理多个任务"。主键是 `(goal_id, task_id)`，一个 holder 可持多条。
但加软约束：同一 holder 的 active claim 数超过阈值（默认 8）→ 回执警告"你可能并行过多"。**只警告，不阻断。**
**残余**：阈值是启发式，需实测调。

**Q11：子代理需要 claim 吗？还是父会话代 claim？**
A：**子代理自己 claim**，以 `child_sid` 为 holder，`holder_kind="subagent"`。父代 claim 会让"谁实际在做"再次丢失，且父无法感知子的完成时机。
现实约束：`spawn_subagent` 异步，子启动后才 claim，存在"已 spawn 未 claim"窗口。缓解：父会话 spawn 时**预声明** `intended_claims`，子启动后必须 claim 其中之一，否则视图层标 `claim_missing`。
**残余**：预声明与实 claim 不一致时只能告警，不能自动修正。

**Q12：claim 强制后，现有 main-only 流程会不会全部拒绝？**
A：会，如果一步强制。三档迁移（§11）：P1 软接入（无 claim → degraded 告警但放行）→ 观察期 → P2 硬拒（config 开关，默认关）。与 v1 落地 L1 时"标注放行"策略同构。
**残余**：若永远不开 P2，软接入只带来可见性、不防重复。需用户裁决（§12-D1）。

### C 组：可见性

**Q13：`coordination_status` 列出所有 session 的 running child，是否越权泄露？**
A：会。所以按三档披露，默认最严：
- **自己**：完整（`child_id`、`state`、`depth`、`generation`；handle **无** `expires_at`，见 §2.1-E3）
- **其他会话**：脱敏（`mask_session` 前 8 字符 + 计数），不列 `child_id`
- **聚合**：`JobRegistry.active_count()` 只给总数

这与 v1 §2-8「`job_output` 跨会话读不到」的既有边界一致——**视图不扩大读权**。
**残余**：`mask_session` 是截断不是哈希（`goal_coordination.py:47` 已核），前缀可被关联到已知 session。改哈希会破坏 v1 既有回执的可读性，本期不动，登记为已知弱化。

**Q14：为什么不能直接让模型去问另一个会话？**
A：因为"问"需要知道问谁，而跨会话消息通道 `agent_message` 只允许 parent↔direct active child，sibling / unknown / grandparent 一律拒绝（`runner.py:688+` docstring 已核）。模型**没有能力**广播询问。只读视图是唯一可行的发现机制。
**残余**：视图是拉取式，不是推送。模型不调就不看（同 Q1）。

**Q15：running children 接线后会不会信息过载？**
A：会，如果有 20 个子代理。默认 `only_in_flight=true` + top-N（默认 10）+ 其余仅计数，`include_all=true` 展开。v1 的 `window_hours` / `only_in_flight` 参数已支持。
**残余**：N 值需实测调。

### D 组：并发与资源

**Q16：子代理真的有全局并发上限吗？128 是什么？**
A（v2.1 更正）：**有上限；v2.0 说「无上限」是错的。** `_prune_handles_locked(reserve_slot=True)` 只淘汰非 running 的 handle，随后 `_reserve_background_child` 判 `if len(self._handles) >= self._max_handles: return None`，spawn 直接失败并回执「后台子代理资源已达硬上限（128）」（`runner.py:1363-1372`、文案 `:1670`）。
所以 128 是**全局句柄表占用上限**（近似 = running + 未收集的 terminal），三个问题：(a) 口径不可配；(b) 与句柄表容量耦合——腾空间靠「收集 terminal」而不是「子代理跑完」；(c) 128 对 LLM 成本过高（最坏 128 路并发流）。
N4 因此改判为**拆口径**而非新建机制：保留 `max_handles=128`（进程保护），新增 per-parent `max_running_children=8`（成本保护，可配 1..32）。判定顺序 depth → global → per-parent（§6.5）。
**残余**：闸只覆盖本进程 `spawn_subagent`；DSH / browser 通道不计入（§10-R11）。拒绝会打断「批量 fan-out」用法，先拒绝不排队（排队需调度器，Q3 已否决）。

**Q17：`workflow_run` 的 parallel 是伪并行，要不要修？修它是不是跑偏？**
A：要处理，但不是 P0/P1。理由：用户诉求"同时推进"里，`parallel` 是最直接的表达面；若它实际顺序执行而回执不说，模型会**以为自己在并行**——这是观测失真，比性能问题更严重。
两条路：(a) 真并发（需解决 step 间共享 registry 状态，成本高）；(b) **诚实降级**——回执明写"本批次顺序执行"并加 `execution=sequential` 标注。
**v2 首选 (b)**：先消除失真，再谈性能。
**残余**：不修 (a) 的话，"parallel"这个词在系统里始终名不副实。诚实登记。

### E 组：失败与边界

**Q18：claim 账本和 task 账本分裂成两个文件，会不会不一致？**
A：会，但方向可控。设计原则：**事实优先于权利**。
```
claim 有效 ⟺ state=active ∧ 未过期 ∧ task.status ∈ {pending, in_progress}
```
task 已 done / cancelled 时，即使 claim 未过期也自动失效，**无需回写 claim 账本**。这样"task 完成但 claim 没释放"不会锁死。
反向（claim active 但 task 不存在）→ 孤儿 claim，视图标 `orphan_claim`，不自动清理。
**残余**：两账本非同一事务。最坏情况是"别人 claim 时先遇 Conflict，再被惰性失效"，多一次往返，不产生错误状态。

**Q19：ttl 用 wall clock，时钟回拨怎么办？**
A：必须用 `time.time()`（跨进程共享时基；monotonic 不可跨进程比较）。回拨会让 claim "看起来没过期"（延长占用）或"看起来早过期"（提前可抢）。
缓解：(1) ttl 加最小裕量；(2) **时间不是安全机制，generation 才是**——回拨只影响可用性方向，不影响 fencing 安全性。
**残余**：这个区分必须写进实现注释，否则后人会用时间戳做安全判定（这是常见错误）。

**Q20：这套机制能防止"两个会话写同一个文件"吗？**
A：**不能**。claim 是 task 级，不是路径级。两个不同 task 完全可能都需要改 `config.py`。
这是 `write_scope` 的领域（只有 P0 落地）。v2 只做**预检警告**（N5）：claim 可声明 `expected_paths`，与另一 active claim 重叠时回执警告，**不阻断**（可能只是读）。
**明确不做**：claim 自动获取路径写权。那会让"抢占 task"等价于"抢占任意文件"，是权限放大。
**残余**：不阻断意味着重叠写仍可能发生，只能事后从 `verify_path_scope` 发现越界。

### F 组：诚实性

**Q21：做完这些，模型就会协调了吗？**
A：不会。claim 只保证"不会两个人做同一件事"，视图只保证"看得到谁在跑"。**策略仍靠模型**：怎么拆 task、并行几个、冲突时让谁等——这些是判断，不是机制。
真正的收益是把失败从"静默重复劳动"变成"显式冲突 + 可执行出口"。与 v1 §8-Q8 同构。
**残余**：软接入期若模型不用 claim，收益接近 0。

**Q22：怎么证明"已生效"而不是"代码存在"？**
A：RULE-AI-35 守卫实验，必须构造真实输入拿到拒绝回执：
| # | 构造输入 | 必须得到 | 反模式 |
|---|---|---|---|
| G1 | 两线程同时 claim 同一 task | 一个 `Granted`、一个 `Conflict` | 两个都 Granted |
| G2 | 用已被 reclaim 的旧 token 写 task | `claim_generation_stale` | 写入成功 |
| G3 | 用别人的 token 写 task | `claim_holder_mismatch` | 写入成功 |
| G4 | 已过期的 token 写 task（**未被接管**） | 写入成功 + `claim_expired_renewed=true`（原为 `claim_expired` 硬拒，Q33 修订） | 静默放行且不续期（时间窗无人知） |
| G5 | 对 done 的 task claim | `task_not_claimable` | 拿到 claim |
| G6 | spawn 超过 `max_running_children` | 拒绝 + 当前计数 + 出口 | 静默起满 |
| G7 | 调 `coordination_status` 前后 | 两账本 sha256/mtime 不变 | 任一变化 |
| G8 | 无 claim 的 session 写 in_progress（P2 开启时） | `claim_required` | 放行 |
| G9 | 重开（done→in_progress）后旧 token 写 | `claim_revoked` | 写入成功 |
| G10 | 传 `holder=` 伪造他人身份 claim | 参数被忽略/拒绝，账本 holder=本 session | 账本记成伪造值 |
| G11 | 两个形似 goal_id（`GOAL/a` vs `GOAL_a`）各 claim 一次 | 两份 claims 文件，互不干扰 | 同一文件串号 |

仅"有代码 + 有单测"不算生效。

---

### 4.2 第二轮拷问（Q23–Q32：全部以源码实测为准）

> 第一轮问的是「要做什么」，第二轮问的是「按这个实现会不会坏」。下面每条的结论都改动了 §5/§6 的具体条款。

**Q23：claim_task 持 claims 锁时去读 task 账本，而 task 写也拿 task 锁——会死锁吗？**
A：会，如果锁序不统一。实测锁结构：`TaskStore.get()` 走 `_file_lock(goal_id)`（`task_store.py:236-238`，**EX 排他**，读写同锁），`TaskStore.update()` 也走同一把锁（`:258`）。因此 `claim_task`（claims 锁内调 `get`）的天然顺序是 **claims → tasks**；若 `task_update` 写成「先 update（持 task 锁）再校 claim（要 claims 锁）」，就是 **tasks → claims**，两条路径交叉即 ABBA 死锁（同进程两线程即可触发，`flock` 不区分线程）。
**定死规则**：全局锁序 `claims → tasks → goal_coord`，**任何路径不得在持 tasks 锁时申请 claims 锁**。实现上一律先取 claims 锁，再在锁内调 `TaskStore`（get/update 都在内层）。
**残余**：`_lock()` 是 fail-open（`task_store.py:747-756`，OSError 时直接 yield，注释自陈「锁不可用时不阻塞后续逻辑」）。即锁在异常文件系统上失效时，claims 的互斥也会静默降级为「无锁」——由 §10-R7 登记，不在本设计修。

**Q24：既然 task 没有版本 CAS，fencing 检查与 task 写入分成两步安全吗？**
A：不安全。`require_current` 通过后到 `store.update` 之间，claim 可能被 reclaim（ttl 边界或显式 reclaim），结果是「检查时有效、写入时已无权」。
**修正**：N2 的实现必须提供**组合入口** `update_task_under_claim(goal_id, task_id, token, **fields)`：单个 claims 临界区内完成 `replay → require_current → TaskStore.update`。禁止调用方自己拼「先 require_current 再 update」。
**残余**：组合入口把 task append 纳入了 claims 锁的持有期（毫秒级）。若 task 账本极大（replay 慢），claim 竞争会排队——量级评估：单 goal task 数 < 200、单行 < 1KB，replay < 5ms，可接受；超出则需游标化，登记为后续性能项。

**Q25：`holder` 从哪来？如果由模型传参，token 绑 holder 还有意义吗？**
A：**没意义，必须由程序注入。** 若 `holder` 来自 `args`，模型只要把别人的 session id 填进 `holder` 就能通过 `cur.holder == holder` 校验——R1 从「弱假设」升级为「可绕过」。
**修正**：`holder = authority_session_id()`（`goal_coordination.py:33-39`，内部走 `tools_status.bound_session_id()`，是运行时绑定而非模型输入）；`holder_kind` 由运行时判定（子代理会话 → `subagent`，否则 `main`）。**session 不可证明（空串）时拒绝 claim**，回执 `claim_unverifiable` + 出口「在工具调用上下文内重试」——比 v1「标注放行」更严，理由：无主 claim 会让 fencing 失去比对基准。
**残余**：同一 session 内的多个 run（父子同 session、重启后的新 run）仍不可区分——R1 保留，但范围显著缩小。

**Q26：`claims/<goal_id>.jsonl` 直接拼 goal_id 有风险吗？**
A：有，且是**串号级**风险。`TaskStore._path` 对 goal_id 做了归一：`re.sub(r"[^A-Za-z0-9_-]", "_", goal_id)`（`task_store.py:145-152`）。若 claims 直接 `f"{goal_id}.jsonl"`，则形如 `GOAL/a` 与 `GOAL_a` 的两个 goal 会共享同一个 claims 文件（一个带路径分隔符的 goal_id 还会**逃出目录**）。
**修正**：claims 复用同一归一函数（抽 `_safe_goal_id()`，与 task_store 逐字符一致），并在 `claim_task` 入口断言归一后非空、不含 `/`。加单测：两个形似 goal_id 的 claims 文件必须不同。
**残余**：归一本身有单向性（不同 goal_id 可归一为同名，如 `A.B` 与 `A_B`）——两者仍会撞。这是 task_store 已有的同类弱点，本设计不扩大也不修，登记 §10-R13；实际 goal_id 形如 `GOAL-20261103-<hex8>`，不触发。

**Q27：task 从 done 重开为 in_progress 后，旧 claim 会「复活」吗？**
A：**会**，这是 v2.0 的漏洞。有效性判定是 `state=active ∧ 未过期 ∧ task.status ∈ {pending, in_progress}`（Q18）；`task_update` 允许 `done → in_progress` 重开（`task_store.py:253-257` 的 `confirm` 就是为此存在）。于是：A 做完 → done（claim 读时失效）→ 数小时后 B 重开 → A 的旧 claim 若仍在 ttl 内，**判定重新成立**，B 与 A 同时「有权」。
**修正**：引入 `revoke_all` 账本行。`tools_task.run_task_update` 在 `done → in_progress` 迁移成功后，向 claims 账本追加 `{"kind":"revoke_all","task_id":...}`，使该 task 全部 active claim 失效（`state` 不变，但 `revoked=True`）；有效性判定追加 `not revoked`。顺序为**先撤销、再重开**：最坏情况是撤销成功而 update 失败 → 无人可写（fail-closed，安全侧）。
**残余**：两文件非同一事务（§10-R10）；且 `revoke_all` 由工具层编排，绕过 `task_update` 直接写 task 账本的路径不会触发撤销（R2 入口绕过的子集）。

**Q28：`claim_task(reclaim_if_expired=true)` 与独立 `reclaim_if_expired()` 是不是同一件事？**
A：是，且 v2.0 写重了。§6.2 的 claim_task 分支 (4) 对过期 claim 直接接手并递增 generation——这**就是 reclaim**。再暴露一个 `reclaim_if_expired` 工具面，会制造「两条路径、两种回执、两处竞态」。
**修正**：收敛为**三个**工具面：`claim_task`（含过期原子接手，回执带 `reclaimed=true`）、`renew_claim`、`release_claim`。删除 `reclaim_if_expired` 参数与工具；§6.3 出口 2 文案改为「直接重新 claim，过期会被原子接手」。

**Q29：ttl 判定用 `time.time()`，进程内与跨进程的时钟回拨分别怎么处理？**
A：进程内用**单调钳制**：模块级 `_last_now`，每次 `now = _last_now = max(_last_now, time.time())`，保证同进程内 `now` 只进不退。跨进程无法共享单调钟（`monotonic` 起点不同），所以跨进程回拨仍可能把「已过期」看成「未过期」。
**修正**：接受该残余并写进注释——回拨只延长占用窗口（可用性），不放大权限；安全边界是 generation，reclaim 后的旧 token 仍被 `claim_generation_stale` 拒绝。登记 §10-R9。
**残余**：极端回拨（小时级）会让孤儿 claim 长期占位，需人工 `release_claim`。不加「回拨检测告警」，因为无法与正常休眠区分。

**Q30：三道闸（depth / 128 / per-parent）的判定顺序与回执怎么统一？**
A：顺序必须固定，否则回执会误导（例如实际被 depth 拦，却报「并发已满」）。定为：`depth ≥ max_depth(3)` → `len(_handles) ≥ max_handles(128)` → `per-parent running ≥ max_running_children(8)`。三闸都在 `_reserve_background_child` 的**同一把 `_children_guard` 临界区**内判定（否则 per-parent 计数会 TOCTOU）。回执分别给 `reason_code=depth_exceeded / handle_capacity / parent_concurrency`，每条都带「当前计数 + 出口」。
`max_running_children=8` 的依据：单会话并行 8 路子代理 ≈ 8 路 LLM 流，是「能真并行推进」与「成本可控」的折中；上限可配到 32，超过仍受 128 全局约束。**这是建议值，不是实测最优值**（§12-D2 一并裁决）。
**残余**：per-parent 计量读的是 `_handles` 里 `parent_id == sid ∧ state == "running"`，不含排队/被 DSH 接管的执行体（R11）。

**Q31：`create_goal` / `task_create` 尾部追加「在途摘要」，会不会让创建操作被视图拖垮？**
A：会，若采集器抛异常或阻塞。工具层 import runner / JobRegistry 属于**反向依赖**（introspection → subagent），且 `collector` 遍历 `_handles` 需拿 `_children_guard`，与 spawn 竞争。
**修正**：三条硬约束——(a) 采集全程 `try/except`，异常时**静默省略该行**（不写 degraded、不影响主回执成功）；(b) 采集是纯读内存 + 已加载账本，不做网络/子进程；(c) 只在 `only_in_flight` 口径下取 top-N（默认 3 条 + 其余计数），不回放完整视图。加断言 N1-A7：采集器抛异常时 `create_goal` 仍成功且回执无异常行。
**残余**：反向 import 仍是模块耦合，若 runner 初始化失败会连带失去摘要行（已被 (a) 兜住）。

**Q32：并发相关的测试怎么避免 flaky？**
A：**不靠 sleep 竞速，靠状态构造**。三类手法：
1. **确定性竞态**：「先 claim A → 把 ttl 改成 0（注入时钟）→ claim B」得到 `reclaimed`，再用 A 的旧 token 写 → 必须 `claim_generation_stale`。全程无并发，断言确定。
2. **真并发只用于「恰好一个赢家」类断言**：`multiprocessing` N 进程 + `Barrier` 同步后同时调 `claim_task`，断言 `Granted == 1 ∧ Conflict == N-1`，且账本只多 1 行 active。允许重跑 3 次取稳定。
3. **锁序死锁用超时失败暴露**：两线程各持一把锁反向申请，`join(timeout=2)` 未退出即判失败——不是「偶尔卡住」，而是**必然失败**的可观测信号。
**残余**：macOS 上 `flock` 对 `fork` 继承有语义差异，多进程测试须用 `spawn` 启动方式（不是 `fork`），否则子进程共享同一把锁——测试会「假通过」。

---

### 4.3 第三轮拷问（Q33–Q39：用真实账本统计推翻语义前提）

> 本轮不新增功能，只做一件事：把 §6 里"照抄来的语义"和"没定义的边界"拉到真实数据前对质。账本口径：`data/audit/tasks/*.jsonl` 全量 1710 行 / 605 task / 141 goal（2026-11-03 读取；同日 19:26 第四轮复测为 239 goal / 282 task 文件，差额来自当天新增 goal）。

**Q33：过期意味着「失权」还是「可被接管」？（与 Q19 自相矛盾）**
A：v2.1 写了两条互斥的话。Q19/§6.2-不变量 3 说「时间只影响可用性，不影响安全性，安全边界是 generation」；而 N2-A7/G4 又说过期 token 写入 → `claim_expired` **硬拒**——那是把时间当成了写入权的边界。两条不能同时成立。
**实测代价**：从账本重建 531 次「状态为 `in_progress` 期间的连续写间隔」——p50 169s、p75 21min、p90 73min、p95 3.1h、max 73h。ttl=30min 时 **19.2%** 的写间隔超过阈值，即近五分之一的正常写入会在**没有任何人抢占**的情况下被硬拒；ttl=60min 仍有 11.5%，120min 7.2%，240min 3.0%。
**为什么 fleet 的语义搬不过来**：`fleet/store.py` 的 `_require_current` 与副作用提交之间隔着 effect fence（检查在锁内、真正提交在锁外），过期即失权是为了防止僵尸在那段窗口里复活。本设计的组合入口把 `check_current` 与 `TaskStore.update` 关在同一 claims 临界区（Q24），僵尸的写只可能落在两种时刻：抢在接管前（此时 generation 仍匹配，这次写入本来合法，且无并发对手）、或在接管后（generation 落后，必被 `claim_generation_stale` 拒绝）。**时间不需要、也不应该再承担安全职责。**
**修正**：`renew_claim` 允许「已过期但未被接管」的 claim 续期（回执 `renewed_after_expiry=true`）；`update_task_under_claim` 对「已过期 + generation 匹配 + 未 revoked」的 token **放行**并顺带续期（回执 `claim_expired_renewed=true`）。只有 `state ∈ {superseded, released}` 或 generation 落后才拒。
**残余**：接管仍会发生（这就是 ttl 的用途）——被接管的原 holder 在下一次写入时才知道，回执必须写明「已由 `sess-xxxx…` 于 <ts> 接管」。

**Q34：claims 账本的坏尾行与增长，谁负责？**
A：两条都没写，且都会致命。**坏尾行**：`task_store._replay` 的既有口径是「坏行跳过 + 告警」（`introspection/task_store.py` `_replay`），而 §6.1/§6.2 的 claims replay 只写 `replay_last_wins`，未定义异常行为——append 中途崩溃留下的半行若让 replay 抛异常，此后**每一次** claim 与写入都失败，fail-closed 直接变成可用性事故（且无法自愈，只能人工删文件）。**修正**：claims replay 与 task_store 同构（跳过坏行 + degraded 计数，绝不抛）；append 持锁单次 `write` 整行。
**增长**：fleet 是整文件重写（天然压缩），append-only 没有压缩。按 renew-on-write，行数 ≈ task 写次数（历史 1710 行 / 605 task / 141 goal，单 goal 最多百行级）。**修正**：单文件 > 2000 行时折叠为「快照行 + 尾部增量」，压缩失败只是不压缩，不影响正确性（§10-R15）。

**Q35：`expires_at: None`（显式无限期）谁能请求？**
A：§6.1 定义了它，却没规定授权来源。若 `ttl_s=None` 是模型可传参数，模型可以 claim 全部 task 并永不释放——一个**模型级 DoS**，且直接违反「模型不是调度者」（§4-Q21）。**修正**：`ttl_s` 一律 clamp 到 `[60, max_claim_ttl_s=28800]`；`None` 仅当配置 `allow_unbounded_claim=true`（默认 false）才接受，否则 `claim_ttl_out_of_range` + 出口。（N2-A16）

**Q36：D3 的「worktree vs claim」是不是伪二选一？**
A：是。`_DEFAULT_DATA_DIR` 绑定**代码根**（`config.py:14-25`），实测 `.worktrees/*/data/audit` 各自独立存在——两个 worktree 的 task/claims 账本从一开始就是两套，claim 冲突在默认配置下**不可能发生**。实测规模：82 个 session workspace 中 16 个是 worktree（19.5%），但 1745 个 child 里只有 8 个（0.5%）来自 worktree 内的 parent。**结论**：不需要 `git rev-parse --git-common-dir` 归一（省一次 subprocess 与一整类跨区 bug），只需在设计里写死「claim 作用域 = 一个 `data_dir`，跨 `data_dir` 不承诺」。真正需要预检的仍是同区内两个 task 改同一批文件（N5 保留）。**残余**：用户显式共享 `DATA_DIR` 跨 worktree 时，账本同源但代码状态不同，claim 会把「不同代码上的同一 task」当成同一占用——该配置不在承诺范围，回执口径需写明。

**Q37：组合入口的锁持有期到底多贵？（§13 ① 结案）**
A：实测结案，不进性能项。最大 goal 账本 71KB / 单次 replay **0.18ms**；全库 1710 行 6.5ms。组合入口每次只 replay 单 goal（≤百行），锁持有期 ~0.2ms，比一次工具调用的序列化开销低两个数量级。真正的长期风险是行数线性增长，由 Q34 的 2000 行压缩阈值兜住。

**Q38：`revoke_all` 的失败组合只登记了一半**
A：§10-R10 只覆盖「撤销成功 + update 失败 → 暂时无人可写」（fail-closed，安全侧）。漏了反向：**撤销失败（IO/锁不可用）+ update 成功 → 旧 claim 复活**，即 Q27 的漏洞原样重现，且不会有人发现。**修正**：撤销失败必须**中止**重开（fail-closed 要落在"不许重开"，不是"继续重开"），回执 `revoke_failed` + 出口（重试撤销 / 放弃重开）。第三个组合（缺 `confirm` 不迁移）不触发撤销，顺序天然正确。

**Q39：N1 的 children 归属与 in-flight 判据**
A：两处易错。(a) `_children_by_parent` 在**完成路径**会 discard（`runner.py:1155-1170`），但 `_prune_handles_locked` 不清它——所以"集合里有没有"**不能**当 in-flight 判据，必须读 `handle.state == "running"`；N1 实现约束补一条，防实现者拿 `active_children()` 当 running 集合。(b) child 只能经 goal 的 `owner_session_id` 归属；无 owner 的 goal 落在 `<unclaimed>` bucket，children 恒为空——回执必须标 `children_scope=owner_session`，否则读者会把"没有 owner"读成"没人在跑"。

### 4.4 第四轮拷问（Q40–Q45：把「埋在哪一行」「要花多少毫秒」问到底）

前三轮收尾时留下的两类问题（§13 原「下一轮」）：观察期指标只有名字、没有采集点；`coordination_status` 的成本曲线未知。本轮把两问都量到代码行与毫秒，并带出三处修正。

**Q40：观察期指标要埋在哪一行？**
A：原稿只有指标名（冲突率/接管率/误拒率），没有写入点——P0 上线第一天就会缺数据。**修正**：三个写入点，各自落在既有临界区内，不新增锁：
(a) `task_store.update()` 的 claims 临界区（`task_store.py:258` 的 `with self._file_lock(goal_id)` 内、`_append`（`:736-741`）之后）→ `claim_decision`；
(b) `runner._reserve_background_child()` 的 `_children_guard` 内（`runner.py:1354-1373`）→ `fanout_decision`；
(c) `coordination_snapshot()`（`goal_coordination.py:348`）**不写事件**——读路径零写，只填 `degraded`。
事件落 `data/audit/claims/events.jsonl`（与 claims 账本同目录、独立文件）：不混进 357MB 的 `action_trace.jsonl`（2026-11-03 实测），也不让观测写失败污染权威路径（Q45）。

**Q41：事件必须和 claim 决策同序吗？**
A：同临界区，但**不必同 fsync**。顺序硬约束：先落 task/claim 账本（fsync），再 append 事件（不 fsync）。崩溃只会丢最后几条事件，**不会凭空造出一条没发生过的决策**——事件可以有损，不可以伪造。

**Q42：`coordination_status` 到千级 goal 要不要索引？（§13 ② 结案）**
A：不需要索引，先修截断。实测（`.venv`，2026-11-03，合成账本 + 真实账本）：

| 场景 | 规模 | 耗时 |
|---|---|---|
| 真实账本全量 | 239 goal / 282 task 文件 / 2.0MB | **14.7ms**（账本解析 2.15ms + frontier 12.5ms） |
| 合成 200 goal × 12 task | 账本 64KB / tasks 982KB | 13.1ms |
| 合成 400 | 账本 129KB / tasks 1964KB | 25.9ms |
| 合成 800 | 账本 257KB / tasks 3928KB | 52.4ms |
| 合成 1600 | 账本 514KB / tasks 7856KB | 106.6ms |

线性（≈0.066ms/goal，200→1600 稳定），没有拐点。索引只能省掉 2.15ms 的账本解析，却要引入一份需要一致性校验的派生数据（F3 的成本）——**不做**。真正的缺陷是 `list(limit=200)`：真实账本 239 行时视图只出 200 条，**12 个 active goal 已不可见**（78/90）。升级门槛写死在 §6.7：p95 > 80ms 或 `goals_in_ledger > 450` 再谈索引。

**Q43：「误拒率」能不能直接算？**
A：不能，必须降级为「疑似误拒」。误拒的定义是「本该放行却拒了」，而系统没有 ground truth：拒绝之后 holder 换条路径把活干完，与「本来就该拒」在账本上同形。**修正**：只报代理指标 `疑似误拒率 = deny 后 30s 内同 holder 同 task 写入成功 / deny 总数`，命名与回执都带「疑似」，不得用它单独宣布「claim 没问题」；真冲突率与疑似误拒率必须成对读。

**Q44：per-parent 闸的计数口径（D4 落地）**
A：现状**没有** per-parent 闸（§2.1-E7），只有全局 `_max_handles=128`（`runner.py:353`，拒绝文案 `:1670`）。新增闸三条硬约束：(a) 计数只能读 `handle.state == "running"`——`pending_obligations`（`runner.py:641-660`）已是这个过滤式，直接复用；不能用 `_children_by_parent` 的集合长度（`active_children()` `:636-639` 返回集合内容、不校验 state，字典清理只在完成路径 `:1161-1166`）；(b) 必须与 depth/128 在同一 `_children_guard` 内判定，否则三闸之间的 TOCTOU 会绕过 128；(c) 拒绝回执必须带当前计数与三个出口（等 / kill / 调参），否则模型只会重试。

**Q45：观测失败能不能拒写？**
A：分两层，不能混。**权威路径 fail-closed**：task 账本或 claims 账本写失败 → 必须拒写（否则就是「假装完成」）。**观测路径 fail-open**：事件 append 失败 → 内存计数 `event_write_failures += 1`、继续写、在 `coordination_status.degraded` 出现一条。若把观测也做成 fail-closed，一次磁盘满就会让整个 task 写入面停摆——那是把可观测性变成新的单点故障。

**本轮修正汇总**：D5（视图 200→500 + 截断/窗口显式化，进 P0）；N4 明确为「新增闸」（E7）；指标落到 3 个写入点 + 1 个代理指标（§6.6）；成本曲线结案（§6.7）；观测与权威分层（Q45）。

---

## 5. 需求条目与可执行验收

> 编号为 N（New）。每条给出**可执行的验收断言**，而非"应支持"这类无法判定的措辞。

### N1（P0）可见性接线：去掉硬编码 degraded

**需求**：`coordination_status` 的 `running.children` / `running.jobs` / `recent_events` 三个字段真实采集，`degraded` 只在数据源确实不可读时出现。

| # | 验收断言 |
|---|---|
| N1-A1 | 起 2 个 subagent + 1 个后台 job，调 `coordination_status` → `running.children` 至少含 2 条、`running.jobs` 至少含 1 条，`degraded` 不含「未接线」字样 |
| N1-A2 | 无任何在跑任务时 → 三字段为空数组且 `degraded` 为空（不伪造、不省略） |
| N1-A3 | runner 不可用时 → `degraded` 恰好出现一条 `running.children: <具体原因>`，字段仍为空数组 |
| N1-A4 | 调用前后 `goals.jsonl` / `tasks.jsonl` / claims 账本的 sha256 与 mtime 不变 |
| N1-A5 | 他人 session 的 child 只出脱敏 id + 计数，不出完整 `child_id` |
| N1-A6 | `create_goal` / `task_create` 成功回执尾部追加「在途摘要」一行（存在运行时），无在途则不出现该行 |
| N1-A7 | **容量自证**：239 行 fixture → 239 条全出；600 行 fixture → 500 条 + `degraded` 含 `goals_truncated: 500/600`；`render_coordination` 首行含 `capacity=`（D5） |
| N1-A8 | **窗口口径**：goal 行 `updated_at` 在 48h 前、其 task 在 1h 前更新 → 24h 窗口下**必须可见**且标 `activity_source=task`；两者都超窗 → 不可见且 `degraded` 含 `window_empty`（E9/Q42） |
| N1-A9 | **事件窗口**（v2.6）：`action_trace` 注入 15 条 5 分钟内 + 5 条 1 小时前 → `recent_events` 只出窗口内 10 条、`recent_events_total=15`、`truncated=true`、`coverage_s` 为真实跨度（不报整窗） |
| N1-A10 | **字节兜底**（v2.6）：把 `_EVENTS_MAX_BYTES` 压到 512B → `truncated=true` 且 degraded 出现「尾部 … 未回溯到 1800s 前」；被切断的半行 JSON 绝不出现在 `recent_events` 里 |

**实现约束**：`runner.py` 新增只读方法 `all_active_children() -> list[_SubAgentHandle]`（返回 handle 对象，由视图层转 dict），遍历既有 `self._handles`（`runner.py:359`）。既有的 `active_children()` 只返回 `list[str]`（`runner.py:636`），出不了 state/depth，故必须新增而非复用。**不得**改动 `_prune_handles_locked` 的驱逐行为。

### N2（P1）TaskClaim：把死字段激活为占用权

**需求**：新增 `claims` 账本与**三个**工具面 `claim_task` / `renew_claim` / `release_claim`（过期原子接手并入 `claim_task`，回执 `reclaimed=true`，不单设 `reclaim_if_expired`）；`task_update` 可选携带 `claim_token`，但**必须**经组合入口 `update_task_under_claim` 完成「校验 + 落笔」（Q24）。`holder` 由程序注入 `authority_session_id()`，**不接受 args**（Q25）。

| # | 验收断言 |
|---|---|
| N2-A1 | 空账本 claim T → `Granted(claim_id, generation=1)`，claims 账本新增一行 |
| N2-A2 | 同 holder 再 claim 同 task → 幂等返回**同一** `claim_id`，`generation` 不变（不递增） |
| N2-A3 | 异 holder claim 未过期 task → `Conflict(holder, remaining_s, generation)`，账本无新行 |
| N2-A4 | 用 `generation` 落后于账本的 token 写 task → `claim_generation_stale`，task 账本字节不变 |
| N2-A5 | 用他人 token 写 task → `claim_holder_mismatch` |
| N2-A6 | ttl 过期后再次 `claim_task` → 原子接手，`reclaimed=true`、`generation + 1`；并发两路接手只有一个赢家 |
| N2-A7 | 已过期但**未被接管**的 claim 可以 `renew_claim` 续期（回执 `renewed_after_expiry=true`）；已被接管（generation 落后 / `superseded`）则拒绝 `claim_generation_stale`（Q33 修订，原「过期即失权」见 §2.1-E5） |
| N2-A8 | `task_update(status=done)` 成功后该 task 的 claim 自动失效（读时判定，不回写） |
| N2-A9 | claim 成功后越界写文件 → 仍被 `write_scope` 拒绝（**claim 不授予路径权**） |
| N2-A10 | **锁序**：`update_task_under_claim` 与 `claim_task` 同时被两线程调用（一个写、一个 claim）→ 2s 内全部返回，无死锁（Q23） |
| N2-A11 | **重开撤销**：claim T → `done` → 重开 `in_progress`（confirm）→ 旧 token 写 → `claim_revoked`；新 holder 可正常 claim（Q27） |
| N2-A12 | **holder 注入**：`claim_task(holder="someone-else")` 传入的参数被忽略（或直接拒绝），账本 holder 恒等于当前绑定 session；绑定为空 → `claim_unverifiable`（Q25） |
| N2-A13 | **归一**：`GOAL/a` 与 `GOAL_a` 两个 goal 的 claims 文件不同；`claim_task` 不接受归一后为空或含 `/` 的 goal_id（Q26） |
| N2-A14 | **组合入口**：`require_current` 与 `store.update` 之间插入「强制 reclaim」的测试钩子 → 写入必须失败（证明无 TOCTOU 窗口）（Q24） |
| N2-A15 | **软过期**：claim 过期但无人接管 → 原 holder 写 task 成功，回执 `claim_expired_renewed=true` 且 `expires_at` 前移；被他人接管后再写 → `claim_generation_stale`（Q33） |
| N2-A16 | **ttl 边界**：`ttl_s=1` → clamp 到 60；`ttl_s=None` 且 `allow_unbounded_claim=false` → `claim_ttl_out_of_range`（不落账本）（Q35） |
| N2-A17 | **坏尾行韧性**：手工向 claims 文件追加半行 → 后续 claim/renew/写**全部正常**，回执 `ledger_degraded=1`；不抛异常、不阻塞（Q34） |

### N3（P2）claim 强制模式（带开关）

**需求**：`config.claim_enforcement ∈ {off, warn, enforce}`，默认 `warn`。`enforce` 时无有效 token 的 `in_progress` 写入拒绝。

| # | 验收断言 |
|---|---|
| N3-A1 | `off`：行为与 P1 完全一致，无告警 |
| N3-A2 | `warn`：无 token 写入成功，回执追加 `claim_missing` 告警与「如何 claim」提示 |
| N3-A3 | `enforce`：无 token → `claim_required` + 三条出口（先 claim / 显式 cross_session / 找 holder 释放） |
| N3-A4 | 三档下既有全绿测试的回执**逐字**不变（除追加行），RULE-AI-24 零退化 |

### N4（P1）并发闸：拆口径，不新建机制

> v2.1 改判：闸**已存在**（全局 128），本轮做的是把它拆成两个可配置口径 + 补齐回执。

**需求**：保留 `max_handles=128`（进程保护，语义不动），新增 per-parent `max_running_children`（默认 **16**，可配 1..32；依据见 §12-D4 实测）与 `max_claims_per_holder`（默认 8，仅警告）。三闸判定顺序与回执口径见 Q30。

| # | 验收断言 |
|---|---|
| N4-A1 | **per-parent 闸**：同 parent 起 16 个 → 第 17 个返回 `parent_concurrency` + 当前计数 + 出口（等 / kill / 调 `max_running_children`）；设 8 时第 9 个被拒（默认值改为 16，见 §12-D4） |
| N4-A2 | 有 child 结束后再 spawn → 成功（计量是 `state=="running"`，不是累计） |
| N4-A3 | 上限设为 1 时首个 spawn 仍成功（不出现「永远无法 spawn」的死锁） |
| N4-A4 | 拒绝信息不暴露内部堆栈，只给计数与出口 |
| N4-A5 | **全局闸不减配**：现有 128 行为与文案逐字保留；per-parent 只在其内层额外收紧（128 仍然是天花板） |
| N4-A6 | **顺序固定**：同时越 depth 与并发上限时，回执必须是 `depth_exceeded`（不是 `parent_concurrency`） |
| N4-A7 | **跨会话隔离**：A 会话起满默认上限时，B 会话仍能起（闸是 per-parent，不是全局） |

### N5（P1）路径重叠预检（警告，不阻断）

**需求**：claim 可带 `expected_paths`；与另一 active claim 重叠时回执警告。

| # | 验收断言 |
|---|---|
| N5-A1 | 两个 claim 的 `expected_paths` 有交集 → 后 claim 成功但回执含 `path_overlap` 警告与对方脱敏 holder |
| N5-A2 | 无交集 → 无警告行 |
| N5-A3 | 重叠时**不**改变任何写权限判定（越界写仍由 write_scope 拒） |

### N6（P2）workflow parallel 的诚实化

**需求**：`workflow_run(mode=parallel)` 回执明示实际执行方式，消除"以为并行"的观测失真。

**实现（v2.7，T-0.5）**：`_execute_linear`（parallel/pipeline）与 `_execute_dag` 的回执首行改为 `[workflow_run] mode=<mode>, steps=<n>, execution=sequential（…）`；工具 descriptions 追加「勿据 mode 推断真并行」。**只追加标注，未改执行语义**（仍是顺序执行+聚合）。

| # | 验收断言 |
|---|---|
| N6-A1 | 回执首行含 `execution=sequential`（在未实现真并发前）→ ✅ `test_receipt_first_line_marks_execution_sequential`（三种 mode 各一） |
| N6-A2 | 既有 `mode=parallel` 的单测断言零改动通过（只追加标注，不改执行语义）→ ✅ 既有 `test_workflow.py` 全部断言未改仍通过 |
| N6-A3 | 若后续实现真并发，同一字段改为 `execution=concurrent`，且 N6-A1 的断言随之更新（文档同步） |

---

## 6. 实现设计细节

### 6.1 数据模型

```python
# src/llm_loop/introspection/task_claim.py（新文件，约 260 行）

@dataclass
class TaskClaim:
    claim_id: str            # "claim-<uuid12>"，程序签发，模型不可自造
    goal_id: str
    task_id: str
    holder: str              # session id 或 child_sid
    holder_kind: str         # "session" | "subagent" | "main"
    generation: int          # 每次成功抢占 +1；fencing 的唯一安全边界
    acquired_at: float       # time.time()
    expires_at: float | None # None = 显式无限期，仅 allow_unbounded_claim=true 可签发（Q35）
    state: str               # "active" | "released" | "superseded" | "expired"
    expected_paths: list[str] = field(default_factory=list)  # N5，仅用于警告
    revoked: bool = False    # Q27：task 重开（done→in_progress）后由 revoke_all 置位
```

> claim 记录只**追加**，不改写：`released`/`superseded`/`revoked` 都是新行 + `replay_last_wins` 折叠，账本本身不可变（F1/F6 的前提）。

**存储落点**：`<audit_dir>/claims/<_safe_goal_id>.jsonl`（`_safe_goal_id` 必须与 `task_store._path` 的 `re.sub(r"[^A-Za-z0-9_-]", "_", goal_id)` 逐字符一致，见 Q26 / §2.1-E4 同行约束）

**为什么独立文件而不是塞进 task 记录**（这是一个必须论证的决定）：
1. task 账本是"任务定义与状态"，claim 是"占用权"，**生命周期不同**：一个 task 可能经历多次 claim（A 做一半 → B 接手）。
2. claim 过期判定是**高频读**，独立文件小，不影响 task replay 的性能。
3. **故障隔离**：claims 文件损坏不拖垮 task 账本（反之亦然），符合 v1 `_degraded_goal_entry` 的单条降级哲学。
4. 有先例：`fleet/store.py` 的 lease 也是与 workspace 定义分离存储的。

**代价**：非同一事务（§4-Q18 已正面处理，用「事实优先于权利」兜住）。

### 6.2 判定算法（最关键的两个临界区）

**claim_task**

```
def claim_task(goal_id, task_id, ttl_s, expected_paths) -> ClaimResult:
    # holder 由运行时注入，不读调用方参数（Q25）
    holder, holder_kind = current_identity()        # authority_session_id() + 主/子代理判定
    if not holder:
        return Refused("claim_unverifiable")
    # 路径必须复用 goal_id 归一（Q26），否则形似 goal 会共享文件
    claims_path = realpath(audit_dir / "claims" / f"{_safe_goal_id(goal_id)}.jsonl")
    with flock(claims_path, LOCK_EX):                # 外层锁；全局锁序 claims → tasks（Q23）
        rows = replay_last_wins(claims_path)         # 单 goal 全量 replay
        cur  = rows.get(task_id)

        # (1) 事实优先：task 必须可 claim（get 内部取 task 锁 = 内层锁）
        task = TaskStore(audit_dir).get(goal_id, task_id)   # 不存在 → task_not_found
        if task.status not in ("pending", "in_progress"):
            return Refused("task_not_claimable", status=task.status)
        if cur and cur.revoked:
            cur = None                               # 重开撤销后，旧记录不再参与比较（Q27）

        # (2) 幂等：同 holder 持有效 claim → 原样返回，不递增 generation
        if cur and cur.state == "active" and cur.holder == holder and not expired(cur):
            return Granted(cur.claim_id, cur.generation, idempotent=True)

        # (3) 冲突：他人持有效 claim → fail-closed，给剩余窗口
        if cur and cur.state == "active" and not expired(cur):
            return Conflict(holder_mask(cur.holder), remaining_s(cur), cur.generation)

        # (4) 发放 / 原子接手：过期 claim 直接在这里被接管，不设独立 reclaim 入口（Q28）
        ttl_s = clamp_ttl(ttl_s)                     # [60, max_claim_ttl_s]；None 需配置授权（Q35）
        reclaimed = bool(cur and cur.state == "active" and expired(cur))
        gen = (cur.generation if cur else 0) + 1
        claim = TaskClaim(new_id(), goal_id, task_id, holder, holder_kind,
                          gen, now(), None if ttl_s is None else now() + ttl_s,
                          "active", expected_paths, revoked=False)
        append_jsonl(claims_path, claim)
        return Granted(claim.claim_id, gen, reclaimed=reclaimed)
```

**fencing 校验（唯一入口：`update_task_under_claim`）**

```
def update_task_under_claim(goal_id, task_id, token, **fields) -> WriteResult:
    """校验与落笔在同一 claims 临界区内完成（Q24）。禁止调用方自行拼接两步。"""
    holder, _ = current_identity()
    with flock(claims_path, LOCK_EX):                  # 外层锁（锁序见 Q23）
        cur = replay_last_wins(claims_path).get(task_id)
        refuse = check_current(cur, token, holder)     # 纯函数，无副作用
        if refuse:
            return refuse
        task = TaskStore(audit_dir).get(goal_id, task_id)      # 内层 task 锁
        if task.status not in ("pending", "in_progress"):
            return Refused("task_not_claimable")
        return TaskStore(audit_dir).update(goal_id, task_id, **fields)  # 同一临界区内落笔

def check_current(cur, token, holder) -> None | Refusal:
    if cur is None:                      return Refused("claim_required")
    if cur.revoked:                      return Refused("claim_revoked")       # 重开撤销（Q27）
    if cur.holder != holder:             return Refused("claim_holder_mismatch", cur.holder_mask)
    if cur.generation != token.generation: return Refused("claim_generation_stale",
                                                          current=cur.generation)  # 不含 token 内容
    if cur.state != "active":            return Refused("claim_released")
    # 软过期（Q33）：过期只取消「独占」，不取消「本人写入权」。
    # 被接管时 generation 已领先，上面的 generation 分支必然先拦下，故此处放行是安全的。
    # 回执侧由调用方补 claim_expired_renewed=true 并顺带续期。
    
    return None
```

**四个必须写进注释的不变量**：
1. `generation` 单调递增由**账本 replay** 保证，不由内存状态保证（进程重启后仍正确）。
2. **锁序单向**：`claims → tasks → goal_coord`；任何路径不得在持 tasks 锁时申请 claims 锁（Q23）。违反即 ABBA，2s 超时测试可见。
3. `expires_at` 用 wall clock，进程内对 `now` 做单调钳制（`_last_now = max(_last_now, time.time())`）；**时间只影响可用性，不影响安全性**（安全边界是 generation）。跨进程回拨残余见 §10-R9。
4. 过期只取消**独占**，不取消**本人写入权**（Q33）：未被接管时原 holder 可续期并在回执标 `renewed_after_expiry`；被接管后由 generation 拦截（`claim_generation_stale`）。fleet 的「TTL is authority」不适用，因为其检查与提交跨 effect fence，本设计的 check+write 在同一临界区。

### 6.3 拒绝契约（回执模板，必须逐条落地）

**Conflict（claim 失败）**
```
[任务已被占用] reason_code=claim_conflict
task TASK-xxx-002 当前由 sess-abcd1234…（subagent）持有，剩余 1_284s，generation=3。
出口：
  1) 等它结束：wait(seconds=...) 后重试；或先做不依赖它的 task（frontier 的 ready 集）
  2) 若确信对方已死：等 ttl 到期后**直接重新** claim_task(...)——过期会被原子接手，回执带 reclaimed=true（没有独立的 reclaim 入口）
  3) 换目标：task_frontier() 里挑另一个 ready task
未做任何写入，账本未变。
```

**claim_generation_stale（fencing 拒绝）**
```
[占用凭据已过期] reason_code=claim_generation_stale
你的 claim 是 generation=2，账本当前 generation=3（已被 reclaim）。
你的写入未发生。请重新 claim_task 获取新 token 后再写。
```

**claim_required（P2 强制模式）**
```
[缺少占用凭据] reason_code=claim_required
claim_enforcement=enforce，写 in_progress 必须先持有 claim。
出口：
  1) claim_task(goal_id=..., task_id=...)
  2) 若这是他人 task：加 cross_session=true + reason + evidence_refs（v1 L1 判定不变）
  3) 若只想记进度不改状态：用 checkpoint_goal
```
注（Q33/D1 建议）：若采纳「隐式 claim」，`claim_required` 只在 `task_update` 显式拒绝自动签发时出现——`pending→in_progress` 由程序自动签发 claim（回执 `auto_claimed=true`），模型无需先调 `claim_task`。

**claim_expired_renewed（不是错误，是标注，Q33）**
```
[占用已续期] claim_expired_renewed=true
你的 claim 于 12min 前过期，但期间无人接管，本次写入已发生，expires_at 已前移。
（若你确实在读旧视图：task_frontier() 可刷新依据；claim 不保证依据新鲜，见 R12。）
```

**claim_ttl_out_of_range（Q35）**
```
[ttl 越界] reason_code=claim_ttl_out_of_range
请求 ttl_s=None/600000 超出 [60, 28800]；无限期需 host 配置 allow_unbounded_claim=true。
出口：1) 用 ttl_s=3600 重试；2) 长任务用 renew_claim 续期（不需要无限期）
```

### 6.4 `coordination_status` 的接线实现

```python
# goal_coordination.py 内，替换现有三条硬编码 degraded（✅ 已实现，2026-11-03）

def _collect_running(*, sid: str, ctx: Any | None) -> tuple[dict, list[str]]:
    running = {
        "children_scope": "owner_session",   # 归属口径必须回执（Q39(b)）
        "children": [], "children_mine_total": 0, "children_others_total": 0,
        "children_truncated": 0,
        "jobs": [], "jobs_mine_total": 0, "jobs_others_total": 0, "jobs_truncated": 0,
    }
    runner = getattr(ctx, "subagent_runner", None) if ctx is not None else None
    if runner is None:
        degraded.append("running.children: 未装配 subagent_runner（不代表没有 child 在跑）")
    else:
        for h in runner.all_active_children():        # 新增只读方法（T-0.3）
            if h.state != "running":                  # 视图侧二次判在飞（见技术要点）
                continue
            same = bool(sid) and h.parent_id == sid
            ...  # child_id/generation 仅 is_mine 时给值；parent 一律 mask_session
    job_registry = getattr(ctx, "job_registry", None) if ctx is not None else None
    ...
```

**技术要点**（全部核对过代码，不是设想）：
- `all_active_children()` 遍历 `self._handles`，加 `_children_guard` 锁，**只读**、不触碰驱逐逻辑；在飞判据是 `handle.state == "running"`——`_children_by_parent`（`runner.py` 初始化处）只是「已登记」，`_prune_handles_locked` 淘汰 handle 时不清它，集合成员资格不能当在飞判据（E7/E12）。
- **`from llm_loop.subagent import get_runner` 不存在（E11）**：该模块无 runner 访问器，`introspection` 层也没有 runner/job 句柄。实现改为**装配点注入**：`factory.build_engine` 内 `correction_ctx.subagent_runner = subagent_runner`、`correction_ctx.job_registry = _job_registry`；`run_coordination_status` 用 `ctx if ctx is not None else host.ctx` 透传。未装配 → 该段显式 degraded，不返回伪造空列表。
- jobs 侧新增 `JobRegistry.active_all()`（与 `active_for_session` 同口径 `not done and not killed`，按 `started_at` 稳定排序）。**未采用**设计原稿的 `snapshots_for_session(sid)`：它会连带返回重启前的 durable orphan 事实，与本段「在飞」语义不同源；代价是重启后未收口的执行不在 running 段（残余登记于 §10-R4）。
- 跨进程（另一个 tab 的 session）的 child/job **看不到**——两源都是进程内内存态。落盘事实在 `_durable_topology`，那是 parent 维度持久边，不代表 child 在跑。
- handle 有 `generation`（parent run 代际）但**无 `started_at`/`expires_at`**（§2.1-E3）；job 有 `started_at`。所以 children 不显示「已运行时长」，渲染只给 state/depth/generation。
- top-N=10（`_RUNNING_TOP_N`）截断必须由 `children_truncated`/`jobs_truncated` + degraded 文案自证；他人 session 只出脱敏行+计数（Q13）。
- 每次采集盖 `observed_at`（`system_local_now()`）：running 是瞬时内存态，不能冒充与 `generated_at` 同刻。

#### 6.4.2 `recent_events` 段（✅ 已实现 2026-11-03；对应 T-0.4b）

**先说结论：不能复用 `event_stream`。** 实测量化（2026-11-03，本仓库 `data/audit`，`action_trace.jsonl` 375MB）：

| 做法 | 实测成本 | 判定 |
|---|---|---|
| `RecordSearcher.event_stream(streams="action_trace", limit=10)` | **3029ms** | 不可用：逐个流全文件逐行 `json.loads` |
| `event_stream(streams="all")` | **4204ms** | 更差 |
| 尾部 128KB 读 + 解析 | 0.6ms | 可用 |
| 尾部 2MB 读 + 解析 | 8.9ms | 上限可用 |

而且 `event_stream` **没有截断语义**：要么全读、要么不读，回答不了「我看到的是不是全的」。T-0.4b 的验收词恰好是 `truncated`，所以只能自己实现尾部读。

**窗口按时间定义，不按字节**——同样 128KB 在不同流上差三个数量级：

| 流 | 尾部 128KB | 尾部 512KB | 尾部 2MB |
|---|---|---|---|
| `action_trace`（热） | 317 行 / **4 分 16 秒** | 1287 行 / 16 分 6 秒 | 5069 行 / 3 小时 34 分 |
| `exception_log`（稀疏） | 354 行 / **1 天 6 小时** | 1428 行 / 2 天 23 小时 | 5809 行 / 9 天 |

「最近 128KB」在 action_trace 上值 4 分钟、在 exception_log 上值 1.3 天，这个量不可解释。因此用 `window_s=1800` 定义「最近」，`_EVENTS_MAX_BYTES=2MB` 只做**成本兜底**，触顶即标截断。

```python
# goal_coordination.py（✅ 已实现）
_RECENT_EVENT_STREAMS = (  # 只取两条：活动主干 + 故障面；其余流（declaration_check 317MB 等）非活动信号
    ("action_trace", "action_trace.jsonl", ("action_type", "detail")),
    ("exception_log", "exception_log.jsonl", ("error_type", "detail")),
)
_EVENTS_TOP_N, _EVENTS_WINDOW_S, _EVENTS_MAX_BYTES = 10, 1800, 2 * 1024 * 1024

def _scan_stream_tail(path, *, cutoff, max_bytes):
    # 倒扫：撞到 cutoff 即停；start>0 时 lines[1:] 丢弃被切开的首行
    ...
```

回执字段（全部常驻，不省略）：

| 字段 | 语义 | 诚实性要点 |
|---|---|---|
| `recent_events[]` | ≤10 条，**旧→新**，`{stream, ts, session_id, is_mine, attributed, summary}` | 与 `event_stream` 同序；不是最新在前 |
| `recent_events_total` | 窗口内命中数 | `>10` 即只出了 top-N |
| `recent_events_truncated` | bool | **两个独立成因**：top-N 截断 / 字节兜底触顶，任一为真 |
| `recent_events_coverage_s` | 最老命中 → now 的秒数 | 安静期有空档时会 < 窗口；这是**真实跨度**，不冒充「看满 30 分钟」 |
| `recent_events_scanned_bytes` | 实际读取字节（每流 `min(size, 2MB)`） | 反映 I/O 成本，不等于解析量 |
| `recent_events_streams` / `_scope` / `_observed_at` | 流清单 / `workspace` / 采集时刻 | 跨进程可见是这一段相对 running 的唯一优势 |

**技术要点**（每条都有测试或实测支撑）：
- **倒扫而非正扫**：正扫 375MB 实测 3029ms；倒扫在 cutoff 处停。测试用 `_entry_ts` **调用次数**做机械判据（2000 条旧记录 + 3 条新记录 → 调用 ≤4 次），不看墙钟——墙钟在 CI 上不可靠。
- **半行不修补**：`start>0` 时直接 `lines[1:]` 丢弃被切断的首行，不做 try/except 兜底；半条 JSON 属于「不知道」，不是「差不多」。
- **无时间戳记录只计数不猜**：计入 degraded（`exception_log` 实测存在这类行），绝不按写入顺序假定时间。
- **缺 `session_id` 的行 `attributed=false`**：`action_trace` 历史上曾整段恒空（见 `status.py` 注释），现在多数行有值但非 100%；不按空 sid 反推归属。
- **零写**：只 `stat`+`read`+`pathlib` 拼路径，不建目录、不写账本（G7 由测试守）。
- **成本**：真实账本 `coordination_snapshot(window_hours=24)` **p50 17.4ms / p95 18.0ms**（含账本 7.6ms 基线；4MB 读 + 窗口内 ~2400 行解析）。预算 80ms，余量约 4×。**升级触发**：p95>40ms 时把「一次读 2MB」改成「64KB 分块倒读、撞 cutoff 停」——语义不变，只改 I/O 粒度。

**残余（§10-R17/R18）**：事件只覆盖**已落账**的动作（正在跑但尚未写审计的看不到）；跨进程可见，但受 `action_trace` 写入节奏约束；`recent_events=0` 只代表窗口内空。

### 6.5 与既有工具的接线点（改动面全表）

| 文件 | 改动 | 风险 |
|---|---|---|
| `introspection/task_claim.py` | **新建**：数据模型（含 `revoked`）+ 三个工具面 + `update_task_under_claim` 组合入口 + `_safe_goal_id` 归一 | 低（新文件） |
| `introspection/tools_task.py` | `task_update` 增可选 `claim_token` 并**只走组合入口**；`done→in_progress` 成功后追加 `revoke_all`（先撤销后重开）；`task_create` 回执追加在途摘要（Q31 三约束） | 中高（既有热点，须逐字回归 + 撤销顺序测试） |
| `introspection/goal_coordination.py` | 替换三条硬编码 degraded；`render_coordination` 增 running 段；`current_identity()` 供 holder 注入 | 低 |
| `introspection/tools_goal.py` | `coordination_status` 参数透传；`create_goal` 回执追加在途摘要 | 低 |
| `subagent/runner.py` | 新增 `all_active_children()` 只读方法；`_reserve_background_child` 内按 depth → 128 → per-parent 顺序判定；spawn 失败回执带 `reason_code` + 计数 + 出口 | 中（并发临界区，三闸须同锁内判定） |
| `tools/builtin/workflow.py` | 回执首行加 `execution=sequential` | 极低 |
| `config.py` | `claim_enforcement` / `claim_ttl_s` / `max_running_children` / `max_claims_per_holder`（frozen dataclass 新增字段） | 低 |

**不动**：`goal.py`（v1 CAS 已闭环，且**只保护 goal**）、`task_store.py` 的状态机与 frontier 求值（**有意不引入 task 版本**，§3.3）、`write_scope` 全部实现。

---

### 6.6 埋点与指标口径（观察期的唯一数据来源）

**为什么单独一个文件**：`action_trace.jsonl` 已有 357MB（2026-11-03 实测），记的是工具调用、不是 claim 决策；把 claim 事件混进去，「哪一行是权威决策」就无法判断，观测写还会和工具调用抢同一个文件。因此用 `data/audit/claims/events.jsonl`：独立、append-only、单行 ≤1KB、**不 fsync**。

**三个写入点**（与 Q40 一致）：

| # | 位置 | 事件 kind | 何时写 | 失败行为 |
|---|---|---|---|---|
| E-1 | `task_store.update()` 的锁内、`_append` 之后（`task_store.py:277` 取锁 / `:371-373` 落笔后写事件） | `claim_decision` | 每次 claim 校验 + 落笔完成后 | fail-open：内存计数 + 进 `degraded` |
| E-2 | `runner._reserve_background_child()` 的 `_children_guard` 内（`runner.py:1398-1419`） | `fanout_decision` | 每次 spawn 闸判定后（放行与拒绝都写） | fail-open |
| E-3 | 读路径 `_collect_claim_metrics()`（`goal_coordination.py:708`，由 `coordination_snapshot():735` 调用） | — | **不写事件**；只把 `claim_event_write_failures` / `claims_events.bad_lines` / `claims_events.bytes` 填进快照与 `degraded` | — |

**事件 schema**（字段固定，后续只增不改）：

```json
{"v":1,"ts":"2026-11-03T19:30:00.123+08:00","kind":"claim_decision",
 "goal_id":"GOAL-…","task_id":"T-…","holder":"sess-…",
 "decision":"grant|renew|reclaim|deny|release|revoke|passthrough",
 "reason_code":null,"claim_generation":3,"auto":true,"ttl_s":1800,
 "expired":false,"revoked":false,"actor":"self|other","latency_ms":0.4}
```
```json
{"v":1,"ts":"…","kind":"fanout_decision","parent":"sess-…",
 "decision":"allow|deny","reason_code":"parent_concurrency|max_handles|depth_exceeded",
 "running_before":16,"limit":16,"depth":1}
```

**指标与算法**（全部由事件流线性扫描得出，不设独立计数器文件——避免双写不一致）：

| 指标 | 计算式 | 用途 | 告警线 |
|---|---|---|---|
| 冲突率 | `deny(claim_conflict) / claim_decision_total` | claim 是否真的在挡事 | > 2% 抽样本人工看 |
| 接管率 | `reclaim / (reclaim + expired_renewed)` | 30min 是否太短 | > 20% 说明 ttl 偏短 |
| 疑似误拒率 | `deny 后 30s 内同 holder 同 task 写入成功 / deny 总数` | 硬拒是否误伤 | > 1% 阻止进入 PR-2 |
| fanout 拒绝率 | `deny(parent_concurrency) / fanout_total` | 16 是否合适 | > 5% 说明偏低 |
| 账本健康 | `event_write_failures`、`ledger_degraded`、`claims_bytes` | 观测与账本是否可信 | 任一 > 0 登记 |

**三条不变量**：
1. **观测不阻断**：E-1/E-2 的任何异常都不得改变调用结果（Q45）。
2. **事件不伪造**：只在账本落笔成功后写；崩溃丢尾行可接受，顺序不可反（Q41）。
3. **事件可丢但要标注**：`event_write_failures > 0` 时，所有比率指标必须标注「分母不完整」，不得直接对外报数（Q43 的同一原则）。

**计算入口**：`scripts/claim_metrics.py --since 7d`（只读事件流 + claims 账本），输出上表与分母完整度。观察期结论一律引用该脚本输出，不手算。**已随 PR-1 落地**（2026-11-03，T-1.11）：分母为空时输出 `null` 而不是 0；事件流含坏行时标 `degraded` 并说明比率是下界；`--since` 支持 `7d/24h/90m` 与 ISO8601。

#### 6.6.1 实现（v2.7，T-0.6 落地）

模块 `src/llm_loop/introspection/claims/events.py`（包 `claims/`，将来 claims 账本同目录）：

| 项 | 实现 | 依据 |
|---|---|---|
| 路径 | `<audit_dir>/claims/events.jsonl`；`audit_dir` = session 根父目录 + `audit`（`runner._audit_dir()`，`runner.py:1369`） | 与 `ToolExecutionJournal` 同根 |
| 写入 | `open("ab")` + `write` + `flush`，**不 fsync**；进程内按路径加锁串行（O_APPEND 原子性在短写面前不足） | Q41 |
| 单行上限 | `MAX_LINE_BYTES=1024`；字符串字段 >96 字符截断 + `…`；仍超限则**不写**并计一次 failure（`line_too_long`），绝不写超长行 | §6.6 |
| 失败语义 | 任何异常 → 计数 + `logger.warning` + 返回 `False`；**绝不抛给调用方** | 不变量 1 |
| 字段时间序 | `v`/`ts`/`kind` 由 `build_row()` 权威生成，调用方传入同名键被忽略 | 不变量 2 |
| `holder` | PR-0 无 claim 层，取当前 run 的 `current_session_id` contextvar；无 run context（后台线程/纯测试）→ `null`，不编造 | Q25 的前置形态 |
| `latency_ms` | **「校验+落笔临界区」耗时**（取锁 → `_append` 完成），PR-0 实测为 replay+append，不是 claim 校验耗时——不得与 N2 的 claim 延迟混同 | Q45 的诚实口径 |
| `fanout_decision` 位置偏差 | 字段在 `_children_guard` 内采集（决策临界区），append 在**锁外同一函数帧**执行：决策点不变，但不在被 `active_children`/topology 共用的热锁上做文件 I/O。已改写 §6.6 表格中 E-2 的表述 | 本轮新增（原稿写「锁内」，实测口径改为「锁内采集、锁外 append」） |
| 读侧成本 | `read_events_stats()` 超 `4MB` 只回 `bytes`，`lines` 置 `null` + `note=skipped_scan_over_cap`；坏行（半行）计入 `bad_lines` 但**不**报 degraded（预期现象，非损坏） | §6.4.2 80ms 预算 |

**验收口径（T-0.6）**：

| # | 断言 |
|---|---|
| N7-A1 | N 次**实际落笔**的 `task_store.update()` → `events.jsonl` 恰好 N 行 `claim_decision`；`no_change` 早退与校验失败（未落笔）**不得**产生事件 |
| N7-A2 | 把 `<audit>/claims` 位置占成普通文件（append 必失败）→ `task_update` 仍成功、task 账本语义不变；`coordination_snapshot()` 的 `claim_event_write_failures > 0` 且 `degraded` 出现「分母不完整」 |
| N7-A3 | 单条事件序列化后 >1KB → 不写该行、计数 +1，事件流不出现超长行 |
| N7-A4 | `fanout_decision` 的 `running_before` 是**决策前**计数：limit=1 时先 allow(`running_before=0`) 再 deny(`running_before=1`,`reason_code=max_handles`) |

测试回执：`tests/unit/test_claims_events.py` 13 条 + `tests/unit/test_claims_events_fanout.py` 2 条。

### 6.7 `coordination_status` 的成本曲线与索引决策

**实测（2026-11-03，`.venv`，口径见 §4.4-Q42）**：真实账本 239 goal / 282 task 文件 / 2.0MB → **14.7ms**（账本解析 2.15ms + frontier 12.5ms）；合成 200/400/800/1600 goal → 13.1 / 25.9 / 52.4 / 106.6ms，线性无拐点。

**结论：不建索引，先修截断。**
1. 索引只能优化 2.15ms 的账本解析；12.5ms 花在 `compute_frontier`（`task_store.py:239`）——那是视图的语义本身，不是可缓存的重复劳动。
2. 建索引 = 多一份需要与 `tasks/*.jsonl` 保持一致的派生数据，直接继承 F3 的失败面，换来 <15% 的加速。不划算。

**D5 修复（P0）**：
1. `goal_coordination.py:371`：`limit=200` → `limit=500`（与 `task_store.py:413/:429` 的 `_goal_status_index` 统一语义）。
2. `degraded` 增两类显式条目：`goals_truncated: 500/600`（真的截断时）与 `window_empty: 24h 内无活动`（窗口过滤后为空时）。**空视图必须能自证是「真的没有」还是「被截断/被窗口吃掉」**。
3. `render_coordination` 首行追加 `capacity=used/limit`。
4. 窗口口径改为 `activity_at = max(goal.updated_at, max(task.updated_at))`（E9）；过滤下沉到 frontier 之后——代价已含在上面 14.7ms 内，不需要额外预算。

**升级触发条件（写死，不靠感觉）**：`coordination_status` p95 > 80ms **或** `goals_in_ledger > 450` 才考虑索引；届时优先做「goal 行尾 512 条 LRU + mtime/size 校验」，不预建全量索引。

**口径说明（防止把临时测量当基准）**：以上数字来自 2026-11-03 单机、单次运行的临时脚本（脚本在 `/tmp`，未入库），是量级判断，不是基准套件。复算方式：按同规模重建 fixture（`goals.jsonl` 行 + `tasks/{goal_id}.jsonl`，每 goal 12 条 task），用 `.venv/bin/python` 跑 `coordination_snapshot` 与 `compute_frontier` 循环；真实账本的 14.7ms 可直接复测，合成数据不适合进 CI（机器差异会让阈值失真）。

---

## 7. 失败模式矩阵

与 v1 §5 同构：每行"系统行为"列即测试断言目标；构造不出该行为视为实现失败。

| # | 机制 | 失败场景 | 系统行为（必须） | 设计对策 | 残余归属 |
|---|---|---|---|---|---|
| F1 | claim 账本（JSONL append） | 两进程同时 append | 逐行完整，无咬行/半行 | append 持 `fcntl.flock` 独占写锁；单行 ≤4KB | 锁语义仅本地文件系统（R7） |
| F2 | ttl 判定 | 时钟回拨 / NTP 跳变 | wall clock 只影响可用性不影响正确性 | 过期且未被接管 → 放行 + 标注续期；被接管 → generation 拦（Q33）；回拨只延长占用窗口 | R7 |
| F3 | 索引文件 | 损坏/截断 | 视图 `degraded=index_corrupt`，拒绝伪造数据 | 索引可从 JSONL 重建；损坏显式登记 | — |
| F4 | claim_token | token 被第二个 session 持有使用 | `claim_holder_mismatch` | token 绑 `holder_sid`；token 是 fencing 票据、不承担鉴权 | R1/R5 |
| F5 | N4 并发闸 | child 走其他进程通道（DSH/browser） | 计数不含它 | 闸明示口径="本进程 `spawn_subagent` 子代理"；回执写明 | R4 |
| F6 | N2 视图读 | 读到并发写中的账本 | 跳过不完整行或等锁 | 读侧 `flock` 共享锁；逐行完整性校验 | — |
| F7 | P2 enforce | 旧调用无 token | 硬拒 `claim_required` + 迁移指引 | 三档迁移（§11）+ 观察期量化无 claim 率 | D1 |
| F8 | renew/reclaim 竞态 | 恰在 ttl 边界 | 序列化为账本 append 顺序，后到者见前者新事实 | fencing generation 单调（§6.2）；复用 fleet 序列化契约（§2-7/2-9） | — |
| F9 | claims 路径构造 | 两个形似 goal_id（`GOAL/a` 与 `GOAL_a`） | 两个 claims 文件必须不同；归一后为空或含分隔符 → 直接拒绝 | 复用 `_safe_goal_id`（§6.2）；单测双 goal 隔离（N2-A13） | R13 |
| F10 | task 重开 | `done → in_progress` 后旧 claim 复活 | 旧 token 写入 → `claim_revoked`；新 holder 可 claim | `revoke_all` 行 + 先撤销后重开（Q27） | R10 |
| F11 | 锁序 | claim 与 task 写并发 | 2s 内全部返回，无死锁 | 全局锁序 claims → tasks → goal_coord（Q23） | R7 |
| F12 | holder 注入 | 调用方伪造 holder / session 不可证明 | 伪造被忽略；不可证明 → `claim_unverifiable` 拒绝（不发无主 claim） | `authority_session_id()` 注入（Q25） | R1 |
| F13 | claims 账本坏尾行 | append 中途崩溃留半行 | 跳过坏行 + `ledger_degraded=n`，后续 claim/写全部正常 | replay 与 `task_store._replay` 同构，绝不抛（Q34） | R15 |
| F14 | 软过期（Q33） | holder 过期但未放手，无人接管 | 本人写入放行 + 自动续期（`claim_expired_renewed`）；被接管后必拒 | 过期只取消独占；安全边界仍是 generation | R14 |

## 8. 测试计划

单元层（新增测试走 `tmp_path` fixture，不碰真实账本）：

| # | 内容 | 对应 |
|---|---|---|
| T1 | claim 原语：claim/renew/release 幂等；fencing generation 单调；ttl 过期后写拒；同 task 双 claim 串行化为 Granted+Conflict（`reclaimed` 标志正确） | N2；G1/G4 |
| T2 | 账本韧性：多进程并发 append 无咬行；索引损坏 → degraded + 可重建 | F1/F3/F6 |
| T3 | 三条硬编码 degraded 替换：`render_coordination` 输出快照对比（无 running 无 degraded 残留；有 running 出真实段） | N1；G7 |
| T4 | `coordination_status` running 段 + `only_in_flight` 过滤 | N1 |
| T5 | `task_update` 软路径：无 token → warn 计数；错 token → `claim_holder_mismatch` 提示；P2 关闭期永不硬拒 | N3；G3 |
| T6 | spawn 闸：达 `max_running_children` 拒 + 回执含计数与出口；释放后放行；闸判定在锁内 | N4；G6 |
| T7 | `task_create` 预检：同 goal in_progress / 标题重叠 → 仅警告不阻塞 | N5 |
| T8 | **调用方清点（P2 前置）**：已实测 2026-11-03——程序内分发入口唯一（`registry_task.py:22-25` → `tools_task.py:214`），无其他 Python 调用方；运行时调用方=模型工具调用，采纳率由观察期统计 | §2-12 |
| T9 | **锁序无死锁**：两线程各持 claim/task 锁反向申请 → 2s 内全部返回（超时即失败，不 sleep 轮询） | N2-A10 / Q23 |
| T10 | **重开撤销**：claim → done → 重开（confirm）→ 旧 token 写 → `claim_revoked`；新 holder claim 拿到 generation+1 | N2-A11 / Q27 |
| T11 | **holder 注入**：传 `holder=` 被忽略/拒绝；session 为空 → `claim_unverifiable` | N2-A12 / Q25 |
| T12 | **路径归一**：`GOAL/a` 与 `GOAL_a` 的 claims 文件不同；归一后为空 → 拒绝 | N2-A13 / Q26 |
| T13 | **组合入口无 TOCTOU**：在校验与落笔之间插入强制 reclaim 钩子 → 写入必败（证明没有窗口） | N2-A14 / Q24 |
| T14 | **软过期**：注入时钟使 claim 过期 → 本人写成功且回执带 `claim_expired_renewed`；再让 B 接管后 A 写 → `claim_generation_stale` | N2-A15 / Q33 |
| T15 | **ttl 边界**：clamp 到 60；`None` 未授权 → `claim_ttl_out_of_range` 且账本零新增 | N2-A16 / Q35 |
| T16 | **坏尾行**：预先写入 `{"kind":"claim",` 半行 → claim/renew/写全部成功，`ledger_degraded>=1`；不抛异常 | N2-A17 / Q34 |

守卫层（RULE-AI-35，G1–G11 表见 §4 末）：全部以 fixture 构造**真实输入**拿拒绝回执；G7 为只读反向断言（调用前后两账本 sha256/mtime 不变）。不引入测试替身屏蔽 `_durable_topology` 真实 I/O。

回归层：`tests/unit/test_fleet_reclaim_race_and_ttl.py` 已实测 PASS（9 passed，2026-11-03，`.venv`）；合入前既有测试全绿逐字比对（基线见 §2-11）。

## 9. 兼容、回滚、非目标

**兼容**：新增文件 1（`task_claim.py`）+ 可选参数与配置项，无签名破坏；无 claim 调用在 P0/P1 期行为与现状逐字一致（回执多 warn 行，不改变成败判定）；账本是新增路径，不动 `tasks.jsonl`/`goals.jsonl` 任何字节。

**回滚**（每档独立）：PR-0 删 running 段即回 v1 表现；PR-1 置 `claim_enforcement` 配置回退为纯日志；PR-2 天生默认关；claim 账本文件可整体删除，不影响 v1 已交付能力（§1 不回退底线）。

**非目标**：跨 workspace claim（边界=现有 workspace 数据边界）；自动调度/优先级队列（模型仍是唯一调度者，§4-Q21）；推送式通知（视图拉取式）；`workflow_run` 真并发引擎（N6 只标注）。

## 10. 残余与已知边界登记

| # | 残余 | 处置 |
|---|---|---|
| R1 | 同一 session 内的多个 run（父子同 session、重启后的新 run）无法区分；session 不可证明时**拒绝**而非放行（v2.1 收紧，Q25） | holder 由 `authority_session_id()` 注入，不再接受模型传参；残余面由「可伪造」缩窄为「同 session 多 run」 |
| R2 | 绕过 `task_update` 入口直改 JSONL 不受 claim 约束 | 入口唯一（§8-T8 已核）；文件级写锁超范围 |
| R3 | `mask_session` 去标识与可关联性的张力 | 沿用 v1 口径：能区分即可，不强匿名 |
| R4 | running 段是本进程内存态（`_handles`），跨 tab/跨进程 child 不可见 | 回执明示口径；跨进程事实看 `_durable_topology`（parent 维度）与 child 侧 lease/settlement |
| R5 | N5 标题重叠是启发式警告，非冲突判定 | 明示启发式 |
| R6 | `workflow_run` parallel 仍顺序执行（§2-10） | 真并发是独立设计 |
| R7 | `flock`/wall-clock 在 NFS/容器卷上弱化 | 声明本地文件系统前提（同 v1） |
| R8 | ~~模型不采纳 claim → 收益≈0~~ **（v2.2 消解）**：隐式签发使采纳率不再是前提 | 改为登记新残余：归属记录晚于动作——「谁想做」只能从 `in_progress` 那一刻起可见，claim 从「意向声明」退化为「动手指纹」 |
| R9 | 跨进程 wall clock 回拨可把「已过期」看成「未过期」（进程内已单调钳制） | 只延长占用窗口，不放大权限；安全边界仍是 generation；极端回拨需人工 release（Q29） |
| R10 | `revoke_all` 与 task 重开非同一事务：撤销成功而 update 失败 → 该 task 暂时无人可写 | fail-closed 侧；重新 claim 即可恢复，回执给出口（Q27） |
| R11 | per-parent 闸只覆盖本进程 `spawn_subagent`；DSH / browser 通道不计入 | 回执明示口径；不承诺全局成本上限（Q30） |
| R12 | task 无版本 CAS → 基于陈旧 frontier 的决策仍可能落到账本（只要 claim 仍有效） | 有意取舍（§3.3）；claim 只管「谁在写」，不管「依据是否新鲜」 |
| R13 | goal_id 归一是单向的：`A.B` 与 `A_B` 可塌缩为同名 claims 文件 | 与 `task_store` 同类既有弱点，本设计不扩大；实际 ID 形如 `GOAL-YYYYMMDD-hex8`，不触发（Q26） |
| R14 | 软过期期间「活着但很久没写」的 holder 会被他人接管（这正是 ttl 的用途） | 回执明示「已由 X 接管」+ 出口；被接管方不静默丢工作，只是丢失写权（Q33） |
| R15 | claims 账本 append-only 无天然压缩（fleet 整文件重写天然压缩）；坏行只跳过不修复 | >2000 行折叠为「快照+增量」；坏行保留原样（可审计），由 `ledger_degraded` 计数暴露（Q34） |
| R16 | 用户显式共享 `DATA_DIR` 跨 worktree 时，账本同源但代码状态不同 | 不承诺；回执口径写明 claim 作用域=一个 `data_dir`（Q36） |
| R17 | `recent_events` 只覆盖**已落账**的动作：正在跑、尚未写审计的动作看不见（与 running 段恰好互补但不相交） | 回执带 `recent_events_scope=workspace` + `observed_at`；文案明写「0 条≠没动过」（T-0.4b） |
| R18 | `recent_events` 的归属不完整：缺 `session_id` 的行 `attributed=false`，不能据此断定「无人推进」；`coverage_s` 可能 < 窗口（安静期出现空档，字节兜底触顶时亦然） | 两个量都常驻回执而不是内部字段：缺失就标缺失，不足就报真实跨度（§6.4.2） |
| R19 | `events.jsonl` **无轮转/无上限**：每 task 写入一行，长期跑会把 `data/audit/claims/` 变成第二个 `action_trace.jsonl`（后者 357MB）。读侧已按 4MB 截断扫描，但磁盘增长无限 | 观察期后按大小切分（`events-<YYYYMMDD>.jsonl`）+ 保留策略；`claim_metrics.py` 只读窗口内文件。不在此刻加轮转是因为写侧切分要配读侧合并，属于 PR-1 之后 **（PR-1 后仍开，安排见 §14.3-U1）** |
| R20 | `claim_event_write_failures` 是**进程内**计数：多进程各记各的，快照只能看到本进程 | 口径写进 §6.6 与渲染文案（「本进程」）；跨进程聚合需扫事件流（`bad_lines` 可部分替代）。**PR-1 后仍开**，安排见 §14.3-U2 |
| R21 | ~~事件里的 `holder` 是 run 的 session id，不是 claim 持有者~~ **（PR-1 闭合 2026-11-03）** | claims 账本的行自带 `holder` + `holder_kind` + `generation`；事件由 claim 层写，`holder` 取 claim 记录（`task_claim._emit_raw`），字段名不变（只增不改）|
| R22 | **warn 模式的跨会话冲突分支不可达**：归属闸（`cross_session_write_denied`）在 claim 校验之前，另一 session 连写都写不进来 | 观察期不得把「跨会话冲突率=0」解读为「不会冲突」——它只说明归属闸先拦住了。真实可达面是同 session 多 run（父子共用 session id）与移交后的新 owner（§14.3-U3）|

## 11. 任务拆解（P0/P1/P2，可逐条勾选）

### 11.0 三档总表

| 档 | 内容 | 进入判据 | 退出判据 |
|---|---|---|---|
| PR-0（P0） | N1 真实数据接线 + `only_in_flight` + N6 回执标注 | 本文档定稿 | 全绿 + G7 |
| PR-1（P1） | N2 claim 全量（锁序 + 组合入口 + 重开撤销 + 归一 + **隐式签发**：`pending→in_progress` 自动 claim）+ N3 软接入（warn）+ N4 拆闸 + N5 预检；`claim_enforcement` 恒 warn | PR-0 退出 | 全绿 + G1–G6/G8–G11 |
| 观察期 | 不写代码只收指标：冲突率 / 接管率 / **疑似误拒率**（隐式签发后「无 claim 率」应恒为 0，只作诊断） | PR-1 合入 | 连续 7 天四项判据全过（§11.4，不含主观项） |
| PR-2（P2） | N3 enforce：把「他人已持 claim 仍写」升为硬拒（`claim_conflict`）；`claim_required` 仅诊断（隐式签发已覆盖）。配置仍可关 | 观察期达标（D1 已裁决，§12） | G8 |

每档独立 PR、独立回滚（§9）。D1 已裁决（§12）：PR-2 只对「他人已持 claim」硬拒——**不存在「静默覆盖真冲突」这个选项**。

### 11.1 PR-0（P0，1–1.5 人日；不碰 claim 语义）

| ID | 改动 | 位置 | 验收 |
|---|---|---|---|
| ✅ T-0.1 | 视图上限 200→500 + 截断自证 | `goal_coordination.py`（`_GOALS_VIEW_LIMIT`、`GoalStore.count()`、`capacity`/`goals_truncated`） | **已实现 2026-11-03**。实测：239 行账本 → `goals_in_ledger=239`、`truncated=false`；`window_hours=0` 下 active **90/90**（旧值 78/90，12 个回归）；600 行 fixture → 500 条 + `goals_truncated: 500/600`。测试 `test_coordination_view_capacity.py` 4 条 |
| ✅ T-0.2 | 窗口改 `activity_at = max(goal.updated_at, max(task.updated_at))`；过滤下沉到 frontier 之后 | `goal_coordination.py`（`_ts_key`、activity 计算块）、`task_store.py:compute_frontier` 增 `last_activity` | **已实现 2026-11-03**。条目带 `activity_at`/`activity_source`；`window_empty` 自证并在文案内给 `window_hours=0` 出口。N1-A8 fixture（goal 48h + task 1h → 可见且 `activity_source=task`）通过。**注意 E10**：真实账本 24h 内仍为 0 条，属数据事实而非缺陷 |
| ✅ T-0.3 | `running.children` 接线：新增 `all_active_children()`，用 `handle.state` 判在飞 | `runner.py`（`all_active_children()`）、`corrections.py`（`CorrectionContext` 增 `subagent_runner`/`job_registry`）、`factory.py`（装配点注入）、`goal_coordination.py`（`_collect_running`） | **已实现 2026-11-03**。`children_scope=owner_session` 常驻回执；自己的出 child_id/generation/depth/state，他人只出脱敏 parent+计数（Q13）；top-N=10 截断自证；未装配 → 显式「未装配…不代表没有 child 在跑」。测试 `test_coordination_running_wiring.py` **7 条**：children 归属/掩码 1、jobs 归属/计数 1、top-N 截断自证 1、未装配 wording 1、在飞过滤（真实 `all_active_children`）1、G7 零写 1、真实 `build_engine` 注入 1 |
| ✅ T-0.4a | `running.jobs` 接线：新增 `JobRegistry.active_all()` + 视图内二次判在飞 | `tools/builtin/job_registry.py`（`active_all`）、`goal_coordination.py` | **已实现 2026-11-03**。自己的出 job_id/command/executor/started_at；他人只计数；`done/killed` 即使被事实源多返也丢弃。**残余**：重启后未收口执行不在本段（E11） |
| ✅ T-0.4b | `recent_events` 接线：审计流**尾部倒扫**（时间窗口 + 字节兜底），双因截断自证 | `goal_coordination.py`（`_collect_recent_events` / `_scan_stream_tail` / `_entry_ts` / `_RECENT_EVENT_STREAMS`、`render_coordination` events 行）、`tools_goal.py`（工具描述改口径）。**不参数化 `event_stream`**（实测 3029ms 且无截断语义，§6.4.2） | **已实现 2026-11-03**。`window_s=1800` + `top_n=10` + `2MB` 兜底；`truncated` 由 top-N 与字节触顶两因判定并各自出 degraded 文案；`coverage_s` 给真实跨度（可 < 窗口）；无 ts 行只计数、缺 sid 行 `attributed=false`；空即空（N1-A2，不编造 degraded）。实测：真实数据窗口内 **2382 条** → 出 10 条 + `truncated`；`coordination_snapshot(24h)` **p50 17.4ms / p95 18.0ms**（预算 80ms）。测试 `test_coordination_events_wiring.py` **12 条**（流表防漂移 / 窗口过滤与脱敏 / top-N / 字节触顶 + 半行丢弃 / 倒扫调用数 ≤4 / 无时间戳 / audit_dir 缺失 / 空即空 / 账本崩不连坐 / 渲染）；全相关面 **1068 passed / 2 skipped** |
| ✅ T-0.5 | N6：workflow 回执标注 `execution=sequential` | `tools/builtin/workflow.py:243`（parallel/pipeline）、`:331`（dag）、`:57`（描述） | **已实现 2026-11-03**。首行 `mode=…, steps=…, execution=sequential（…）`；三种 mode 各一条断言 + 既有断言零改动（N6-A1/A2）。G7 不受影响：纯字符串拼装，不写账本 |
| ✅ T-0.6 | 埋点骨架：`claims/events.py` + `claims/events.jsonl` + `claim_decision`/`fanout_decision`（此阶段只写 `passthrough`/`allow`）+ 失败计数器 | `introspection/claims/events.py`（新）；`task_store.py:277/371-373`；`runner.py:1369/1398-1419`；`goal_coordination.py:708` | **已实现 2026-11-03**。三条不变量（不阻断/不伪造/可丢但标注）由 `write_event` 单点执行；`claim_decision` 在锁内落笔后写（N7-A1 行数==写入次数），`fanout_decision` 锁内采集 + 锁外 append（N7-A4 running_before=决策前）；超 1KB 拒写并计数（N7-A3）；append 失败 → 调用照常成功 + `claim_event_write_failures` 进 `degraded`（N7-A2）。测试 13 + 5 条（§11.1.1 已按实测更新）；相关面 **1158 passed**（`-k "goal or task or coord or subagent or job or workflow or claim"`）。**未做**：`scripts/claim_metrics.py`（比率分母在 PR-0 无意义，见 §6.6） |

**为什么 T-0.6 排在 P0**：观察期要看的是 PR-1 上线后的真实比率；埋点若等 PR-1 再写，PR-1 第一周的数据就永久缺失。空跑一周还可提前验证「观测不阻断」这条不变量。

### 11.1.1 PR-1 落地结果（2026-11-03，逐条对账）

| ID | 实现落点 | 验证 | 状态 |
|---|---|---|---|
| T-1.1 | `introspection/task_claim.py`：`Claim`/`ClaimStore`、append-only 账本（**每 goal 一份** `claims/claim-<safe>.jsonl`）、last-wins 重放、坏行跳过 + `bad_lines`、>2000 行折叠 | `tests/test_task_claim.py::test_half_line_is_tolerated_and_claim_still_works` / `::test_ledger_compaction_keeps_current_state` | ✅ |
| T-1.2 | `tools_task.py`：`claim_task` / `renew_task` / `release_task` + `registry_task` 分派；`ttl_s` clamp `[60, 28800]`，`unbounded` 未授权 → `claim_ttl_out_of_range` | `::test_ttl_is_clamped_not_rejected` / `::test_invalid_ttl_is_refused` / `::test_unbounded_requires_authorization` / `test_task_claim_tools.py::test_claim_then_update_then_release` | ✅ |
| T-1.3 | 组合入口：`TaskStore.update_with_claim` → `ClaimStore.update_task_under_claim`，**claims 锁在外、tasks 锁在内**，同一临界区完成 check+write | `::test_update_with_token_writes_and_renews_in_one_critical_section` / `::test_concurrent_claim_has_exactly_one_winner` | ✅ |
| T-1.4 | 隐式签发：`pending→in_progress` 且无 token 时自动 grant，回执 `auto_claimed` | `::test_implicit_claim_on_pending_to_in_progress` | ✅（同 session 无 `write_holder()` 时改为标注 `claim_unavailable`，见 D-3） |
| T-1.5 | 重开撤销：`done→非done` 先 append `revoke` 行，失败即拒绝重开 | `::test_reopen_revokes_claim_before_writing` / `::test_revoke_failure_refuses_reopen` | ✅ |
| T-1.6 | holder 由程序注入：`write_holder()`（authority session id），模型无法传参；`holder_kind` 由前缀判定 | `test_task_claim_tools.py::test_claim_then_update_then_release`（回执 holder=run-…，非模型输入） | ✅ |
| T-1.7 | `task_store.safe_goal_id()` 成为唯一归一函数；claim 文件名直接复用它 | `::test_claim_and_task_use_same_safe_id` | ✅ |
| T-1.8 | `runner.py`：per-parent 闸 `max_running_children`（默认 16，clamp 1..32），与 global 128 **同锁判定**；`_ReserveDenied` 回执带计数/上限/三出口 | `tests/unit/test_claims_events_fanout.py::test_per_parent_gate_denies_and_reports_count_and_exits` / `::test_per_parent_gate_defaults_to_16_and_clamps_env` | ✅ |
| T-1.9 | 路径交叉预检：claim 时对其它活跃 claim 的 `expected_paths` 做前缀边界比对，命中只在回执提示 | `::test_path_overlap_detection` + `claim_task` 回执 `⚠ 路径可能交叉` | ⚠ 落在 claim 入口而非 spawn 入口（见 D-5） |
| T-1.10 | 真实 `claim_decision`（grant/renew/reclaim/revoke/deny/passthrough）+ `fanout_decision`（allow/deny + `reason_code`）；`task_store` 在 claim 路径下不再补 passthrough（`emit_event=False`） | `tests/test_task_claim.py` 全量断言事件行；`::test_quota_is_warning_not_refusal` 查 `reason_code` | ✅ |
| T-1.11 | `scripts/claim_metrics.py`：五指标 + 账本侧交叉计数 + `--since` | `tests/test_claim_metrics.py`（3 条：空分母=null / 冲突率分母 / 坏行 degraded） | ✅ |

**验证面**（2026-11-04 实测，按 `--collect-only` 计数，不沿用估算）：`tests/test_task_claim.py` 31 条、`tests/test_task_claim_tools.py` 3 条、`tests/test_task_claim_hardening.py` 18 条（四轮审查逐条对应）、`tests/test_claim_metrics.py` 3 条、`tests/unit/test_claims_events.py` 13 条 + `test_claims_events_fanout.py` 5 条 = **73 条**；`ruff check` 在改动文件上 0 新错；`pyright` `new=0`、`changed_file_diagnostics=0`。

### 11.2 PR-1（P1，3–4 人日；claim 全量 + 隐式签发 + 新闸）

| ID | 改动 | 位置 | 验收 | 依赖 |
|---|---|---|---|---|
| T-1.1 | `task_claim.py`：Claim 模型 + append-only 账本 + replay 韧化（跳坏行 / `ledger_degraded` / 2000 行折叠） | 新文件 | 半行截断 fixture 下 claim 与写仍可用（R15/Q34） | — |
| T-1.2 | 三个工具面 `claim_task` / `release_task` / `renew_task` | `tools_task.py` + 注册 | 回执符合 §6.3；ttl clamp `[60, 8h]` | T-1.1 |
| T-1.3 | 组合入口 `update_task_under_claim()`：锁内 check+write | `task_store.py:258`（临界区） | G2/G3/G4；接管后必现 `claim_generation_stale`（Q33） | T-1.1 |
| T-1.4 | 隐式签发：`pending→in_progress` 自动 claim，回执 `auto_claimed=true` | `task_store.py:240-300` | G1；`claim_required` 不再触发（N2-A9 降为诊断） | T-1.3 |
| T-1.5 | 重开撤销：先撤销，撤销失败即中止重开 | `task_store.py:301`（重开机械闸，撤销须先于该写入）、`:351`（下游 `premise_stale` 级联）；回执面 `tools_task.py:214` | G6；撤销失败路径必须**拒绝重开**（Q38 反向） | T-1.3 |
| T-1.6 | holder 由程序注入（`authority_session_id()`） | `tools_task.py:214` | 伪造 `holder` 参数被覆盖；G5 | — |
| T-1.7 | 路径归一 `_safe_goal_id` | `task_store.py:736-741`（与写路径同源） | 含 `/`、`..`、超长 goal_id 的写与 claim 落到同一文件（G5） | — |
| T-1.8 | **新增** per-parent 闸 16（1..32 可配），与 depth/128 同锁判定 | `runner.py:1354-1373` | 17 个并发 spawn → 第 17 个 `deny(parent_concurrency)` + 三出口；`running_before`/`limit` 字段正确 | — |
| T-1.9 | N5 路径重叠预检（warn 级） | spawn 入口 | 两子任务写同一批文件 → 回执带 `path_overlap` 与两 task id | — |
| T-1.10 | 埋点接线：真实 `claim_decision`（grant/deny/renew/reclaim/revoke）+ `fanout_decision` | `task_store.py:258`、`runner.py:1354-1373` | 事件与账本 1:1（丢弃尾行除外）；`latency_ms` 有值 | T-1.3 / T-1.8 |
| T-1.11 | `scripts/claim_metrics.py`：五指标 + 分母完整度 | 新脚本 | 对 fixture 事件流输出可复算数值；缺行时标「分母不完整」 | T-1.10 |

### 11.3 PR-2（P2，0.5 人日；观察期达标后才进）

| ID | 改动 | 验收 | 依赖 |
|---|---|---|---|
| T-2.1 | `claim_enforcement=enforce` 下「他人已持 claim 仍写」→ `claim_conflict` 硬拒 | G8；硬拒后同 holder 30s 内成功率为 0（真拒，不是误拒） | 观察期达标 |
| T-2.2 | §6.3 回执模板逐条覆盖（含 `claim_expired_renewed` / `claim_ttl_out_of_range`） | 模板表逐行有单测 | T-2.1 |
| T-2.3 | 回滚演练：置回 `warn` 后同一 fixture 的冲突写入恢复成功 | 演练记录落 `docs/changes/` | T-2.1 |

### 11.4 观察期判据（可算，不含主观项）

连续 7 天，`claim_metrics.py --since 7d` 同时满足：

| 判据 | 门槛 | 不达标时先查什么 |
|---|---|---|
| `event_write_failures` / `ledger_degraded` | 均为 0 | 磁盘/权限；事件写是否误入权威路径 |
| 疑似误拒率 | ≤ 1% | ttl 偏短、reclaim 抢在 holder 重试之前 |
| 冲突率 | ≤ 2% | 隐式签发是否覆盖全部写入入口 |
| 冲突回执可解释性 | 100% 带 `reason_code` + 出口 | §6.3 模板是否漏分支 |

四项全过才进 PR-2；任一不达标 → 停在 warn，先修因，**不改判据**。

**关键路径**：T-0.1/T-0.2（视图自证）→ T-0.6（观测就位）→ T-1.1 → T-1.3 → T-1.4 → T-1.8/T-1.10 → 观察期 → T-2.1。T-1.6/T-1.7 可与 T-1.1 并行。

## 12. 裁决归档（D1–D5，2026-11-03 已定）

| # | 问题 | 裁决（采纳建议） | 依据（可核） | 生效值 |
|---|---|---|---|---|
| D1 | P2 硬拒是否最终开启、何时开启？ | **(d) 隐式 claim 先行 + 冲突硬拒**（新增选项，比 a/b/c 更优） | ① `enforce` 会闸住 63% 的真实写（1710 行里 570 `in_progress` + 507 `done`）；② 采纳率是模型行为，不能当前提（R8 的反向风险=自伤停摆）；③ 隐式 claim 让「无 token」不再是错误——`pending→in_progress` 由程序自动签发（`auto_claimed=true`），硬拒只剩「他人已持 claim」这一个真冲突；④ 真冲突时让位（fail-closed）永远优于静默覆盖。原三选项的问题：a/b/c 都在赌采纳率，而采纳率本可以不经赌 | 先实现隐式 claim（PR-1 内），PR-2 只开「冲突硬拒」；`claim_required` 降级为诊断信息 |
| D2 | claim ttl 默认值 | **30min 保留，但语义改为「接管资格」而非「写权期限」**（Q33） | 硬失权下：30min → 19.2% 的写被误拒，60min → 11.5%，120min → 7.2%，240min → 3.0%（531 次实测间隔）。软过期后 30min 只意味着「闲置 30min 后可被接管」，误拒归零 | 按 30min（接管阈值）实现 + 软过期语义；`max_claim_ttl_s=8h` |
| D3 | worktree 与 claim 的关系 | **(a) claim 为主**，但不做 git-common-dir 归一——账本天然按 `data_dir`（=代码根）隔离 | 16/82 workspace 是 worktree（19.5%），但仅 8/1745 child（0.5%）来自 worktree 内 parent；`.worktrees/*/data/audit` 各自独立（E6/Q36）。跨 worktree 冲突只在你显式共享 `DATA_DIR` 时出现 | 写死「claim 作用域=一个 `data_dir`」；共享 `DATA_DIR` 登记为不承诺（R16） |
| D4 | per-parent 并发闸默认值 | **16**（可配 1..32） | 实测 per-parent 峰值并发：中位 1、p90 4，但有 10 个 parent 曾 ≥8、最高 30。闸=8 会拦掉 4.3% 的 parent（且都是高产 fan-out），闸=16 只拦 1.7%；全局 128 仍在天花板（Q30/§2.1-E1）。口径说明：峰值由 session `created_at→updated_at` 近似，偏上限，方向可靠 | 按 16 实现 + 记录 `parent_concurrency` 拒绝事件用于校准 |
| D5 | 视图容量与窗口口径（本轮新增） | **200→500 + 截断/空窗口显式化** | 真实账本 239 行时视图仅 200 条 → **12 个 active goal 不可见（78/90）**；全量 239 goal 实测 14.7ms；合成 400→25.9ms、800→52.4ms，线性（§6.7/Q42） | `limit=500` + `goals_truncated`/`window_empty` + `capacity=` |
| D6 | 协调视图默认窗口（2026-11-03 用户裁决） | **24h → 0（不限）** | 同一 `data/audit` 实测：`window_hours=24 + only_in_flight=true` → **0 个 goal**；`window_hours=0` → **78 个**。24h 默认把全部在飞目标隐掉，视图返回空会让调用方以为"没人推进"，从而在别人正在推进的 goal 上再开一条线——正是 claim 层要防的冲突来源。容量与刷新率都不是瓶颈（239 goal 14.7ms），窗口省的是行数、丢的是可见性；`only_in_flight` 已限定 active，"久没动"恰是最该被看见的僵死项 | 工具 schema 描述 / `args.get("window_hours", 0)` / `coordination_snapshot(window_hours=0)` 三处同改；首行渲染 `window=all`（不再写 `0h` 误导）；`test_default_window_is_unbounded` 锁定 |

**裁决记录（2026-11-03）**：用户指令「按你的建议继续完善」→ D1–D5 按「采纳建议」列定案，锁定如下：
- PR-1 内含**隐式签发**；PR-2 只开「他人已持 claim 仍写」的 `claim_conflict` 硬拒，`claim_required` 仅作诊断——**不存在「静默覆盖真冲突」这个选项**。
- ttl 30min = 接管阈值（不是写权期限）；`max_claim_ttl_s = 8h`，`expires_at` 由程序 clamp。
- claim 作用域 = 一个 `data_dir`；共享 `DATA_DIR` 跨 worktree 明确不承诺（R16）。
- per-parent 上限 16（**新增闸**，1..32 可配）；全局 `_max_handles=128` 不动。
- 视图 `limit=500`（可配）；截断与空窗口必须自证，`capacity=` 进 `render` 首行。
- 回滚成本：五项均为配置/常量级回退，无数据迁移；D5 回退即改回 200（会重新引入今天的截断）。

---

## 13. 修订记录

### v2.8（2026-11-03，PR-1 落地）

1. **T-1.1–T-1.11 全部落地**，逐条对账见 §11.1.1；新增 `introspection/task_claim.py`、`scripts/claim_metrics.py`、`tests/test_task_claim.py`(31)/`test_task_claim_tools.py`(3)/`test_claim_metrics.py`(3)。
2. **修正 §6.6 的过期口径**：过期不是失权。`update_task_under_claim` 对"过期 + generation 匹配 + 未撤销"的 token **放行并续期**（`claim_expired_renewed`），只有 generation 落后/换手或 released/revoked 才拒（Q33 早已如此裁定，本版把实现对齐）。原先实现按"过期即拒"写，属于实现偏离设计，已改。
3. **R21 闭合**（`holder` 改取 claim 记录）；**新增 R22**（跨会话冲突分支不可达，归属闸先拦）。
4. **新增 §14**：交付边界、6 条偏差（D-1–D-6）、8 条未解决事项及安排、观察期日历、降级路径。
5. `fanout_decision.reason_code` 由 `max_handles` → `handle_capacity`（D-2），PR-0 断言同步更新。

| 版本 | 变更 | 触发 |
|---|---|---|
| v2.0 | Q1–Q22 搭骨架：四类并发控制正交性、N1–N6、§5/§6 设计、§7 F1–F8 | 首轮拷问 |
| v2.1 | Q23–Q32 源码实测纠错：§2.1 勘误 E1–E4；N4 改判为「拆口径」；新增锁序 / 组合入口 / 重开撤销 / holder 注入 / 路径归一 5 项实现约束；工具面 4→3；T1–T8→T1–T13，G1–G8→G1–G11；新增 D4 | 第二轮拷问 |
| v2.2 | Q33–Q39 用真实账本统计推翻三处语义前提：§2.1 勘误 E5（过期≠失权）/E6（账本按代码根隔离）；新增 §4.3；N2-A7 改判 + A15–A17；N4 默认 8→16；F13/F14、T14–T16、R14–R16；§12 四问全部附建议与数据 | 第三轮拷问 |
| v2.3 | Q40–Q45 把两处"只有名字"落到可执行：新增 §6.6（3 个埋点写入点 + 事件 schema + 五指标 + 三条不变量）、§6.7（成本曲线实测：239 goal 14.7ms、1600 goal 106.6ms，判定不建索引）；新增 §2.1 勘误 E7/E8/E9；新增 §4.4；§11 拆成 T-0.1–T-2.3 共 20 条可勾选任务 + 观察期四项判据；§12 由「待裁决」改为「裁决归档 D1–D5」；N1 增 A7/A8 | 第四轮拷问 + 裁决收口 |
| v2.4 | **T-0.1 / T-0.2 落地并实测**（首批实现代码，不再是纯设计）：`_GOALS_VIEW_LIMIT=500` + `GoalStore.count()` + `capacity`/`goals_truncated`；`activity_at` 口径 + `activity_source` + `window_empty` 自证入口。真实账本 active **78/90 → 90/90**；`window_hours=24` 仍 0 条（新增 E10：口径修正不产生数据）；新增回归测试 `test_coordination_view_capacity.py`（4 条）。性能 p95 **11.6ms** | 第二轮拷问遗留的「下一步」执行 |
| v2.5 | **T-0.3 / T-0.4a 落地**（`running` 段首次接真实事实源）：`SubAgentRunner.all_active_children()`（在飞判据 `handle.state=="running"`）+ `JobRegistry.active_all()`；`CorrectionContext` 增 `subagent_runner`/`job_registry` 并在 `build_engine` 装配点注入；`_collect_running` 输出 `children_scope=owner_session`、mine/others 计数、top-N=10 截断自证、`observed_at`；他人 session 只出脱敏 parent+计数。**新增勘误 E11**（设计原稿的 `subagent.get_runner` 不存在、`snapshots_for_session` 语义不同源）与 **E12**（`active_children()` docstring 说在飞、实现不看 state）。`recent_events` 仍未接线（拆为 T-0.4b）。新增测试 `test_coordination_running_wiring.py`（7 条，含真实 `build_engine` 注入与 G7 零写）；相关面 **1056 passed / 2 skipped**；真实账本 p95 7.6ms | 第五轮执行 |
| v2.6 | **T-0.4b 落地，并推翻原设计的事件源方案**：原稿写「事件源 = `event_stream`」，实测 `event_stream(streams="action_trace")` **3029ms**、全流 **4204ms** 且无截断语义 → 改为自建尾部倒扫（`_scan_stream_tail`：撞 cutoff 即停、`start>0` 丢弃半行）；「最近」由字节量（128KB 在两条流上分别值 4 分 16 秒 vs 1 天 6 小时）改为**时间窗口 1800s + 2MB 成本兜底**；`truncated` 拆两因（top-N / 字节触顶）；新增 `coverage_s`/`scanned_bytes`/`attributed` 三个诚实字段与 §10-R17/R18。真实数据窗口内 2382 条 → 出 10 条；`coordination_snapshot(24h)` p50 **17.4ms** / p95 **18.0ms**（预算 80ms）。新增 `test_coordination_events_wiring.py` 12 条（含流表防漂移、字节触顶+半行丢弃、倒扫调用数 ≤4、账本崩不连坐 events）；旧断言「degraded: recent_events」按新语义改写；相关面 **1068 passed / 2 skipped** | 第六轮执行 |
| v2.7 | **T-0.5 / T-0.6 落地，PR-0 收口**：① workflow 回执首行加 `execution=sequential`（三 mode 均断言，既有断言零改动）；② 新模块 `introspection/claims/events.py`（`write_event` 单点执行三条不变量：吞异常+计数 / 权威落笔后才写 / 超 1KB 拒写）；③ `claim_decision` 接在 `task_store.update()` 锁内 `_append` 之后（行数==写入次数）、`fanout_decision` 接在 `_reserve_background_child` 的决策临界区；④ **实现偏差**：`fanout_decision` 字段锁内采集、append 锁外同一帧（不在被 `active_children`/topology 共用的热锁上做 I/O）；⑤ **语义澄清**：PR-0 的 `latency_ms` 是「校验+落笔临界区」耗时（replay+append），不是 claim 延迟，`holder` 是 run 的 session id 而非 claim 持有者；⑥ 读侧 `_collect_claim_metrics()` 把 `claims_events{lines,bad_lines,bytes}` + `claim_event_write_failures` 进快照，失败计数进 `degraded`（「分母不完整」），坏行只计数不报 degraded，超 4MB 只回 size；新增 §10-R19/R20/R21（无轮转 / 进程内计数 / holder 语义）。测试 13+2+1 条；相关面 **1158 passed**；ruff 仅剩 1 条既有 `tools_skills.py` UP032 | 第七轮执行（继续） |

**v2.1 相对 v2.0 的实质变化（不是文字润色）**：

1. **N4 改判**：从「新建并发闸」→「拆既有 128 闸的口径」。工作量下降，但仍必须动 `runner.py` 的临界区（三闸同锁内判定）。
2. **fencing 从「写前检查」→「校验与落笔同一临界区」**，新增 `update_task_under_claim` 组合入口。**这是本轮最重要的实现约束**：没有它，N2 的 fencing 在 ttl 边界仍有 TOCTOU 窗口。
3. **新增 `revoke_all`**：修补 `done → in_progress` 重开后旧 claim 复活的漏洞。
4. **holder 改为程序注入**，session 不可证明时**拒绝**（比 v1「标注放行」更严）。
5. **claims 路径复用 goal 归一**，堵住两个 goal 塌缩到同一文件后的串号。
6. **工具面 4 → 3**：删除 `reclaim_if_expired`，过期接管并入 `claim_task`（回执 `reclaimed=true`）。
7. **测试方法论补一条**：并发测试不靠 sleep 竞速，靠「状态构造」造确定性竞态；真并发只用于「恰好一个赢家」类断言（Q32）。

**未变的结论**：N1 / N3 / N5 / N6 的定位与验收、三档迁移与 D1 的阻塞关系、fleet 同构论证（§2-6/2-7/2-9）、§9 非目标。

**v2.2 相对 v2.1 的实质变化（不是文字润色）**：

1. **过期语义从「失权」改为「可被接管」**（Q33）。这不是放宽，是把安全边界从时间挪回 generation——后者本来就在。代价：被接管的原 holder 会在下一次写入才发现（已要求回执明示）。
2. **ttl 从「危险参数」变成「无关紧要参数」**（D2）。19.2% 的误拒风险归零，30min 不再需要观察期校准才能用。
3. **D1 的赌注被拆掉**：隐式 claim 让「模型会不会主动 claim」不再是成败前提（Q33/D1）。
4. **D3 的前提被证伪**：账本绑定代码根，worktree 默认就隔离（E6/Q36）——省掉一次 subprocess 与一类跨区 bug。
5. **补两个会永久卡死/静默复活的边界**：claims 坏尾行必须跳过（Q34）、`revoke_all` 失败必须中止重开（Q38）。
6. **§13① 结案**：组合入口锁持有期实测 0.18ms（最大 goal 账本 71KB），不进性能项（Q37）。

**第四轮把上轮留下的两类问题都问完了，两类都结案**：① 埋点位置已落到 3 个写入点 + 1 个代理指标（§6.6），且提前到 P0（T-0.6 空跑一周）；② 成本曲线实测为线性、无索引必要（§6.7），真正的问题是 200 行截断（E8），已作为 D5 进 P0。**注意 v2.2 引用的 6.5ms 是默认 24h 窗口下的空视图耗时**（窗口内 0 个 goal），不能当作全量成本；全量口径实测 **14.7ms**（239 goal）。

**v2.3 相对 v2.2 的实质变化**：
1. **新增 D5**：视图 200→500 + 截断/空窗口显式化。理由不是「未来可能」，而是**现在已有 12 个 active goal 不可见**（78/90）。
2. **N4 从「调参」改判为「新增闸」**：`_max_handles=128` 是全局的，per-parent 闸在代码里并不存在（E7）；实现风险集中到 `runner.py:1354-1373` 一个函数。
3. **新增 §6.6**：事件 schema、三个写入点、五指标、三条不变量（不阻断 / 不伪造 / 可丢但标注）；「误拒率」降级为「疑似误拒率」这一代理指标（Q43）。
4. **新增 §6.7**：三条硬结论——不建索引、D5 四项修复、升级门槛 `p95>80ms` 或 `>450 goal`。
5. **§11 从三档表升级为 20 条任务**：T-0.1–T-0.6 / T-1.1–T-1.11 / T-2.1–T-2.3，每条带位置与验收；观察期四项判据全过才进 PR-2。
6. **§12 收口**：D1–D5 全部定案（用户指令 2026-11-03「按你的建议继续完善」），并写死「不存在静默覆盖真冲突选项」。

**v2.6 相对 v2.5 的实质变化**（2026-11-03，T-0.4b 落地后回填；改的是设计本身，不是措辞）：

1. **`recent_events` 的事件源从「参数化 `event_stream`」改为「自建尾部倒扫」**：实测 `event_stream(streams="action_trace")` **3029ms**、全流 **4204ms**，且该接口**没有截断语义**，无法满足「被截断即标 `truncated`」的验收词。新实现 p95 **18.0ms**（含账本 7.6ms 基线）。
2. **「最近」从字节量改为时间量**：同一 128KB 在 `action_trace` 上值 4 分 16 秒、在 `exception_log` 上值 1 天 6 小时——字节窗口的「最近」不可解释。改用 `window_s=1800` 定义，2MB 仅作成本兜底（§6.4.2 数据表）。
3. **`truncated` 拆成两个独立成因**：top-N 截断 与 字节兜底触顶，各自出 degraded 文案；并新增 `coverage_s`（真实跨度）、`scanned_bytes`、`attributed`——三者都是「不许把不知道说成没有」的落地字段。
4. **新增 §10-R17/R18**：事件只覆盖已落账动作；归属不完整（缺 sid 行）、覆盖可能不足整窗。
5. **§11 T-0.4b 勾选**：代码 + 12 条测试 + 实测延迟回执齐备，相关面 **1068 passed / 2 skipped**。

**v2.7 相对 v2.6 的实质变化**（2026-11-03，T-0.5/T-0.6 落地后回填）：

1. **埋点写入点从「锁内」改为「锁内采集、锁外 append」**（E-2）：原稿把 `fanout_decision` 的写盘放在 `_children_guard` 里；实现时发现该锁被 `active_children`/topology 等读路径共用，在热锁上做文件 I/O 会把一段 append 延迟传染给所有查询。决策临界区仍是同一个 `with` 块，只是把 syscall 挪到块外同一函数帧。E-1（`claim_decision`）保持在账本文件锁内 —— 那里本来就在做 fsync 写，多一次小 append 是边际成本，且必须与「落笔成功」严格同序。
2. **`latency_ms` 的口径被迫写清**：PR-0 没有 claim 层，这个字段实际测的是「取锁 → `_append` 完成」（replay+append）。把它当成 claim 校验延迟会直接污染 N2 的延迟验收，因此在 §6.6.1 与模块注释里都固定了定义。
3. **`holder` 在 PR-0 不是 claim 持有者**：取当前 run 的 session contextvar，无 run context 时为 `null`。字段名保留（只增不改），语义在 PR-1 接线 claim 后切换 → 登记 §10-R21。
4. **读侧新增「分母完整性」出口**：`coordination_snapshot()` 多出 `claims_events{lines,bad_lines,bytes}` 与 `claim_event_write_failures`，失败计数进 `degraded`；坏行（崩溃半行）只计数不报 degraded —— 半行是预期的，不是损坏。超 4MB 只回 size，避免为一次快照全量扫事件流。
5. **新增 §10-R19/R20**：事件流无轮转/无上限（长期会变成第二个 `action_trace.jsonl`）；`claim_event_write_failures` 是进程内计数，跨进程不可见。
6. **`scripts/claim_metrics.py` 明确延后**：PR-0 的 `claim_decision` 全是 `passthrough`，五个指标的分母都没有意义；此时写脚本只会产出看起来像结论的空比率。改为随 T-1.10 一起落地。

**仍未解决的问题（诚实清单）**：
1. **PR-0 全部 7 条任务已有实现代码与测试回执**（v2.4 + v2.5 + v2.6 + v2.7；`test_coordination_view_capacity.py` 4 条、`test_coordination_running_wiring.py` 7 条、`test_coordination_events_wiring.py` 12 条、`test_claims_events.py` 13 条、`test_claims_events_fanout.py` 2 条、`test_workflow.py` 新增 1 条；`-k "goal or task or coord or subagent or job or workflow or claim"` 共 **1158 passed**）。**没有实现的只有 `scripts/claim_metrics.py`**（比率分母在 PR-0 无意义，随 T-1.10 补）与 PR-0 观察期的空跑本身（需真实时间，无法伪造）。
2. **`recent_events` 只是「已落账」的窗口**：正在跑但尚未写审计的动作看不见；`action_trace` 部分行缺 `session_id`，只能标 `attributed=false`（§10-R17/R18）。它与 running 段互补但不相交——两段都空**不能**推出「无人推进」。
3. **running 段只是本进程内存态**：另一个 tab/进程的 child 与 job 不可见（E11/§10-R4）。回执已盖 `observed_at` 且未装配时显式 degraded，但「看到 0 条」不能推导出「全局无人在跑」——这条边界没有在 UI 文案上强制提示。
4. **重启后的在飞执行不在 running 段**：`JobRegistry.active_all()` 只读内存 `_jobs`；`snapshots_for_session` 里的 durable orphan 事实未被纳入（语义是「不再推断存活」，与本段「在飞」不同源）。若需要「重启后谁可能还在跑」，应另开一段而不是把 orphan 塞进 running。
5. **旧接口 `active_children()` 的语义漂移未修**（E12）：它仍返回「已登记」而非「在飞」。新调用方一律用 `all_active_children()`；旧调用点未审计——有需要时按 `handle.state` 自查。
6. **top-N=10 只能看计数、不能展开**（两段都是）：`coordination_status` 没有 `include_all` 参数，超过 10 条时只能看到计数（Q15 原设计的展开口未实现）。
7. **`recent_events` 的 I/O 粒度尚未优化**：当前每次读满 `min(size, 2MB)`×2 流（p95 18ms）。升级触发与方案已写在 §6.4.2（p95>40ms → 64KB 分块倒读）。
8. 全局 `_max_handles=128` 在高并发下是否该下调，未测——它现在是唯一的兜底闸。
9. claims 账本跨会话并发（两个 session 同时写同一 goal）的锁争用只有估算值（replay 0.18ms/71KB），未做压测。
10. 观察期 7 天的真实数据尚不存在：§11.4 的门槛是**预测值**，跑完可能需调整——但调整必须落记录，不得事后改判据。
11. **E10 的产品含义未定**：本仓库 24h 热窗口常态为空，`window_empty` 只解决「诚实」，未解决「默认可用」。是否把 `only_in_flight` 视图默认改为 `window_hours=0`，需产品判断（当前按既有测试锁定保持 24h）。
12. **埋点自身有三个已知缺口**（§10-R19/R20/R21）：事件流无轮转（磁盘无上限，读侧只做到 4MB 截断扫描）；`claim_event_write_failures` 只统计本进程；PR-0 的 `holder` 是 run 的 session id，不代表「谁占了 task」。三项都不影响「观测不阻断」，但会让第一周的比率解读需要额外口径说明。
13. **`fanout_decision` 的 append 在锁外**：字段仍是决策临界区内的值，但若两个线程几乎同时决策，事件在文件里的顺序可能与其决策顺序相反。只影响「时序阅读」，不影响计数类指标；如将来要用事件重建时序，需在锁内追加单调序号（现未做）。

## 14. PR-1 交付边界与未解决事项安排（2026-11-03）

### 14.1 已做 / 未做（不混淆）

**已做且有回执**：T-1.1–T-1.11 的代码与测试（见 §11.1.1）；`scripts/claim_metrics.py` 可对任意 audit 目录离线复算；`ruff check` 在改动文件上无新错。

**未做（明确列出，避免"看起来做完了"）**：
1. **全量测试**未跑：按 RULE-AI-28，全量测试需先取得覆盖当前产物的独立审查 PASS，本轮只做了分批定向回归。**不得据本轮结果声称"全量绿"**。
2. **观察期数据**为零：`claim_metrics` 现在对本仓库只能输出「分母为空」。
3. **`claim_enforcement=enforce` 未开启**（T-2.1 的“打开”动作属 PR-2）。精确表述：`task_claim.update_task_under_claim` 里 `enforcement == "enforce"` 的**判定分支代码已存在**，但**没有任何测试覆盖**（`grep enforce tests/` 只命中 config 默认值断言），默认仍是 `warn`；warn 下没带 token 的写入仍然成功。因此现在不能说「enforce 已实现」，只能说「代码路径存在、未验证、未开启」。开启前必须先补 enforce 用例（他人持 claim → 硬拒；同 holder 30s 内成功率 0）。
4. **事件流轮转**（R19）、**跨进程失败计数**（R20）未做。
5. **独立审查已发生过一次 REVISE**（P0=0 / P1=1 / P2=7），见 §14.6；修复后需重新取证。

### 14.2 与原设计的偏差（逐条给理由）

| # | 偏差 | 理由 | 影响面 |
|---|---|---|---|
| D-1 | 账本从"单文件 `ledger.jsonl`"改为**每 goal 一份** `claims/claim-<safe>.jsonl` + 同名 `.lock` | T-1.7 的存在前提就是"claim 与 task 必须落在同一归一化文件名上"——单文件下这条无从验证；分文件同时把锁争用从全局降到每 goal | 指标/回执不变；`claim_metrics` 已按 `claim-*.jsonl` 统计账本行 |
| D-2 | `fanout_decision` 的 reason_code 由 `max_handles` 改为 **`handle_capacity`** | 与 §4-Q30 的命名一致（§6.6 示例沿用旧名）。保留旧名会让两个真值并存 | 已同步更新 PR-0 的断言；属于字段值变更，**读旧事件流时需按新名匹配** |
| D-3 | 无 run 身份时**不隐式签发**，改为回执标注 `claim_unavailable` | 没有身份就没有 fencing；此时拒绝写入会让脚本/评测这类无 run context 的调用整体失败，而它们本来也不并发 | 这类调用仍可写 task，但不会被计入"受保护写入"（`unprotected_write_share` 会体现） |
| D-4 | `task_not_claimable` 只在**带 token** 时强制 | warn 模式下若把它当硬闸，会让「done 任务补录 evidence_refs」这类既有合法写入直接失败 | 与 N3「warn 期不硬拒」一致 |
| D-5 | 路径交叉预检放在 **claim 入口**，不是 spawn 入口 | 单点判据：claim 时已知 `expected_paths`，spawn 时不知道子任务会写哪里；两处都做会产生两个真值 | 与 §5-N5「预检」语义一致；spawn 侧未加 |
| D-6 | `config.py` 与 `task_claim.policy_from_env()` **同读一批环境变量**，不是单一读取入口 | claim store 在深调用栈里构造，注入 settings 需要改动面更大的装配链 | 用 `test_policy_matches_config_defaults` 锁定默认值一致，漂移会被测试抓住；**clamp 一致性**由 §14.6-P2-4 的测试补上（默认值相同 ≠ 下界相同） |
| D-7 | 组合入口 `update_task_under_claim` / `TaskStore.update_with_claim` 增加**显式 `authorized` 契约**（默认 False → `ValueError`） | 该入口会先改 claim 账本再调 `store.update`，自身不做归属判定；原来只靠“工具层已 `_require_active_goal`”这一顺序事实，任何直接调用（含脚本、测试、未来新工具）都会绕过归属门 | 工具层 `run_task_update` 显式传 `authorized=True`；绕过者立即失败而不是静默生效。测试 `test_under_claim_requires_explicit_authorization` |
| D-8 | token 路径的**续租行落账移到 `store.update` 成功之后** | 原顺序先 append `renew` 再 update；update 因非法转移/证据缺失抛错时，账本留下一条没有对应 `claim_decision` 事件的 renew 行，破坏 T-1.10 的 1:1。改序后代价是「写入成功但续租落账失败 ⇒ 租约不续」，但 generation 未变，安全性不由时间承担（Q33） | 失败路径不再污染账本；成功路径事件与账本仍成对。测试 `test_renew_row_written_only_after_update_succeeds` |
| D-9 | `policy_from_env()` 补齐与 `config.py` 相同的 **clamp/回落**：TTL 与 max TTL `max(60,…)`、`max_per_holder max(1,…)`、未知 `enforcement` 回落 `warn` | 原实现只读不 clamp，`LFL_CLAIM_TTL_S=1` 会签出 1 秒租约、`=bogus` 会进入非预期分支；`test_policy_matches_config_defaults` 只比默认值，比不出下界差异 | 两个读取入口对同一批 env 现在语义一致。测试 `test_policy_from_env_clamps_like_config` |
| D-10 | `compute_frontier` 的 `last_activity` 改为**按解析后的时刻**取最晚（`_iso_key`），`stalled` 同源；`now_ts` 朴素时间按本机时区补齐 | 账本跨机器/容器共享，历史行可能带 `+00:00` 而同机写入带 `+08:00`；字符串 `max()` 在混合偏移下不选最晚，naive 与 aware 相减还会抛 `TypeError`（原 `except ValueError` 抓不到，会打断整个 frontier 构建） | 输出字符串保持原样（不改写账本格式）；混合时区输入不再算错/打断。测试 `test_frontier_last_activity_compares_instants_not_strings` |
| D-11 | `fanout_decision` 事件的 `(running_before, limit)` 统一取 **deny 自身的口径**（`deny.count`/`deny.limit`），不再是“全局 handle 数 + per-parent 上限”的混搭 | `parent_concurrency` 拒绝时真值是 per-parent running 数，此前从未落到事件里，读数无法解释（Q30 要求同口径） | 事件可解释性修复；allow 路径口径不变。纯函数 `_fanout_observation` + 测试 `test_fanout_event_uses_deny_own_scope` |

### 14.3 未解决事项与安排

每条都写清「为什么不现在做」，避免下一个人误以为忘了。

| # | 事项 | 为什么不现在做 | 触发条件 | 动作 | 时间 |
|---|---|---|---|---|---|
| U1 | 事件流无轮转（R19） | 切分要写侧切分 + 读侧合并同时改，否则会出现"读一半文件"的新故障 | `claims/events.jsonl` > 64MB，或观察期结束 | 按日切 `events-<YYYYMMDD>.jsonl`；`claim_metrics` 只读窗口内文件；保留 30 天 | 观察期结束后第一个 PR |
| U2 | 跨进程失败计数（R20） | 需要写侧在失败时也想落一条（现在失败即不写），会引入"失败即报错"的新路径 | 出现 `bad_lines > 0` 或快照 `degraded` | 失败改走独立 `write_failures.jsonl`（append-only，同样不阻断） | 同 U1 |
| U3 | 跨会话冲突分支不可达（R22） | 归属闸先于 claim 校验是既有安全设计，不能为了测指标去放宽 | 实现 `transfer_goal`（P2）后 | 用两个真 owner 交接的场景验证 `claim_conflict_warning` 可达，并补一条端到端测试 | 随 transfer_goal |
| U4 | ~~`only_in_flight` 默认 24h 视图常态为空（E10）~~ **已裁决并落地（D6）** | 用户 2026-11-03 拍板：默认改 `window_hours=0`（不限） | 已生效 | 三处默认同改 + 首行 `window=all` + `test_default_window_is_unbounded`；回滚=改回 24 | ✅ |
| U5 | 观察期 7 天空跑 | 只能等真实时间 | 2026-11-04 起 | 见 §14.4 日历 | 2026-11-11 结算 |
| U6 | 全量测试 + 独立审查 | RULE-AI-28 要求独立审查覆盖当前产物；本轮产物仍在同一工作树变动 | 本 PR 代码冻结时 | `review_admission(action=start, kind=full_test)` → PASS 后跑全量 | PR-2 前 |
| U7 | `enforce` 切换（T-2.1） | 依赖观察期判据；过早切换会让正常写入失败 | §11.4 四项判据全过 | 切 `LFL_CLAIM_ENFORCEMENT=enforce`，先在一个 goal 上试 24h | 观察期后 |
| U8 | per-parent 闸不覆盖 DSH/browser 通道（R11） | 跨进程成本上限是独立问题 | 出现"绕开 spawn_subagent 的 fanout"实例 | 在 DSH 侧加同名计数器，或把闸下移到 job 层 | 未排期 |

### 14.4 观察期日历（判据见 §11.4）

| 日期 | 动作 | 产出 |
|---|---|---|
| 2026-11-03 | 基线：`claim_metrics.py --since 7d`（预期空） | 基线 JSON 存 `docs/changes/` |
| 2026-11-04 → 11-10 | 每日一次 `claim_metrics --since 24h`，只记不判 | 7 份日读数 |
| 2026-11-11 | `--since 7d` 结算，对照 §11.4 四项 | 结论未达标则调整阈值并**记录调整理由**，不得事后改判据 |

**注意**：观察期内 `claim_enforcement` 必须保持 `warn`；把 warn 改成 enforce 会让 U1/U2 的读数失去可比性。

### 14.5 降级与回滚

| 场景 | 动作 | 生效方式 |
|---|---|---|
| claim 层本身出问题（拒绝过多） | `LFL_CLAIM_ENFORCEMENT=off`：跳过无 token 的冲突判定，仍记账 | 环境变量，重启生效 |
| 账本文件损坏 | 删除 `claims/claim-<safe>.jsonl` 即等于"无人持有"；task 账本不受影响 | 手工，需记录原因 |
| 想完全停用 claim 工具面 | 从 `TASK_TOOL_DEFS` 移除三项 + `registry_task` 分派返回 `None` | 代码回滚 |

### 14.6 独立审查处置（2026-11-03，U6 第一次）

**回执事实**：`review_admission(start, kind=full_test, scope=patch, 22 paths)` → child `subagent_fa0b528c1807`，材料 `f77d5637…`（233,632 字符），结论 **REVISE**：**P0=0 / P1=1 / P2=7**。按闸规则「P1+P2 非零 ⇒ 无 PASS」，因此**本轮没有取得全量测试资格**，`scripts/ci_gate.sh` 未跑。

逐条处置（每条都有对应测试；测试文件 `tests/test_task_claim_hardening.py`，8 条）：

| Finding | 实质判断 | 处置 | 证据 |
|---|---|---|---|
| **P1-1** 三个 claim 工具入口无跨会话归属强制 | reviewer 明确写了「`_require_active_goal` body 不在切片内，无法确认」。核对后：该函数（`tools_task.py:160-215`）**已调用** `resolve_write_permission`，跨会话（双方 sid 非空且不等）返回 `DENY`。所以风险不是"缺失"，而是"靠未在材料里的上游函数隐式提供" | ① 补**负向测试**：goal 属 owner 会话时，另一会话调 `claim_task` 必须 FAILURE 且落不下任何 claim；② 更根本地把顺序事实变成契约（D-7）：组合入口要求显式 `authorized=True` | `test_claim_task_from_foreign_session_is_refused`、`test_under_claim_requires_explicit_authorization` |
| P2-1 过期 claim 的 reclaim 跳过 task 状态检查 | **真缺陷**（与 §6.2 第 (1) 步"无条件查状态"不符） | `grant` 里状态检查从 `existing is None` 分支移出，改为无条件 | `test_reclaim_of_expired_claim_still_checks_task_status`（变异验证：还原旧条件后该测试失败） |
| P2-2 无身份无 token 的 `release` 可释放任意活跃 claim | 真缺口（纵深防御层）；工具层总会带 token 或 run 身份，故只在绕过工具层时可达 | `release` 早失败：`not holder and not token` → `holder_unavailable` | `test_release_without_holder_or_token_is_refused` |
| P2-3 `parent_concurrency` 拒绝事件的 `running_before` 是全局 handle 数、`limit` 是 per-parent 上限 | 真缺陷（读数不可解释，`deny.count` 从未落事件） | 抽纯函数 `_fanout_observation`：deny 时一律用 `deny.count/deny.limit` | `test_fanout_event_uses_deny_own_scope` |
| P2-4 `policy_from_env` 不做 clamp | 真缺陷（`TTL=1` 可绕过 config 下界） | 补齐 `max(60,…)`/`max(1,…)`/未知值回落 warn（D-9） | `test_policy_from_env_clamps_like_config` |
| P2-5 `last_activity` 用字符串 `max()` | 真缺陷（跨时区账本下选错；naive/aware 相减还会 `TypeError` 打断构建） | `_iso_key`/`_latest_iso` 按时刻比较，`now_ts` 同源补齐（D-10） | `test_frontier_last_activity_compares_instants_not_strings` |
| P2-6 组合入口先改账本、无自身守卫 | 真缺口（只剩"调用方顺序"） | 显式 `authorized` 契约（D-7） | 同 P1-1 第 ② 条 |
| P2-7 token 路径 renew 行先落账，随后 update 可抛错 | 真缺陷（破坏账本与事件 1:1） | renew 落账移到 `store.update` 成功之后（D-8） | `test_renew_row_written_only_after_update_succeeds` |

**变异验证**（证明测试不是空转）：临时把 `grant` 的状态检查还原成旧条件 → 对应测试 FAIL；临时把 `authorized` 门短路 → 对应测试 FAIL；两处均恢复后 8 条全绿。恢复后 `ruff check` 在改动文件上 All checks passed。

**仍未闭合的部分**：
1. **没有 PASS 回执**：本轮是"REVISE 后已修复"，不等于"审查已通过"。必须重新取证（续审 + 新材料 SHA）。
2. **enforce 仍无测试覆盖**：本轮 8 条测试不含 enforce 分支；`T-2.1` 的"打开"动作缺前提（§14.1-3）。
3. **P1-1 的残余**：`resolve_write_permission` 在"无 session 身份"时放行为 `allow_annotated`（D-3/R22 已登记）。本轮负向测试只覆盖"有外部 session 身份"这一支；无身份调用仍可 claim，只是回执标注 `claim_unavailable`。

### 14.7 全量门禁暴露的守卫红与修复（2026-11-03，U6 第二次）

`ci_gate.sh` 第一次跑到 [4/5] tier0 预检时出现 **2 条守卫红**（不是业务测试红），都属"新代码触碰了架构守卫的登记面"，逐条修复后复验通过：

| 守卫 | 红的内容 | 根因 | 处置 | 复验 |
|---|---|---|---|---|
| `test_function_lines_ratchet_within_baseline` | `task_claim.py::update_task_under_claim` 实测 **133 行 ≥120**，且不在 `function_lines∪legacy` | 本轮为满足 D-7/D-8 往组合入口里加了授权门、续租延后与冲突分支，把函数撑过门槛 | **拆函数**（RULE-AI-24 先保真）：抽出 `_resolve_token_or_conflict`（token 校验/冲突判定/续租计划）、`_revoke_on_reopen`（重开撤销）、`_auto_claim_on_start`（隐式签发）；主函数只剩锁、读、调用、落笔、发事件。行为不变，62 条 claim 测试全绿 | `2 passed`（该守卫 + durability 守卫） |
| `test_durability_write_candidates_registered` | `claims/events.py`、`task_claim.py` 是写入候选但未登记 | 新模块首次落盘，`durability_registry` 里没有对应 surface | 在 `tests/guards/function_size_baseline.json` 新增 `claim_ledger`（T1/observe）与 `claim_events`（T1/observe），rationale 写清各自 fsync 策略、读侧容错与"不承担准入判定"的边界 | 同上 |
| （同批）pyright | `TaskStore(audit_dir)` 传 `str \| PathLike[str]` 给只收 `str \| Path` 的参数（new=1） | 模块级便捷函数的类型比 `TaskStore` 宽 | `TaskStore(str(audit_dir))` | `new=0, changed_file_diagnostics=0`，PASS |

**诚实边界**：这一批修复发生在第二轮审查 PASS（`b29ddf88…`）**之后**，因此那条 PASS 随即失效——全量门禁不能凭它放行，必须对 `4d1c0a59…` 之后的新材料重新取证。这正是"签发后改动即失效"的机械含义。

**第三批红（env 访问守卫，`test_runtime_env_access_gate`）**：tier0 预检暴露 2 条红——`task_claim.py` 的 `LFL_CLAIM_*` 四个读取点与 `runner.py` 的 `LFL_MAX_RUNNING_CHILDREN` 是**新增 env 签名**，未登记进 `tests/fixtures/runtime_env_access_baseline.json`。处置按守卫自身的规定做（"adding debt requires an explicit reviewed baseline update"），不手工改 JSON：

```
.venv/bin/python scripts/audit_runtime_env.py --update-baseline \
  --reason "DESIGN-20261103 PR-1 新增 claim 策略与 per-parent fanout 闸的配置面…" \
  --parent-commit ba08911eb51f
```

登记差异（工具回执）：`access_count 202→206`、`direct_access_count 202→206`、`effective_access_count 221→228`、`unique_key_count 87→90`、新增签名 7 条（含 `_env_int|<dynamic>` 与 3 条 helper 签名）、新 env key 3 个（`LFL_CLAIM_ALLOW_UNBOUNDED`/`LFL_CLAIM_ENFORCEMENT`/`LFL_MAX_RUNNING_CHILDREN`）。`registration_log` 记录了 reason 与 parent commit，可追溯。复验：`test_runtime_env_access_gate` 11 passed、`tier0` **341 passed / 2 skipped**、`test_arch_guards.py` **52 passed**。

**这条登记是"债务增加"，不是"修复"**：它意味着本仓库的直接 env 读取点又多了 4 处。若要走反向（减少读取点），只能把 `policy_from_env` 改成从已装配的 settings 注入（D-6 说明的代价：装配链改动面变大），不在本轮范围。

### 14.8 第四轮审查（P2×6）处置与一次"格式假 REVISE"（2026-11-03）

**先记一个必须说清的事实**：第 5 次审查回执的 `qualification` 是 `REVISE`，但 reviewer 正文写的是「**判定结果：通过** P0=0 P1=0 P2=6」。`reason=review_verdict_incomplete_or_not_pass` 的直接原因是**结论行不是闸可解析的 `VERDICT: PASS` 形式**（它写成了中文），不是发现了 P1。按 RULE-AI-01，不能把这次结果称作 PASS；但它也不该被读成"又有阻断项"。

6 条 P2 逐条处置（P0=0/P1=0，均属边缘或可观测性）：

| Finding | 处置 | 证据 |
|---|---|---|
| P2-1 续租落账失败时任务已写、回执却报 FAILURE | `update_task_under_claim` 捕获 `ClaimLedgerUnavailableError`，改为**成功 + `claim_renew_unavailable` 降级标注**。理由写进注释：报失败会让调用方误判"没写进去"，比缺口本身更危险；generation 未变，租约到期只意味着"可被接管" | `test_renew_ledger_failure_reports_success_with_degraded_note`、`…_does_not_emit_renew_row` |
| P2-2 冲突回执泄露完整 holder sid | 新增 `mask_holder()`（≤8 原样，否则前 8 + …），grant 冲突消息、`claim_held_by_other` 异常、`claim_conflict_warning` note、release 拒绝文案全部改用它 | `test_conflict_message_masks_other_holder`、`test_conflict_warning_is_masked_on_write_path` |
| P2-3 `max_claims_per_holder` 实为 per-goal 统计 | 不改实现（claim 账本按 goal 隔离，跨 goal 聚合成本不划算且软指标不需精确），**把口径写进注释**：读数按"单 goal 内同一 holder 的活跃 claim 数"解释 | 代码注释（`ClaimStore.grant`） |
| P2-4 模块 docstring 仍写 `claims/ledger.jsonl` | 改为 `claims/claim-<safe_goal_id>.jsonl`（每 goal 一份，D-1） | docstring |
| P2-5 `LFL_MAX_RUNNING_CHILDREN` 无 config↔runner 漂移测试 | 新增漂移测试，覆盖 `""/1/16/32/64/0/abc` 七档，config 侧从 `settings.tool_runtime` 取 | `test_max_running_children_config_and_runner_agree` |
| P2-6 `enforce` 分支无测试 | **补了**：他人持 claim + enforce → 硬拒且任务状态不变；同 holder 带 token → 成功。`enforce` 现在有覆盖，但**仍未开启**（U7 等观察期） | `test_enforce_mode_hard_denies_foreign_holder_write`、`test_enforce_mode_allows_holder_with_token` |

另修两条 reviewer 标注的「非影响观察」：
1. `test_claim_and_task_use_same_safe_id` 原是**空断言**（`safe_goal_id(goal) and "/tmp"` 恒为 `"/tmp"`），改为真比较两条账本文件名。
2. `scripts/claim_metrics.py` 缺省 audit 目录从 `Path.cwd()/audit` 改为 `LFL_AUDIT_DIR` → `<repo>/data/audit`（与 `config._DEFAULT_DATA_DIR` 同源），避免在别处运行时静默读到空目录。

复验（第四轮时点）：claim 相关 6 个测试文件全绿（hardening 14 条）、`tier0` **341 passed / 2 skipped**、`ruff` All checks passed、`pyright` `new=0`。**条数以 §14.9 的实测计数为准**（第四轮后再补 4 条，合计 73）。

### 14.9 第五轮审查（git_push）处置与吞吐债务登记（2026-11-04）

push 前审查发现 P1×1 / P2×6（P0=0）。逐条：

| Finding | 处置 | 证据 |
|---|---|---|
| P1-1 文档把 `test_coordination_view_capacity.py` 列为已交付，但该文件**未跟踪**（只在工作树里，没进 commit） | 承认：文档先于提交声称交付。已 `git add` 并在修复提交里带上该文件；本条属于"文档与仓库不自洽"，不是测试不存在 | 该文件现有 4 条断言，随本提交入库 |
| P2-1 warn 透传事件冒用他人 generation | 冲突透传时 `emit_generation=0`（本次未持 claim）；别人的代次不写进本 holder 的记录 | `test_conflict_passthrough_event_reports_generation_zero` |
| P2-2 重开撤销只落账本、不发事件 | `_revoke_on_reopen` 补 `claim_decision=revoke`（`reason_code=reopen_revoke`），`claim_metrics.revoke_count` 不再漏一半 | `test_reopen_revoke_emits_matching_event` |
| P2-3 文档测试条数与实测不符（15 vs 18；`13+2` vs `13+5`） | 全部改为 `--collect-only` 实测值；§11.1.1 一次列清 73 条构成 | §11.1.1、§6.6.1、`docs/changes/…claim-layer.md` |
| P2-4 进程锁跨 goal 串行化 `task_update` | **登记不修**：`_CLAIM_PROCESS_LOCK` 是防 ABBA 的进程级总锁，缩范围要先重排锁序（claim→task→event 三段），改动面等同于重写临界区。登记为 **R23**，触发条件见下 | 本表下方 R23 |
| P2-5 程序化 `ClaimPolicy(ttl_s=1)` 绕过下界 | `_clamp_ttl(None)` 也过 `MIN_TTL_S` | `test_policy_ttl_below_minimum_is_clamped_on_grant` |
| P2-6 畸形 token 后缀跳过 generation 比较 | `#` 后的段必须 `isdigit()`，否则 `claim_token_malformed` 拒绝 | `test_malformed_token_suffix_is_rejected_not_skipped` |

**顺带修掉一个审查没点、但写测试时暴露的真问题**：warn 模式下，`pending→in_progress` 的隐式签发会**抢占他人活跃 claim**（`generation+1` 直接 reclaim）。这与 D1「硬拒只剩他人已持 claim」直接矛盾——warn 不是"允许抢锁"，是"允许在冲突下继续写但不夺权"。已改为：他人持活跃 claim 时不签发（保持警告 + 透传），并由此得到 `generation=0` 的正确事件语义。

**R23（新增已知边界）：`task_update` 的进程级串行化**

- 事实：`ClaimStore.update_task_under_claim` 持 `_CLAIM_PROCESS_LOCK` 覆盖整段（含 `store.update` 的 replay + append + fsync 与事件 append）。多 goal 并发写 task 时，进程内完全串行。
- 量级：单次写入 ≈ replay(该 goal 账本) + 一次 append + fsync + 一次 event append。goal 账本 239 行时 replay 约 3–5ms；估算串行吞吐上限 **≈100–200 次 task 写入/秒**，远高于当前实际（日级几十次）。
- 触发条件（何时必须先做）：出现「同一进程内多 goal 并发 task 写入导致 `task_update` 排队 > 50ms」或写入速率稳定 > 50/s。
- 届时的做法：把进程锁拆成「账本段」与「事件段」两把，或改为每 goal 文件锁 + 全局仅保护锁序不变量；**不要**简单去掉进程锁（会重新引入 ABBA）。
- 为什么现在不做：观察期第一天就可能被它影响读数，但改锁序的回归风险高于收益，且当前速率离上限两个数量级。

复验：claim 相关 **73 条**（31+3+18+3+18）全绿；`tier0` **341 passed / 2 skipped**；`ruff` All checks passed；`pyright` `new=0`。
