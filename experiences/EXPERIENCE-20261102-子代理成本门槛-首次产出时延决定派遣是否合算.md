---
title: 子代理成本门槛：首次产出时延决定派遣是否合算
scenario: "把\"写一个 40 行脚本 + 单测\"这类确定性、验收可一句话写清的 ≤30 分钟任务派给子代理（glm-5.3），期望省时间。"
root_cause: ""
solution: |
  判定门槛：确定性改动 + 验收可一句话写清 + 预估 ≤30 分钟（含测试）→ 留在主线程做；只有长时探索/多轮试错的定位，或多条互不依赖分支可并行（并行收益 > 三段开销）才派子代理。观测口径用首次产出时延（first-signal latency），不是只看最终质量。
  当前性验证：派任一个子代理后记 t0=spawn 时刻、t1=首个文件写入/首个工具产出时刻；若 t1-t0 > 10 分钟且任务本身预估 ≤30 分钟，即判定该路径不划算，改回主线程并用 task_state recent_tools 复核产出是否已存在。
evidence: 2026-11-01 实测：EVO 编号检查脚本+单测派给 glm-5.3，28 分钟才落第一个文件，其中 20 分钟零产出，父代理第 20 分钟喊停接管测试文件；脚本质量可用但净收益为负。同期同类改动留在主线程完成（in_flight live_converged、receipt 核验字段、EVO baseline）均为分钟级。
tags: [subagent, cost, efficiency, orchestration]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-02T11:51:36.534818+08:00"
updated_at: "2026-11-02T11:51:36.534818+08:00"
---