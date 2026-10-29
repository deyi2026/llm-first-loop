---
title: "子代理上下文耗尽：任务书必须同时约束\"读什么\"与\"读多少\""
scenario: "用 spawn_subagent 派发独立评审/审查任务时，子代理因上下文窗口耗尽而 failed（非逻辑失败）：单批 25 张方法卡 → 419K input tokens；单批 5 张 → 311K；代码审查子代理读 store.py + registry_experience.py 大段源码 → 273K。根因不是卡正文太大（25 张卡正文合计仅 81KB），而是子代理自发\"考古\"：从被审对象出发 grep 到 action_trace / hit_win_size / process_versions / evolution_complete / llm_rounds / registry_*.py / store.py 等与任务无关的模块，并 ls data/methods 这类 1600+ 卡的目录。且中途 agent_message 纠偏来不及——纠偏只在下一个 step boundary 生效，子代理往往已冲到边界。"
root_cause: ""
solution: |
  两处必须同时约束，缺一不可：
  (1) 任务书给出取证预算与禁区：明确"总工具调用 ≤ N"、"禁止读 src/ 下大文件、禁止 grep data/ 全库、禁止 ls 大目录、禁止读 data/action_trace|data/event_logs"；
  (2) 缩小工具面本身：只给 execute_command + read_file，不给 search_files（search_files 极易诱发全库 grep）；并用 requires.tools 在程序层强制。
  另一个有效杠杆：把"取证"从子代理手里拿走——父代理先用 grep 批量产出证据包，子代理只做判断，上下文可压到 1/10。
  还要把任务拆小：单卡 1 轮（成功）优于 5 卡 1 轮（失败）；失败模式是撞窗口而非结论错误。
  判定失败原因要看子代理 result.available 的 outcome 与最后一条错误信息，不要盲重试同一任务书——重试必须换任务书。
evidence: "实测三档：subagent_369088f43f01（25 卡单批）tokens_in=419303 failed；subagent_cdff5b7c516c（5 卡单批）tokens_in=419303 failed；subagent_a9d291abf627（5 卡单批，纠偏未赶上）tokens_in=311434 failed；subagent_e1953b161a08（代码审查，读 store.py/registry 大段）tokens_in=273189 failed。改为单卡 + 工具面收紧到 execute_command+read_file + 取证预算 ≤4 次后，subagent_affb4f1cd2ef 一次成功产出合格结论（7/7 claims verified，指到 evidence.py:775-812 等精确行号）；其余 24 张按 3-4 张/批亦全部成功。"
tags: [subagent, context-window, task-design, tool-scope, evidence-budget, review]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T02:05:10.804102+08:00"
updated_at: "2026-10-30T02:05:10.804102+08:00"
---