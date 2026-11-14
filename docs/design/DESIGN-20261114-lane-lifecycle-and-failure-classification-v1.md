# lane 生命周期收尾与队列失败分类 实现设计 v1

- 文档类型：design（**delta v2**：只写 v1 未闭合的后半程，重述 v1 已闭合部分视为缺陷）
- 日期：2026-11-14
- 状态：**草案**，未经独立审查（RULE-AI-28 未过）；任何「生效」声明须以 §6 的应拦实测为准（RULE-AI-35）
- 关联规则：RULE-AI-01（事实/完成诚实）、RULE-AI-24（防退化）、RULE-AI-30（fail-closed）、RULE-AI-35（门槛实测）、RULE-AI-37（事故修复落在动作层）、RULE-AI-36（一次性脚本先落盘）
- 上游设计：`DESIGN-20261105-main-lane-parallel-delivery-v1.md`（下称 v1）§13.3 未闭合清单、§14 已知未实现项
- 事实基线：mirror 工作区，2026-11-14 11:28–11:31 实测；账本为 `data/audit/{lanes,merge_queue,verify_receipts,goals}.jsonl` 当时快照

---

## 0. 结论摘要

1. **v1 的前半程已经闭合**：lane 实体、写前 CAS、merge-tree 零副作用预检、S1 十条机检、自动回滚绑定、Board 只读、协助收件箱均已落地并有账本证据（61 条 lane / 74 项队列 / 60 张凭证 / 169 次 merge commit）。
2. **未闭合的是后半程**：失败原因不可区分、lane 不会自己收口、返工全靠人。本期只做这三件事，不重做并发协议。
3. **主因口径纠正**：34 次队列失败按「机检顺序取首个失败项」分类为 `base_stale` 17 / `main_head_unknown` 7 / `verify_required` 7 / `verify_stale` 3。**`merge_conflict` 作为主因出现 0 次**。瓶颈不是冲突检测，是 base 新鲜度与凭证齐备度。
4. **`main_head_unknown` 与 `merge_tree_unavailable` 是同一根因的级联**（见 §1 E7），不是两个独立故障；上轮把 7+7 记作 14 次环境返工属重复计数。
5. **不加 `blocked` 状态**：`LANE_STATUSES` 里没有 blocked，新增状态要连带改状态迁移表、S1 的收口计时口径（`_CLOSING_STATUSES`）、Board 渲染与 push 门 30min 截止判定。本期用「**事件标疑 + 确证后 `close(abandoned)`**」替代。
6. **收尾必须三判据同时成立**：超时 + 探针确证失联 + 工作树干净。任一不足只标疑、不改状态。理由：实测 68 条 lane worktree 中 **22 条有未提交改动**，任何「按时间自动回收」都会毁掉真实产物。
7. **本期不新增第 5 套账本、不新增终态、不改既有工具签名**：全部复用 `close_if_live` / `requeue` / `check_paths_disjoint` / `assess_rebase_replay` 四个既有原语，只做**接线与投影**。
8. 交付 4 批，P1（诊断性）单独可用且零行为变更；P2（收尾）默认 `dry_run=true`；P3（重投）默认关；P4（开门告警）默认只告警不阻断。

---

## 1. 事实基线（2026-11-14 实测，均可复现，见附录 A）

| # | 事实 | 证据 |
|---|---|---|
| E1 | lane 账本 62 行 / **61 条唯一 lane**：merged 46、abandoned 8、closed 6、verifying 1 | `data/audit/lanes.jsonl`；`lane_role` 分布 main 28 / sub 32 / 空 1 |
| E2 | 队列 74 项唯一：merged 36、failed 34、aborted 4 | `data/audit/merge_queue.jsonl` |
| E3 | 凭证 60 张；**38/61** 条 lane 带 `verify_ref` | 同上 + `verify_receipts.jsonl` |
| E4 | 主因分布（按 `last_preflight.checks` 顺序取首个 fail）：`base_main_current/base_stale` 17、`base_main_current/main_head_unknown` 7、`verify_covers_base/verify_required` 7、`verify_covers_base/verify_stale` 3 | 34 项 failed 全部有 `last_preflight.checks`，无缺失记录 |
| E5 | 34 项中 17 项带**多个** reason_code；`main_head_unknown`(7) 与 `merge_tree_unavailable`(7) **完全共现** | 共现矩阵：`(main_head_unknown, merge_tree_unavailable)=7` |
| E6 | `merge_conflict` 仅作为**次要**码出现 2 次，**从未**成为主因 | 同 E4 |
| E7 | 级联关系在代码上是确定的：`check_base_main_current` 在 `main_head` 为空时返回 `main_head_unknown`；`merge_tree_conflicts` 见 `not main_head` 直接 `available=False`，于是 `check_merge_tree_clean` 报 `merge_tree_unavailable` | `merge_queue.py:181-186`、`:193-196`、`:215-228` |
| E8 | `merge_tree_unavailable` 的证据里只有 `{command, main_head}`，**没有 rc / stderr**；真实原因只进 logger | `merge_queue.py:225-228` vs `:211`（`logger.warning(... rc=%s stderr=%s)`） |
| E9 | preflight 失败即 `status=failed`（终态）+ `close_reason=preflight_failed`，**无**可重试性区分 | `merge_queue.py:884-888` |
| E10 | `requeue` 已存在：仅接受 failed → `queued`，清空 `failure_reasons/stale/close_reason`，bump version | `merge_queue.py:940-990` |
| E11 | `close_if_live` 已存在：幂等自动收口，CAS 冲突重读重试（`max_attempts=3`），返回 closed/already/missing/conflict 四态 | `lane.py:335-380` |
| E12 | `LANE_STATUSES = (open, active, verifying, merging, merged, closed, abandoned)`，**无 blocked**；迁移表见 `ALLOWED_STATUS_TRANSITIONS`（`verifying→active` 允许，用于回退） | `lane.py:33-48` |
| E13 | `_assert_unique` 已在同一 flock 内挡：同 branch、同 worktree、同 goal 的第二条 main lane | `lane.py:461-470`；`tests/unit/test_lane_store.py` |
| E14 | `create()` 对 `goal_id` **只判非空**（`if not goal_id: raise`），不查 `goals.jsonl` | `lane.py:165-166` |
| E15 | `lane_open` 无 paths 重叠检测；`_inflight_note()` 只给通用提示 | `tools_lane.py:197-198`；`lane.py` 全文件无 `overlap` 命中 |
| E16 | 唯一非终态 lane `lane-a4e7865d` 停在 `verifying`，`last_activity=2026-11-11T17:12:32+08:00`，至取数时已 **≈2.75 天**未动；`closing_since=2026-11-11T17:12:30` | `lanes.jsonl` |
| E17 | 4 条 lane 的 `owner_session_id` 为空串 → 无归属可追 | 同上 |
| E18 | `git worktree list` 共 100 条：main 1 + `.worktrees/` 68 + `.releases/` 21 + 其他 10；**68 条中 22 条 `git status --porcelain` 非空** | 实测（附录 A 脚本） |
| E19 | 9 条 lane 的 `goal_id` 不在 `goals.jsonl`：3 条探针/诊断（`GOAL-probe-mq-availability-20261105`、`GOAL-SELFTEST`、`diagnostic-nonexistent-goal-20261107`）+ 1 条 `GOAL-20261110-770a4230`（merged）+ **5 条 `task-github-ci-hermetic-20261110`（均 merged）** | 交叉比对 `goals.jsonl` 的 `id` 字段 |
| E20 | 全仓无 lane 回收/巡检实现：`grep -rn 'reap|reclaimer|sweep' src/llm_loop` 仅命中 web 的 `human_turn_queue._reap_stale_claims_locked` 与 `queue_recovery._alive`，与 lane 无关 | 实测 |
| E21 | 既有「超时≠死亡」的正确先例：`queue_recovery` 的 `_alive(sid)` 为**注入谓词**，能力缺失时**保守跳过**，绝不把「探不到」判成「已死」 | `web/queue_recovery.py`（recovery 段） |
| E22 | 现有 34 项 failed 中 `base_stale` 17 项：`note_main_advanced` 只标 **queued** 项 stale，已 failed 的项不会被告知「main 已前进，可重投」 | `merge_queue.py:908` 区段 |

---

## 2. 对上轮判断的修正（自我拷问产物，逐条给反证）

本节存在的意义：上轮回复里有 6 处判断在核对源码/账本后被推翻。设计书若沿用这些判断，会做出错误的实施项。

| # | 上轮判断 | 反证 | 修正 |
|---|---|---|---|
| C1 | 「62 行 vs 61 条说明 CAS 在真实路径生效」 | 重复行是 `lane-selftest-guard`（自检 lane），是测试残留而非并发双写 | **撤回**。CAS 有效性由 `tests/unit/test_lane_store.py` + `close_if_live` 的 conflict 四态证明，不由该重复行证明 |
| C2 | 「环境类失败 14/34，砍掉可省 14 次返工」 | `main_head_unknown` 与 `merge_tree_unavailable` 100% 共现且代码上是级联（E7） | 改为 **7 项**，且修一处、两码同消 |
| C3 | 「非终态超 TTL 自动转 blocked」 | 账本无 blocked 状态；加状态要动迁移表 + 收口计时 + Board + push 门 | 改为 **事件标疑 + 确证后 close(abandoned)**；加 blocked 列入 §10 未决 |
| C4 | 「凭证分级复用是待做项」 | `assess_rebase_replay`（EVO-20261111-c273f61c）已实现纯 replay + 路径不相交判据（`merge_queue.py:467` 判定、`:571-574` 签发前 fail-closed 校验），并由 `tests/unit/test_merge_queue_verify_replay.py` 覆盖 | 改为 **已实现**；真缺口是「失败回执不告诉人这一步」 |
| C5 | 「同 goal 同分支前缀硬拦」 | `_assert_unique` 已挡 branch/worktree/同 goal main 1:1；同一 goal 下多条 **sub** lane 共享前缀是 v1 的合法设计 | **撤回**。硬拦会切断合法的多子 lane 并行 |
| C6 | 「goal 存在性硬拦」 | 现存 9 条 lane 命中（E19），其中 **6 条是已合并的真实 lane**；且 `goals.jsonl` 可能被轮转/裁剪，缺席≠从未存在 | 改为 **默认告警 `goal_unknown`**，配置项 `lane_require_goal=true` 时才硬拒 |

---

## 3. 需求（R1–R5，每条给可机检验收断言）

### R1 失败可诊断

- **现状**：E8 —— 最贵的失败（`merge_tree_unavailable`）在账本里只剩一个码，真相在 `logger.warning`；E9 —— 所有失败同落一个终态桶。
- **需求**：任何 preflight 失败都必须能回答三个问题：**主因是哪个机检**、**能不能自动重试**、**为什么（rc/stderr 摘要）**。
- **验收断言**：
  - R1-a 对任一项 failed 记录，能从账本单独算出 `primary_check`/`primary_reason`/`failure_class`，无需读日志。
  - R1-b `merge_tree_unavailable` 与 `main_head_unknown` 的证据中必含 `rc` 与 `stderr_tail`（≤200 字符）。
  - R1-c `failure_class` 取值域封闭为 `{env_transient, env_config, needs_rebase, verify_missing, true_conflict, needs_serialize}`（与 §4.2 表一一对应），未知码**必须**落 `env_config` 或拒绝，不得落「其他」。

### R2 生命周期收尾

- **现状**：E16 一条 lane 卡 2.75 天；E18 100 条 worktree 里 22 条带未提交改动；E20 无巡检；E17 4 条无 owner。
- **需求**：系统必须能**发现**长期不动的 lane，并在**判据确证**时收口与回收 worktree；证据不足时只标疑、不改状态、不删目录。
- **验收断言**：
  - R2-a `dry_run=true` 时对 `lanes.jsonl` / 工作树**零写**（sha256 与 `git worktree list` 前后一致）。
  - R2-b 干净可回收的 lane → 收口 `abandoned` + `git worktree remove`（不带 `--force`）+ 追加 `lane.reaped` 事件含判据快照。
  - R2-c 脏 worktree → 只追加 `lane.stale_suspected`，状态不变、目录不动，回执列路径与脏文件数。
  - R2-d liveness 谓词不可用（无注入能力）→ 输出 `liveness_unavailable`，**一律不收口**。
  - R2-e 已被他人并发改动 → 走 `close_if_live` 的 `conflict` 四态并原样回执，不静默重试到成功。

### R3 重投自动化（默认关）

- **现状**：E10 `requeue` 存在但需人工；E22 main 前进后 failed 项无人告知。
- **需求**：对**环境类**失败按退避自动重投，其余类别只给建议不动手。
- **验收断言**：
  - R3-a 仅 `failure_class ∈ {env_transient}` 自动重投；`true_conflict` 永不自动重投（否则掩盖真冲突）。
  - R3-b 同一 queue_id 最多自动重投 3 次，退避 60s/300s/900s；超限转 `needs_human=true` 并停止。
  - R3-c 每次自动重投追加 `queue.auto_requeued` 事件，含 attempt/backoff/failure_class。
  - R3-d 开关 `lane_auto_retry_enabled` 默认 `false`；关闭时 `lane_reap` 只输出建议不调用 `requeue`。

### R4 开门校验（告警级）

- **现状**：E14 只判非空；E15 无重叠检测；E13 已挡的三类是硬拦。
- **需求**：开门时把「你要踩的坑」提前说清，但**不阻断**已经合法的用法。
- **验收断言**：
  - R4-a 声明 paths 与任一非终态 lane 交叉 → 回执含 `overlap_warning: [{lane_id, shared_paths}]`，**登记成功**。
  - R4-b `goal_id` 不在 `goals.jsonl` → 回执含 `goal_unknown: true` + 提示，**登记成功**；`lane_require_goal=true` 时才 `reason_code=goal_not_found` 失败。
  - R4-c 上述两项均不改 `create()` 的返回值类型，只在回执侧附加。

### R5 失败可读（人能一眼分诊）

- **现状**：`coordination_status` 有 lane 段但无队列失败分类；分诊要逐条读 `last_preflight.checks`。
- **需求**：一个只读视图，把 34 项 failed 压成「该重投 / 该 rebase / 该补凭证 / 该人看」四类计数 + 每类前 3 条。
- **验收断言**：
  - R5-a 调用前后 `merge_queue.jsonl` sha256 不变（零写）。
  - R5-b 四类计数之和 == 当期 failed 总数（不漏项）。
  - R5-c 每条给出**可直接粘贴**的下一步命令（requeue / 补凭证 / 人工判定）。

---

## 4. 设计

### 4.1 三条硬裁决（先定不可协商的部分）

**D1 超时 ≠ 死亡。** 时间只用于**筛候选**，不用于判定死亡。判死必须由一个**注入的 liveness 谓词**回答 `dead`；谓词缺失或返回 `unknown` 时，一律不收口（R2-d）。依据是既有先例 E21：`queue_recovery._alive` 在能力缺失时保守跳过，绝不把「探不到」当成「已死」。

**D2 收口不等于清理。** 这与队列侧已写死的既有不变量一致：`merge_queue` 模块 docstring 明确写着「绝不静默删除、绝不直接判 failed」（`merge_queue.py:32`）——本期只是把同一条纪律搬到 lane 侧。 收口只写状态（可追溯、带 reason、可被 Board 看到）；删除目录是**独立的第二步**，且只对 `git status --porcelain` 为空的树执行。**不用 `--force`**，不删分支。依据是 E18：68 条 lane worktree 中 22 条有未提交改动——任何「按时间自动回收」都会毁真实产物。

**D3 分类是读时纯函数，不是新状态。** `failure_class` 不进新账本、不进新文件：落账时写进既有 queue entry 的字段（首次可查询），老记录由读时现算兼容。唯一必须持久化的是**重投计数**（否则每次都是第一次，会无限重投），它也只落在既有 entry 的同名字段上。

### 4.2 R1：失败分类

**函数签名（新增，纯函数，零 I/O）**

```python
def classify_failure(entry: dict) -> dict:
    """返回 {primary_check, primary_reason, failure_class, retryable,
             cascade_of, evidence_hint}。纯读，不写盘。"""
```

**主因判定规则**：按机检顺序 `base_main_current → merge_tree_clean → paths_disjoint → verify_covers_base` 取**第一个** verdict≠pass 的项为主因（与 §1 E4 口径一致，使历史数据可回算）。

**分类表（取值域封闭）**

| 主因码 | failure_class | retryable | 处置 |
|---|---|---|---|
| `base_stale` | `needs_rebase` | 否（rebase 需人或模型动作） | 回执给「rebase 后重投」命令 |
| `main_head_unknown`（`rc∈{空 repo_root, 路径不存在}`） | `env_config` | 否 | 改配置；重投无意义 |
| `main_head_unknown`（超时/锁/临时失败） | `env_transient` | **是** | 退避重投 |
| `merge_tree_unavailable`（同批有 `main_head_unknown`） | 继承主因 | 否 | 标 `cascade_of=main_head_unknown`，**不重复计数** |
| `merge_tree_unavailable`（独立） | `env_transient` | 是 | 退避重投 |
| `verify_required` / `verify_stale` / `verify_invalid` / `verify_expired` | `verify_missing` | 否 | 给 carryover 或全量重验命令（§2 C4） |
| `verify_layer_not_enabled` | `env_config` | 否 | 必须人开签发层，补凭证无效 |
| `merge_conflict` | `true_conflict` | **永不** | 转 `needs_human` |
| `paths_overlap` | `needs_serialize` | 否 | 等对方或改 paths |
| 未知码 | `env_config` | 否 | fail-closed（RULE-AI-30），并记 `unknown_reason_code` |

**证据补齐**：`probe_main_head()` 增加 `probe_main_head_detail() -> (head, rc, stderr)`；`check_merge_tree_clean` 的 evidence 增 `rc` 与 `stderr_tail`（截 200 字符）。这是 R1-b 的落点，也是让 `env_config` 与 `env_transient` 可区分的前提——**没有 rc/stderr，这一层分类只能靠猜，属不可实现**。

**落账字段**（写进 queue entry，向后兼容）：

```json
{"failure_class": "env_transient", "primary_check": "base_main_current",
 "primary_reason": "main_head_unknown", "cascade_of": "", "evidence_hint": "rc=-1 stderr_tail=..."}
```

### 4.3 R2：lane 收尾（`lane_reap`）

**新增一个工具**（不改既有签名）：

```
lane_reap(dry_run=true, ttl_hours=168, limit=20)
```

收口状态**固定为 `abandoned`**，不做成参数：`close_if_live` 接受 `merged/closed/abandoned` 三种终态，把状态开放成入参等于允许 reaper 声称「已合并」——这是它不该有的权力（§7 Q12）。

**判据三元组（全部成立才收口）**

```
idle_ttl    : now - max(last_activity, closing_since) > ttl_hours
liveness    : probe(session_id) == dead          # 注入谓词；unknown/unavailable ⇒ 停
tree_state  : git -C <worktree> status --porcelain == ""   # 仅对 clean 执行 remove
```

**liveness 探针优先级**（从强到弱，取第一个可用的）：

1. `session_registry.is_running(owner_session_id)` → `alive|dead`（权威）
2. `lane_events.jsonl` 中该 lane 最近事件时间在 `ttl` 内 → `alive`（弱证据，只能证明“可能活”不能证明死）
3. 无任何可用来源 → `unknown` → **不收口**

注意第 2 条只能用于**否决**（当作活着），不能用于判定死亡；判定死亡只认第 1 条。这是 D1 的直接推论。

**输出三态**

| 态 | 条件 | 动作 |
|---|---|---|
| `conclusive` | 三判据全成立 | `close_if_live(status="abandoned", reason="reaped:idle=<h>h;liveness=dead;tree=clean")` → 成功后 `git worktree remove <path>`（无 `--force`） |
| `suspect` | 超时但 liveness 非 dead，或树脏 | 只追加 `lane.stale_suspected` 事件，**状态与目录都不动** |
| `unavailable` | 无 liveness 谓词 | 回执 `liveness_unavailable`，**零动作** |

**顺序为什么是「先收口、后删目录」**：反过来的坏结局更严重——目录删了但 lane 还在非终态，等于「在跑的 lane 被人抽走了工作树」，且不可逆；先收口则即使 `remove` 失败，最强后果只是「lane 已 abandoned、目录残留」，可由人工清理，且账本仍可解释。因此 `remove` 失败**不回滚**收口，只把事实写进事件（`worktree_kept` + 原因）。

**不做全量扫描**：先按 `idle_ttl` 过滤出候选（当前数据量下 1 条），只对候选跑 `git status`。100 条 worktree × `status` 是几十秒级操作，不能放进读路径。

**并发安全**：全部写操作走 `LaneStore` 的 flock + `close_if_live` 的 CAS 重试；`conflict` 四态原样回执（R2-e），不循环到成功——因为 conflict 意味着有别的写者在动它，此时「成功」是覆盖别人的判断。

### 4.4 R3：自动重投（默认关）

```
if not lane_auto_retry_enabled: 只输出建议
cls = classify_failure(entry)
if not cls["retryable"]: 只输出建议
attempt = entry.get("auto_retry_attempt", 0)
if attempt >= 3: entry["needs_human"] = True; 停
next_retry_at = now + [60, 300, 900][attempt]      # 秒；由巡检触发，不 sleep
requeue(lane_id=..., expected_version=...,
        head_sha=..., base_main_sha=<当前 main head>)
# requeue 内部读旧 entry 的 auto_retry_attempt → 写回 attempt+1；
# 不新增 kwarg，因此签名不变（§5.3）
```

**重投的判据是 `next_retry_at` 已到，不是「立刻」**：`lane_reap` 只挑 `next_retry_at <= now` 的项，所以重投节奏由数据驱动，不需要 sleep 也不占线程。

**必须显式保留 `auto_retry_attempt`**：`requeue` 会清空 `failure_reasons/stale/close_reason`（E10），若连 attempt 一起清，则每次重投都是第一次 → 无限重投。实现上 `requeue` 不清该字段，并在 `auto_requeued` 事件里带 attempt。

**为什么 `true_conflict` 永不自动重投**：冲突重投的唯一效果是把「真冲突」洗成「偶发失败」，让人看不到需要改方案的事实。

### 4.5 R4：开门预检（零签名变更的关键设计）

不在 `create()` 里塞返回值（会污染账本或改签名），而是**新增只读预检**：

```python
def precheck(self, *, branch, worktree, goal_id, paths) -> dict:
    """纯读：{"overlap_warning":[{lane_id, shared_paths}], "goal_unknown": bool,
              "goal_id": ...}。不写账本、不建目录。"""
```

`run_lane_open` 流程改为：`precheck()` → `create()` → 回执合并 `precheck` 的告警。

- 重叠复用 `task_claim.overlapping_paths`（v1 E8 已证存在，队列侧 `check_paths_disjoint` 已在用同一函数且**已返回对端 `lane_id`**）——这里零新算法。
- `goal_unknown` 默认只告警（§2 C6），`lane_require_goal=true` 时 `create()` 前硬拒。

### 4.6 R5：分诊视图

`coordination_status` 增 `merge_queue` 段（与 v1 §2.2「复用并扩展」同策略，只加字段）：

```json
{"failed_total": 34,
 "by_class": {"needs_rebase": 17, "env_config": 7, "verify_missing": 10, "true_conflict": 0},
 "undetermined": {"env_config_vs_transient": 7},
 "samples": {"needs_rebase": [{"queue_id": "...", "next": "lane_queue_submit ..."}], "...": []},
 "self_check": {"sum_matches_total": true}}
```

`sum_matches_total` 是**给读的人看的自检**：四类之和必须等于 failed 总数（R5-b），不等就说明分类漏项，属于本设计自身的缺陷暴露，不做静默补齐。

### 4.7 明确不做（防止范围蔓延）

| 不做 | 理由 |
|---|---|
| lane 自动 rebase / 自动解冲突 | 冲突解决是语义判断，必须人或模型做；自动化会把「绿但错」变成默认结果 |
| 自动 push / 自动合并 | 归 v1 的 S1/S2 授权，本设计不碰 |
| `.releases`（21 条）与历史 worktree 的批量清扫 | 与 lane 生命周期无关，属独立议题（避免混入不可逆删除） |
| 常驻 reaper 进程 | 需常驻授权（仅真人 run 可签发）；本期用「显式工具 + 读路径提示」 |
| `blocked` 状态 | 见 §2 C3 与 §10 U1 |

---

## 5. 契约变更清单（逐条可核）

### 5.1 新增（4 函数 + 1 工具 + 1 配置组）

| 类型 | 名称 | 位置 | 备注 |
|---|---|---|---|
| 函数 | `classify_failure(entry)` | `introspection/merge_queue.py` | 纯函数，零 I/O |
| 函数 | `probe_main_head_detail()` | 同上 | 返回 `(head, rc, stderr)` |
| 函数 | `LaneStore.precheck(...)` | `introspection/lane.py` | 纯读 |
| 函数 | `reap_candidates(...)` | `introspection/lane.py` | 纯读，返回三态候选 |
| 工具 | `lane_reap` | `introspection/tools_lane.py` + registry | 默认 `dry_run=true` |
| 配置 | `lane_reaper_ttl_hours=168` / `lane_reaper_enabled=false` / `lane_auto_retry_enabled=false` / `lane_require_goal=false` | 运行时配置 | 全部默认关或保守 |

### 5.2 新增字段（均落在既有记录内，不新建文件）

| 账本 | 字段 | 语义 |
|---|---|---|
| `merge_queue.jsonl` | `failure_class` / `primary_check` / `primary_reason` / `cascade_of` / `evidence_hint` | 首次落账写入；老记录读时现算 |
| `merge_queue.jsonl` | `auto_retry_attempt` / `next_retry_at` / `needs_human` | 重投计数，`requeue` **不得清空** |
| `lane_events.jsonl` | `lane.stale_suspected` / `lane.reaped` / `queue.auto_requeued` | 三个新事件名 |

### 5.3 明确零变更（RULE-AI-24 防退化）

- `LaneStore.create/update/close/close_if_live` **签名与语义不变**；`lanes.jsonl` **schema 不变**（不加 `blocked`、不加 `warnings`）。
- `MergeQueue.submit/run_preflight/requeue/request_merge/abort` 签名不变。
- S1 十条机检的判定条件**一条不改**（本期不碰合并门禁强度）。
- 既有 46 条 merged / 6 条 closed / 8 条 abandoned 记录不改写（只追加事件）。

---

## 6. 验收（每条门槛都必须实测「应拦输入」，RULE-AI-35）

「实现了」不算通过，**必须出现预期中的拦截/降级**才算。下表左列是断言，中列是**必须被拦的输入**，右列是期望回执。

| # | 应拦输入 | 期望回执 | 反例（出现即未生效） |
|---|---|---|---|
| R1-b | `repo_root` 置空后 `lane_queue_submit` | `primary_reason=main_head_unknown` + `evidence_hint` 含 `rc=-1` 与 `stderr_tail` 非空 | `evidence_hint` 为空或仍只有 `{command, main_head}` |
| R1-c | 手工注入 `failure_reasons=["no_such_code"]` 的 entry | `failure_class=env_config` + `unknown_reason_code=no_such_code` | 落到 `"other"` 或抛异常 |
| R1-级联 | 同时含 `main_head_unknown` + `merge_tree_unavailable` | `cascade_of=main_head_unknown`，`by_class` 只计 **1** 项 | `by_class` 里两码各计一次（复现 §1 E5 的重复计数） |
| R2-a | `lane_reap(dry_run=true)` 对现存 61 条 lane | `lanes.jsonl` sha256 前后一致 + `git worktree list` 条数不变 | 任一变化 |
| R2-c | 对 22 条脏 worktree 之一做 `dry_run=false` | 回执 `suspect` + `tree_dirty=true` + 列出脏文件；**目录仍在、状态不变** | 目录被删，或 lane 状态变成 abandoned |
| R2-d | 不注入 liveness 谓词时 `dry_run=false` | `liveness_unavailable`，零收口、零删除 | 以「超时」为由收口 |
| R3-a | 造一条 `merge_conflict` 的 failed 项，开 `lane_auto_retry_enabled=true` | 不调用 `requeue`，回执 `true_conflict` + `needs_human=true` | 被重投（真冲突被洗成偶发失败） |
| R3-b | 对同一项连续放行 4 次重投 | 第 4 次停止并回执 `retry_exhausted`；`auto_retry_attempt` 单调递增不被清零 | 计数回到 0 / 无限重投 |
| R4-a | 用与 `lane-a4e7865d` 重叠的 paths 开新 lane | 回执 `overlap_warning` 含该 `lane_id` 与 `shared_paths`，且**登记成功** | 登记失败（过度阻断）或告警缺失 |
| R4-b | `goal_require=true` 时用 `diagnostic-nonexistent-goal-20261107` 开门 | `reason_code=goal_not_found` 失败；默认配置下**成功**且带 `goal_unknown` | 默认配置下也拒（切断 §1 E19 那 6 条真实用法） |
| R5-a | 调 `coordination_status` 前后比对 sha256 | `merge_queue.jsonl` 不变 | 视图写盘 |
| R5-b | 当期 34 项 failed | `sum(by_class.values()) == 34` 且 `sum_matches_total=true` | 之和 ≠ 总数 |

**回归闸**：`tests/unit/test_lane_store.py`、`test_lane_tools.py`、`test_lane_close_governance.py`、`test_merge_queue.py`、`test_merge_queue_verify_replay.py`、`test_lane_gate.py` 必须全绿；新增用例不得改动既有断言（RULE-AI-24）。

---

## 7. 边界与失败模式（拷问记录）

| # | 问题 | 回答 |
|---|---|---|
| Q1 | 收口成功但 `worktree remove` 失败怎么办？ | 不回滚收口。追加 `lane.reaped{worktree_kept:true, why:...}`，回执 `worktree_kept`。理由见 §4.3 顺序论证：残留目录可人工清，反向不可逆。 |
| Q2 | 两个 `lane_reap` 并发跑？ | 写路径全走 flock + `close_if_live` CAS；后者返回 `already`（幂等）或 `conflict`（有别人在动）。`conflict` 不重试到成功——那会覆盖别人的判断。 |
| Q3 | owner 其实活着，只是 TTL 到了？ | `liveness` 谓词返回 `alive` ⇒ 落 `suspect` 只标疑。TTL 只筛候选，不判死（D1）。 |
| Q4 | lane 停在 `merging` 而队列已 merged（2026-11-09 事故形态）？ | 已有 `close_if_live` 覆盖该场景（lane.py:343-353 的 docstring 就是这个事故）。本设计不重复实现，只在 `lane_reap` 里优先处理该形态。 |
| Q5 | `main_head_unknown` 的真相是 `repo_root` 没配？ | `probe_main_head_detail()` 的 `rc/stderr` 区分：配置类 → `env_config`（不重投）；超时/锁 → `env_transient`（重投）。**没有 rc/stderr 就无法区分**，所以 R1-b 是 R1-c 的前置，不可拆。 |
| Q6 | 分类遇到没见过的码？ | `env_config` + `unknown_reason_code`，fail-closed。不许新增「其他」桶——那会让未来所有新码隐形。 |
| Q7 | 老记录没有 `failure_class`？ | 读时现算（D3）。34 条历史项实测 100% 有 `last_preflight.checks`，可回算；若无 checks 则 `insufficient_evidence`，不猜。 |
| Q8 | `requeue` 清空 `failure_reasons`，会不会连重投计数一起清？ | 会，如果实现时不小心。**这是本设计最容易踩的一个坑**：必须在 `requeue` 里白名单式保留 `auto_retry_attempt`，并由 R3-b 的用例守住。 |
| Q9 | `verify_missing` 能不能自动补 carryover？ | 不做。carryover 需要判断「纯 replay + 路径不相交」且要人确认重验范围，自动签发等于自己给自己发通行证。只给命令。 |
| Q10 | 分类依赖 `last_preflight`，缺失时怎么办？ | `insufficient_evidence` + `needs_human`，不按「无失败」处理（RULE-AI-30）。 |
| Q11 | 时间怎么存？ | 一律 `system_local_now()` 绝对时间戳；不存「已空闲 3 天」这类相对量（相对量一旦落盘即失真）。 |
| Q12 | reaper 需不需要额外授权？ | 默认 `dry_run=true` 且 `lane_reaper_enabled=false`；真删只在「三判据全成立 + clean 树」时发生。它**不能**改 `head_sha`/`verify_ref`/`paths`，只能 `close(abandoned)`。 |
| Q13 | 22 条脏 worktree 是不是都被 reaper 认定为「有主」？ | 不是。脏只让它们不进 `conclusive`，不构成归属证明。它们的清算在 §10 U5，本期不碰。 |
| Q14 | 这套东西会不会自己变成第 5 个需要维护的账本？ | 不会：零新文件、零新终态。新增的只有 4 个函数、1 个工具、6 个字段、3 个事件名。 |

---

## 8. 实施计划（4 批，每批独立可验）

| 批 | 内容 | 改动面 | 验证 | 风险 |
|---|---|---|---|---|
| **P1 诊断性** | `classify_failure` + `probe_main_head_detail` + evidence 补 rc/stderr + `coordination_status` 的 `merge_queue` 段 | 2 函数 + 2 处 evidence + 1 视图字段 | §6 R1-b/c/级联、R5-a/b | 低（零行为变更，纯读） |
| **P2 收尾（默认 dry_run）** | `reap_candidates` + `lane_reap` + 3 个事件名 | 1 函数 + 1 工具 + registry | §6 R2-a/c/d | 中（唯一涉及删除，靠 dry_run + clean 门槛） |
| **P3 重投（默认关）** | `auto_retry_attempt` 保留 + 退避 + `queue.auto_requeued` | `requeue` 内部 + 配置 | §6 R3-a/b | 中（Q8 是主要陷坑） |
| **P4 开门告警** | `precheck()` + `run_lane_open` 合并回执 | 1 函数 + 1 调用点 | §6 R4-a/b | 低（只加回执字段） |

顺序理由：P1 先把「看不见」变成「看得见」，后面三批的判断都靠它；P2 与 P3 都依赖 P1 的 `failure_class`/liveness 结论，不能并行；P4 独立，可提前也可推后。

---

## 9. 回滚

- 全部为**追加式**改动：事件是 append-only，字段是新增，无破坏性迁移 → 回滚只需关闭配置（`lane_reaper_enabled=false` / `lane_auto_retry_enabled=false` / `lane_require_goal=false`）并 revert 代码，账本无需回滚。
- P2 的删除动作**不可逆**，但范围受限：只删 `clean` 且 `idle > ttl_hours` 的 lane worktree，且分支保留。事故后可用 `git worktree add <path> <branch>` 原样恢复工作树（内容在分支上）。
- 任何一批出现「被拦输入没被拦住」（§6 反例列），按 RULE-AI-37 从**动作层**修（判据/证据），不在文档层打补丁。

---

## 10. 未决事项（不装作已经有答案）

| # | 未决 | 为什么现在不定 |
|---|---|---|
| U1 | 是否引入 `blocked` 状态 | 需要「暂停但可续」的真实需求出现才加；加了要同步 4 处（迁移表/收口计时/Board/push 门），当前无证据表明必要（§2 C3） |
| U2 | `goals.jsonl` 会不会被轮转/裁剪 | 若会，则「goal 存在性」永远只能是告警不能是硬拦；需先确认 goal 账本的保留策略 |
| U3 | **lane 的 liveness 权威源缺失** | **已核（2026-11-14）：不存在可用权威源。** `BackgroundRunner.is_running`（`core/loop/runner.py:405`）只查进程内 `self._registry`，同处注释明示同步 run 走 `engine._sync_active`、不在 registry；`web/queue_recovery.py:176` 的 `_alive` 同样取进程内 handle；`data/audit/` 下无 session/run/lease 账本（`ls | grep session\|run\|lease` 无命中）。失效条件：跨进程重启、CLI 会话、DSH 会话、同步 run、`owner_session_id` 为空。**结论：`lane_reap` 自备谓词必然把「重启后仍活」误判为死亡，R2 改为「谓词注入 + 缺失即不收口」。** |
| U4 | `verify_missing` 7 项是否值得批量补凭证 | **已核（2026-11-14）：0 项值得。** 10 项 verify 类失败（7×`verify_required` + 3×`verify_stale`）对应 lane 状态全为 `merged`(9) 或 `abandoned`(1)，无一条在途；对已合并 lane 补签只增加账本噪音。该批归 R5「该补凭证」桶仅为保证计数闭合，不做批量补签。 |
| U5 | 22 条脏 worktree 的归属清算 | 属于 v1 遗留的历史债，与本设计正交；批量删不可逆，需独立方案与人工确认 |
| U6 | 谁来触发 `lane_reap` | 不做常驻进程（需常驻授权）；候选触发点：宿主收尾流程、web tick、人工显式调用。选哪个未定 |

### 10.1 检验结论对方案的影响（2026-11-14 实测）

**U3 使 P2 从「可实现」降为「前置条件缺失」。** 原 §4.3 假设 `lane_reap` 能自备 liveness 谓词；实测证明当前架构下任何自备谓词都会把「跨进程重启后仍活」误判为死亡，进而删除仍在运行的 lane。据此调整：

| 原设计 | 修订 | 理由 |
|---|---|---|
| `lane_reap` 内部按优先级自选 liveness 探针 | **改为注入** `alive=` 谓词（与 `queue_recovery._alive` 同构）；不传 → `liveness_unavailable` | 自选探针在跨进程场景必然误判（U3） |
| P2 本轮实现收口（`close` + `worktree remove`） | **本轮不实现收口**，只保留设计；先落地跨进程 liveness 基础设施（会话心跳账本或 lease），再开 P2 | 无权威谓词时收口即 D1 禁止项 |
| P2 验收「能收口 dead lane」 | P2 验收改为「能给出候选 + 缺哪份证据」，且必须先实测「存活 lane 不被收口」 | RULE-AI-35：先证「不误杀」，再谈「能杀」 |

**U4 使「批量补凭证」不再是一个待办。** 10 项全部指向已合并/已放弃的 lane；R5 保留该桶（否则四类不闭合），但语义是「历史项，仅需核对」。

**实现期修正（已落代码，与 §4.2 表的差异登记）**：

| 设计书写法 | 实现 | 原因 |
|---|---|---|
| `merge_tree_unavailable` 独立 → `env_transient` | 先看 stderr：能归类则尊重 stderr（配置错→`env_config`），仅 `stderr_unclassified` 落 `env_transient` | 纯按表会把「git 版本不支持」误当临时失败反复重投 |
| stderr 关键词含 `lock` | 收窄为 `index.lock` / `lock file` / `could not lock` | `lock` 会误命中 `blocked`，把人工阻塞判成可重投 |
| `main_head_unknown` 无 rc 时的归类未定义 | 落 `env_config` + `evidence_hint=rc_missing` | fail-closed：不确定不得当成可重投 |
| 落账字段只在失败时写 | 失败时写；**转 pass 时显式清除** 并重置 `auto_retry_attempt` | 残留字段会让读侧把上次失败当成当前事实 |

**实施进度**：P1（R1 诊断 + R5 视图）已实现并通过 19 项新验收测试；P2/P3/P4 未实现，P2 依赖 U3 基础设施，P3 依赖 P2 的 `lane_dead` 类，P4 可独立先做。

---

## 附录 A. 事实复现（一次性脚本先落盘再执行，RULE-AI-36）

```bash
cat > .tmp-analysis/lane_facts.py <<'PY'
import json, collections
from pathlib import Path
D = Path('data/audit')
rd = lambda p: [json.loads(l) for l in (D/p).read_text(encoding='utf-8').splitlines() if l.strip()]
lanes = {r['lane_id']: r for r in rd('lanes.jsonl')}
print('lanes', len(lanes), collections.Counter(r['status'] for r in lanes.values()))
row = {r['queue_id']: r for r in rd('merge_queue.jsonl')}
failed = [r for r in row.values() if r.get('status') == 'failed']
order = ['base_main_current', 'merge_tree_clean', 'paths_disjoint', 'verify_covers_base']
prim = collections.Counter()
for r in failed:
    checks = (r.get('last_preflight') or {}).get('checks') or []
    for name in order:
        c = next((x for x in checks if x.get('check') == name), None)
        if c and c.get('verdict') != 'pass':
            prim[f"{name}/{c.get('reason_code')}"] += 1
            break
print('failed', len(failed), dict(prim))
print('dupe', [k for k, v in collections.Counter(r['lane_id'] for r in rd('lanes.jsonl')).items() if v > 1])
PY
python3 .tmp-analysis/lane_facts.py
```

实测输出（2026-11-14 11:29）：

```
lanes 61 {'closed': 6, 'abandoned': 8, 'merged': 46, 'verifying': 1}
failed 34 {'base_main_current/base_stale': 17, 'base_main_current/main_head_unknown': 7,
           'verify_covers_base/verify_required': 7, 'verify_covers_base/verify_stale': 3}
dupe ['lane-selftest-guard']
```

worktree 规模（`git worktree list --porcelain` 解析）：100 条 = main 1 + `.worktrees/` 68 + `.releases/` 21 + 其他 10；68 条 `.worktrees/` 中 22 条 `status --porcelain` 非空。

---

## 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-14 | v1 草案 | 初稿；含 §2 对上一轮口头判断的 6 处自我修正 |
| 2026-11-14 | v2 | 填入 U3/U4 实测结论（U3 无权威 liveness 源、U4 0 项值得补签）；新增 §10.1：P2 降级为「谓词注入 + 本轮不实现收口」，登记 4 处实现期修正；P1 已实现并通过 19 项验收测试 |
