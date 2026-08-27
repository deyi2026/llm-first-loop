# Tasks: 注入生命周期 Turn 级快照（EVO-20260827-ed4c1350 批次1：P0-A + P0-B）

- 来源: 三方综合裁决定稿（GPT 原审 × DM 核验 × CodeArts 复核），口头审批生效（RULE-AI-06 accepted）
- 范围: P0-A（memory + experience 双通道 turn 级快照）+ P0-B（effective budget 口径暴露）
- 排除: P1-A Turn Runtime Delta（刻意排在 P0-A 实测验证之后）、Evidence canary（P0-A 后启动）、契约文档（批次1 伴随产物）

## 背景数据（收口基线）

- 实测会话 09c44093: persisted_injection 67 条 / 54,630 字符 / 单帧最大重复 x18（memory 类）与 x10（experience 类）
- 根因: 检索注入挂在 round 循环内（engine.py:465-516 每轮重检索+append；tool_exec.py:244 每 tool round 触发 tip），尾部 8 条文本比对幂等窗口被 round 内消息滑出
- 设计简化: turn 边界天然存在——run() 结构 = user append（422-423）→ round 循环（449），一次 run = 一个 user turn = N 个 tool rounds

## T1: engine.py — memory turn 级快照

- 落点: engine.py 427 行（interruption_recovery 注入后）与 449 行（round 循环前）之间
- 行为: 检索一次 build_memory_messages → 包装（无 anchor 保字节稳定）→ append 单条
- metadata: `injection_kind=memory_snapshot` + `turn_ref`（user_msg 在 sess.messages 中的 seq）+ `query_fp`
- 迁移: 465-516 round 内每轮检索整体上移到入口；fail-open 回退路径保留并一并上移
- 幂等: `turn_ref + injection_kind` 全局查重（替换尾部 8 条文本比对）
- 语义冻结: `_runtime_memory_top_k()` 等动态入参在 turn 入口取值一次（快照语义，run 中途 adjust_strategy 不影响本 turn）

## T2: tool_exec.py — experience tip 同型修复

- 注入条件增加"本 run 未注入过"（run 级 flag，run 入口重置，仿 engine.py:438 `_reset_overflow_state` 模式）
- metadata 增加 `turn_ref`（与 T1 同源）

## T3: P0-B — architecture_status 暴露 effective budget

- `architecture_status.context_usage` 输出 `effective_budget + limited_by`
- 归因来源: routing.py `_effective_history_budget` 的 min() 链（global / provider_budget / model_window）
- 展示字段: configured_global_budget / provider_budget / physical_window_budget / runtime_override / effective_budget / limited_by

## T4: 测试 oracle — 新建 tests/unit/test_memory_turn_snapshot.py

- 用例1: 同 run 模拟 10+ tool rounds → memory 注入恰 1 条；experience tip 同理
- 用例2: 新 run（新 user message）→ 允许新 snapshot；重试轮不膨胀
- 用例3: 旧 session 消息无 turn_ref → 零回归（读写路径兼容）

## 验证标准（量化收口）

- 复跑同类多轮任务: persisted_injection 总数 ≤ user turn 数，单帧重复 ≤ 1 次（对照基线 67/x18）
- 全部单测绿 + 既有测试零回归（ruff 通过）
- 命中率不劣化（注入点收敛后前缀更稳）

## 收口方式（定稿裁决）

1. P0-A 实测通过 → P0-B
2. 与 worktree 现有 14 个未提交文件分 commit 一起提审（同主题前置修复）
3. 用户批准后应用主区