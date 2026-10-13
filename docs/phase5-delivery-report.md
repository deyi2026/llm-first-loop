# Phase5 交付报告：流式打断 + P2-4 混合路径戳记时序修复

- 日期：2026-10-13　状态：交付（M4 全量回归与发布验证见 §4/§5）
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
- （待填：pytest 全量 N passed + ruff 0 error 回执）

## 5. 发布与验证
- （待填：git 提交、publish、真机抽查结果或阻塞说明）

## 6. 遗留与 Phase6 候选
- 流式打断仅在 chat_stream 通道生效；同步 chat（第三方 client）保守路径
  兜底（设计 §8 非目标，如需可评估异步化）。
- 打断轮 usage/reasoning 不完整归集属打断固有（与 cancelled 同口径）。
- G1 真实用户形态 t_effect（注入→检查点等待窗 ≤90ms 量级）未在真机量化，
  真机抽查见 §5。
