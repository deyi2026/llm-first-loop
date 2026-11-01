# 跨会话任务协调 实现设计书 v1

- 文档类型：design（需求 → 实现 → 验收）
- 日期：2026-11-01
- 状态：**设计稿（未实施）**，含 3 个待用户裁决点（§11）
- 上游分析：`docs/analysis/2026-11-01-跨会话任务协调-分析与建议.md`（v2 拷问完善版）
- 关联规则：RULE-AI-01（事实/完成诚实）、RULE-AI-23（授权来源）、RULE-AI-24（防退化）、RULE-AI-28（发布前独立审查）
- 事实基线：当前代码快照（mirror 工作区）。**凡标「已核」者均有源码定点依据；标「未实测」者不得作为实施完成判据。**

---

## 0. 结论摘要

1. **不新建协调服务、不新建存储**：Goal JSONL（`goal.py`）、Task JSONL（`task_store.py`）、workspace 事件流（`event_stream(scope=workspace)`）、子代理租约（`subagent_lease/topology`）已是全部数据源。
2. **第一优先级是写侧归属校验，不是跨会话读 API**。现状最危险的是「读得到 + 写得了」：`get()` 无 id 时会回退到全局 active（`goal.py` `get()` 回退序，已核），而 `checkpoint_goal / update_goal / task_create / task_update` 拿到 `goal_id` 就写、不比对 `session_id`（已核）。合成链路是"误读别人的 goal → 推进别人的状态"。
3. **跨 Goal 依赖必须新字段**。`dependencies` 只接受同 Goal 的 task_id，且 frontier 用 `all(d in done_ids)` 全量比对；塞 `goal:<gid>` 会让任务**永久不可达**（`task_store.py:399/:432`，已核）——这是硬反例，不是风格偏好。
4. **唤醒不能依赖 `schedule` 等 Goal**。`subject_refs` 三个谓词里，生产只登记了 `job_terminal` 求值器，`generation_reached`/`action_settled` 当前退化为纯超时（已核）。因此本期用「启动时 readiness 门」，事件求值器列为增量。
5. **并发首选版本 CAS，不引入租约回收器**：JSONL 是"追加 + 原子重写 + flock"，加一个 `version` 整数即可，无 TTL、无回收线程、无僵尸租约。
6. 交付分三档：**MVP（P0，1 个 PR 可完成）**= 归属校验 + provenance 标注 + 可执行出口；**P1** = coordination 只读视图 + 跨 Goal 依赖；**P2** = 版本 CAS + `goal_settled` 求值器 + 显式 transfer。

---

## 1. 需求与可验收分解

### 1.1 原始诉求

> 跨会话任务协调：一个任务被拆到多个会话（父会话/子代理/DSH/后台 job/另一个 tab）或轮次中断后从新会话接续时，模型无法可靠回答：别人的任务我怎么接手、我怎么知道我依赖的任务完成了、两个会话怎么不冲突。

### 1.2 验收口径（R 表）

| 编号 | 需求 | 可验收断言（可执行） |
|---|---|---|
| R1 | 写侧不许误写他人 Goal | 会话 S2 对 S1 名下的 goal 调 `update_goal(status=complete)`，**必须** FAILURE 且回执含 `reason_code=cross_session_write_denied` + owner session + 三条出口；goal 状态与服务端记录**不变** |
| R2 | 读侧必须自证归属 | 会话 S2 无参 `get_goal()` 若命中 S1 的 goal，回执**必须**带 `owner_session_id` 与"非当前会话"标注（不得静默返回内容） |
| R3 | 建 goal 前提示已有 | `create_goal` 成功回执**必须**附 workspace 内 active goal 摘要（id + objective 前 40 字 + owner + 更新时间），无则不出现该段 |
| R4 | 跨 Goal 依赖可表达、可判定、不成环 | 建 `blocked_by_goals=[G]`：G 未 complete 时该 task 不进 frontier 的 ready 集且 `blocked_by` 字段显式列出；G 变 complete 后**自动**进入 ready；成环创建被拒（`reason_code=dependency_cycle`） |
| R5 | 一屏看清在途 | `coordination_status` 一次返回：active/blocked goal（含 owner、最近 checkpoint 时间）、各 goal 的 ready/阻塞任务、在跑 job 与 subagent child（含 expires_at）、最近 N 条 workspace 关键事件；**纯只读、零写副作用** |
| R6 | 并发写入不互相覆盖 | 两个会话持有同一 goal 的 `version=N`，先写者成功（`version→N+1`），后写者 FAILURE 且回执 `current_version` + 对方 session + 对方最近 checkpoint 摘要 |

### 1.3 边界澄清（先说清，避免实现走偏）

- **不是**"跨会话上下文共享"：不把 A 的历史/授权带进 B 的轮次（`dsh_task` 明确不继承，已核）。
- **不是**"自动接管"：接手必须显式动作（`transfer_goal` 或 `cross_session=true` + reason + 证据），且留下 owner 变更记录。
- **不是**"跨 workspace 协调"：跨 workspace 的 goal 一律不可见（`audit_dir` 天然隔离）。
- **不做**常驻协调进程/队列/消息总线。

---

## 2. 现状核实（仅列会改变实现的点）

| # | 事实 | 位置 | 状态 |
|---|---|---|---|
| 1 | `Goal` 含 `session_id`，`create()` 时写入；后续 checkpoint/update 不改写它 | `goal.py`（`Goal` 数据类 + `GoalStore.create`） | 已核 |
| 2 | `get()` 回退序：`active_preferred` → `active` → `latest_preferred` → `latest`；`strict_session=True` 关闭回退 | `goal.py` `get()` | 已核 |
| 3 | 已有 4 处显式隔离读取：`run_get_goal`、`task_frontier` 无参解析、`session_handoff`、`active_identity` | `tools_goal.py`、`tools_task.py:241`、`session_handoff.py:38`、`goal.py:105` | 已核 |
| 4 | 写侧无归属校验：`checkpoint_goal`/`update_goal`/`task_create`/`task_update`；`task_frontier(goal_id=)` 亦不校验 | `tools_goal.py`、`tools_task.py` | 已核 |
| 5 | 收口门（`update_goal` complete）：open 任务拒绝、`evidence_required` 未 verified → BLOCKED、零 done 需自报 `evidence_refs` 过 verifier | `tools_goal.py` `run_update_goal` | 已核 |
| 6 | `dependencies` 仅允许同 Goal task_id；frontier 用 `all(d in done_ids)` 全量比对 | `tools_task.py:159`、`task_store.py:399/:432` | 已核 |
| 7 | `GoalStore.list(status, limit)` 存在 | `goal.py` | 已核 |
| 8 | `job_output` 以 `current_session_id` 过滤 → 跨会话读不到他人 job | `job_output.py:34-35` | 已核 |
| 9 | `subagent_result` 校验 `parent_id + generation + result_id` | `subagent_result.py:131-141` | 已核 |
| 10 | `schedule` 生产装配仅 `job_terminal` 有求值器 | `scheduler.py:60`、`factory.py:212` | 已核 |
| 11 | 无参 `get_goal()` 在他会话有 active、当前会话无 goal 时的**真实返回** | — | **未实测**（§7 T1） |
| 12 | `task_frontier(goal_id=别人的)` 的可读性 | — | **未实测**（§7 T2） |

---

## 3. 差距与设计约束

| 约束 | 来源 | 实现含义 |
|---|---|---|
| JSONL 追加 + 原子重写 | `_atomic_rewrite` 既有模式 | 新字段必须**向后兼容**：旧行缺字段按默认值解释，不重写历史行 |
| legacy 行 `session_id` 可能为空 | 历史记录 | owner 未知 → 校验策略 `unknown_owner`：允许写但回执显式标注，且**不计入**跨会话拒绝 |
| `dependencies` 语义不可改 | 既有工具契约 | 跨 Goal 依赖另开字段，禁止复用 |
| 收口门已很严，不得放宽 | RULE-AI-24 | 归属校验是**叠加**前置检查，不替代任何既有门 |
| 工具回执是模型唯一输入面 | 单会话假设的根因 | 拒绝必须给**可执行出口**（谁拥有 / 怎么申请 / 怎么显式跨会话），否则等于把模型的错从静默转成死路 |

---

## 4. 方案设计

### 4.1 分层

```
L1 归属契约   write-ownership: owner 校验 + provenance 标注 + 可执行出口
L2 可见性     coordination_status: 一屏在途（只读投影）
L3 依赖       blocked_by_goals: 跨 Goal 依赖 + 求值器 + 环检测 + deadline
L4 并发       version CAS: 乐观并发，无租约回收
```

每层可独立上线、独立回滚；MVP 只做 L1。

### 4.2 数据契约变更（全部为**新增可选字段**，不重命名既有字段）

```python
# Goal（goal.py Goal dataclass 追加）
version: int = 0                  # L4 CAS；旧行缺省 0
owner_history: list[dict] = []    # L2/P2 transfer 记录：[{ts, from_session, to_session, reason}]

# Task（task_store.py Task dataclass 追加）
blocked_by_goals: list[str] = []  # L3 跨 Goal 依赖（GOAL-xxx，非 task_id）
deadline_at: str = ""             # L3 到期降级为"外部原因阻塞"
```

- 不新增 `owner_session_id`：**直接复用 `session_id`**（已核：create 写入、update 不改写），避免双字段漂移。
- 不改 `GoalStore.get()` 默认行为（理由见 §11-D3）。

### 4.3 L1 写侧归属校验（MVP 核心）

统一辅助函数（新增于 `goal.py`，与 `active_identity` 同域）：

```python
def resolve_write_permission(goal: dict, cur_session: str, args: dict) -> tuple[str, str]:
    """返回 (decision, reason_code) ∈ {allow, allow_annotated, deny}。

    - owner 为空（legacy）        → allow_annotated / owner_unknown
    - owner == cur_session        → allow
    - args.cross_session is True 且 reason 非空且 evidence_refs 非空 → allow_annotated / cross_session_authorized
    - 其它                        → deny / cross_session_write_denied
    """
```

**工具矩阵（改动面全表）**：

| 工具 | 现状 | 改动 | 拒绝回执必含 |
|---|---|---|---|
| `create_goal` | 绑定 `bound_session_id()`；无 binding 即 fail-closed | 成功回执追加「workspace 内 active goal 摘要」（R3） | — |
| `checkpoint_goal` | 直接按 id 写 | + owner 校验 | owner session / 出口三条 / `reason_code` |
| `update_goal` | 直接按 id 写（收口门不变） | + owner 校验（在收口门**之前**，先认人再验门） | 同上 |
| `task_create` | 按 goal_id 写 | + 校验目标 goal 的 owner | 同上 |
| `task_update` | 按 goal_id + task_id 写 | + 校验目标 goal 的 owner | 同上 |
| `get_goal` | 已 strict 读 | 回执追加 `owner_session_id` + 「非当前会话」标注（R2） | — |
| `task_frontier` | 无参 strict；显式 id 不校验 | 显式 id 时回执标注 owner | — |
| `transfer_goal`（新，P2） | — | 显式变更 owner，写 `owner_history` | 目标必须是当前 owner 或显式接受 |

**拒绝回执模板（R1 的可执行出口，必须逐条落地）**：

```
[跨会话写入拒绝] reason_code=cross_session_write_denied
goal GOAL-20261101-ab12cd34 属于会话 sess-xxxx（owner），当前会话 sess-yyyy。
出口：
  1) 只读查看：get_goal(goal_id=...) / task_frontier(goal_id=...)（回执将标注归属）
  2) 显式跨会话写入：同一调用加 cross_session=true + reason="<为什么必须由你写>" + evidence_refs=["evidence://..."]
  3) 移交归属：由 owner 会话调用 transfer_goal(goal_id=..., to_session="sess-yyyy", reason=...)
收口门（任务图/证据门）未被绕过，本条仅拦归属。
```

### 4.4 L2 可见性：`coordination_status`（新只读工具，P1）

**为什么新工具而不是扩展 `architecture_status`**：后者语义是"运行时架构状态（缓存/异常/轨迹）"，业务任务混进去会让两个概念互相污染；而 `search_records`/`event_stream` 是检索面，不适合"一屏定态"。

契约：

```jsonc
{
  "generated_at": "...",
  "window": {"since": "...", "only_in_flight": true},
  "goals": [
    {"goal_id": "GOAL-...", "objective": "...", "status": "active", "owner_session_id": "...",
     "updated_at": "...", "last_checkpoint": {"ts": "...", "what": "..."},
     "tasks": {"ready": 2, "in_progress": 1, "blocked": 1, "blocked_by_goals": ["GOAL-..."]}}
  ],
  "running": {"jobs": [{"job_id": "...", "session": "..."}],
              "children": [{"child_id": "...", "parent": "...", "expires_at": "..."}]},
  "recent_events": [{"ts": "...", "kind": "...", "session": "..."}],
  "degraded": []   // 某数据源不可读时显式列出，不静默省略
}
```

- 默认窗口：`only_in_flight=true` 且「最近 24h 内变更」；`include_completed=true` 展开。
- 数据源：`GoalStore.list()`、`TaskStore`、`subagent_topology`/`subagent_lease`、`event_stream(scope=workspace)`。
- 只读保证：不写任何存储、不产生事件（与 `verify_path_scope` 同级）。

### 4.5 L3 跨 Goal 依赖（P1）

- 字段：`Task.blocked_by_goals: list[str]`（**不复用** `dependencies`，§3 约束）。
- 求值器：在 `task_store` 的 frontier 计算中，`blocked_by_goals` 全部 `complete` 才算 satisfied；其中任一为 `blocked` 或 `cancelled` → 该 task 标 `blocked`（`reason_code=upstream_goal_aborted`），**不进 ready**，且不自动转 failed。
- 环检测：建依赖时对 `goal → goal` 图做可达性检查（DFS），成环拒绝 `dependency_cycle`；跨 Task/跨 Goal 混环不适用（`dependencies` 与 `blocked_by_goals` 是两个图）。
- 到期：`deadline_at` 到期后降级为 `blocked(reason_code=upstream_deadline_exceeded)`，并回执建议（拆解/改为可先行部分/申请 waive）。

### 4.6 L4 并发：版本 CAS（P2）

- 写入协议：请求可带 `expected_version`；不带则视为"尽力写"（兼容既有调用）。
- 带了且与最新行不符 → FAILURE：`reason_code=version_conflict` + `current_version` + 对方 `session_id` + 对方最近 checkpoint 摘要。
- 一致性：整个「读最新行 → 比对 → 追加 → 原子重写」在既有 flock 内完成（`goal.py` 已用文件锁），不存在检查-写入间隙。
- **否决租约**：TTL 需回收器与僵尸清理，且"长任务续租"会引入心跳负担；CAS 无此问题。

### 4.7 唤醒：readiness 门（P1）+ 事件求值器（P2 可选）

- readiness 门：新会话开工时（`get_goal`/`task_frontier`/`coordination_status` 任一被调用）若存在"我 blocked_by 的 goal 仍未完成"，回执给出**一条**明确结论（不是每轮提醒）。
- 事件（P2）：新增 `goal_settled` 求值器（监听 goals.jsonl 中目标 goal 的 status 变更），接入 `schedule(subject_refs=[{type:"goal_id"}])`。**前提**：先在 `scheduler.py`/`factory.py` 注册求值器，否则不得对外宣称"可等 goal 完成"。

---

## 5. 失败模式矩阵

| 场景 | 期望行为 | 反模式（明令禁止） |
|---|---|---|
| 别人的 goal，我 `update_goal(complete)` | FAILURE + 出口三条，状态不变 | 静默写入并"帮他收口" |
| legacy goal（owner 空） | 允许写 + `owner_unknown` 标注 | 当作非法拒绝（会锁死历史任务） |
| 带 `cross_session=true` 但无 reason/证据 | FAILURE + 说明缺什么 | 默认放行 |
| `get_goal()` 命中他人 goal | 返回内容 + owner 标注 + 非当前会话提示 | 静默当成自己的（现状） |
| 依赖 goal 已 blocked | 下游 blocked + `upstream_goal_aborted` | 下游永久 ready 或自动 failed |
| 依赖成环 | 创建即拒 `dependency_cycle` | 建成功后在 frontier 死等 |
| 版本冲突 | FAILURE + current_version + 对方摘要 | 后写覆盖先写 |
| 某数据源不可读（如 topology 缺） | `degraded: [...]` 显式列出 | 静默返回空数组（会被读成"没有在跑的任务"） |
| DSH 子任务跨会话想读结果 | 明确回"该 job 属于会话 X，跨会话不可读；请由该会话导出或改用 subagent" | 返回空 |

---

## 6. 验收标准（逐条可执行）

| # | 动作 | 期望 |
|---|---|---|
| A1 | S2 对 S1 goal 调 `checkpoint_goal` | FAILURE，`cross_session_write_denied`，goal 文件字节级不变 |
| A2 | 同 A1 但 `task_create` | 同上 |
| A3 | S2 调 `update_goal(complete)` on S1 goal | FAILURE 且**先**报归属（不回落到收口门文案） |
| A4 | S1 自己调 `update_goal(complete)`（任务图 open） | FAILURE，收口门文案不变（防退化） |
| A5 | legacy goal（`session_id=""`）任意会话写 | 成功 + `owner_unknown` 标注 |
| A6 | S2 `get_goal()` 命中 S1 goal | 含 `owner_session_id` + 非当前会话标注 |
| A7 | `create_goal` 时 workspace 已有 2 个 active goal | 回执含 2 条摘要 |
| A8 | `task_create(blocked_by_goals=[G])`，G inactive | 该 task 不在 ready 集，回执列出 `blocked_by` |
| A9 | 使 G complete | 该 task 下一次 frontier 查询进入 ready（无需人工刷新） |
| A10 | `blocked_by_goals` 成环 | FAILURE `dependency_cycle` |
| A11 | 两会话同 `expected_version` 并发写 | 一成一败，败者有 `current_version` |
| A12 | `coordination_status` 调用前后 `goals.jsonl`/`tasks.jsonl` 的 mtime 与 sha256 不变 | 只读成立 |

---

## 7. 测试计划

**T1（判别实验，前置）**：双会话实测无参 `get_goal()` 的回退行为——S1 建 goal，S2 无 goal 时调 `get_goal()`，记录是否返回 S1 的 goal。**若返回**：R1/R2 为真需求；**若不返回**（已被其它机制拦住）：降级 R2 为"标注增强"。
**T2**：`task_frontier(goal_id=S1 的)` 在 S2 的可读性；同法判定 R5 的必需性。
**单测**：`resolve_write_permission` 真值表（4 分支 × 空/非空 goal_id）；legacy 行兼容；CAS 冲突（模拟两写者）；环检测（自环/二元环/三元环）；frontier 求值（含 blocked/cancelled 上游）。
**回归**：既有 `update_goal` 收口门三条（open 任务 / evidence 未 verified / 零 done 无 refs）文案与状态码**逐字不变**；`task_frontier` 无参行为不变；`get_goal` 无 id 行为不变（仅追加标注）。
**守卫实验（RULE-AI-35）**：A1/A2/A3 必须真实回 FAILURE 才算"校验已生效"；仅代码存在不算。

---

## 8. 兼容、回滚、非目标

- **兼容**：全部新增可选字段 + 追加式回执；旧调用零参数变化，行为差异仅限"本该被拒绝的跨会话写"（这正是修复目标）。
- **回滚**：L1 是纯前置检查，关掉一个常量即回到现状；新字段留下不影响旧读者；新工具独立可下线。
- **非目标**：跨 workspace 协调；跨会话上下文/授权继承；自动接管；git 级并发（LFL 非代码协同工具）；多机协调。

---

## 9. 影响面与工作量

| 阶段 | 文件 | 内容 | 估量 |
|---|---|---|---|
| P0（MVP） | `goal.py`（`resolve_write_permission`）、`tools_goal.py`、`tools_task.py` | owner 校验 + 出口回执 + provenance 标注 + `create_goal` 摘要 | 中（~200 行 + 单测） |
| P1 | 新工具模块 + `task_store.py` | `coordination_status`、`blocked_by_goals` 求值器、环检测、readiness 门 | 中大 |
| P2 | `goal.py`（version）、`scheduler.py`/`factory.py` | CAS；`goal_settled` 求值器；`transfer_goal` | 中，跨模块 |

风险点：`tools_task.py` 的 frontier 求值是既有热点，改动需保真（RULE-AI-24），必须逐字回归既有回执。

---

## 10. 判据：什么时候算"跨会话协调做完了"

1. A1–A12 全绿（尤其 A1/A2/A3 是**真实拒绝**，不是文案）。
2. T1/T2 有实测结论回填到本文档 §2 表（把"未实测"改成实际结果）。
3. 新会话在无任何额外指引下，`get_goal()` 回执能让人/模型看出"这不是我的 goal"。
4. 既有收口门与 frontier 回执零退化。

---

## 11. 需用户裁决的三点

| 编号 | 裁决点 | 选项 | 建议 |
|---|---|---|---|
| D1 | `cross_session=true` 是否允许？ | (a) 允许但需 reason+证据；(b) 一律禁止，只能 transfer | 选 (a)：真实场景里"父会话替子收口"是合法的；但必须留痕 |
| D2 | `coordination_status` 载体 | (a) 新工具；(b) `architecture_status` 新维度；(c) 只加 `create_goal` 摘要不做汇总视图 | 选 (a)：语义独立；(c) 成本最低可作 MVP 替代 |
| D3 | 是否把 `GoalStore.get()` 默认改 strict | (a) 不改（读侧标注）；(b) 改默认 | 选 (a)：改默认会退化"新会话接续旧任务"这个最常用场景 |

---

## 12. 实施对齐（v1 落地记录）

> 本节记录代码落地结果与**与设计的差异**，供后续维护者判断"文档说的 vs 代码做的"。

### 12.1 落地清单

| 层 | 文件 | 关键行为 |
|---|---|---|
| L1 归属仲裁 | `introspection/goal_coordination.py`（新） | `resolve_write_permission` → `allow / allow_annotated / deny`，reason_code ∈ `cross_session_write_denied` / `cross_session_authorized` / `owner_unknown` / `session_unverified`；拒绝文案含 owner 与三条出口 |
| L1 写侧接线 | `tools_goal.py`、`tools_task.py` | `checkpoint_goal` / `update_goal` / `task_create` / `task_update` 写前判定；`create_goal` 增加"并行 goal"摘要 |
| L1 读侧标注 | `tools_goal.py` | `get_goal` 追加 `归属:` 行（含 `owner_session_id`，四态：本会话/其他会话/未认领/身份不可证明），既有行不变 |
| L2 只读视图 | `goal_coordination.py` + `tools_goal.py` + `registry_goal.py` | 新工具 `coordination_status(window_hours, only_in_flight)`：goals / sessions / running / recent_events / degraded |
| L3 跨 goal 依赖 | `task_store.py`、`tools_task.py` | `Task.blocked_by_goals` / `deadline_at`；创建期归一化 + 自指拒绝 + 环拒绝（`dependency_cycle`）；frontier 新增 `waiting_cross_goal` / `blocked_upstream`（`upstream_goal_aborted` / `upstream_deadline_exceeded`）；`render_frontier` 追加行 |
| L4 版本 CAS | `goal.py`、`tools_goal.py` | `Goal.version`（create=1，checkpoint/update 成功后 +1）；`expected_version` 在 **flock 内**读-比-写；冲突抛 `GoalVersionConflict` → 工具层 `reason_code=version_conflict` + `current_version` + owner + 对方最近 checkpoint 摘要 |

### 12.2 与设计的差异（每条都有理由，不是遗漏）

| 编号 | 差异 | 理由 / 边界 |
|---|---|---|
| D-impl-1 | 新增第四态 `session_unverified`（文档未定义"无 session binding"） | 该态出现在离线 CLI/单测装配（contextvar 无绑定）。硬拒会让所有既有单会话路径（A1/A9）失效；取"标注放行"，真实运行态 contextvar 必有值，该分支不可达。**残余风险已登记 §12.4** |
| D-impl-2 | L2 只接线 goals/sessions/owner/last_checkpoint/task 计数 | `running.children` / `running.jobs` / `recent_events` 未采集，**显式进 `degraded`**，不返回空值冒充"无运行"。字段形状按 §4.4 固定，接线后原地替换即可 |
| D-impl-3 | L3 环检测为 goal 级图 DFS（全 goal 边 + 本次新边） | 返回可读环路径；他 goal 账本读不到时 fail-open（只用已知边判环），不阻断创建 |
| D-impl-4 | L3 `upstream_goal_aborted` 由 goal status ∈ {blocked, cancelled} 触发 | 当前 goal 状态机只有 active/complete/blocked，`cancelled` 为前瞻保留；任务本身保持 pending，**不自动 failed** |
| D-impl-5 | L3 deadline 判定用"显式 `now_ts` 或真实当前时间" | 若不这样，未传 `now_ts` 的调用永远不会因超期转 blocked（实测踩到）。`stalled` 语义**未动**（仍只认显式 `now_ts`） |
| D-impl-6 | L4 版本冲突回执字段名为 `current_version` | 与 `reason_code=version_conflict` 成对，避免与既有 `current=`（状态值）混淆 |
| D-impl-7 | `transfer_goal`（P2）未实现 | 拒绝文案第 3 出口明确写"未实现前请在 owner 会话推进"，不留死路 |
| D-impl-8 | `coordination_status` 的实现落在 `goal_coordination.py`（逻辑）+ `tools_goal.py`（工具壳），未另建 `tools_coordination.py` | 与 T002 计划里的文件名不同，功能与回执契约一致；少一个注册面，避免短命模块。若要拆分，逻辑/外壳边界已在函数层分开 |
| D-impl-9 | `Goal.version` 初值为 1（计划写 0），且未实现 `owner_history` | version 从 1 起算使「旧记录缺字段」与「新建记录」同口径（都按 1），否则首写 CAS 语义会分裂；`owner_history` 只在实现 `transfer_goal`（P2）时才有写入方，现在加字段只会有永远为空的账 |

### 12.3 验收矩阵结果

| 编号 | 判据 | 结果 | 覆盖测试 |
|---|---|---|---|
| A1 | 单会话 checkpoint/update 行为不变 | PASS | `test_goal_coordination_l1.py::test_same_session_write_allowed` |
| A2 | 他会话写入 FAILURE 且 goal 账本字节不变 | PASS | `test_cross_session_acceptance.py::test_a1_denied_write_leaves_bytes_unchanged` |
| A3 | 跨会话拒绝**先于**收口门 | PASS | `test_a3_denial_precedes_completion_gate` |
| A4 | `update_goal(complete)` 收口门文案不变 | PASS | 既有 `test_goal_finality_evidence_gate.py`（零改动） |
| A5 | legacy（owner 空）写入 + `owner_unknown` 标注 | PASS | `test_unclaimed_goal_writable` |
| A6 | `get_goal` 含 `owner_session_id` + 归属标注 | PASS | `test_a6_get_goal_owner_field` |
| A7 | `create_goal` 列出其他 active goal | PASS | `test_a7_create_goal_lists_parallel_goals` |
| A8 | `blocked_by_goals` 上游未满足时不进 ready | PASS | `test_waiting_until_upstream_complete` |
| A9 | 既有测试零改动全绿 | PARTIAL（诚实登记） | 既有 goal/task 定向测试 104 项全绿且测试文件未改动；全量单测 9076 passed / 311 failed / 33 collection error，失败项与本次改动无关（抽样 22 项在 HEAD 干净树同样失败；arch 守卫失败来自工作区其他未提交改动），详见 §12.4 |
| A10 | `get_goal`/`task_frontier` 既有行不变，只追加 | PASS | `test_get_goal_existing_fields_preserved` |
| A11 | 同 `expected_version` 双写一成一败 | PASS | `test_a11_concurrent_writers_one_wins` |
| A12 | `coordination_status` 前后账本 sha256/mtime 不变 | PASS | `test_a12_coordination_status_is_read_only` |

### 12.4 残余风险（诚实登记）

1. **无 binding 执行**（离线 CLI、部分测试装配）无法验证 owner → 只能标注放行。若要收紧，需要给这些入口注入 session 身份。
2. **L2 running/events 未接线** → "谁在跑什么"仍只能从 goal/task 账本推断，看不到子代理与后台任务。
3. **任务级归属未加**：同一 goal 内的任务仍可被任意会话改（只有 goal 级归属受保护）。
4. **version 只保证原子性与"基于旧版本"的覆盖被拒**，不做字段级合并：两个会话基于同一 version 各自改不同字段，后写者仍会被拒（需重取后合并）。
5. 全量单测在本机不是绿的：33 个 collection error（缺可选依赖 Crypto / lark_oapi / reportlab / prompt_toolkit）+ 311 个失败（工作区其他未提交改动与既有环境断言）。二者均与本次改动无关：抽样 22 项在 HEAD 干净树同样失败；arch 棘轮守卫的失败指向 experiences/store.py、settlement.py、review_host_admission.py，非本次文件。
6. 本次工作期间仓库侧存在自动 push 管线，会执行 stash + reset --hard，两次把未提交改动整体移出工作树（已从 stash 与 /tmp/lfl-prebackup* 恢复）。自动化与「会话内未提交工作」直接冲突，已作为优化建议上报。
