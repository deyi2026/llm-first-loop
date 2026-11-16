# BUG/阻断队列（多 Agent 协作 v1.3）— 2026-11-16

- 真值源: 设计正本 docs/design/DESIGN-20261116-multiagent-coordination-closure-v1.md（§证据索引，行号基线 origin/main 9e6b438cc；**2026-11-16T21:00+08 对账基线已前进到 origin/main 40ba2d9**——W1 PR#48 合并于 73e5053c3，其后 PR#49 为 Deepin 发行改动）
- 字段: ID | 证据 | 严重度 | owner | 依赖 | 状态 | 下一动作
- 状态机: open → in-design → ready(待实施) → fixed(待审) → verified(R9+Reviewer 过) → closed；HOLD 项单列
- 行号引用为当前基线快照，实施时按 task_state/子代理报告复核偏移

## P0（先行）
| ID | 证据 | 严重度 | owner | 依赖 | 状态 | 下一动作 |
|---|---|---|---|---|---|---|
| BUG-01 | lane.py:761-766 `_file_lock` OSError→warning+yield（fail-open，无 threading 锁）；docstring:748 自认 | P0 | GLM-5.3 实施 lane（M2-A，批次二） | 无 | open | M2-A: 增加 lock_strict（默认 off=warn 兼容）；strict 下 OSError/锁实现导入失败/锁文件不可写 → create/update/close **三入口一致** raise 拒写；RULE-AI-35 负测：注入锁不可用实测三入口应拦（设计 §3.2-1） |
| BUG-02 | 跨 Goal 路径冲突检查缺失+TOCTOU：precheck [463-509] 只警告且在 create 前锁外；_assert_unique [538-555] 完全不看 paths；历史**声明**重复实证 lanes.jsonl 行 50/51（仅证告警价值，**≠同时写入事故**，P2-1） | P0 | GLM-5.3 实施 lane（M2-A，批次二） | BUG-01（**INV-1**: enforce 硬依赖经核验 strict 锁；enforce=true+strict=false → 拒绝启用） | open | create/update/close 三入口锁内扫描在途 lane paths；跨 Goal warn/enforce（enforce 默认 off，**无 force 放行参数**——模型仅可申请 owner 复核/缩小自身 paths/等待对端终态，不自报批准，P0-2）；同 Goal 仅警告；paths=[]→unknown 不误报且登记待办不长期放行；路径规范化按设计 §3.2-4（repo-root 绑定/reject/unknown 规则） |
| BUG-03 | goal_coordination.py:797-821 `_lane_status_map` 读失败→空 dict 与账本真空同形、坏行 [813-816] 静默；895-898 lane_state=""→is_terminal=False；845-846 对已 merged lane 发可执行命令（lane map 空时终态护栏失效） | P0 | GLM-5.3 实施 lane（M1，批次一） | 无 | closed（PR#42 合并 96098972f，push CI success；ecac7aecf 结构重构后仍在 main） | M1: health{read_ok, bad_rows, duplicate_lane_ids, invalid_status_rows} 暴露；来源未知独立类别（**保守 unknown**: 不在账/读失败/坏 JSON/非 dict/重复 lane_id 冲突/无效 status，P1-2）；source_complete 与 parsed_closure_ok 分离；未知/降级项不发写操作命令（设计 §2.2 B/C） |

## P1
| ID | 证据 | 严重度 | owner | 依赖 | 状态 | 下一动作 |
|---|---|---|---|---|---|---|
| BUG-04 | R5 四桶混计历史终态项：实测 35 failed=34 历史+1 活待办；closure 恒等式 [921-924] 缺 terminal/unknown 项；桶默认 human [893] | P1 | GLM-5.3 实施 lane（M1，批次一） | BUG-03 | closed（PR#42 合并 96098972f） | 双轨（设计 §2.2 A/B，P1-1）: legacy 字段原口径全保留（closure_ok/bucket_sum/failed_total 原值不动，现有测试不改）；新增 actionable_*/unknown_total+新恒等式 actionable_bucket_sum==failed_total−terminal_total−unknown_total **只作用于 actionable 轨**；渲染三分行置前+legacy 行保留；新增双轨断言测试 |
| BUG-05 | lane.py:607-616→704-712 公开 append_lane_event 写 lane_events.jsonl 不持 lanes 锁、OSError 只 warning（fail-open） | P1 | GLM-5.3 实施 lane（M2-A 批次二附加） | BUG-01 | open | 纳入 strict 覆盖；负测：锁不可用时公开入口拒写（strict）；主账本成功+事件失败 → 显式 event_append_failed 不回滚不谎称成功；锁序无嵌套死锁测试（设计 §3.2-6，P1-6） |
| BUG-06 | 11-15 P0-1 未修：_override_authorized 把自报 reason+refs 当授权（goal 域；子代理 C 实证）；P0-2 部分修：create_goal 显式 session_id 按原文采信 [tools_goal.py:394-396]，不一致时才拒（本会话 01:08 实测拒 ✓）。上游 11-15 定级 **P0，本队列不降级** | **外部 P0 / HOLD 依赖（不阻 M1/批次一，P2-1）** | 独立授权任务（不在本 Goal） | 用户授权+独立设计 | HOLD-ref | 移交：作为 M2-B/M4-B 解除 HOLD 的前置；本 Goal 只引用不修；不阻塞批次一任何 GO 项 |
| BUG-09 | 设计 v1.2 §3.2-3/§3.3 将 close 纳入跨 Goal 路径重叠硬拒——close 是终态释放（只减不增占用），误拒将使 lane 永远无法收口（GPT-6 主统筹 2026-11-16 01:34 复审意见(1)） | P1（批次二前置） | GLM-5.3 实施 lane（M2-A，批次二） | BUG-01/02 | in-design（v1.3 已修 §3.2-3/§3.3） | 批次二实施: 跨 Goal 重叠判定仅作用于 create/update（引入/扩大占用）；close 不因现有重叠被拒、仍受 strict 锁串行保护；负测=两 active lane paths 重叠时 close 其一必须成功（RULE-AI-35 实测应拦误拒） |
| BUG-10 | 设计 v1.2 §2.2 legacy next_command 兼容保留与「unknown/degraded 禁发写命令」间存在安全例外缺口（GPT-6 主统筹 2026-11-16 01:34 复审意见(2)） | P1 | GLM-5.3 实施 lane（M1，批次一 Lane A） | BUG-03/04 | closed（PR#42 合并 96098972f） | M1 实施: legacy next_command 结构兼容但来源不完整/降级时必须安全降级（不得携带写命令）；新增 actionable_next_command/safe_to_execute 显式字段；负测=坏源下 next_command 含 requeue/rebase/merge → fail、safe_to_execute=false 断言 |
| BUG-11 | _coordination_goal_entry 无条件调用 _closure_projection: 真实账本 299 goal 中 107 个 closure 投影、其中 99 个 status=complete 被建议「可收口」（GPT-6 2026-11-16 06:32 复审实测；本 run 同参复现 candidate=107/complete=99） | P1 | 主代理（A 子代理 SSL 熔断后父代单 writer 接管收口） | 无 | closed（PR#42 合并 96098972f；修复提交 b9ed9aad5 已在 main） | 已修 @ feat/batch1-m1m3-coord-dual-track b9ed9aad5: 调用点加 status=='active' 门（goal_gates 判据与既有 API 不变，unknown status 同样不投影）；修复后同账本 candidate=8/pending_evidence=36 全 active；新增负测 complete（三道门全过）与 paused（GOAL_STATUSES 外历史值）均不投影；定向 42 passed（原 40+2）、邻接 122 passed、Ruff PASS、Pyright(src) 0 errors；待冻结集成候选复核后走 R9+Reviewer 转 verified |
| BUG-12 | GLM-5.3 Provider 连续 3 次 SSL EOF: 上一父 Run 失败、A 子代理 subagent_2bf76d0da8a8 熔断（3 文件未提交滞留 worktree，父代核对后收口；B 子代理 subagent_745c0a665342 正常完成）（用户 2026-11-16 06:32 裁决转述） | P1（并行开发可用性） | 主代理/宿主 | 无 | open | 下次 spawn 前单次探活+明确重试预算（熔断≠无界重试）；父代单 writer 降级路径本 run 已实测可用；机制级退避重试待用户裁决（守 §7 无界重试边界） |
| BUG-14 | 生产 lanes.jsonl 历史重复 lane_id lane-selftest-guard（行 11 active v1 / 行 12 closed v2，goal=GOAL-SELFTEST、paths=[]、branch=selftest、owner_session_id=selftest-other-session —— 旧测试残留，非真实在途 lane）→ R5 实测 failed=35（历史 34 + 活待办 1）、unknown=0、坏行 0、source_complete=false → 写命令建议全量安全降级（M1 保守分类按设计工作，属数据侧历史脏行） | P1 | owner（用户）；**本 Goal 不改生产审计账本** | BUG-03（M1 分类）/BUG-07（同 lane 冲突面）/BUG-16（读取侧聚合） | 读取侧 fixed（PR#48 73e5053c3）；账本行 open-ref | 已实证：备份 data/backups/lanes-20261116T153712.jsonl，sha256=06aa90ed…（与现账本一致，未删历史）。修法三分：a) Board 聚合按 lane version 取最大 → inflight 14→13（**done**，PR#48）；b) LaneStore.list() 版本语义 = lane.py 单 writer（M2-A，HOLD）；c) 生产账本纠正/归档双行 = owner 书面批准后单独动作。处置前写命令建议维持安全降级为预期行为 |
| BUG-15 | e162e1c3d 原版 ci_gate.sh 真实 exit=1：test_function_lines_ratchet_within_baseline 1 failed——coordination_snapshot 登记 119→实测 122（增长 3）、_collect_merge_queue 166/_coordination_goal_entry 143/render_coordination 133/run_lane_queue_submit 120 均 ≥120 未登记（日志 /tmp/lfl-batch1-r9-e162e1c3d.log；同轮 WebUI 600 passed、pytest tier0 340P/1F/2S——属新增功能引入的可修结构问题，非存量债） | P1（新功能引入，已修） | LFL 父代理（单 writer，本会话） | 无 | closed（PR#42 合并 96098972f 内含 ecac7aecf） | 最小无行为重构（不重登记 baseline、不改 guard/测试）: 抽 10 个 helper（_frontier_projection/_stalled_hint/_closure_for_active/_queue_buckets/_merge_queue_degraded_block/_lane_source_health/_project_queue_item/_goals_truncated_note/_render_goal_m3_lines/_contract_same_key_hint_note，均 <120 行）；5 目标 122/166/143/133/120→113/101/96/109/100；回执: arch_guards 52 passed（RED→GREEN）、邻接 27 文件 454 passed、ruff check 0、两文件 pyright 0 errors（src 存量 8 errors 在未触碰文件）、format 规范化后与 HEAD 逐字节一致（纯搬移）、diff --check clean、git_security_scan passed |

| BUG-16 | Board 把本机 worktree HEAD 当 main：`_probe_git_head` 用 `git -C <workspace_root> rev-parse HEAD` 填 main_head——根 worktree detached 于 3e0202b5b（=PR#44 合并 head，当时落后 origin/main 37 提交），而 desired/live 均 b7aef87b → 回执 in_sync=false / sync_state=mismatch，属**假告警**（2026-11-16T15:33+08 以 build_board('data/audit', workspace_root='.') 复现） | P1（误导运维/收口） | 父代理（单 writer，lane_board.py） | BUG-14（同文件聚合语义） | fixed @ PR#48 merge 73e5053c3（GitHub CI success，已入 main） | 真实契约：① `versions.worktree{head,ref,detached,behind_main}` 与 `versions.main{head,source∈explicit\|local_tracking\|unknown,ref,remote_verified=false,freshness=unknown}` 分开——origin/main 只是本地 remote-tracking ref，不得声称"远端已验证"；② `versions.desired{generation,sha,deployment_id,source}` 与 `versions.live{sha,recorded_at,source,authoritative}` 只由权威源填充，缺失即 unknown、不拿 live 或 checkout 顶替；③ 非法/非 40-hex 的 main_head → main.head=""、behind_main=None、degraded 记 main_head_unknown，含 NUL 的显式值在任何 subprocess 前被拒；④ origin/main 必须 `^{commit}` peel（坏 ref 指向 blob/tree 不再被当 main）；⑤ `deployment.deployed_sha` 按既有消费契约原样保留（test_coordination_routes 钉 12 位短 sha），版本身份只由 versions.*.sha 主张；⑥ 探针按 strict UTF-8 解码，坏字节降级 unknown 而非抛错/乱码；⑦ behind_main 只对"Board 实际报告的 main"计算。负测：detached 落后 worktree + 同步部署不得报 mismatch |

## P2（登记不阻塞）
| ID | 证据 | 严重度 | owner | 依赖 | 状态 | 下一动作 |
|---|---|---|---|---|---|---|
| BUG-07 | 旧在途 lane paths=[]（lanes.jsonl 行 11 lane-selftest-guard active；行 12/18 终态）→ 冲突面 unknown，enforce 模式不得误报无冲突；selftest lane **未经 owner 核验不得自动清理/改判**（P1-3） | P2 | GLM-5.3 实施 lane（M2-A 批次二负测） | BUG-02 | open | 负测: 对 paths=[] 在途 lane 造 create，断言回执 unknown 非无冲突且**登记待办**（不长期静默放行）；owner 处置 selftest lane 为独立人工动作，本 Goal 不自动清理 |
| BUG-08 | 本地主树曾与 origin/main 分叉（ahead10/behind33）且脏（未跟踪设计文档）——**定性: 集成前置阻断（非业务 bug，P2-1）** | **集成前置阻断** | 主代理（移交用户裁决） | 用户 | closed（改走远端 PR 路径，未动本地主树） | 收敛事实：批次一/二全部改动改由**远端 PR**合入 origin/main（PR#42/#48），本地主树不做 merge/reset；本地主树仍 detached 于 3e0202b5b 并含其他任务未跟踪文件，属**独立遗留**、不阻塞 S0（S0 以 origin/main=40ba2d9 为 base）；本 Goal 不再触碰本地主树 |
| BUG-13 | 子代理熔断交接护栏缺口: A 熔断时无「崩溃前提交/移交」机制，3 文件未提交滞留 worktree，需父代逐文件核对归属后收口；另实测沙箱内从 worktree cwd 执行 git commit 因主仓 .git/worktrees/* 元数据写被拒（index.lock EPERM），须从主仓根以 git -C 执行 | P2（机制缺口，不阻批次一） | 主代理 | BUG-12 | open | 两个事实供机制优化: spawn 任务书要求阶段提交（熔断前已落盘）；沙箱 git 调用姿势写入任务书模板。不改运行时代码 |

## LCLOSE-1 Lane 收口核验批次（2026-11-16T21:00+08，基线 origin/main=40ba2d9）

- 基线：origin/main=`40ba2d91710916d5d21331e1faa97487b6477bf0`，其父提交 `73e5053c3` 即 W1 PR#48 合并提交（W1 已在祖先链内）。service_control desired generation=426，code_root=`.releases/40ba2d9…`；web/feishu/learning/wecom 四服务 alive、`git_head=40ba2d9…`、`matches_desired_generation=true`、admission barrier 为空。
- 边界：本批只做**追加式** lane 终态（append-only CAS），不改历史行、不改 goal 账本、不改生产审计文件。

### D1 本 Goal 已收口 lane（逐条核验后 close）
| lane | 核验依据 | 终态 |
|---|---|---|
| lane-3745d912（M1/M3） | PR#42 merge `96098972f`（second parent `115a4d3ce` 在 main 祖先链）；分支 `b9ed9aad5` 与 main patch-equivalent（git cherry 未上游=0） | closed→merged (v2) |
| lane-ab6ad3da（M4-A） | 同 PR#42；main 内四处接线实证：`lane.py` contract_same_key_hint、precheck 挂载、`tools_lane.py`、`tools_merge_queue.py` | closed→merged (v3) |
| lane-78e5bf89（批次一集成 lane） | 记录 head `115a4d3ce` 本身即 main 祖先 | 原已 merged，未重复动作 |
| lane-523dfae6（W1 Board 版本条带） | PR#48 MERGED（merge `73e5053c3`）；分支 cherry 未上游=0；push CI + 合并后 CI success；generation 426 上线 | closed→merged (v4) |
| lane-d6ceb9dd（设计正本/队列） | 设计正本 blob 与 main 完全相同；队列内容经本 PR 修订后合入 | 本 PR 合并后 closed |

### D2 其他 Goal 的 lane：只读核验，不做任何动作
| lane | 观测事实 | 处置 |
|---|---|---|
| lane-193be56b / lane-694a0b00 / lane-8f8c539c / lane-deb190f7 | 记录 head `49de82a5f` / `03f68de45` / `9dc015944` / `375495909`，均为 origin/main 祖先 | 仅记录；跨 Goal 关闭须该 Goal owner 授权，本队列不代决 |
| lane-a8e26601 | PR#44 已 merged，但账本 head `8a619a9f5` 未入 main（合并后新提交） | **不得关闭**；待其 owner 决定合并或撤回 |
| lane-939514f6 / lane-a4e7865d / lane-492d8ed9 / lane-d19cb525 | 无 in-main 证据 | 只读，不动 |

### D3 未终态 Goal 口径（禁止批量关闭）
goals 账本约 300 条唯一 Goal、未终态约 88；本批**不关闭任何其他 Goal**，只在证据满足时关闭本 Goal。

### D4 发布回执口径（docs-only 与已部署代码分离）
已部署代码 SHA=`40ba2d9…`（generation 426，四服务 verified_converged）。若 main 后续仅前进 docs/队列类提交（如本 PR），**不重复触发四服务重启**；发布回执同时记录两条事实：已部署代码 SHA 与 docs-only main HEAD——禁止用后者冒充已部署代码，也禁止用前者掩盖文档落后。

### D5 下一门禁
本批为 docs-only（仅 docs/queues 两文件）：门禁 = 隐私/A.5 提交门 + 独立 Reviewer + 原版完整 R9（仓库无 docs-only 豁免，真实执行一次）+ 远端 CI 全绿；不重启服务、不改运行时代码。批次二代码（M2-A lane.py 锁/跨 Goal 冲突）仍 HOLD，等 GPT-6 复审。

## HOLD（不做，防范围扩大）
- 同 Goal 写入强门（M2-B）、结构化契约硬门（M4-B）、任何自动清理/自动完成/第五套账本/常驻编排器/自动审批/无界重试——依据设计正本 §4/§7。
