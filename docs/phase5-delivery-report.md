# Phase5 交付报告：流式打断 + P2-4 混合路径戳记时序修复

- 日期：2026-10-13　状态：交付完成（全量回归+发布+真机抽查收口，§4/§5）
- 设计：docs/phase5-stream-interrupt-design.md（r2 定稿 + §10 实施修订）
- 上游遗留处置：Phase4 交付报告 §5.3（P2-4）/§5.4（llm_stream 桶）

## 1. 交付内容

### 1.1 P2-4 混合路径戳记时序修复（M1）
- `tool_cycle.py`：`last_receipt_interrupted` 置位前移至轮内 gap 消费 ack 之前
  （recorded_results 构建后）。「同轮打断+剩余 skipped」混合路径的 ack 不再读
  上轮残值；S18-M1（正向 True）/S18-M2（反向 False）双向锁定，red→green 证据
  完整（回退修复 2 failed → 恢复 2 passed）。
- 语义零变化：仅真相源时序修正；Phase4 S13/M2/M3 回归全绿。

### 1.2 LLM 流内插话打断（M2）
- engine 流内检查点：每 delta 后（Stop 优先 → 插话次之），节流 ≥40ms，
  `LLM_STREAM_INTERJECT_CHECKPOINT` 配置级开关（关闭=保守 final_gate 回退）。
- 打断收割路径：半截产物如实落盘（`interjection_interrupted`，P1-6 不伪装
  完整）→ close 流 → settle INTERRUPTED + attempt 收口 → 轮边界消费
  （via=llm_stream_interrupt）→ 下一轮 LLM 历史含插话 user 消息（半截行按
  既有中断行退役纪律不进 provider 投影）。
- P2-5 轮首复位：复位置于轮内消费点**之后**（保留 interruptible 桶口径），
  消除其后跨轮/跨 run 残值（S18-M3 锁定）。
- 戳记双保险：新 via 消费点 interrupt_receipt 恒 False + 桶派生判序最前；
  汇总桶集合扩为五桶（+llm_stream_interrupt），Phase4 四桶语义不变。
- FakeLLM 可选 chat_stream（缺省关闭）+ 确定性注入钩子（跨线程事件同步）。

### 1.3 场景与度量（M3）
- tests/phase5/：S17-M1/M2（打断生效+半截语义）、S17-M3（stop 优先）、
  S17-M4（开关关闭保守回归）、S18-M1/M2/M3（P2-4 双向+跨 run 复位）。
- reports/phase5/m3/：G1 llm_stream_interrupt n=10 P50=3.7ms/P95=6.2ms
  （确定性钩子下界口径，门 500/900）；G2 保守路径 n=10 P50=919.6ms
  （门 1550，Phase4 基线 1240 同形态不回归）。

## 2. 设计评审与实施修订
- 独立子代理评审（实读代码）：2 blocking/6 question/8 comment 全处置，
  映射留设计 §10；实施期 5 项修订（复位位置、S18-M2 构造、桶集合断言、
  FakeLLM 线程模型、runner 终报形态）留 §10 实施修订记录。

## 3. 不变量回归
- 消息必达/停止四态/D 红线/P1-6：S17-M3（含打断后 stop 变体）、Phase4
  M2/M3 全组回归绿；全量回归见 §4。

## 4. 全量回归
- pytest 全量（tests/，除度量场景外的 gate 复验组另计）：Phase4+Phase5 场景
  26 passed；gate 复验组（env_access/static_diagnostic 等）30 passed。
  初跑 4 个 gate 失败已归零：根因=engine 模块级 os.environ 违反环境访问门，
  已改走 config.py 集中装配（settings.tool_runtime.llm_stream_interject_
  checkpoint）；另 tests/web/test_knowledge_endpoints.py F841 为前会话已提交
  遗留（gate 阻塞），一行最小修复（语义保留）。
- ruff：本任务改动面 0 error（全仓 4350 为历史存量，非本任务引入，不在
  本阶段清偿范围）。

## 5. 发布与验证
- 提交：62602acca（phase5 交付，含设计/测试/报告）。
- 发布：publish generation=251（deploy-7988bde9a99b4ed6832f98bd481405d6，
  git_head=62602acca，webui 产物 sha 绑定）；web restart 动作
  svc-b1aafbdaf1e946c1b908ee0be39e99e4 已 succeeded（2026-10-13T14:26:15，
  generation=251 lag=0，pid 35147 存活，matches_desired_generation=true）。
- **真机抽查**（S17 等效流式打断 + hq 戳记核验，2026-10-13T14:36，glm-5.3
  真实流，新会话单发一次命中；工件 reports/phase5/m4/s17-realtime-spotcheck.json）：
  - 打断生效：answer 流中注入（queue 202→interject 202）→ hq 条目
    status=interject_received、**consumed_via=llm_stream_interrupt**、
    grade=applied；**t_effect=93.0ms**（t_ack 6.4ms + 检查点窗 86.6ms），
    门 ≤500ms 达成，真实形态与 §6「≤90ms 检查点窗量级」预测相符
    （n=1 抽查口径，桶内如实标注 insufficient_sample）。
  - hq 戳记：条目无 interrupt_receipt 键（mark_interject_received 仅 True
    落键，human_turn_queue.py:411——与 S17-M1 锁定口径「is not True」一致）；
    桶派生五桶在位，新桶 llm_stream_interrupt n=1、p50=p95=93.0ms，判序最前
    （human_turn_queue.py:619 代码核实）；P2-4/P2-5 混合与跨轮路径由 S18
    三场景单测锁定。
  - 半截语义（P1-6）：会话半截行 1 条（metadata.llm_interrupted +
    partial_chars/interrupted_text_tail/truncation_artifact_ref 在位，尾部
    标注 reason=interjection_interrupted）；插话 user 消息入会话；事件审计
    llm.interrupted(seq28)→message.appended(seq29) 如实落盘。
  - 续答语义：打断后同 run 续流 49 delta，终答主动确认「按您的最新要求：
    主题改为海雾」——下一轮真实消费插话（半截行不进 provider 投影的 B1 纪律
    由 S17-M2 单测锁定，真机以续答方向变化为外部证据）。

## 6. 遗留与 Phase6 候选
- 流式打断仅在 chat_stream 通道生效；同步 chat（第三方 client）保守路径
  兜底（设计 §8 非目标，如需可评估异步化）。
- 打断轮 usage/reasoning 不完整归集属打断固有（与 cancelled 同口径）。
- G1 真实用户形态 t_effect 已真机抽查量化：93.0ms（§5，n=1 单发抽查；
  批量统计口径仍以 m3 确定性钩子下界 P50=3.7ms 为准）。
