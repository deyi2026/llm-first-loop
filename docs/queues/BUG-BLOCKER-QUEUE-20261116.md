# BUG/阻断队列（多 Agent 协作 v1.1）— 2026-11-16

- 真值源: 设计正本 docs/design/DESIGN-20261116-multiagent-coordination-closure-v1.md（§证据索引，行号基线 origin/main 9e6b438cc）
- 字段: ID | 证据 | 严重度 | owner | 依赖 | 状态 | 下一动作
- 状态机: open → in-design → ready(待实施) → fixed(待审) → verified(R9+Reviewer 过) → closed；HOLD 项单列
- 行号引用为当前基线快照，实施时按 task_state/子代理报告复核偏移

## P0（先行）
| ID | 证据 | 严重度 | owner | 依赖 | 状态 | 下一动作 |
|---|---|---|---|---|---|---|
| BUG-01 | lane.py:761-766 `_file_lock` OSError→warning+yield（fail-open，无 threading 锁）；docstring:748 自认 | P0 | GLM-5.3 实施 lane（M2-A） | 无 | open | M2-A: 增加 lock_strict（默认 off=warn 兼容）；strict 下 raise 拒写；RULE-AI-35 负测：注入锁不可用实测应拦 |
| BUG-02 | 跨 Goal 路径冲突检查缺失+TOCTOU：precheck [463-509] 只警告且在 create 前锁外；_assert_unique [538-555] 完全不看 paths；历史重复实证 lanes.jsonl 行 50/51（.github/workflows/ci.yml+pyproject.toml 跨 Goal） | P0 | GLM-5.3 实施 lane（M2-A） | BUG-01（须先在同一真实锁内） | open | create [194-195 间]/update [268-272 间] 锁内扫描在途 lane paths；跨 Goal warn/enforce（enforce 默认 off）；同 Goal 仅警告；paths=[]→unknown 不误报 |
| BUG-03 | goal_coordination.py:797-821 `_lane_status_map` 读失败→空 dict 与账本真空同形、坏行 [813-816] 静默；895-898 lane_state=""→is_terminal=False；845-846 对已 merged lane 发可执行命令（lane map 空时终态护栏失效） | P0 | GLM-5.3 实施 lane（M1） | 无 | open | M1: health{read_ok,bad_rows} 暴露+来源未知独立类别+未知项不发动作命令 |

## P1
| ID | 证据 | 严重度 | owner | 依赖 | 状态 | 下一动作 |
|---|---|---|---|---|---|---|
| BUG-04 | R5 四桶混计历史终态项：实测 35 failed=34 历史+1 活待办；closure 恒等式 [921-924] 缺 terminal/unknown 项；桶默认 human [893] | P1 | GLM-5.3 实施 lane（M1） | BUG-03 | open | 恒等式改 bucket_sum==failed_total−terminal_total−unknown_total；渲染三分行；测试 188-234/291-315 同步 |
| BUG-05 | lane.py:607-616→704-712 公开 append_lane_event 写 lane_events.jsonl 不持 lanes 锁、OSError 只 warning（fail-open） | P1 | GLM-5.3 实施 lane（M2-A 附加） | BUG-01 | open | 纳入 strict 覆盖；负测：锁不可用时公开入口拒写（strict） |
| BUG-06 | 11-15 P0-1 未修：_override_authorized 把自报 reason+refs 当授权（goal 域；子代理 C 实证）；P0-2 部分修：create_goal 显式 session_id 按原文采信 [tools_goal.py:394-396]，不一致时才拒（本会话 01:08 实测拒 ✓） | P1 | 独立授权任务（不在本 Goal） | 用户授权+独立设计 | HOLD-ref | 移交：作为 M2-B/M4-B 解除 HOLD 的前置；本 Goal 只引用不修 |

## P2（登记不阻塞）
| ID | 证据 | 严重度 | owner | 依赖 | 状态 | 下一动作 |
|---|---|---|---|---|---|---|
| BUG-07 | 旧在途 lane paths=[]（lanes.jsonl 行 11 lane-selftest-guard active；行 12/18 终态）→ 冲突面 unknown，enforce 模式不得误报无冲突 | P2 | GLM-5.3 实施 lane（M2-A 负测） | BUG-02 | open | 负测: 对 paths=[] 在途 lane 造 create，断言回执 unknown 非无冲突 |
| BUG-08 | main 与 origin/main 分叉 ahead10/behind33、主工作树脏（未跟踪 docs/DESIGN-20261115-knowledge-…md） | P2 | 主代理（移交用户裁决） | 用户 | open-ref | 不在本 Goal 处理；合并任何 lane 前需先收敛分叉（rebase/取舍），否则 S0 base_main_current 恒 stale |

## HOLD（不做，防范围扩大）
- 同 Goal 写入强门（M2-B）、结构化契约硬门（M4-B）、任何自动清理/自动完成/第五套账本/常驻编排器/自动审批/无界重试——依据设计正本 §4/§7。
