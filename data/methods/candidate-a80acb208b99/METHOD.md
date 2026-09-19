---
method_id: candidate-a80acb208b99
name: 会话级知识层双向同步（开局检索·使用裁决·收尾结算）
description: 每个真实任务对经验/方法库做一次双向同步：开局检索+一行裁决、使用时显式标注、收尾结算+实录。打破慢记忆"只有单向写"的死锁。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:feae84dd-a346-494a-b79b-f0b5708ed2c6:83:40833e4af7d01d3a843e
created_at: 2026-09-11T05:57:04.585357+00:00
updated_at: 2026-09-11T05:57:04.585357+00:00
---
# 目的
让经验库/方法库（慢记忆）与当前会话（快记忆）在真实任务上双向同步一次，打破"只有单向写"死锁：条目未评估→命中不可信→被忽略→永不产生使用记录。

# 触发条件
用户指令要求产出外部结果（代码/文档/调研/分析/修复等）的**真实任务**。元讨论、闲聊、对记忆系统本身的操作不触发。

# 开局门（任务启动后第一组动作内）
1. 确认任务为真实任务。
2. `search_records(kind=method)` 与 `search_records(kind=experience)`，各 1~2 个领域关键词，limit≤5，有界成本。
3. 对每个命中写**一行**裁决：适用 / 不适用 / 存疑 + 一句理由。
4. 未评估条目一律按"假设"内化，绝不作为指令或既定事实。

# 使用时（命中影响决策的瞬间）
在回复中显式写明：该依据来自库的哪一条 + 裁决结论。一句话，不写报告。

# 收尾结算（任务完成时）
1. method：对实际走完的候选执行 `record_qualification`，填 mechanism / task_benefit / promotion 三个独立裁决 + evidence_refs。
2. experience：被证伪或过期的命中**当场** `refine_experience(archive)`，不推迟。
3. 入口门槛：仅当存在真实证据链（具体任务的观察 + 因果）才 `save_experience` / `save_candidate`，否则不入库。
4. 产出实录：开局查了什么、命中什么、逐条裁决、收尾结算了什么、库里净变化。

# 诚实边界
- 无 runtime 级强制，本协议依赖开局门自身的检索动作自举（检索 method 库即可命中本协议）。
- 合规性依赖 action_trace 事后审计，不声称自动执行。
- 本协议自身在试点结束后同样走 `record_qualification`，不豁免。
