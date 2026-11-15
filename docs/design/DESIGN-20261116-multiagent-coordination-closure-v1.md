# LFL 多 Agent 协作优化：队列降噪、冲突前置、Goal 收口与契约协调——需求与实现设计 v1.2

- 状态: **DRAFT-待复审**（v1.2 已并入 GPT-6 主统筹 2026-11-16 01:24 REVISE 全部意见 P0-1/P0-2/P1-1..P1-6/P2-1/P2-2，逐项落点与验证见 §16；复审 PASS 前不进入 M1+ 实施）
- 日期: 2026-11-16（宿主本地时区）
- 本文件: docs/design/DESIGN-20261116-multiagent-coordination-closure-v1.md（设计正本 v1）
- Lane: lane-d6ceb9dd / Goal: GOAL-20261116-d83c9c53 / 基线: origin/main 9e6b438cc814844fde49b519824cd359b5a27cdc

## 0. 权威来源与证据声明

1. 本正本的裁决真值 = 用户 2026-11-16 授权消息中的「设计硬裁决 M1-M4」（经反例拷问的 v1.1 决策摘要）。
2. 源码/账本事实 = 本会话独立核验：主代理直读 + 3 个只读调查子代理（A=lane 锁/冲突、B=merge queue 来源完整性、C=goal/契约/安全边界），子代理全程零写入，主代理对关键结论逐条交叉核验一致。
3. **未读取 ChatGPT 沙盒文件**（不可达）；用户消息中的裁决摘要即上游 v1.1 的权威投影，本正本据其+仓库源码重新生成，不经由任何沙盒拷贝。
4. 上游链: DESIGN-20261105-main-lane-parallel-delivery-v1（lane 并行交付）、DESIGN-20261114-lane-lifecycle-and-failure-classification-v1（R1-c 失败分类/lane_reap 三判据）、DESIGN-20261115-trusted-shared-workstate-multiagent-v1（P0-1/2/3 跨会话授权边界，NO-GO 项）、DESIGN-20261115-unified-managed-four-service-release-v1（受管发布链）。规则: RULE-AI-24/28/34/35/36；AGENTS.md 准入不对称；docs/DEVELOPMENT_REPAIR_SAFETY.md 六问。
5. v1.2 修订真值 = 用户（GPT-6 主统筹）2026-11-16 01:24 REVISE 审查意见（10 项: P0-1/P0-2/P1-1..P1-6/P2-1/P2-2），逐项落点与验证见 §16；§1 账本计数与 §14 成本数据已按该消息提供的独立实测校正。

## 1. M0 状态快照（2026-11-16 01:07-01:20 实测）

- 主工作树: 脏（未跟踪 docs/DESIGN-20261115-knowledge-self-improvement-loop-v1.md）；main 与 origin/main 分叉 ahead 10 / behind 33 → **禁止直接改 main**，全部产出写入隔离 worktree `.worktrees/multiagent-coord-design-20261116`（分支 docs/multiagent-coordination-closure-20261116）。
- Lane 账本（双口径，v1.2 按 GPT-6 独立实测校正，P1-3）: 本 lane 登记前 69 行 = merged 51 / closed 8 / abandoned 8 / verifying 1 / **active 1**（51+8+8+1+1=69 ✓）；登记 lane-d6ceb9dd 后 70 行 = merged 51 / closed 8 / abandoned 8 / **active 2** / verifying 1（+1=70 ✓）。v1.1 曾误写「唯一在途 lane-a4e7865d」，漏计 active 的 lane-selftest-guard，已删（漏项=数字不闭合的直接原因）。
- 在途 lane 共 3（登记后口径）: lane-a4e7865d（verifying, GOAL-20261111-1e19d24f, paths=scripts/ci_gate.sh+tests/…，与本设计 docs 路径零重叠）、lane-selftest-guard（active, 行 11, **paths=[]**）、lane-d6ceb9dd（本 lane）。lane-selftest-guard 为历史自检 lane，**未经 owner 核验不得自动清理/改判**；enforce_cross_goal 启用后其 paths=[] 按冲突面 unknown 受控处置（§3.2-3），不得长期静默放行。
- Merge queue: 76 行；failed 35 = 历史终态 34 + 活待办 1 + 来源未知 0（97% 噪音，M1 的实证）。
- 旧 Goal GOAL-20261114-474ab491 已 complete，不恢复不覆盖。

## 2. M1 队列降噪：三分展示与来源诚实（P0，GO）

### 2.1 现状证据（代码级）
- `_lane_status_map` [goal_coordination.py:797-821]：lanes.jsonl 读失败 → 返回空 dict（与「账本真空」同形）；坏行静默 continue [813-816]；merge_queue.py 自身读取是 fail-closed 抛错 [1396-1418]，**静默退化仅此一条路径**。
- `_collect_merge_queue` [850-939]：lane_state="" → is_terminal=False [895-898]；「来源未知（lane_id 不存在）」「读失败」「lane 在途」三种情况同形，均落入四桶且 `_queue_next_command` [845-846] 照发可执行命令（如对已 merged lane 发 lane_merge_request）。
- closure_ok = (四桶和 == failed_total) [921-924]：由构造成立（未知类默认 human 桶 [893]），证明「没丢行」不证明「账本完整」；坏行不计入分母仅 note 披露 [883-885,919-920]。
- 实测: `failed=35 闭合=ok(35) 该重投=0 该 rebase=17 该补凭证=11 该人看=7 | 历史=34`——桶计数混入历史终态项，真待办仅 1 条不可见。
- 跨文件快照非事务: lanes.jsonl 与 merge_queue.jsonl 两次裸 open 无锁无版本 [808/876]；宿主自标 `audit_toctou=trusted_host_race_not_closed`；写侧 CAS [merge_queue.py:1493-1500] 承担权威重查。

### 2.2 EARS 需求（双轨: legacy 原口径全保留 + 新增 actionable/来源完整性字段，P1-1）
**A. legacy 轨（原口径完全保留，原有消费者/测试不破）**: `failed_total`、四桶 `buckets`（含历史终态项的原计数口径）、`bucket_sum`、`closure_ok == (bucket_sum == failed_total)`、`terminal_total`、`items[].terminal`、`next_command` 语义与现状逐字段一致；tools_goal.py:382-384 纯透传无需改动；tests/unit/test_merge_queue_failure_class.py 对 legacy 字段的既有断言**不修改、必须继续通过**。
**B. 新增轨（独立字段，不动 legacy 值）**:
- `actionable_total` / `actionable_buckets`: 只收「当前活待办」项的桶计数（历史终态项不进入）。
- `unknown_total`: 来源无法确定的 failed 项计数。
- `source_complete`(bool): lanes.jsonl 可读、无坏行、无重复 lane_id、无无效 status、merge_queue.jsonl 无坏行时为 true；任一不满足为 false（含义=**来源完整性**，≠解析闭合）。
- `parsed_closure_ok`(bool): 可解析部分自洽（每条可归因 failed 恰属 活待办/历史终态/来源未知 之一）。
- `overall_view_ok == source_complete && parsed_closure_ok`: 视图整体可信才为 true；false 时一切计数标注降级、next_command 降级为提示类。
- 新恒等式**只用于 actionable 轨**: `actionable_bucket_sum == failed_total − terminal_total − unknown_total`；legacy `closure_ok` 保持原恒等式原值不变。
- 分类规则: lane_id 在账且终态 → 历史终态（terminal_total）；在账且在途 → 活待办（actionable）；**不在账 / 账本不可读 / 重复 lane_id 冲突状态 / 无效 status / 坏行关联项 → 一律保守归 unknown**（宁可 unknown，不冒充已知）。未知/降级项 next_command 禁止发放 requeue/rebase/merge 等写操作命令，只允许「人工核对账本/权威重查」类提示。
- 默认文本渲染优先三分行: `failed=N | 当前待办=M 历史=K 来源未知=J 坏行=L | 四桶(legacy)…`——三分行在前，legacy 桶行保留在后（老读者仍见原口径）。
**C. 来源损坏与重复 ID（P1-2）**: lanes.jsonl 读失败、坏 JSON、非 dict 行、重复 lane_id、同 lane_id 状态冲突、无效 status 枚举、merge_queue.jsonl 坏行 → 一律**不得伪装为「来源完整/无待办」**；分别计入 health 计数（read_ok / bad_rows / duplicate_lane_ids / invalid_status_rows / mq_bad_rows）并使 source_complete=false。区分两个事实: **parsed closure**（能解析部分是否自洽）与 **source completeness**（来源是否完整）；parsed_closure_ok=true 不代表 source_complete=true。
**D. 快照与动作纪律**: lanes.jsonl 与 merge_queue.jsonl 两次裸读非事务（§2.1），R5 整体标注 best-effort 快照；任何基于 R5 的 requeue/abort/merge 决策，动作前必须用对应工具做权威重查（非事务快照不可作为动作依据；文档化，不改代码）。

### 2.3 最小改动
仅 goal_coordination.py 三函数: `_lane_status_map` → 返回 (map, health{read_ok, bad_rows, duplicate_lane_ids, invalid_status_rows})（重复 lane_id/无效 status 计入且不静默丢弃）；`_collect_merge_queue` → **新增** actionable_total/actionable_buckets/unknown_total/source_complete/parsed_closure_ok/overall_view_ok 字段（legacy 字段原值一律不动）；`_render_merge_queue` [1063-1090] → 新增三分行（置前）+ best-effort 标注 + 保留 legacy 四桶行与 closure_ok 行。测试: 现有断言不改（回归必过），**新增**双轨断言与三分/未知/降级负测（追加于 test_merge_queue_failure_class.py，覆盖 188-234/291-315 相邻场景）。

### 2.4 验收/负测
- 负测: lanes.jsonl 缺失 / 全坏行 / 权限不可读 / 坏 JSON / 非 dict 行 / **重复 lane_id 且状态冲突** / **无效 status** / merge_queue.jsonl 坏行 → source_complete=false、渲染降级标注、不发放写操作命令；lane_id 不在账 → unknown_total 计数+提示类 next_command；已 merged lane 不再收到 merge_request 建议（actionable 轨）；parsed_closure_ok 失败路径；overall_view_ok=false 时全部计数标注降级。
- legacy 回归: 现有测试全量不改断言通过；closure_ok/bucket_sum/failed_total 与改动前**同输入逐字段相等**。
- 验收: 实账本回放 → 三分行 `当前待办=1 历史=34 来源未知=0` 且 actionable 恒等式成立；R9 全量 exit 0。

### 2.5 回滚
纯只读投影层，单 commit revert 即恢复，无数据迁移。

## 3. M2-A Lane 锁 fail-closed + 跨 Goal 路径冲突原子检查（P0，条件 GO）

### 3.1 现状证据
- `_file_lock` [lane.py:747-776]: fcntl.flock OSError → `logger.warning("…fail-open，并发保护降级")` + 裸 yield（连 threading 锁都没有）[761-766]；docstring 自认 [748]。
- 写入口清单: create [145] / update [202] / close [324]，全部在 `with self._file_lock()` 内；`_atomic_rewrite` [721-744] 仅这三处调用；**无锁外写 lanes.jsonl 的路径**（全仓 grep：其余引用只读；docs 促销脚本写临时副本）——改单点即全覆盖。
- `_assert_unique` [538-555]: 只挡在途 branch 唯一、worktree 唯一、同 goal 在途 main 1:1；**完全不看 paths**。
- precheck [463-509]: 有 overlap_warning（overlapping_paths 前缀包含原语 [task_claim.py:285-299]，lane.py 已 import）但**只告警、在 create 之前、与 create 不同锁**（TOCTOU）。
- 历史声明重复实证（**≠事故断言，P2-1**）: lanes.jsonl 行 50/51——lane-0495df87(main, task-github-ci-hermetic-20261110) 与 lane-99aeeea2(sub, GOAL-20261111-8e5a6b50) paths 声明重叠 `.github/workflows/ci.yml`+`pyproject.toml`。该事实**仅证明「跨 Goal 路径声明重复真实发生过」**（告警有真实价值），**不证明发生过同时写入事故**；是否发生过同时写入未证实，本文不作此断言。
- paths 现状: 69 lane 中 66 非空、3 显式 `[]`（含在途 lane-selftest-guard active [行 11]）；`_normalize_paths` [94-103] 只做 strip/`\\`→`/`/去重/排序，无存在性校验。
- 附加: 公开 `append_lane_event` [607-616→704-712] 写 lane_events.jsonl 不持 lanes 锁且自身 OSError 只 warning。

### 3.2 条件 GO 的门槛（先修锁，后做检查）
1. 严格模式 fail-closed: 新增 LaneStore 锁模式开关（`lock_strict`，默认 **off=warn 兼容现状**）。strict 下 flock OSError / 锁实现导入失败（如 fcntl 不可用）/ 锁文件不可写 → raise `LaneStoreLockUnavailable`，**create/update/close 三入口一致拒写**（同一判定，任何入口不得降级放行；fail-closed）。**RULE-AI-35: 宣称"生效"前必须实测应拦输入**——负测注入锁不可用断言 strict 三入口全拒写、warn 模式仅告警。
2. **机械不变量 INV-1（P0-1）: `enforce_cross_goal` 硬依赖经核验的严格跨进程锁**，二者不是可自由组合的独立开关:
   - 启用时: enforce=true 且 lock_strict=false → **配置校验失败，拒绝启用**（初始化即抛错，该状态不存在可用实例）。
   - 运行时: enforce=true 且锁获取失败/导入失败/OSError → 该次 create/update/close **一律拒写**（继承 strict fail-closed），**不得静默退化为 warn 或无锁放行**；回执显式拒绝原因。
   - 覆盖面: create [194-195 间] / update [268-272 间] / close [324] 三入口一致（v1.1 仅列 create/update，v1.2 补 close）。
   - 配置组合负测矩阵（RULE-AI-35 实测应拦，交付前全跑）:

     | lock_strict | enforce | 锁可用 | 预期行为 |
     |---|---|---|---|
     | false | false | 任意 | 现状兼容（warn 告警） |
     | true | false | 是 | 锁内检查，warn 回执 |
     | true | false | 否 | 三入口拒写 |
     | true | true | 是 | 锁内检查，跨 Goal 冲突硬拒 |
     | true | true | 否 | 三入口拒写（**不降级 warn**） |
     | false | true | 任意 | **拒绝启用**（初始化抛错） |

3. 锁内原子检查: 在 create / update / close（同一 `_file_lock` 临界区内）扫描全部在途 lane:
   - 跨 Goal 重叠（overlap）→ warn 模式: 回执 warning 列重叠路径与对方 lane_id/goal_id；enforce 模式: 硬拒 LanePathConflict。
   - 同 Goal main/sub 或 sub/sub 重叠 → **警告不硬拒**（可能合法，见 11-05）。
   - 对方 lane `paths=[]` 或缺失（如 lane-selftest-guard）→ 冲突面 unknown: warn 模式提示「存在未知冲突面」；enforce 模式**不得据此放行**也不得据此误报冲突——回执显式 unknown 项，要求补 paths 或 owner 裁决（fail-closed: 不假装知道没有冲突）；unknown 项**登记待办直至 paths 补齐或 owner 处置，不得长期静默放行**。
   - **AGENTS.md 准入落实（P0-2）: 本批不引入任何 force/override 直接放行设计。** 模型侧仅提供「申请/复核流程」: (a) 请求 owner 复核该冲突；(b) 缩小自身 paths 后重试；(c) 等待对端 lane 终态后重试——三者均不改变硬门判定本身；模型**不得自报批准**，任何批准必须来自 owner（用户/独立授权链）的显式新输入。若未来需要紧急放行出口，须**另立设计+独立用户授权**，且形态为「人工审批面签发的一次性凭据」，不是模型可传参数。同时文档说明「为何模型+现有工具不能自判」（答: 真实多进程竞态下模型无法原子读改写账本，锁内检查必须由代码承担）。
4. 规范化与冲突比较规则（P1-6）: 复用 `_normalize_paths`（strip/`\\`→`/`/去重/排序）并补充:
   - **repo-root 绑定**: lane paths 一律为 repo 根相对 POSIX 路径；绝对路径按 repo root 归一，越出 repo root → reject；`..` 归一后逃出 repo root → reject。
   - 父子覆盖: `docs/` 与 `docs/x.md` 视为重叠（前缀包含原语 [task_claim.py:285-299]）。
   - 不存在路径: 允许声明（前瞻性建文件合法），按归一后字面比较，**不因不存在而拒**；realpath 解析仅对存在路径作辅助。
   - 软链/symlink TOCTOU: realpath 归一仅作检查层辅助比较（不改账本存储格式）；TOCTOU 窗口内 realpath 可变 → 软链场景冲突结论标 **best-effort**；**不得因 realpath 暂时一致就声称文件写隔离**（登记门≠写入隔离，见第 5 条）。realpath 解析 OSError → 该路径计 unknown 披露，不冒充无冲突。
   - 归一失败（NUL/编码异常/超长）→ reject 该 lane 登记。
   - 负测覆盖: 父子路径、反斜杠、绝对路径（repo 内/外）、`..` 逃逸、symlink 指向 repo 外、symlink 交换竞态（断言结论标 best-effort）、不存在路径声明、两进程并发 create 交叉 paths（锁内扫描应可见）、锁文件不可写、fcntl 导入失败模拟（strict/enforce 均拒写）。
5. 边界声明（docstring+本文档）: flock 仅对同主机同 audit_dir 的参与者有效，非跨设备全局锁；**Lane 登记门 ≠ shell/file-tool 写入安全隔离**（写侧安全仍依赖 sandbox 与 worktree 物理隔离）；`append_lane_event` 的锁外 fail-open 一并纳入 strict 覆盖（P1 附加项）。
6. **两个事实 + 锁序（P1-6）**: lanes 主账本提交与 `append_lane_event`（lane_events.jsonl）写入是**两个独立事实**: strict 下主账本拒写时事件不写；主账本成功而事件写失败 → 回执显式 `event_append_failed`，**不回滚主账本、也不谎称全成功**。锁序纪律: 事件写入纳入 strict 后**不得嵌套持锁**（禁止「持 lanes 锁再取事件锁」与反向交叉顺序）——实施时二选一: 同一把 lanes 锁覆盖，或事件锁外独立写+显式失败披露；并附无重入死锁测试证明。

### 3.3 EARS（摘要）
- 当 strict 开启且锁不可用（OSError/导入失败/锁文件不可写）→ create/update/close 一致拒写并抛 LaneStoreLockUnavailable；warn（默认）→ 行为与现状完全一致（含 warning）。
- 当 enforce=true 且 lock_strict=false → 拒绝启用（初始化抛错）；当 enforce=true 且运行时锁不可用 → 拒写，不降级 warn（INV-1）。
- 当 create/update/close 在锁内检出跨 Goal 路径重叠 → warn: 回执告警；enforce: 拒绝。
- 当重叠对象 paths 为空/缺失 → 回执 unknown 冲突面，永不输出「无冲突」结论；unknown 项登记待办直至补齐或 owner 处置。
- 当同 Goal 内重叠 → 仅告警。
- 当模型对冲突结论不认可 → 可调用申请/复核流程（请求 owner 复核/缩小自身 paths/等待对端终态重试）；**不存在模型可传的 force/override 放行参数**（P0-2）。
- 当旧接口（现有 create/update/close 调用方）不带新模式参数 → 行为不变（默认 warn）。

### 3.4 回滚
开关默认 off（warn=现状），无迁移；lock_strict 可单 commit revert；enforce_cross_goal 受 INV-1 约束**不能脱离 strict 独立存在**——回滚 strict 必同时使 enforce 回到拒绝启用态，不产生「enforce 在、锁已 warn 化」的中间态。

## 4. M2-B 同 Goal 写入强门: **HOLD**
依据（子代理 C 实证）: 11-15 P0-1 未修（`_override_authorized` 仍把自报 reason+refs 当授权）、P0-2 部分修（run_create_goal 会拒与运行时不一致的 session_id——本会话 2026-11-16 01:08 实测被拒 ✓；但显式 session_id 参数按原文采信、无校验 [tools_goal.py:394-396]）。跨会话写门 `_write_permission_gate`（cross_session_write_denied）已存在 [tools_goal.py:326-343]。强门设计依赖 P0 修复 + 独立用户授权，另立设计，本轮不实施。

## 5. M3 Goal 收口只读视图（P1，GO-只读）
### 5.1 现状证据
- complete 三道门已在 goal_gates.py: 任务图收口 [22-31]、逐任务 evidence verified（cancelled 豁免）[33-57]、空图自报 evidence_refs + verifier fail-closed [58-90]、账本不可读拒写终局 [91-98]；工具层前置 [tools_goal.py:597-600]。
- activity_at = max(goal.updated_at, 该 goal 最新 task.updated_at) 带 activity_source [goal_coordination.py:304-324]（N1-A8 已实现）；capacity.truncated=账本数>展示数(500) 且必自证 degraded [974-1001]；running 显式「内存态未装配≠没在跑」[461-468]；全仓**无任何 TTL 自动 complete/cleanup**。
- Gap: goal 条目 `next` 仅投影首个 in_progress 任务标题 [280,297-300,358]，无「收口候选/停滞候选/owner 下一步」。

### 5.2 EARS
- 「收口候选」判定**机械复用 goal_gates 三道门同一判据实现**（任务图收口 [22-31]、逐任务 evidence verified（cancelled 豁免）[33-57]、空图自报 refs+verifier fail-closed [58-90]、账本可读 [91-98]）——投影层直接调用/共享该判据代码，**不得另写第二套判据逻辑**；判据全部满足才投影「收口候选」行（goal_id、owner、activity_at、建议动作=update_goal complete+evidence_refs、判据来源=goal_gates）。
- 当判据不完整（如图收口但 evidence 未 verified、或证据链有缺口）→ 投影**「待补证据」行**（列出具体缺口: 缺 verified 的 task_id / 缺 refs），**不输出「可 complete」**（P1-5: open_tasks=0 本身不构成收口结论，推测自报 evidence 也不构成）。
- 当活跃 goal 的 activity_at 落后当前窗口阈值 → 投影「停滞候选」行（提示 owner 检查，**不判僵尸、不给 TTL 结论**）。
- 当 capacity.truncated=true → 收口候选段标注「视图不完整，账本截断」，且**该状态下不投影收口候选**（宁缺勿假）；时间戳不可读 → 宁缺勿假。
- 系统**不自动清理/不自动完成/不自动 reap**（lane_reap 维持三判据+人工 confirm 的既有契约）。

### 5.3 落点/回滚
`_coordination_goal_entry` [252-361] 追加派生字段（判定调用复用 goal_gates 判据函数）+ render 循环 [1113-1125] 追加行；零写路径；单 commit revert。

## 6. M4-A contract_changes 确定性提示（P1，GO-只读提示）
- 现状: string[]；无任何同键冲突/阻断代码（S1 检查不含跨 lane contract 键比较；实施时须复核 lane_gate_check 检查体——本轮未逐行核，fail-closed 声明）。
- EARS: 当 lane_open/lane_queue_submit 时存在另一在途 lane 的 contract_changes 含相同键 → 回执确定性提示（键名+对方 lane_id/goal_id），**不阻断**；提示不读 approved_by/自报理由作为授权（授权判定仍走用户显式指令）。同键≠设计冲突，语义由模型/人判。
- 落点: precheck 扩展 [lane.py:463-509 先例] + queue_submit 回执；纯提示。

## 7. M4-B 结构化契约硬门: **HOLD**
需契约 schema 设计、跨会话授权边界（P0-1/2）修复、以及独立用户授权；不建第五套账本/新常驻编排器/自动审批/无界重试（AGENTS.md 准入不对称 + DEVELOPMENT_REPAIR_SAFETY Q5）。

## 8. 多 Agent 实施模式（用户 2026-11-16 授权的受控链路）
1. 主代理（LFL 本会话族）: 统筹、交叉核验、门禁执行；只读调查子代理 ≤3 个/轮、互不冲突、禁写。
2. 实施代理: **单一 GLM-5.3 开发代理**；Lane/worktree 按**文件不重叠**划分——M1 与 M3 同改 goal_coordination.py → **同一实施 lane 内串行**（先 M1 后 M3），不并行；M4-A 改 lane.py/merge_queue.py，可独立 lane 并行（与 M1/M3 文件不重叠）；M2-A 与 M4-A 同改 lane.py → M2-A 排批次一集成之后（批次二），禁止并行改同文件。严格记录 model_used，非 glm/glm-5.3 不得宣称 GLM 开发。
3. 独立 Reviewer（≠开发代理，GLM-5.3）: 绑定精确冻结 SHA/tree/diff，真实 completed 且 PASS、P0=P1=0 才算过（RULE-AI-28 review_admission 机制）。
4. 原版完整 R9 真实 exit 0（不对 known-reds 放宽基线；红线要么修要么显式登记接受）。
5. GitHub PR + CI 精确 SHA 全绿 → 才合 main/push（RULE-AI-34 分支收口合并闸；push 前独立审查闸）。
6. 受管发布: 核 desired/live 一致、idle/barriers、活跃 Run 不强杀、回滚预案与健康检查（沿 11-15 四服务受管发布链）。
7. 每阶段 checkpoint_goal；报告真实 Goal ID/文件路径/候选 SHA/子代理终态/发现/风险/下一阶段最小执行建议。

## 9. 与现有设计的冲突与裁决
| 冲突面 | 上游 | 裁决 |
|---|---|---|
| enforce_cross_goal 硬拒 vs 11-05 多 lane 并行自由 | 11-05 | enforce 默认 off 且硬依赖 lock_strict（INV-1，§3.2-2）；warn 提示即覆盖 11-05 的并行提示需求；跨 Goal 声明重复实证（行 50/51，≠同时写入事故）说明提示有真实价值，硬拒仅在受控启用后；无 force 放行参数（P0-2） |
| M1 三分 vs 11-14 R1-c 四桶失败分类 | 11-14 | legacy 四桶与 failure_class **原口径全保留**；新增 actionable_* 独立字段承载三分（活待办/历史终态/来源未知外层归因），不推翻 R1-c（双轨，§2.2） |
| M3 vs lane_reap 三判据 | 11-14 | M3 只投影候选、不自动 reap；判定机械复用 goal_gates（P1-5）；lane_reap 维持超时+注入式 liveness+凭证复核三判据 |
| M2-B/M4-B vs 11-15 P0 NO-GO | 11-15 | HOLD 直接引用其结论；P0-1/2 修复属独立任务，不在本 Goal 范围 |
| 锁 strict 模式 vs 现有调用方 | — | 默认 warn=现状完全兼容；strict/opt-in；enforce 受 INV-1 约束不能独立启用 |
| 与 knowledge_flush 门/命令闸/review 预检 | 多处 | 不触碰、不绕行 |

## 10. 依赖与实施顺序（v1.2: 批次化一次集成，P1-4）
```
批次一（本 Goal 集成候选）:
  M1(只读投影, goal_coordination.py) → M3(只读投影, 同文件) —— 同一实施 lane 内串行
  M4-A(只读提示, lane.py/merge_queue.py) —— 独立 lane，可与 M1/M3 并行（文件不重叠）
  ↓ 三者合流 → 一次集成冻结候选（统一 tree/diff SHA）
批次二（独立后续候选，单独验收）:
  M2-A: BUG-01(strict 锁+INV-1) → BUG-02(锁内跨 Goal 检查) 串行，独立 lane
       （M2-A 与 M4-A 同改 lane.py → 排批次一集成之后，禁止并行改同文件）
M2-B/M4-B: HOLD（外部依赖，不在本 Goal）
```
- M0 已完成（本文档 §1）；设计正本=本文件；队列=docs/queues/{BUG-BLOCKER-QUEUE,OPT-QUEUE}-20261116.md。
- **批次一验收 = 一次**: 冻结集成候选 → 统一独立 Reviewer（≠开发代理，绑定精确冻结 SHA/tree）→ 一次原版完整 R9 → 一次 PR/CI → 合 main（Rule34）。批次一内任一成分再 commit（漂移）→ 整批重新冻结/重审/重跑 R9，**不复用旧 PASS**。
- 批次二（M2-A）独立走完整 Reviewer→R9→PR/CI 链，与批次一不共享不互认。
- 全程禁止两个代理同时改同一文件（M1/M3 已按此同 lane 串行；M2-A 已按此排批次二；lane paths 声明重叠即冲突）。

## 11. 验收与 R9（v1.2: 按批次一次全量）
- 批次一（M1+M3+M4-A）: 各 M 新增单测+负测（见各节）随集成候选一次性提交；**一次**原版完整 R9 真实 exit 0（不对 known-reds 放宽基线）；legacy 双轨回归断言（M1）与 goal_gates 判据一致性单测（M3）为批次一必含项。
- 批次二（M2-A）: 独立一次完整 R9；护栏类变更（lock_strict/enforce/INV-1）按 RULE-AI-35 实测「应拦输入」——§3.2-2 六组合配置矩阵 + §3.2-4 路径负测清单全跑通过，才可宣称生效。
- 验收数据: M1 真实账本回放 `当前待办=1 历史=34 来源未知=0` 且 legacy 字段逐值不变；M2-A 复现「两进程并发 create 交叉 paths」负测 + 六组合配置矩阵负测通过。
- 集成漂移纪律: 批次一冻结后任何成分再 commit → 整批重冻/重审/重 R9，旧 PASS 作废。

## 12. 回滚总则
全部改动可按 commit 独立 revert；无数据迁移；开关默认关闭或 warn=现状；不依赖并行部署顺序。

## 13. GO/HOLD 总表
| 项 | 判定 | 门槛 |
|---|---|---|
| M1 | GO（批次一） | 无前置；与 M3 同文件（goal_coordination.py）→ 同 lane 串行 |
| M2-A | 条件 GO（批次二，批次一集成后） | 先 strict 锁+INV-1 六组合负测矩阵，后锁内检查；enforce 默认 off 且硬依赖 strict；无 force 放行参数 |
| M2-B | HOLD | 11-15 P0-1/2 修复+独立授权 |
| M3 | GO(只读, 批次一) | 机械复用 goal_gates 判据；证据不全→「待补证据」；与 M1 同 lane 串行 |
| M4-A | GO(只读提示, 批次一) | 独立 lane 并行（与 M1/M3 文件不重叠） |
| M4-B | HOLD | schema+P0 修复+独立授权 |

## 14. 本轮成本记账（v1.2: 实测数据，不宣称提速，P2-2）
- 墙钟: 2026-11-16 01:07-01:22，约 15 分钟（M0+调查+设计+队列）；v1.2 修订轮 01:24 起仅主代理文档修订，无子代理（GPT-6 明示不再启动调查子代理）。
- 主 run（调查+设计轮，工具回执口径）: input 2,569,095 / output 41,617 tokens，cache hit 2,315,648（≈90%）。
- 只读子代理 3 个: A=14 轮 19 工具（回执未含 token 计数）; B=14 轮 19 工具 tokens_in 778,824 / out 14,687; C=30 轮 35 工具 tokens_in 2,167,584 / out 15,173。
- 调查分工: A/B/C 问题族按不重叠设计（锁与冲突/队列完整性/goal 契约与安全边界）；主代理对关键结论交叉核验一致，未发生对同一问题的重复完整调查（此为分工记录，非「零重复」成效宣称）。
- 冲突/回退: worktree/lane 登记一次成功；FR-SAFE-01 两次拦截（here-doc/管道）为环境护栏正常工作，非任务回退。

## 15. 证据索引（主代理与子代理核验，行号基于 origin/main 9e6b438cc）
- lane.py: 761-766(fail-open), 748(docstring), 145/202/324(写入口), 721-744(_atomic_rewrite), 538-555(_assert_unique), 463-509(precheck), 94-103(_normalize_paths), 607-616/704-712(append_lane_event)
- goal_coordination.py: 797-821(_lane_status_map), 850-939(_collect_merge_queue), 893/895-898/921-924(closure), 835-846(next_command), 1063-1090(render), 304-324(activity_at), 974-1001(capacity), 252-361(goal entry), 461-468(running 语义)
- merge_queue.py: 1396-1418/1448-1449/1525-1526(fail-closed 读), 1131-1163(note_main_advanced 只标 queued), 1493-1500(写侧 CAS)
- goal_gates.py: 22-31/33-57/58-90/91-98(complete 三道门); tools_goal.py: 326-343/394-407/457-459/586-600(写门/会话绑定/complete 前置)
- 账本: lanes.jsonl 登记前 69 行 / 登记 lane-d6ceb9dd 后 70 行（v1.2 双口径见 §1，含 GPT-6 独立实测校正: 登记后 closed8/abandoned8/merged51/active2/verifying1 = 70 ✓；行 11/12/18 paths=[]，行 11 lane-selftest-guard 在途; 行 50/51 跨 Goal 声明重叠 ≠ 同时写入事故）; merge_queue.jsonl 76 行（M0 时点）
- 测试: tests/unit/test_merge_queue_failure_class.py:188-234, 291-315
- v1.2 修订来源: 用户（GPT-6 主统筹）2026-11-16 01:24 REVISE 消息（10 项审查意见+独立实测数据，含 lanes.jsonl 70 行分布与主 run/子代理 token 计数）
- 未逐行核（fail-closed 声明）: lane_gate_check S1 检查体第 5-10 条; task_claim 租约到期语义; 11-14/11-12 设计原文与 P0-1/2 修复状态比对（代码侧事实已独立成立）。

## 16. v1.2 修订对照表（GPT-6 REVISE 2026-11-16 01:24，逐项位置与验证）
| 审查项 | 修改位置 | 验证方式 |
|---|---|---|
| P0-1 enforce 硬依赖严格锁 | §3.2-2 INV-1+六组合矩阵、§3.3 EARS 第 2 条、§3.4、§9 表 2 行、§13 表、BUG-01/02 | 批次二 R9 六组合配置负测矩阵全跑（RULE-AI-35 实测应拦输入） |
| P0-2 删除 force/override 出口 | §3.2-3 AGENTS 落实条（申请/复核流程: owner 复核/缩 paths/等对端终态，模型不自报批准；紧急放行=另立设计+用户授权+人工审批面一次性凭据）、§3.3 EARS、§9 表 | 设计审查: §3 内无任何模型可传放行参数残留；实施时配置矩阵含「无 force 路径」断言 |
| P1-1 legacy/新增双轨 | §2.2 A/B 轨、§2.3、§2.4、§9 表、OPT-01、BUG-04 | M1 双轨断言: legacy 逐字段回归（同输入等值）+ actionable 恒等式单测 |
| P1-2 来源损坏/重复 ID | §2.2 C/D、§2.3 health 扩展、§2.4 负测、BUG-03 | 坏 JSON/非 dict/重复 lane_id/无效 status/mq 坏行负测 → source_complete=false 且禁发写命令 |
| P1-3 §1 计数闭合 | §1 双口径（69=51+8+8+1+1; 70=51+8+8+2+1）、在途 3 lane、selftest 处置、§15 账本行 | 算术自检（两行加法闭合）+ 与 GPT-6 实测 70 行分布一致 |
| P1-4 一次集成批次化 | §8-2、§10 批次图、§11、§13 表、BUG-01/05 批次标注 | 流程审查: 批次一单次 Reviewer/R9/PR/CI; M1+M3 同 lane 串行; M2-A 排批次二; 漂移→重冻重审重 R9 |
| P1-5 M3 复用 goal_gates | §5.2 第 1/2 条、§5.3、OPT-03 | M3 单测: 投影判定与 goal_gates 直接调用输出一致；证据不全→「待补证据」负测 |
| P1-6 路径规范化/锁序 | §3.2-4 规则（repo-root 绑定/父子/不存在/软链 TOCTOU best-effort/unknown/reject）、§3.2-6 两事实+锁序、BUG-05 | §3.2-4 路径负测清单全跑 + 无重入死锁测试（两实现方案二选一附证） |
| P2-1 BUG-06/08 定性 | BUG-06（外部 P0/HOLD 依赖，不阻 M1）、BUG-08（集成前置阻断，非业务 bug）、§3.1 措辞、§9 表 | 队列字段审查; §3.1 无「事故」断言 |
| P2-2 效率实测 | §14 实测数据+分工记录（不宣称零重复/提速）、OPT-06/07（可测最小改进，不本轮开发）、OPT 不纳入纪律行 | M1 实施轮记录对照数据（任务书行号窗口/父侧定点核验 token 对照） |
