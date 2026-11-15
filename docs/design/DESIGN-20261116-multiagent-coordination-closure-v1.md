# LFL 多 Agent 协作优化：队列降噪、冲突前置、Goal 收口与契约协调——需求与实现设计 v1.1

- 状态: **DRAFT-待审**（等待 GPT-6 主统筹交叉审查；审查通过前不进入 M1+ 实施）
- 日期: 2026-11-16（宿主本地时区）
- 本文件: docs/design/DESIGN-20261116-multiagent-coordination-closure-v1.md（设计正本 v1）
- Lane: lane-d6ceb9dd / Goal: GOAL-20261116-d83c9c53 / 基线: origin/main 9e6b438cc814844fde49b519824cd359b5a27cdc

## 0. 权威来源与证据声明

1. 本正本的裁决真值 = 用户 2026-11-16 授权消息中的「设计硬裁决 M1-M4」（经反例拷问的 v1.1 决策摘要）。
2. 源码/账本事实 = 本会话独立核验：主代理直读 + 3 个只读调查子代理（A=lane 锁/冲突、B=merge queue 来源完整性、C=goal/契约/安全边界），子代理全程零写入，主代理对关键结论逐条交叉核验一致。
3. **未读取 ChatGPT 沙盒文件**（不可达）；用户消息中的裁决摘要即上游 v1.1 的权威投影，本正本据其+仓库源码重新生成，不经由任何沙盒拷贝。
4. 上游链: DESIGN-20261105-main-lane-parallel-delivery-v1（lane 并行交付）、DESIGN-20261114-lane-lifecycle-and-failure-classification-v1（R1-c 失败分类/lane_reap 三判据）、DESIGN-20261115-trusted-shared-workstate-multiagent-v1（P0-1/2/3 跨会话授权边界，NO-GO 项）、DESIGN-20261115-unified-managed-four-service-release-v1（受管发布链）。规则: RULE-AI-24/28/34/35/36；AGENTS.md 准入不对称；docs/DEVELOPMENT_REPAIR_SAFETY.md 六问。

## 1. M0 状态快照（2026-11-16 01:07-01:20 实测）

- 主工作树: 脏（未跟踪 docs/DESIGN-20261115-knowledge-self-improvement-loop-v1.md）；main 与 origin/main 分叉 ahead 10 / behind 33 → **禁止直接改 main**，全部产出写入隔离 worktree `.worktrees/multiagent-coord-design-20261116`（分支 docs/multiagent-coordination-closure-20261116）。
- Lane 账本: 69 lane（merged 51 / closed 8 / abandoned 8 / verifying 1）。唯一在途 lane-a4e7865d（GOAL-20261111-1e19d24f，paths=scripts/ci_gate.sh+tests/…，与本设计 docs 路径零重叠）。
- Merge queue: 76 行；failed 35 = 历史终态 34 + 活待办 1 + 来源未知 0（97% 噪音，M1 的实证）。
- 旧 Goal GOAL-20261114-474ab491 已 complete，不恢复不覆盖。

## 2. M1 队列降噪：三分展示与来源诚实（P0，GO）

### 2.1 现状证据（代码级）
- `_lane_status_map` [goal_coordination.py:797-821]：lanes.jsonl 读失败 → 返回空 dict（与「账本真空」同形）；坏行静默 continue [813-816]；merge_queue.py 自身读取是 fail-closed 抛错 [1396-1418]，**静默退化仅此一条路径**。
- `_collect_merge_queue` [850-939]：lane_state="" → is_terminal=False [895-898]；「来源未知（lane_id 不存在）」「读失败」「lane 在途」三种情况同形，均落入四桶且 `_queue_next_command` [845-846] 照发可执行命令（如对已 merged lane 发 lane_merge_request）。
- closure_ok = (四桶和 == failed_total) [921-924]：由构造成立（未知类默认 human 桶 [893]），证明「没丢行」不证明「账本完整」；坏行不计入分母仅 note 披露 [883-885,919-920]。
- 实测: `failed=35 闭合=ok(35) 该重投=0 该 rebase=17 该补凭证=11 该人看=7 | 历史=34`——桶计数混入历史终态项，真待办仅 1 条不可见。
- 跨文件快照非事务: lanes.jsonl 与 merge_queue.jsonl 两次裸 open 无锁无版本 [808/876]；宿主自标 `audit_toctou=trusted_host_race_not_closed`；写侧 CAS [merge_queue.py:1493-1500] 承担权威重查。

### 2.2 EARS 需求
- 当 lanes.jsonl 可读且 lane_id 在账 → 该 failed 项分类为「历史终态」（lane 状态 ∈ merged/abandoned/closed）或「当前待办」。
- 当 lanes.jsonl 可读且 lane_id 不在账 → 分类为「来源未知」，next_command 只允许「人工核对账本」类提示，禁止发放 requeue/rebase/merge 等可执行命令。
- 当 lanes.jsonl 读失败或存在坏行 → R5 显式 degraded（ledger_read_ok=false、坏行计数），桶计数标注降级；不得冒充空账本推断「全部待办」。
- closure 恒等式改为 **bucket_sum == failed_total − terminal_total − unknown_total**（每条 failed 恰属活待办/历史终态/来源未知之一）；渲染顺序 `failed=N | 当前待办=M 历史=K 来源未知=J 坏行=L | 四桶…`。
- 系统**保留旧接口**：R5 现有字段（四桶 count、closure_ok、items[].terminal、next_command）全部保留语义或向后兼容；tools_goal.py:382-384 纯透传无需改动。
- 动作前置纪律（文档化，不改代码）：任何基于 R5 的 requeue/abort 决策，动作前必须用对应工具做权威重查（非事务快照不可作为动作依据）。

### 2.3 最小改动
仅 goal_coordination.py 三函数: `_lane_status_map` → 返回 (map, health{read_ok, bad_rows})；`_collect_merge_queue` → 补 unknown_total、桶只收活待办、closure 恒等式更新；`_render_merge_queue` [1063-1090] → 补三分行。测试同步: tests/unit/test_merge_queue_failure_class.py:188-234、291-315。

### 2.4 验收/负测
- 负测: lanes.jsonl 缺失 / 全坏行 / 权限不可读 → degraded 且不发放动作命令；lane_id 不存在 → 来源未知桶；已 merged lane 不再收到 merge_request 建议；closure 断言失败路径。
- 验收: 实账本回放 → `当前待办=1 历史=34 来源未知=0`；R9 全量 exit 0。

### 2.5 回滚
纯只读投影层，单 commit revert 即恢复，无数据迁移。

## 3. M2-A Lane 锁 fail-closed + 跨 Goal 路径冲突原子检查（P0，条件 GO）

### 3.1 现状证据
- `_file_lock` [lane.py:747-776]: fcntl.flock OSError → `logger.warning("…fail-open，并发保护降级")` + 裸 yield（连 threading 锁都没有）[761-766]；docstring 自认 [748]。
- 写入口清单: create [145] / update [202] / close [324]，全部在 `with self._file_lock()` 内；`_atomic_rewrite` [721-744] 仅这三处调用；**无锁外写 lanes.jsonl 的路径**（全仓 grep：其余引用只读；docs 促销脚本写临时副本）——改单点即全覆盖。
- `_assert_unique` [538-555]: 只挡在途 branch 唯一、worktree 唯一、同 goal 在途 main 1:1；**完全不看 paths**。
- precheck [463-509]: 有 overlap_warning（overlapping_paths 前缀包含原语 [task_claim.py:285-299]，lane.py 已 import）但**只告警、在 create 之前、与 create 不同锁**（TOCTOU）。
- 历史重复实证: lanes.jsonl 行 50/51——lane-0495df87(main, task-github-ci-hermetic-20261110) 与 lane-99aeeea2(sub, GOAL-20261111-8e5a6b50) paths 重叠 `.github/workflows/ci.yml`+`pyproject.toml`（跨 Goal 路径重复真实发生过）。
- paths 现状: 69 lane 中 66 非空、3 显式 `[]`（含在途 lane-selftest-guard active [行 11]）；`_normalize_paths` [94-103] 只做 strip/`\\`→`/`/去重/排序，无存在性校验。
- 附加: 公开 `append_lane_event` [607-616→704-712] 写 lane_events.jsonl 不持 lanes 锁且自身 OSError 只 warning。

### 3.2 条件 GO 的门槛（先修锁，后做检查）
1. 严格模式 fail-closed: 新增 LaneStore 锁模式开关（`lock_strict`，默认 **off=warn 兼容现状**）。strict 下 flock OSError → raise `LaneStoreLockUnavailable`，create/update/close 拒写（fail-closed）。**RULE-AI-35: 宣称"生效"前必须实测应拦输入**——负测注入锁不可用（如不可写锁文件）断言 strict 拒写、warn 仅告警。
2. 锁内原子检查: 在 create [194-195 之间] / update [268-272 之间]（同一 `_file_lock` 临界区内）扫描全部在途 lane:
   - 跨 Goal 重叠（overlap）→ warn 模式: 回执 warning 列重叠路径与对方 lane_id/goal_id；`enforce_cross_goal` 模式（默认 off，受控启用）: 硬拒 LanePathConflict。
   - 同 Goal main/sub 或 sub/sub 重叠 → **警告不硬拒**（可能合法，见 11-05）。
   - 对方 lane `paths=[]` 或缺失 → 冲突面 unknown: warn 模式提示「存在未知冲突面」；enforce 模式**不得据此放行**也不得据此误报冲突——回执显式 unknown 项，要求补 paths 或人工裁决（fail-closed: 不假装知道没有冲突）。
   - AGENTS.md 准入: enforce 属新硬门，须提供模型可调用 veto/override 出口（如带 reason 的 force 参数走人工审批面）+文档说明「为何模型+现有工具不能自判」（答: 真实多进程竞态下模型无法原子读改写账本）。
3. 规范化与负测: 复用 `_normalize_paths`；负测覆盖 父子路径（`docs/` vs `docs/x.md`）、反斜杠、绝对路径、`..` 逃逸、软链（realpath 归一后比较，仅作检查层不改账本存储格式）、两进程并发 create 交叉 paths（锁内扫描应可见）、锁文件不可写（strict 拒/warn 降级）。
4. 边界声明（docstring+本文档）: flock 仅对同主机同 audit_dir 的参与者有效，非跨设备全局锁；**Lane 登记门 ≠ shell/file-tool 写入安全隔离**（写侧安全仍依赖 sandbox 与 worktree 物理隔离）；`append_lane_event` 的锁外 fail-open 一并纳入 strict 覆盖（P1 附加项）。

### 3.3 EARS（摘要）
- 当 strict 开启且锁不可用 → 拒写并抛 LaneStoreLockUnavailable；warn（默认）→ 行为与现状完全一致（含 warning）。
- 当 create/update 在锁内检出跨 Goal 路径重叠 → warn: 回执告警；enforce: 拒绝。
- 当重叠对象 paths 为空/缺失 → 回执 unknown 冲突面，永不输出「无冲突」结论。
- 当同 Goal 内重叠 → 仅告警。
- 当旧接口（现有 create/update 调用方）不带新模式参数 → 行为不变（默认 warn）。

### 3.4 回滚
开关默认 off（warn=现状），无迁移；enforce_cross_goal 独立于 lock_strict，均可单 commit revert。

## 4. M2-B 同 Goal 写入强门: **HOLD**
依据（子代理 C 实证）: 11-15 P0-1 未修（`_override_authorized` 仍把自报 reason+refs 当授权）、P0-2 部分修（run_create_goal 会拒与运行时不一致的 session_id——本会话 2026-11-16 01:08 实测被拒 ✓；但显式 session_id 参数按原文采信、无校验 [tools_goal.py:394-396]）。跨会话写门 `_write_permission_gate`（cross_session_write_denied）已存在 [tools_goal.py:326-343]。强门设计依赖 P0 修复 + 独立用户授权，另立设计，本轮不实施。

## 5. M3 Goal 收口只读视图（P1，GO-只读）
### 5.1 现状证据
- complete 三道门已在 goal_gates.py: 任务图收口 [22-31]、逐任务 evidence verified（cancelled 豁免）[33-57]、空图自报 evidence_refs + verifier fail-closed [58-90]、账本不可读拒写终局 [91-98]；工具层前置 [tools_goal.py:597-600]。
- activity_at = max(goal.updated_at, 该 goal 最新 task.updated_at) 带 activity_source [goal_coordination.py:304-324]（N1-A8 已实现）；capacity.truncated=账本数>展示数(500) 且必自证 degraded [974-1001]；running 显式「内存态未装配≠没在跑」[461-468]；全仓**无任何 TTL 自动 complete/cleanup**。
- Gap: goal 条目 `next` 仅投影首个 in_progress 任务标题 [280,297-300,358]，无「收口候选/停滞候选/owner 下一步」。

### 5.2 EARS
- 当活跃 goal 的收口判据满足（open_tasks=0 且全部任务终态、evidence 已 verified 或可自报 refs）→ 投影「收口候选」行（goal_id、owner、activity_at、建议动作=update_goal complete+evidence_refs）。
- 当活跃 goal 的 activity_at 落后当前窗口阈值 → 投影「停滞候选」行（提示 owner 检查，**不判僵尸、不给 TTL 结论**）。
- 当 capacity.truncated=true → 收口候选段标注「视图不完整，账本截断」；时间戳不可读 → 宁缺勿假。
- 系统**不自动清理/不自动完成/不自动 reap**（lane_reap 维持三判据+人工 confirm 的既有契约）。

### 5.3 落点/回滚
`_coordination_goal_entry` [252-361] 追加派生字段 + render 循环 [1113-1125] 追加行；零写路径；单 commit revert。

## 6. M4-A contract_changes 确定性提示（P1，GO-只读提示）
- 现状: string[]；无任何同键冲突/阻断代码（S1 检查不含跨 lane contract 键比较；实施时须复核 lane_gate_check 检查体——本轮未逐行核，fail-closed 声明）。
- EARS: 当 lane_open/lane_queue_submit 时存在另一在途 lane 的 contract_changes 含相同键 → 回执确定性提示（键名+对方 lane_id/goal_id），**不阻断**；提示不读 approved_by/自报理由作为授权（授权判定仍走用户显式指令）。同键≠设计冲突，语义由模型/人判。
- 落点: precheck 扩展 [lane.py:463-509 先例] + queue_submit 回执；纯提示。

## 7. M4-B 结构化契约硬门: **HOLD**
需契约 schema 设计、跨会话授权边界（P0-1/2）修复、以及独立用户授权；不建第五套账本/新常驻编排器/自动审批/无界重试（AGENTS.md 准入不对称 + DEVELOPMENT_REPAIR_SAFETY Q5）。

## 8. 多 Agent 实施模式（用户 2026-11-16 授权的受控链路）
1. 主代理（LFL 本会话族）: 统筹、交叉核验、门禁执行；只读调查子代理 ≤3 个/轮、互不冲突、禁写。
2. 实施代理: **单一 GLM-5.3 开发代理**按不重叠问题族分隔 Lane/worktree（M1/M3/M4-A 只读族可并行 lane；M2-A 写路径族独立 lane）；严格记录 model_used，非 glm/glm-5.3 不得宣称 GLM 开发。
3. 独立 Reviewer（≠开发代理，GLM-5.3）: 绑定精确冻结 SHA/tree/diff，真实 completed 且 PASS、P0=P1=0 才算过（RULE-AI-28 review_admission 机制）。
4. 原版完整 R9 真实 exit 0（不对 known-reds 放宽基线；红线要么修要么显式登记接受）。
5. GitHub PR + CI 精确 SHA 全绿 → 才合 main/push（RULE-AI-34 分支收口合并闸；push 前独立审查闸）。
6. 受管发布: 核 desired/live 一致、idle/barriers、活跃 Run 不强杀、回滚预案与健康检查（沿 11-15 四服务受管发布链）。
7. 每阶段 checkpoint_goal；报告真实 Goal ID/文件路径/候选 SHA/子代理终态/发现/风险/下一阶段最小执行建议。

## 9. 与现有设计的冲突与裁决
| 冲突面 | 上游 | 裁决 |
|---|---|---|
| enforce_cross_goal 硬拒 vs 11-05 多 lane 并行自由 | 11-05 | enforce 默认 off；warn 提示即覆盖 11-05 的并行提示需求；跨 Goal 重叠历史实证（行 50/51）说明提示有真实价值，硬拒仅在受控启用后 |
| M1 三分 vs 11-14 R1-c 四桶失败分类 | 11-14 | 四桶与 failure_class 全保留；三分是外层归因（历史/待办/未知），不推翻 R1-c |
| M3 vs lane_reap 三判据 | 11-14 | M3 只投影候选、不自动 reap；lane_reap 维持超时+注入式 liveness+凭证复核三判据 |
| M2-B/M4-B vs 11-15 P0 NO-GO | 11-15 | HOLD 直接引用其结论；P0-1/2 修复属独立任务，不在本 Goal 范围 |
| 锁 strict 模式 vs 现有调用方 | — | 默认 warn=现状完全兼容；strict/opt-in |
| 与 knowledge_flush 门/命令闸/review 预检 | 多处 | 不触碰、不绕行 |

## 10. 依赖与实施顺序
```
M1(只读投影) ─┐
M3(只读投影) ─┼─ 可并行，三条独立 lane（问题族不重叠）
M4-A(只读提示)┘
M2-A: BUG-01(strict 锁) → BUG-02(锁内跨 Goal 检查) 串行，独立 lane
M2-B/M4-B: HOLD（外部依赖，不在本 Goal）
```
- M0 已完成（本文档 §1）；设计正本=本文件；队列=docs/queues/{BUG-BLOCKER-QUEUE,OPT-QUEUE}-20261116.md。
- 每 M 完成后: 独立 Reviewer → R9 全量 → PR/CI → 合 main（Rule34）→ 下一 M。

## 11. 验收与 R9
- 每个 M: 新增单测+负测（见各节）；R9 全量真实 exit 0；护栏类变更（strict/enforce）按 RULE-AI-35 实测「应拦输入」后才可宣称生效。
- 验收数据: M1 在真实账本回放 `当前待办=1 历史=34 来源未知=0`；M2-A 复现「两进程并发 create 交叉 paths」负测通过。

## 12. 回滚总则
全部改动可按 commit 独立 revert；无数据迁移；开关默认关闭或 warn=现状；不依赖并行部署顺序。

## 13. GO/HOLD 总表
| 项 | 判定 | 门槛 |
|---|---|---|
| M1 | GO | 无前置 |
| M2-A | 条件 GO | 先 strict 锁+负测，后锁内检查；enforce 默认 off |
| M2-B | HOLD | 11-15 P0-1/2 修复+独立授权 |
| M3 | GO(只读) | 无前置 |
| M4-A | GO(只读提示) | 无前置 |
| M4-B | HOLD | schema+P0 修复+独立授权 |

## 14. 本轮成本记账（无对照，不宣称加速）
- 墙钟: 2026-11-16 01:07-01:2x（M0+调查+设计+队列）。
- 只读子代理 3 个: A=14 轮 19 工具; B=14 轮 19 工具 tokens_in 778,824 / out 14,687; C=30 轮 35 工具 tokens_in 2,167,584 / out 15,173（A 回执未含 token 计数）。
- 重复调查: 0（A/B/C 问题族不重叠；主代理直读与子代理结论交叉一致，无返工）。
- 冲突/回退: 0（worktree/lane 登记一次成功；FR-SAFE-01 两次拦截为本环境护栏正常工作，非任务回退）。

## 15. 证据索引（主代理与子代理核验，行号基于 origin/main 9e6b438cc）
- lane.py: 761-766(fail-open), 748(docstring), 145/202/324(写入口), 721-744(_atomic_rewrite), 538-555(_assert_unique), 463-509(precheck), 94-103(_normalize_paths), 607-616/704-712(append_lane_event)
- goal_coordination.py: 797-821(_lane_status_map), 850-939(_collect_merge_queue), 893/895-898/921-924(closure), 835-846(next_command), 1063-1090(render), 304-324(activity_at), 974-1001(capacity), 252-361(goal entry), 461-468(running 语义)
- merge_queue.py: 1396-1418/1448-1449/1525-1526(fail-closed 读), 1131-1163(note_main_advanced 只标 queued), 1493-1500(写侧 CAS)
- goal_gates.py: 22-31/33-57/58-90/91-98(complete 三道门); tools_goal.py: 326-343/394-407/457-459/586-600(写门/会话绑定/complete 前置)
- 账本: lanes.jsonl 69 行(状态分布见 §1; 行 11/12/18 paths=[]; 行 50/51 跨 Goal 重叠); merge_queue.jsonl 76 行
- 测试: tests/unit/test_merge_queue_failure_class.py:188-234, 291-315
- 未逐行核（fail-closed 声明）: lane_gate_check S1 检查体第 5-10 条; task_claim 租约到期语义; 11-14/11-12 设计原文与 P0-1/2 修复状态比对（代码侧事实已独立成立）。
