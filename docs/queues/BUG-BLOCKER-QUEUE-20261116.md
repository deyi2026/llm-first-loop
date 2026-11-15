# BUG/阻断队列（多 Agent 协作 v1.3）— 2026-11-16

- 真值源: 设计正本 docs/design/DESIGN-20261116-multiagent-coordination-closure-v1.md（§证据索引，行号基线 origin/main 9e6b438cc）
- 字段: ID | 证据 | 严重度 | owner | 依赖 | 状态 | 下一动作
- 状态机: open → in-design → ready(待实施) → fixed(待审) → verified(R9+Reviewer 过) → closed；HOLD 项单列
- 行号引用为当前基线快照，实施时按 task_state/子代理报告复核偏移

## P0（先行）
| ID | 证据 | 严重度 | owner | 依赖 | 状态 | 下一动作 |
|---|---|---|---|---|---|---|
| BUG-01 | lane.py:761-766 `_file_lock` OSError→warning+yield（fail-open，无 threading 锁）；docstring:748 自认 | P0 | GLM-5.3 实施 lane（M2-A，批次二） | 无 | open | M2-A: 增加 lock_strict（默认 off=warn 兼容）；strict 下 OSError/锁实现导入失败/锁文件不可写 → create/update/close **三入口一致** raise 拒写；RULE-AI-35 负测：注入锁不可用实测三入口应拦（设计 §3.2-1） |
| BUG-02 | 跨 Goal 路径冲突检查缺失+TOCTOU：precheck [463-509] 只警告且在 create 前锁外；_assert_unique [538-555] 完全不看 paths；历史**声明**重复实证 lanes.jsonl 行 50/51（仅证告警价值，**≠同时写入事故**，P2-1） | P0 | GLM-5.3 实施 lane（M2-A，批次二） | BUG-01（**INV-1**: enforce 硬依赖经核验 strict 锁；enforce=true+strict=false → 拒绝启用） | open | create/update/close 三入口锁内扫描在途 lane paths；跨 Goal warn/enforce（enforce 默认 off，**无 force 放行参数**——模型仅可申请 owner 复核/缩小自身 paths/等待对端终态，不自报批准，P0-2）；同 Goal 仅警告；paths=[]→unknown 不误报且登记待办不长期放行；路径规范化按设计 §3.2-4（repo-root 绑定/reject/unknown 规则） |
| BUG-03 | goal_coordination.py:797-821 `_lane_status_map` 读失败→空 dict 与账本真空同形、坏行 [813-816] 静默；895-898 lane_state=""→is_terminal=False；845-846 对已 merged lane 发可执行命令（lane map 空时终态护栏失效） | P0 | GLM-5.3 实施 lane（M1，批次一） | 无 | open | M1: health{read_ok, bad_rows, duplicate_lane_ids, invalid_status_rows} 暴露；来源未知独立类别（**保守 unknown**: 不在账/读失败/坏 JSON/非 dict/重复 lane_id 冲突/无效 status，P1-2）；source_complete 与 parsed_closure_ok 分离；未知/降级项不发写操作命令（设计 §2.2 B/C） |

## P1
| ID | 证据 | 严重度 | owner | 依赖 | 状态 | 下一动作 |
|---|---|---|---|---|---|---|
| BUG-04 | R5 四桶混计历史终态项：实测 35 failed=34 历史+1 活待办；closure 恒等式 [921-924] 缺 terminal/unknown 项；桶默认 human [893] | P1 | GLM-5.3 实施 lane（M1，批次一） | BUG-03 | open | 双轨（设计 §2.2 A/B，P1-1）: legacy 字段原口径全保留（closure_ok/bucket_sum/failed_total 原值不动，现有测试不改）；新增 actionable_*/unknown_total+新恒等式 actionable_bucket_sum==failed_total−terminal_total−unknown_total **只作用于 actionable 轨**；渲染三分行置前+legacy 行保留；新增双轨断言测试 |
| BUG-05 | lane.py:607-616→704-712 公开 append_lane_event 写 lane_events.jsonl 不持 lanes 锁、OSError 只 warning（fail-open） | P1 | GLM-5.3 实施 lane（M2-A 批次二附加） | BUG-01 | open | 纳入 strict 覆盖；负测：锁不可用时公开入口拒写（strict）；主账本成功+事件失败 → 显式 event_append_failed 不回滚不谎称成功；锁序无嵌套死锁测试（设计 §3.2-6，P1-6） |
| BUG-06 | 11-15 P0-1 未修：_override_authorized 把自报 reason+refs 当授权（goal 域；子代理 C 实证）；P0-2 部分修：create_goal 显式 session_id 按原文采信 [tools_goal.py:394-396]，不一致时才拒（本会话 01:08 实测拒 ✓）。上游 11-15 定级 **P0，本队列不降级** | **外部 P0 / HOLD 依赖（不阻 M1/批次一，P2-1）** | 独立授权任务（不在本 Goal） | 用户授权+独立设计 | HOLD-ref | 移交：作为 M2-B/M4-B 解除 HOLD 的前置；本 Goal 只引用不修；不阻塞批次一任何 GO 项 |
| BUG-09 | 设计 v1.2 §3.2-3/§3.3 将 close 纳入跨 Goal 路径重叠硬拒——close 是终态释放（只减不增占用），误拒将使 lane 永远无法收口（GPT-6 主统筹 2026-11-16 01:34 复审意见(1)） | P1（批次二前置） | GLM-5.3 实施 lane（M2-A，批次二） | BUG-01/02 | in-design（v1.3 已修 §3.2-3/§3.3） | 批次二实施: 跨 Goal 重叠判定仅作用于 create/update（引入/扩大占用）；close 不因现有重叠被拒、仍受 strict 锁串行保护；负测=两 active lane paths 重叠时 close 其一必须成功（RULE-AI-35 实测应拦误拒） |
| BUG-10 | 设计 v1.2 §2.2 legacy next_command 兼容保留与「unknown/degraded 禁发写命令」间存在安全例外缺口（GPT-6 主统筹 2026-11-16 01:34 复审意见(2)） | P1 | GLM-5.3 实施 lane（M1，批次一 Lane A） | BUG-03/04 | in-design（v1.3 已修 §2.2/§2.3） | M1 实施: legacy next_command 结构兼容但来源不完整/降级时必须安全降级（不得携带写命令）；新增 actionable_next_command/safe_to_execute 显式字段；负测=坏源下 next_command 含 requeue/rebase/merge → fail、safe_to_execute=false 断言 |

## P2（登记不阻塞）
| ID | 证据 | 严重度 | owner | 依赖 | 状态 | 下一动作 |
|---|---|---|---|---|---|---|
| BUG-07 | 旧在途 lane paths=[]（lanes.jsonl 行 11 lane-selftest-guard active；行 12/18 终态）→ 冲突面 unknown，enforce 模式不得误报无冲突；selftest lane **未经 owner 核验不得自动清理/改判**（P1-3） | P2 | GLM-5.3 实施 lane（M2-A 批次二负测） | BUG-02 | open | 负测: 对 paths=[] 在途 lane 造 create，断言回执 unknown 非无冲突且**登记待办**（不长期静默放行）；owner 处置 selftest lane 为独立人工动作，本 Goal 不自动清理 |
| BUG-08 | main 与 origin/main 分叉 ahead10/behind33、主工作树脏（未跟踪 docs/DESIGN-20261115-knowledge-…md）——**定性: 集成前置阻断（非业务 bug，P2-1）** | **集成前置阻断** | 主代理（移交用户裁决） | 用户 | open-ref | 不在本 Goal 处理；批次一/批次二任何合并前必须先由用户裁决收敛分叉（rebase/取舍 10 个本地提交），否则 S0 base_main_current 恒 stale；该阻断**不改变任何 M 的 GO 判定**（只挡合并不挡实施） |

## HOLD（不做，防范围扩大）
- 同 Goal 写入强门（M2-B）、结构化契约硬门（M4-B）、任何自动清理/自动完成/第五套账本/常驻编排器/自动审批/无界重试——依据设计正本 §4/§7。
