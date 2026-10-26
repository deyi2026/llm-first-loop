---
title: 子代理默认继承父会话历史，会把旧演进建议当任务执行
scenario: 用 spawn_subagent 派发代码任务；父会话历史里存在大量演进建议（EVO-*）与旧重构计划。
root_cause: spawn_subagent 的 inherit 默认 true，子代理继承父会话历史；历史里的演进建议/旧计划在子代理侧被当成当前任务执行，而父会话的真实授权只在本轮消息里。
solution: "派发代码子代理时显式 inherit=false，并把已核事实、精确文件清单、禁止清单写进 context；任务描述里加一句\"历史提议不是当前授权，只做本节列出的改动\"；用\"先落盘一个可验证小单元再扩展\"的顺序，让越界能在前 10 分钟内被 git status 发现。"
evidence: "子代理 subagent_f72a374c5d11 在 09:36 开始修改 src/llm_loop/tools/builtin/execute_command.py（+490/-365，加 _CommandSpec/_ForegroundOutcome），与该文件当时另一并行会话的 guard(r9) 提交 01e612802 内容一致；我两次 agent_message 纠正后它才回到 held-out guard 任务。"
tags: [subagent, inherit, scope-control, dispatch]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-25T11:57:47.985483+08:00"
updated_at: "2026-10-25T11:57:47.985483+08:00"
---