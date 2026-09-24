---
title: eval harness 冻结前必须对每个任务冒烟执行 staging 路径；seed 存储根必须与 runtime 工具读取根一致
scenario: 自建 eval harness 对合成任务套件做判别力预检（hev0 v0，8 任务双臂）
root_cause: ""
solution: "每个任务在冻结前执行\"零 token 冒烟\"：worker 装载+seed+判分器 dry-run 全路径走一遍（不调 LLM）；凡 seed 直写存储的，先读 runtime 工具侧的根解析代码再定写入路径。修复后单冻结全量重跑保证统一代码基线。"
evidence: "results/hev0-freeze-20260920T214836Z t7/t8 worker.log FileNotFoundError；results/hev0-freeze-20260920T215448Z t7 rows.jsonl get_goal 回执\"[无活动目标]\"+data/goal/goals.jsonl 存在；.worktrees/compaction-merge-20260916/src/llm_loop/config.py:545 audit_dir 属性；修复后 v4 冻结 t7 双臂 1.0/1.0"
tags: [eval-harness, measurement-defect, precheck, goal-store]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-21T06:09:09.414015+08:00"
updated_at: "2026-09-21T06:09:09.414015+08:00"
---

hev0 预检三轮冻结暴露两个 pilot 覆盖不到的缺陷：(1) worker 对无 workspace/ 的任务无条件 copytree → 0 秒崩溃；(2) Goal seed 直写 DATA_DIR/goal，engine 工具读 settings.audit_dir=DATA_DIR/audit → get_goal 永远回"无活动目标"，模型行为正确却被记 0 分。教训：冻结前必须对每个任务做零成本 staging 冒烟（只跑装配路径，不调模型）；seed 写入路径必须与 runtime 工具读取路径用同一个符号根（audit_dir）对齐。判别力误判风险：装配缺陷表现为"双臂同败"，极易被误读为任务太难。