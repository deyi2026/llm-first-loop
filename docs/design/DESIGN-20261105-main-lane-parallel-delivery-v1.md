# main 主线 + 多 Lane 并行开发 统一管理 实现设计 v1

- 文档类型：design（需求 → 现状核实 → 方案 → 时序统筹 → 验收）
- 日期：2026-11-05
- 状态：**v1.1 裁决已落定（§11），P0 实施中**；§4.4.1 三级授权 / §4.4.2 K·F 校准 / §8 P2a·P2b / §10 影子期 为裁决后修订
- 关联规则：RULE-AI-01（事实/完成诚实）、RULE-AI-24（防退化）、RULE-AI-28（审查闸）、RULE-AI-30（fail-closed）、RULE-AI-34（分支收口合并闸）
- 上游设计：`DESIGN-20261101-cross-session-coordination-v1.md`（L1–L4）、`DESIGN-20261103-multi-task-concurrency-v2.md`（claim / 可见性 / 路径重叠）
- 事实基线：mirror 工作区 `0cb127578`（2026-11-05 实测）。凡标「已核」均有源码行号或命令回执；标「未核」者不得作为实施完成判据。

---

## 0. 结论摘要

1. **本设计只做既有协调体系没做的那一维：分支与合并/部署**。goal/task/session 维度的归属校验、只读快照、依赖、CAS、claim 租约、路径重叠预检**已全部落地**，本设计**不重做、不改语义**（§2.2 给出逐项不重复清单与源码依据）。
2. **真正的空白是四件事**：① 没有 branch↔worktree↔goal 的绑定实体（worktree 至今是 `--detach`）；② 没有 main 权威与合并串行化；③ 没有验证凭证复用（每次 rebase 全量重验是效率黑洞）；④ 协调视图**零 UI**（`webui/src` 中 `coordination` 命中 0 个文件）。
3. **「先完成先合并」是错的排序策略**，会制造"谁后合谁吃亏"的饥饿博弈。本设计用**批次窗口（batch）+ 冲突面最小排序 + 契约先行 + 分级凭证失效**替代 FIFO，把 main 前进次数从 O(lane 数) 压到 O(批次数)。
4. **时序问题的本质是 base 漂移**，三种代价必须分开处理：冲突（用 merge-tree 零副作用预检提前暴露）、凭证失效（用 `patch_digest + base_sha` 三元组做**分级**失效，不是一刀切全量重跑）、绿但错（用 `contract_changes` 广播做 fail-closed 兜底）。
5. **不让 UI 承担判断**：Board 只读聚合、零写副作用，写操作仍走工具（lane_* / claim_task / 合并队列），保持"程序管结构、模型管策略"的既有分工。
6. 交付分三档：**P0** 可见性（lane 账本 + Board + Sidebar tab，零破坏）；**P1** 协调（验证凭证 + 预检 + 落后度 + 协助收件箱）；**P2** 自动化（合并队列串行化 + batch + main broken 联动部署）。
7. **用户裁决已落定（§11）**：合并执行分三级授权——S0 人工确认（默认）/ S1 十条机检全满足自动 / S2 低风险三类全自动；**自动合并必须绑定自动回滚**（归因不到单条则只标 broken，绝不自动回滚）；开关默认关，配置开启。
8. **交付顺序修订**：P2 拆为 **P2a 人确认**（先交付）与 **P2b 条件自动**（执行器 + 自动回滚）。两者共用同一队列与判定，差别只在"谁按最后一下"。

---

## 1. 需求与可验收分解

### 1.1 原始诉求（用户原话拆解）

| # | 诉求 | 归属 |
|---|---|---|
| U1 | 以 main 和生成部署为主导 | §4 L0 |
| U2 | 各分支并行开发，统一管理 | §4 L1 |
| U3 | 设立专门管理的会话条目栏 | §4 L2 |
| U4 | 各会话进展管理，接收协助信息并协调 | §4 L3 |
| U5 | 避免污染、避免重复开发与重复验证 | §4 L4 |
| U6 | 不同会话完成/提交时间不同，对后续未完成会话的影响要统筹 | §5 时序统筹（本设计重点） |

### 1.2 验收口径（可执行断言）

| 编号 | 断言 | 判据 |
|---|---|---|
| A1 | 开工前可见重叠 | 第二个 lane 声明与在途 lane 重叠的 paths，`lane_open` 回执**必须**含 `overlap_warning` 并列出对方 `lane_id`，且**不阻断**（警告级） |
| A2 | 凭证分级复用 | lane 在 S0 验证 pass，rebase 到 S1（S1 未触碰其 paths）后，凭证 `reusable="impacted"`，**不需**全量重跑 |
| A3 | 契约变更 fail-closed | 若 S1 的 `contract_changes` 命中该 lane paths，`reusable=false`，**必须**全量重跑 |
| A4 | 合并串行 | 两个 lane 同时请求合并，只有一个进入 `merging`，另一个回执 `queued` 或 `main_advanced` |
| A5 | broken 默认拒绝 | `main_broken=true` 时 `lane_open` 默认 FAILURE（`reason_code=main_broken`），显式 `override_broken=true` 才放行 |
| A6 | Board 只读 | 调用 `/api/v1/coordination/board` 前后 `lanes.jsonl` 与 `goals.jsonl` 的 sha256 不变 |
| A7 | 关闭不自动清理 | `lane_close` 只把 lane 收敛到终态；worktree 删除仍由 `release_worktree` / 人工执行（避免吞掉未提交产物）。**按实际实现修正：close 不使 worktree 计数 -1** |
| A8 | 批次可归因 | 一个 batch 合并后 main 全量验证红 → `main_broken=true` 且 `last_good_sha` = 上一批 main |
| A9 | 写侧 CAS | 两会话对同一 lane 并发 `lane_update`，版本失配方 FAILURE 并回执当前 `version` |
| A10 | 无凭证不合 | lane 无有效凭证时 `lane_merge_request` 拒绝（`reason_code=verify_required`） |
| A11 | 自动合并门禁 | S1 下十条机检任一不满足 → 回落 S0 并回执 `auto_denied:["条件名"]`，**未执行 merge** |
| A12 | 自动回滚可归因 | 合并后 main RED 且归因到顶端 merge → 自动 `revert -m 1` 并记 `auto_reverted`；归因不到单条 → 只标 `main_broken`，**不 revert** |

---

## 2. 现状核实（只列会改变实现的点）

### 2.1 已核事实

| # | 事实 | 证据 |
|---|---|---|
| E1 | 隔离 worktree 以 **detached HEAD** 创建，不绑分支 | `workspace/worktree_isolation.py:350-354`：`git worktree add --detach <dir> HEAD` |
| E2 | 脏树在释放时**保守保留**，只有干净树才 `worktree remove --force` | 同文件 `release_worktree` `386-417`（`kept_dirty` 分支在 `393-409`）|
| E3 | 已有 worktree 数量护栏（`WORKTREE_LIMIT`）与孤儿清扫 | 同文件 `327-331`；`_sweep_orphans` |
| E4 | **linked worktree 的 data_dir 默认自动 rebind 到 git common root** | `runtime/paths.py::resolve_runtime_paths`：`linked_worktree` 为真且未显式指定时 `data = common_root/"data"`、`data_auto_rebind=True`（115-150 区段已读）|
| E5 | goal 账本是 `audit_dir/goals.jsonl`，带跨进程写锁 | `introspection/goal.py:94`（`self._path = self._dir / "goals.jsonl"`）、`goal.py:435`（flock，仅锁获取失败 fail-open）|
| E6 | 审计目录统一解析为 `Path(data_dir)/"audit"`，append + flock | `runtime/admission_barrier.py:94-98` |
| E7 | `coordination_status` 已实现且零状态变更 | `introspection/tools_goal.py:346`（`run_coordination_status`，docstring 明示「只读协调快照；零状态变更」）、注册 `registry_goal.py:34-37` |
| E8 | **路径重叠预检已实现**（警告级，不阻断） | `introspection/task_claim.py:285/293/297`（`_paths_overlap` / `overlapping_paths`）、`564-577`（`_warn_path_overlap`）、渲染 `tools_task.py:494` |
| E9 | Sidebar 现有 6 个 tab：sessions / files / evo / esc / archived / metrics | `webui/src/components/sidebar/Sidebar.tsx:274-321` |
| E10 | **UI 层完全没有 coordination** | `grep -rln "coordination" webui/src` → 0 命中 |
| E11 | 工作树规模已膨胀：`git worktree list` **265** 条，`.releases` **183** 个 detached 快照树 | 实测命令回执（2026-11-05）|
| E12 | 已存在长期**分支** worktree 的实践先例 | `git worktree list`：`lfl-service-gen-experience-20261025 [fix/service-gen-experience-20261025]`、`lfl-web-restart-main-integration-20261026 [fix/web-restart-main-integration-20261026]` |
| E13 | **不存在** lane / merge_queue / main_broken / verify_receipt / merge-tree 任何概念 | `grep -rn "merge_queue\|main_broken\|verify_receipt\|merge_tree\|lanes\.jsonl" src/ webui/src` → 0 命中 |

### 2.2 与既有设计的不重复清单（防重复开发）

| 已有能力 | 位置 | 本设计的态度 |
|---|---|---|
| 写侧归属校验（cross-session write denied） | `goal_coordination.py::resolve_write_permission` | **复用**，lane 写入沿用同一判定 |
| `coordination_status` 只读快照 | `tools_goal.py:346` | **复用并扩展**（新增 lanes 段），不新建工具名 |
| Goal/Task 依赖与 frontier | `task_store.py`（`blocked_by_goals`）| **不动**；lane 依赖另设字段，绝不塞进 `dependencies`（v1 已证会让任务永久不可达）|
| Goal 级 version CAS | `goal.py:188/:256` | **复用同一模式**为 lane 加 `version` |
| TaskClaim + fencing + 路径重叠预检 | `task_claim.py` | **复用** `overlapping_paths`，不再造一份重叠算法 |
| 子代理 worktree 隔离与释放语义 | `worktree_isolation.py` | **不改既有函数签名**；lane 走新增路径，`--detach` 行为对 `spawn_subagent` **保持原样**（RULE-AI-24）|

---

## 3. 差距与设计约束

**G1 没有"分支"这个实体。** goal 是意图、task 是工作单元、session 是执行者，三者都不是 git 分支。没有实体承载「这条分支归谁、要合到哪、改哪些文件」，于是 main 上有多少条并行分支无法回答。

**G2 没有 main 权威。** 任何人都可能直接 commit 到 main；合并顺序、合并后是否验证、部署的是哪个 SHA，全凭各会话自觉。

**G3 没有验证凭证。** 现状是每次 rebase 后重跑全套。在 265 个 worktree 的规模下，这是主要效率损失来源，也是"谁都不愿意先合"的根因。

**G4 协调视图对人不透明。** `coordination_status` 只对模型可见，人打开面板看不到"哪几条分支在跑、卡在哪、要不要我决策"。

**设计约束**
- C1 不新建服务、不新建数据库：一律 JSONL + flock + 原子重写，与 `goal.py` 同构。
- C2 不在 UI 里做写操作：Board 只读。
- C3 不改 `spawn_subagent` 的既有行为（`--detach` 保留）。
- C4 所有自动判定 fail-closed：判断不了按"未通过"处理（RULE-AI-30）。
- C5 改 main 的执行权分三级（§4.4.1）：S0 人工确认（默认）、S1 机检全满足自动、S2 低风险全自动；**自动合并与自动回滚同时授权**，开关默认关。任何一级都不允许"自动合并但不自动回滚"。

---

## 4. 方案设计

### 4.1 分层

```
L0 main 主线与部署（权威层，只读判定 + 串行闸）
      main_sha / last_good_sha / main_broken / deploy_generation
        │  只接受 batch 合入，一次一批，一次一验证
L1 BranchLane 登记（新增，唯一新实体）
      lane = 1 分支 × 1 worktree × 1 goal × 1 owner session
        │  lanes.jsonl（data/audit，复用 E4/E6 的路径解析与 flock）
L2 会话条目栏 Board（新增 UI + 只读 API）
      GET /api/v1/coordination/board → Sidebar 第 7 个 tab「Lanes」
        │  零写副作用（A6）
L3 协助通道（新增，文件式收件箱）
      data/interop/session/{pending,done}/  —— 与既有 interop 目录同构
L4 防污染四道机制（组合既有 + 新增）
      ① 路径重叠（复用 E8） ② merge-tree 预检（新）
      ③ 验证凭证（新）       ④ 契约变更广播（新）
```

### 4.2 数据契约：lanes.jsonl

`data/audit/lanes.jsonl`，追加式 + flock + 原子重写（与 `goal.py` 同构，复用 E5/E6 模式）。每条 lane 一行全量快照（last-write-wins + `version` CAS），非事件流，便于整行读取与 CAS。

```python
@dataclass
class Lane:
    lane_id: str              # "lane-<8hex>"
    branch: str               # "lane/20261105-board"
    worktree: str             # 绝对路径（realpath 校验）
    base_main_sha: str        # 分叉时的 main
    base_is_broken: bool = False   # 是否在 broken main 上开工（override 记录）
    owner_session_id: str     # 显示用，**不作鉴权依据**
    goal_id: str              # 1:1，强绑定
    paths: list[str]          # 声明改动面（复用 claim 的语义）
    contract_changes: list[str]   # 对外接口变更（新增/改签名/改协议），默认空
    status: str = "open"      # open|active|verifying|merging|merged|closed|abandoned
    head_sha: str = ""
    version: int = 1          # lane_update 的 CAS 依据
    created_at: str = ""
    last_activity: str = ""
    verify_ref: str = ""      # 最近一张凭证的 id
    close_reason: str = ""
```

**写权限模型（重要）**：`owner_session_id` 只用于显示与提示，**鉴权不看 session 身份**——沿用既有 `resolve_write_permission` + claim fencing 的口径。理由是 CLI/DSH 会话 id 不稳定，用它鉴权既不可靠又会造成"自己也被拒"的假故障。

### 4.3 工具面（4 个，均为新增，不改既有签名）

| 工具 | 语义 | 关键点 |
|---|---|---|
| `lane_open` | 建 lane：分支 + worktree + goal 绑定 + 归属登记 | 前置做三查（§4.5）；`main_broken` 时默认拒绝（A5）|
| `lane_update` | 改 status/paths/contract_changes/head_sha | 必须带 `expected_version`（A9）|
| `lane_close` | 终态释放 | 干净树 `worktree remove`，脏树 `kept_dirty`（复用 E2 语义）|
| `lane_merge_request` | 申请合入 main | 无有效凭证直接拒（A10）；只入队，不自动改 main（C5）|

`lane_open` 创建 worktree 用 **`git worktree add -b <branch> <path> <base_sha>`**，与 `worktree_isolation.py:351` 的 `--detach` **并存**（不同函数，不触碰既有路径）。

### 4.4 合并队列与批次（L0 核心）

**为什么不采用 FIFO「先完成先合并」**：它把 base 漂移的成本全部压给后完成者，理性策略是"等别人先合"，于是 main 长期不动、部署滞后；一旦被迫合并，冲突面已经很大。这是排序激励问题，不是工程细节。

**批次窗口**：main 只接受 batch 合入。

```
batch = { base_sha, lanes[1..K], order[], state }
K ≤ K_MAX（默认 3），且 Σ changed_files ≤ F_MAX（默认 30）
```

- `K_MAX` 由**部署归因粒度**决定：一个 batch 合并后若部署失败，必须能把问题归因到 ≤3 条 lane。合并更多条再部署，出事只能整体回滚（RULE-AI-34 的可归因要求）。
- 未成批的 lane **不被阻塞**，继续开发——这是与"合流冻结"的关键区别。

**合并顺序算法（贪心，非最优但足够）**：

```python
def order_batch(lanes, base_sha):
    # 1) 契约变更者先：它是全体的基线，晚合会让所有人返工
    # 2) 再按冲突面升序：零冲突先合，冲突者后合（只需 rebase 一次）
    # 3) 同冲突面按 behind 升序（落后少的先，减少重验）
    for lane in lanes:
        lane.conflicts = merge_tree_conflicts(base_sha, lane.head_sha)  # 零副作用
    return sorted(lanes, key=lambda l: (not l.contract_changes,
                                        len(l.conflicts),
                                        l.behind))
```

`merge-tree` 预检用 `git merge-tree --write-tree`，**不建 worktree、不动 index、不写 ref**——这是把"冲突发现"从"真 rebase 之后"提到"排队之前"的低成本手段。**它是有损启发式**：预检无冲突 ≠ 真实合并无冲突（rename/二进制等场景），因此真实 merge 仍必须处理冲突，并把 `precheck_miss` 记下来用于校准，不假装预检等价于合并。

**合并临界区（唯一能改 main 的地方）**：

```
lock main_merge.lock
  current = rev-parse main
  if current != batch.base_sha:      # 期间被推进
       unlock; return main_advanced(current)   # 回 rebasing 重验
  git merge --no-ff <lane_head>  (逐 lane，产生 merge commit，可单独 revert)
  main_sha = rev-parse main
  run main 全量验证
  if fail: main_broken = True; last_good_sha 保持上一批
unlock
```

用 `--no-ff` 而非快进，是为了**单 lane 可回滚**：`git revert -m 1 <merge_sha>`。可回滚性优先于线性历史的 bisect 便利。

#### 4.4.1 三级授权：谁按最后一下（用户裁决 2026-11-05）

改 main 的执行权不是二值开关，而是三级。**共用同一合并队列、同一预检、同一凭证判定**，差别只在"谁做最后裁决"。

| 级 | 名称 | 行为 | 人的角色 | 默认 |
|---|---|---|---|---|
| **S0** | `human_confirm` | 排队 + 预检 + 凭证校验 → 产出**合并建议卡**（建议顺序 / 冲突矩阵 / 需重验清单 / revert 单元 sha）；人点确认才执行 merge | 逐次确认 | **开（唯一默认）** |
| **S1** | `conditional_auto` | 下列 10 条机检**全部满足**才自动执行；**任一不满足 fail-closed 回落 S0** 并回执 `auto_denied[]` | 只裁例外 | 关 |
| **S2** | `full_auto` | `docs-only` / `test-only` / `revert-only` 三类直接自动执行 | 事后审计 | 关 |

**S1 十条机检（全满足才自动，缺一即回落）**

| # | 条件 | 失配理由码 |
|---|---|---|
| 1 | `main_broken=false` 且部署态可判定（非部署窗口） | `main_broken` / `deploy_window` |
| 2 | `git merge-tree` 预检零冲突 | `conflict_precheck` |
| 3 | 凭证有效：`patch_digest` 匹配，且（`base_sha == main_head` 或 `impacted` 级复验通过） | `verify_stale` |
| 4 | 独立审查 PASS 回执绑定当前 sha 且未过期 | `review_missing` |
| 5 | 改动路径 ⊆ `auto_merge_allowlist`（**默认空 = 全不自动**，必须显式配置） | `path_not_allowed` |
| 6 | 改动路径 ∩ `sealed_paths` = ∅，且不含 rules / 部署配置 / 迁移脚本 | `sealed_path` |
| 7 | K / F 权重未超限（§4.4.2） | `budget_exceeded` |
| 8 | 无 `need=block` 的未决协助请求 | `help_blocking` |
| 9 | 无其他 lane 对重叠 paths 持有 claim | `claim_overlap` |
| 10 | 可一步 revert（`--no-ff` 且父即当前 main head） | `not_revertible` |

**自动合并必须绑定自动回滚（硬约束）**

只自动合并、不自动回滚 = 把风险全留给人，人工成本反而高于纯手工。因此：

- 合并后 main 全量验证 **RED** 且**该 merge 是 main 顶端**（或 bisect 精确归因到它）→ 自动 `git revert -m 1 <merge_sha>`，记 `auto_reverted` + `revert_reason`。
- **归因不到单条就绝不自动回滚**：只置 `main_broken=true` + 输出候选列表，等人工判断。错误地 revert 一条无关 lane 比不回滚更糟。
- 自动回滚后同样跑一次 main 验证；若仍 RED → `main_broken=true` 且 `auto_rollback_failed=true`，停止一切自动动作。

**影子期（S0 → S1 的唯一通道）**

开启 S1 前必须先跑 **≥10 次 dry-run**：机检判定与人工判定逐条对照。要求**一致率 100% 且零漏拦**（机检放行而人判拒绝 = 漏拦，一票否决）。这是 RULE-AI-35 的延伸——"应拦输入"必须实测拦过，不能靠代码写完宣称生效。

#### 4.4.2 K_MAX / F_MAX 的约束理由与校准（用户裁决维持 K=3 / F=30）

- **K_MAX=3** 的真实约束不是"部署归因"，而是**自动回滚的可枚举性**：K=3 时最坏只需在 3 个 merge 里判断撤哪个；K>3 只能整体回退，单 lane 归因失效。
- **F_MAX=30** 的真实约束是审查子代理的认知负荷（>30 文件 diff 时 P0/P1 检出率下降）——**这条是假设，未实测**，因此必须可校准。
- **按 lane 类型加权**（名义 K 可容纳更多低风险 lane）：`docs-only` 权重 0.3、常规 1.0、涉及 `sealed_paths` 1.5；权重和 ≤ K_MAX 才成批。
- **校准规则**：前 3 次真实批次记录实际文件数与归因耗时；归因 >30min → K 降至 2；从未需要归因 → 可试 K=5。K/F 是初始值，不是最优值。

### 4.5 开工前三查（防重复开发，U5 核心）

`lane_open` 顺序执行，**全部为警告级，除 contract 冲突**：

| 查 | 手段 | 命中后 |
|---|---|---|
| ① 路径重叠 | 复用 `task_claim.overlapping_paths`（E8）| 回执列对方 lane_id + 重叠文件；**不阻断** |
| ② 在途同主题提交 | `git log --all --oneline -- <paths>`（worktree 共享对象库，廉价）| 回执列出候选提交；提示"可能已有人在做" |
| ③ 同类 goal | `goals.jsonl` 中 status=active 且 objective 相似的 goal | 回执列出，建议接续而非新建 |
| ④ 契约冲突 | 在途 lane 的 `contract_changes` ∩ 本 lane paths ≠ ∅ | **阻断**（fail-closed），要求先协调 |

②的做法来自既有方法卡 `method:probe-inflight-same-topic-work-across-all-refs-when-concurrent-sessions`（candidate）：多会话共享仓库时「还需要我修」是分钟级衰减的前提，开工前用 `git log --all` 探测。

### 4.6 会话条目栏（L2）

**API**：`GET /api/v1/coordination/board?window_hours=0`，只读，**复用** `coordination_snapshot`（E7）并追加 lanes 段，不新建采集层。

```json
{
  "generated_at": "2026-11-05T09:58:00+08:00",
  "main": {"sha": "...", "broken": false, "last_good_sha": "...",
           "deploy_generation": 41, "ahead_of_deploy": 2},
  "lanes": [{
    "lane_id": "lane-3f2a9c1d", "branch": "lane/20261105-board",
    "goal_id": "G-...", "objective": "...",
    "status": "active", "ahead": 4, "behind": 11,
    "stale": "ok|stale|blocked_for_merge",
    "paths": ["webui/src/components/sidebar/Sidebar.tsx"],
    "verify": {"result": "pass", "base_sha": "...", "age_s": 3600,
               "reusable": "exact|impacted|none"},
    "merge": {"batch_id": "b-7", "order": 2, "state": "verifying"},
    "pending_help": 1
  }],
  "batches": [{"batch_id": "b-7", "state": "merging", "lanes": ["lane-...", "lane-..."]}],
  "help_requests": [{"id": "...", "from": "...", "topic": "...", "need": "..."}]
}
```

**UI**：`Sidebar.tsx` 新增第 7 个 tab（现有 6 个已核，E9），`view === "lanes"`。每条一行，展开显示 goal/task/凭证/协助。**定位澄清**：它不是第二个 sessions 列表——sessions 是"谁在跑"，lanes 是"哪条分支要合、卡在哪"。.releases 的 183 个快照树**不展示**（E11 规模问题），只展示 `status ∈ {open, active, verifying, merging}`。

### 4.7 协助通道（L3）

`data/interop/session/{pending,done}/<id>.json`（与既有 `data/interop/dsh_to_lfl` 等同构）：

```json
{"id":"...","from_lane":"...","to":"any|lane-...","topic":"...",
 "need":"info|decision|handoff","body":"...","created_at":"...","state":"pending"}
```

- 消费点：`coordination_status`（新段）与 Board「待协助」。
- **收到协助请求 ≠ 获得写权**：这是权限边界，不能因为"有人请我帮忙改他的分支"就绕过归属校验。
- 不做自动派发：写入 pending 即止，由被请求方（人或模型）自行认领。

---

## 5. 时序统筹（本次重点：完成/提交先后不同的影响）

### 5.1 问题形式化

N 条 lane 从同一 `S0` 分叉，完成时刻 t1 < t2 < … < tN，合并时刻 m1 < m2 < … < mN。合并 lane_k 后 main 前进到 `S_k`，此时 lane_{k+1..N} 的 base 仍是旧 SHA，产生**四类代价**：

| 代价 | 机制 | 若不处理的后果 |
|---|---|---|
| P1 冲突增长 | 后合 lane 与已合改动命中同一文件 | 越晚越难合，最终放弃或大改 |
| P2 凭证失真 | 绿是基于旧 base | **绿但错**：语义冲突（接口改了，调用方还按旧契约） |
| P3 重验成本 | 每次 rebase 强制全量重跑 | 「谁都不愿先合」的饥饿博弈，main 停滞 |
| P4 归因模糊 | 连合多条再部署 | 部署失败只能整体回滚，无法定位到 lane |

### 5.2 四条对策（与代价一一对应）

#### D1 批次窗口 → 压 P1/P3

main 前进次数从 O(N) 降到 O(⌈N/K⌉)。同批 lane 一起 rebase 到**同一个** `batch_base_sha`，一起验证、一次合并。批内不互相推进 base，因此批内任意两条 lane 之间**零 base 漂移**。

**副作用与处置**：批次会把"先完成"的 lane 按住等"后完成"的 lane（最多等一个窗口）。这是有意的：等待成本（wall-clock）远低于多轮重验成本（token + 人工），且等待期 lane 仍可开发。窗口策略：满 K 或最早 lane 等待超 `T_batch_wait`（默认 45 min）即开批，避免无限等。

#### D2 冲突面最小排序 → 压 P1

见 §4.4 算法。零冲突者先合、契约变更者最前。这样"冲突"只发生一次（需要 rebase 的那条），而不是每条都撞。

#### D3 验证凭证三元组 + 分级失效 → 压 P2/P3（本设计性价比最高的一条）

```json
{"receipt_id": "vr-...", "lane_id": "...",
 "patch_digest": "sha256(git diff <base_sha>..<head_sha>)",
 "base_sha": "S0", "tested_tree_digest": "sha256(git ls-tree -r HEAD)",
 "command": "pytest tests/...", "result": "pass", "scope": "full|impacted",
 "failed_tests": [], "reviewer_pass_ref": null,
 "created_at": "...", "ttl_s": 86400}
```

**为什么不能只绑全树 digest**：rebase 后 base 变了 → 全树 digest 必变 → 即便自己的 patch 一字未改，凭证也全废。这正是"重验成本"的根源。

**失效判定表（fail-closed，判断不了一律当失效）**：

| 条件 | 判定 | 动作 |
|---|---|---|
| `patch_digest` 不一致 | 失效 | 全量重跑 |
| 无凭证 / TTL 过期 / `created_at` 在未来 | 失效 | 全量重跑 |
| patch 同 + base 同 + tree 同 | `exact` | 直接复用 |
| patch 同 + base 变 + 新 main 的 `contract_changes` ∩ 本 lane paths = ∅ | `impacted` | **只跑受影响集** |
| patch 同 + base 变 + 契约命中 | 失效 | 全量重跑（语义可能已变）|

「受影响集」= 本 lane `paths` + 由 `paths` 反向依赖（import/引用）得到的下游测试集。产物落 `receipt.impacted_tests`，供审计。

#### D4 落后度阈值 + 反饥饿 → 压 P1 的尾部风险

| behind（提交） | stale（小时） | 标记 | 行为 |
|---|---|---|---|
| < 20 | < 48 | `ok` | 正常 |
| ≥ 20 或 ≥ 48 | | `stale` | Board 黄色，提示 rebase |
| ≥ 50 或 ≥ 96 | | `blocked_for_merge` | **不得进入批次**，必须先 rebase+重验；**开发不冻结** |

不设"必须 rebase 才能提交"：rebase 会打断在途验证，强制只会逼出假 rebase。只在下一次合并前结算落后度。

#### D5 main broken 的时序语义 → 压 P4

- `main_broken=true` 时，`lane_open` **默认拒绝**（A5），防"基于坏基线开工"的错误级联。
- 在途 lane 的凭证**全部暂停复用**（基线不可信）；`reusable` 一律降为 `none`。
- 修复走 hotfix lane，`priority=hotfix` **插队**到下一个批次首位（D2 排序的第一项升级为 hotfix 优先）。
- 部署失败 → 标 broken + 给出 `last_good_sha` 作为回滚建议，**不自动回滚**（人工决策，与既有风格一致）。

### 5.3 端到端时序（示例，N=3）

```
t0  main=S0 生成 deploy_gen=41
t1  laneA 基于 S0 开工（paths: a.py）
t2  laneB 基于 S0 开工（paths: b.py）
t3  laneC 基于 S0 开工（paths: a.py, c.py）  ← 与 A 重叠，回执 overlap_warning
t4  laneA 完成，凭证 vr-A(base=S0, patch=P_A) pass
t5  laneB 完成，凭证 vr-B(base=S0, patch=P_B) pass
t6  laneC 完成，凭证 vr-C(base=S0, patch=P_C) pass
    —— 到此三条 base 都是 S0，零漂移（因为在同一批次窗口内）
t7  开批 b-1 = {A, B, C}，batch_base_sha = S0
    排序：A(无契约,冲突{A,C}) vs B(无冲突) vs C(无契约,冲突{A,C})
         → B 先（0 冲突）→ A（与 C 冲突，但 A 先完成）→ C
    B 合入 → main=S1；A 需 rebase 到 S1（A 的 paths 与 B 的 b.py 不重叠
      → 但 base 变了，凭证降级 impacted → 只跑 a.py 相关测试）
    A 合入 → main=S2；C rebase 到 S2，与 A 冲突命中 a.py → 真实冲突
      → 人工解冲突 → 凭证失效 → 全量重跑 C
    C 合入 → main=S3
t8  main 全量验证 pass → 部署 deploy_gen=42 (sha=S3)
    ｜ 若部署失败 → main_broken=true, 回滚建议 S0（上一批）
```

**对照 FIFO**：A、B、C 各自完成即刻合并，则每次合并都推进 main，后完成者每次都要 rebase 重验 → 3 次 base 漂移 + 3 次全量重验。批次法把这个数字压到 2 次（其中 1 次退化为 impacted 级）。

### 5.4 时序相关的已知残余风险（如实登记）

| # | 风险 | 为何不消除 | 缓解 |
|---|---|---|---|
| R1 | 批次等待使最早完成者空等 | 等待换重验成本，是刻意的权衡 | `T_batch_wait` 上限 45min；可临时 `lane_merge_request(urgent=true)` 单独走一批（K=1）|
| R2 | `impacted` 级判定可能漏掉隐性依赖（动态 import、字符串拼路径） | 静态依赖分析不完备 | 契约变更广播兜底 + 定期（每批）对 main 全量验证；漏检记入 `precheck_miss` 统计 |
| R3 | `merge-tree` 预检与真实 merge 不等价 | git 不提供等价保证 | 预检只用于**排序**，不用于"判定可合"；真实 merge 仍 fail-closed |
| R4 | 多人同时改同一 hotfix 区域 | 无全局锁 | 路径重叠 + 契约阻断；hotfix 走插队但同批 K=1 |
| R5 | 部署与合并仍是两步，存在"已合未部署"窗口 | 不引入自动部署（超出授权）| Board 显示 `ahead_of_deploy`，>0 时显著提示 |

---

## 6. 失败模式矩阵

| # | 失败 | 检测 | 处置 | 是否 fail-closed |
|---|---|---|---|---|
| F1 | `lanes.jsonl` 损坏 | json 解析失败 | 拒绝一切 lane 写入，回执指明行号，不猜旧状态 | 是 |
| F2 | 并发 `lane_update` | `version` CAS 失配 | FAILURE + 回执当前 version，调用方重读 | 是 |
| F3 | 合并时 main 被推进 | 临界区内二次比对 sha | 退回 `rebasing`，重验 | 是 |
| F4 | 凭证伪造/篡改 | `tested_tree_digest` 重算比对 | 拒复用，标 `receipt_invalid` | 是 |
| F5 | worktree 丢失 | realpath 不存在 | 标 `worktree_missing`，禁合并 | 是 |
| F6 | 部署失败 | 部署回执 | `main_broken=true` + 回滚建议 | 是 |
| F7 | 预检与真实 merge 不一致 | 真实 merge 冲突而预检无 | 记录 `precheck_miss`，用于校准 | 否（仅记录）|
| F8 | 时钟漂移（`created_at` 在未来）| 时间比较 | 视为过期 | 是 |
| F9 | 磁盘满 | `shutil.disk_usage`（复用 E3 模式）| 拒绝 `lane_open`，`DISK_LOW` | 是 |

---

## 7. 测试计划

**单元**
1. `order_batch` 排序：契约变更者最前；零冲突先；同冲突面按 behind 升序。
2. 凭证失效表 5 行逐条断言（含"base 变 + 契约命中 → 必须全量"）。
3. `patch_digest` 在 rebase 前后不变（构造 rebase，断言 digest 相等）。
4. `lane_update` 版本 CAS：并发两次，第二次 FAILURE 且回执含当前 version。
5. `lane_open` 重叠三查：路径/在途提交/同类 goal 各命中一次，断言回执字段。

**集成**
6. 三 lane 并发开、合批一次：断言 main 前进 1 次，lens 状态全部 `merged`，`last_good_sha` 正确。
7. 合并临界区竞争：两 lane 同时 `lane_merge_request`，断言只有一个进 `merging`（A4）。
8. `main_broken` 时 `lane_open` 默认拒绝，`override_broken=true` 放行且 `base_is_broken=true` 落账（A5）。
9. `lane_close` 只收敛状态、不删 worktree；清理走 `release_worktree`（干净树 removed / 脏树 kept_dirty）（A7 已按实现修正）。
10. Board 只读：调用前后 `lanes.jsonl`/`goals.jsonl` sha256 不变（A6）。

**回归（防退化，RULE-AI-24）**
11. `spawn_subagent` 路径仍产出 detached worktree（断言 `git status` 显示 detached HEAD）——**证明 lane 改动没污染既有隔离语义**。
12. 既有 `overlapping_paths` 与 `coordination_status` 行为不变（快照对比）。

---

## 8. 分期与工作量

| 期 | 内容 | 交付物 | 破坏性 |
|---|---|---|---|
| **P0** | `lanes.jsonl` + `lane_open/update/close` + `GET /api/v1/coordination/board` + Sidebar 第 7 tab | 能看见"哪条分支在跑、改什么、领先落后多少" | 零（纯新增）|
| **P1** | 验证凭证（D3）+ merge-tree 预检（D2）+ 落后度阈值（D4）+ 协助收件箱 | 能判断"能不能合、要不要重验" | 零（新增判定，不强制）|
| **P2a** | 合并队列串行化 + batch（D1）+ `main_broken`（D5）+ 部署联动；**S0 人确认** | 能把"排队合并"变成一个受控动作 | 中（新增 main 写路径，需授权）|
| **P2b** | S1/S2 执行器 + 十条机检 + **自动回滚** + 影子期校准（配置默认关） | 常规合并无需人按，人只裁例外 | 高（自动改 main，需显式配置开启）|

P0 单独可用：即使不做 P1/P2，人在 Board 上已能看到并行现状并口头协调——这是「先可见、后自动」的一贯顺序。

---

## 9. 与既有规则的对齐

| 规则 | 对齐点 |
|---|---|
| RULE-AI-01 | §2 每条事实带源码行号/命令回执；未核者标注 |
| RULE-AI-24 | §2.2 + 测试 11/12：不改既有函数语义 |
| RULE-AI-28 | P2 合并前仍走独立审查闸（`review_admission`），lane 不豁免 |
| RULE-AI-30 | §6 九条失败全部 fail-closed；凭证判定表默认失效 |
| RULE-AI-34 | batch 合并即"分支收口合并闸"的批量形态；K≤3 保证可归因 |
| RULE-AI-35 | A1–A10 每条都可对"应拦输入"实测（如 A5 的 broken 拒绝、A6 的只读性）|

---

## 10. 判据：什么时候算做完了

- **P0 完成** = A6/A9 PASS + A7 按修正口径 PASS（close 不改 worktree）+ Sidebar 能显示 ≥2 条真实 lane + `spawn_subagent` 回归 11 PASS。
- **P1 完成** = A1/A2/A3 PASS，"base 变但 patch 未变"的场景实测不触发全量重跑。
- **P2a 完成** = A4/A5/A8/A10 PASS + 一次真实批次合并（≥2 lane）后 main 全量绿 + 部署成功。
- **P2b 完成** = 影子期 ≥10 次 dry-run 人工判定与机检判定一致率 100%（零漏拦）+ 至少一次自动合并后自动回滚实测成功（构造 RED 输入）+ 十条机检的「应拦输入」全部实拦（RULE-AI-35）。
- 任何一期：不得以"代码写完"代替上述断言；无回执即未完成。

---

## 11. 用户裁决（2026-11-05，已落定）

| # | 待裁决点 | 裁决 | 落地位置 |
|---|---|---|---|
| 1 | lane 与 goal 是否强制 1:1 | **强制 1:1**。同一 goal 若需并行多条，必须显式 `lane_role=main\|sub`，sub 由 main lane 汇总合并。**边界：subagent 的 `--detach` 隔离 worktree 不登记为 lane**——它是私有中间态、产出由父会话收口，登记会把 265 个 worktree 的规模问题原样搬进 Board | §4.2 `lane_role` |
| 2 | 是否允许自动执行 `git merge` | **允许，三级授权**：S0 人工确认（默认）/ S1 十条机检全满足自动 / S2 低风险三类全自动；**自动合并必须绑定自动回滚** | §4.4.1 |
| 3 | K_MAX / F_MAX | **维持 K=3、F=30**，但改为"初始值 + 类型加权 + 校准规则"；理由改述为**自动回滚可枚举性**（K）与**审查认知负荷**（F，未实测假设） | §4.4.2 |
| 4 | `lanes.jsonl` 落盘位置 | **`data/audit/`**，且**拆两个文件**：`lanes.jsonl`（当前态，last-write-wins + `version` CAS）+ `lane_events.jsonl`（append-only 历史）。与 `goals.jsonl`/`events.jsonl` 同构，避免当前态与历史争同一把写锁 | §4.2 |
| 5 | Board 是否展示 `.releases` 的 183 个快照 | **不列详情**，但**必须显示部署条带**：`deployed_sha` / `main_head` / 两者是否一致；其余快照进折叠区默认收起 | §4.6 |

### 11.1 实施约束（裁决附带）

- **开闸方式**：用户明确要求"直接实现，把开关留给配置"——P2b 执行器**直接实现**，不以 `submit_evolution` 人工审批为前置；但配置项**默认关**（`lane_auto_merge=off`、`auto_merge_allowlist=[]`）。任何新实例上行为等价于 S0。
- **"实现了自动" ≠ "默认自动"**：默认态必须是 S0；开启需宿主显式配置并留审计。
- **A6 只读性不因自动化降级**：Board API 在 S1/S2 开启后依然零写副作用。
- **部署记录接入方式**：`data/audit/deployments/*.jsonl` 已有手工 `pre_deploy` 记录（字段含 `target_sha`/`rollback_sha`/`target_worktree`/`deploy_command`/`rollback_command`），但 `src/` 零代码引用、最后一份停在 2026-09-16。P2 的部署联动是**接入并结构化这个既有格式**，不是发明新格式（RULE-AI-24）。

---

## 12. 拷问记录（附：工具能力边界声明）

### 12.1 工具事实

本次调用 `grill_me` 对本文档的方案骨架做追问式评审，回执为 `mode=template_only`——工具未能在正文中锚定可锚定的标题/数值/断言，输出的是**通用模板问题**（空值/并发100次/磁盘满等），与 S0–S3 的具体时序无关。**该回执不构成对本文档的有效评审**，不记为「已审」。以下 Q&A 为自审，逐条针对本设计的具体断言。

### 12.2 自审 Q&A

**Q1 为什么"批次"能减少重验，而不是把重验推迟？**
A：重验次数取决于 **base 变化次数**，不是合并次数。批内所有 lane 共享同一 `batch_base_sha`，批内零漂移；批间每个 lane 至多经历一次 base 变化。N=10、K=3 → 每个 lane 平均经历 ⌈10/3⌉−1 ≈ 2 次漂移，而 FIFO 是平均 4.5 次。且 D3 把其中大部分降级为 `impacted`。

**Q2 如果一条 lane 迟迟不完成，批次会不会被它拖住？**
A：不会无限拖。`T_batch_wait=45min` 到点即用现有成员开批；未完成者进入下一批。极端情况可 `urgent=true` 单独成批（K=1）。

**Q3 `impacted` 级复用会不会掩盖真实的语义破坏？**
A：会漏，这是登记在 §5.4 R2 的真风险。兜底有两条：契约变更广播（硬拦截）+ 每批 main 全量验证。若某 lane 未申报 `contract_changes` 却改了接口，属于申报纪律问题，靠 code review 闸兜（RULE-AI-28），凭证机制不承担这个职责。

**Q4 两条 lane 都改同一文件（A、C 都改 a.py），批次还有意义吗？**
A：有，但收益下降。排序让 A 先合、C 后合并在同一批内 rebase 一次；若走 FIFO，C 在 A 合并时立刻要 rebase 一次、在 B 合并时再 rebase 一次。同批只结算一次。真正的解法是 §4.5 第①查——开工时就知道重叠，提前协商谁改。

**Q5 为什么合并用 `--no-ff`，不怕历史变脏？**
A：为了**单 lane 可回滚**。部署失败时 `git revert -m 1 <sha>` 精确撤掉一条 lane，而快进/线性历史只能整体回退到某点。回滚是高频风险，bisect 是低频需求，故选前者。历史"脏"在这个仓库已有先例——实测全历史 144 个 merge commit，集中在 2026-10-27～10-31 的分支整合期，11-04 起日常提交为线性。（**更正**：v1 此处曾写"占比七成"，那是把全历史 merge 总数误当近期占比，已删。）

**Q6 Board 只读，那人在 UI 上怎么"协调"？**
A：协调动作 = 会话里的工具调用（`lane_update` / `lane_merge_request` / 协助收件箱），Board 只负责让人**看见**该不该动作。这是刻意的：写操作留在有审计、有授权检查的路径上，UI 不成为第二条写入口。

**Q7 265 个 worktree 的规模问题本设计解决了吗？**
A：部分。`lane_close` 会清干净树；但 `.releases` 183 个快照树是部署产物，不在本设计范围（Board 不展示，避免污染视图）。真正清理需单独的保留策略（保留最近 N 个），列为**后续项**，不在本文档承诺。

**Q8 `owner_session_id` 不做鉴权，会不会导致互相踩？**
A：写保护来自 claim fencing 与 `resolve_write_permission`（已有），lane 只是新增维度、沿用同一口径。用会话 id 鉴权在 CLI/DSH 场景下不可靠（会话 id 不稳定），会造成"自己被拒"的假故障——那是比"互相踩"更常见的失败。跨会话写入仍会被既有 L1 拒绝（A1 系列已 PASS）。

**Q9 main broken 时在途 lane 的凭证全部作废，代价是否过大？**
A：broken 意味着基线不可信，作废是 fail-closed 的必然代价。但 D3 的分级仍保留信息：凭证记录完备，`reusable=none` 只表示"不可直接复用"，重跑时 `patch_digest` 未变可直接对 diff 做定向验证，不必重新分析改动面。

**Q10 这套东西会不会自己变成需要维护的第 5 套账本？**
A：会多一个 `lanes.jsonl`，但它只有 4 个写入工具、1 个只读 API，结构同构于 `goals.jsonl`。相对收益是可回答"哪条分支要合、能不能合"——这是当前 265 个 worktree 完全无法回答的问题。若 P0 落地后 1 个月内无人使用 Board，应按 RULE-AI-06 评估撤回，而不是继续加功能。

---

## 13. 实施回写（2026-11-05 落地期发现并修正）

本节只记录**实施证据推翻或修正设计假设**的地方，不重复正文。

### 13.1 已修正的设计缺陷

| # | 原设计 | 实际问题 | 处置 |
|---|---|---|---|
| 1 | S0 下机检全过后继续持有全局串行槽，等人工确认 | S0 没有执行器推进，人不在场时一条全过项会永久占槽，整个队列被一条"等人确认"的项卡死 | 新增 `ready_for_confirm` 状态：机检全过即**交还** slot，确认入口 `request_merge` 时重新抢槽。`SLOT_STATUSES` 仅含 `preflight|merging` |
| 2 | 队列账本命名 `merge_queue_state.jsonl`（当前态）+ `merge_queue.jsonl`（事件） | 与 lanes 账本惯例相反（`lanes.jsonl` 当前态 + `lane_events.jsonl` 事件），同一目录两套规则易误读 | 统一为 `merge_queue.jsonl`（当前态）+ `merge_queue_events.jsonl`（事件） |

### 13.2 设计未覆盖、按最小改动补齐

| # | 缺口 | 处置 | 状态 |
|---|---|---|---|
| 3 | 队列缺少"人工确认 → 合并完成"的状态出口 | 新增 `request_merge`（ready_for_confirm→merging）与 `mark_merged`（merging→merged，释放槽） | 已实现 + 3 条测试 |
| 4 | 工具面（模型可调用）未随模块交付 | 新增 `tools_merge_queue.py`（5 工具）+ `registry_merge_queue.py` 并接入 `_REGISTRIES`（13→14） | 已实现 + 7 条测试 |
| 5 | Board 要显示 ahead/behind，但 `lanes.jsonl` 不存该字段 | Board 如实显示 `head@base`，并用 `base_main_sha != main_head` 判 stale；不伪造计数 | 已在 LaneBoard 落地 |

### 13.3 仍未闭合（不得宣称已生效）

| # | 事项 | 影响 | 现状 |
|---|---|---|---|
| 6 | §4.4.1 第 8/9 条机检依赖 P1 协助收件箱与 claim 视图，二者尚未实现 | 这两条恒 `skip`，按 `skip ≠ pass` 规则整单**永不 pass** | 已实现为 `dependency_unavailable`；**自动合并在当前代码下不可启用** |
| 7 | `git merge-tree` 不在 `execute_command` 静态白名单 | 工具内可调用，但模型经 shell 无法预跑；真实仓库的冲突预检走 `MergeQueueStore` 内部子进程 | 已记录，未改白名单（属安全边界，需独立评审） |
| 8 | 开关载体不统一：`merge_queue` 读 `LFL_LANE_AUTO_MERGE` 环境变量，`lane_gate` 用 `GateConfig` 参数 | 同一开关两处口径，可能出现"队列认为开了、机检认为关" | 待统一（建议单一来源：配置层注入两者） |
| 9 | `patch_digest` 分级凭证（设计 D3/F4）未实现，当前以 `base_sha` 全等判定 | rebase 后即使自身 diff 未变也会判凭证过期，重跑成本高于设计预期 | 已标注为最小可用；F4 待后续 |

### 13.4 验证回执（本次落地期实测）

- `tests/unit/test_lane_{store,tools,board}.py` → 23 passed
- `tests/unit/test_merge_queue.py` → 13 passed（含新增 slot 释放 / confirm 闭环 / 非 ready 拒绝）
- `tests/unit/test_lane_gate.py` → 39 passed（含 3 条 RED：凭证 SHA 不匹配 / paths 未声明 / main broken）
- `tests/unit/test_coordination_routes.py` → 3 passed（含调用前后 `data/audit` 目录 sha256 全等）
- `tests/unit/test_tools_merge_queue.py` → 7 passed
- 合并回归 138 passed；`ruff check` 相关文件 All checks passed
- 前端 `tsc --noEmit` 通过；`SidebarView` 联合已并入 `"lanes"`（删除 `as` 断言）

> 以上计数为本次会话实测，非历史引用。运行时生效仍需重新部署（`sys.path` 首位为 `.releases/` 快照）。

## 14 已知未实现项（v1.2 如实标注，勿当作已完成）

| 项 | 状态 | 影响与兜底 |
|---|---|---|
| A1 `lane_open` 回执带 `overlap_warning`（列 counterpart lane_ids） | **未实现**：当前只在回执追加通用在途 lane 提示，未计算路径重叠 | Board 仍能看到 overlaps；但 open 当场拿不到对端 id，需回看 Board |
| A5 `lane_open` 对 `main_broken` 默认拒绝 | **未实现**：`main_broken` 尚无数据源（RedMainMonitor 未建） | S1 第 1 条对 `main_broken` 只能 skip；skip ≠ pass，故不会误放行 |
| L3 协助收件箱（`data/interop/session/`） | **未实现**（P1） | S1 第 8/9 条在数据源缺失时返回 skip + `dependency_unavailable` |
| ahead/behind 显示 | **无数据源**：Lane 记录不存 upstream 信息 | Board 该列显示未知（-1），不伪装成 0 |
| S1/S2 自动执行 | **未启用**：`lane_auto_merge`/`lane_auto_rollback` 默认 false；S1 执行器只判定不执行 | 合并仍需人工 `lane_queue_confirm`；S0 建议卡是唯一入口 |
| 合并队列与真实 `git merge` 的衔接 | **未实现**：`mark_merged` 由人工登记，队列不执行 git | 合并动作仍在主会话/人工侧完成 |

## 15 影子期校准结果与判定口径澄清（2026-11-05）

### 15.1 校准结果

19 个场景，verdict 一致 19/19、auto_allowed 一致 19/19、漏拦 0、误拦 0，一致率 100%，
满足 §4.4.1「开启 S1 前 ≥10 次 dry-run、一致率 100%、零漏拦」的前置条件。
报告：`docs/analysis/SHADOW-CALIBRATION-20261105-lane-s1.md`；脚本：`scripts/lane_gate_shadow_calibration.py`。

**边界（勿高估）**：场景由同一模型构造，证明的是「实现与文档规则一致」，不证明「规则覆盖了真实失败分布」。
开启后前 10 次自动判定建议记 `shadow_compare` 与人工事后判定对账，发现分歧即回落 S0。

### 15.2 第 3 条：impacted 级复验是双条件

`base_sha != main_head` 时，必须 `scope == "impacted"` **且** `impacted_result == "pass"`；
仅给 `impacted_result` 不够。首轮校准曾因此误判「机检有缺陷」，核对 `_check_s1_03` 后确认是人工判定错误。

### 15.3 第 5 条：空 allowlist 判 `path_not_allowed`

「默认空 = 全不自动」落成为 `s1_05 fail(path_not_allowed)`，而非 `verdict=pass` + `allowed=false`。
两者都不放行，但语义不同：前者是「策略不允许该路径」，后者是「开关关闭」。
需要区分这两种情形时按此读；`verdict=pass` + `allowed=false` 的场景见校准 C19。
