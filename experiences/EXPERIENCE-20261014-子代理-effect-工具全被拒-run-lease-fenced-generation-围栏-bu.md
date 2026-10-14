---
title: 子代理 effect 工具全被拒（run lease fenced）：generation 围栏 bug，重启运行时前改用 dsh_task 委派
scenario: "需要子代理执行命令类任务（git/pytest）做独立核验，但子代理 execute_command 全部 unauthorized（\"run lease fenced\"）"
root_cause: ""
solution: 识别为平台 bug 而非 spawn 参数问题：spawn 白名单已含 execute_command 仍被拒即此症；用最小探针子代理（任务=跑一条 pwd 命令并原文回报）确认，再查是否已有修复提交（本例 47773fff5）；运行时未换新前改走 dsh_task 同步通道委派独立审核，勿反复重派子代理
evidence: "evidence://v1/5e7b4d8fca6cf18798a05ab796bf4c342d6c95c9bbcc41bfbdfd1d12c0becb24; evidence://v1/4faeb91f32b6f226b17faab4e2f8aabad9282c24e42e63a0ba94a69559538759"
tags: [spawn_subagent, execute_command, unauthorized, run-lease-fenced, 47773fff5, dsh_task]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T17:34:09.766284+08:00"
updated_at: "2026-10-14T17:34:09.766284+08:00"
---

2026-10-14 实测：本会话 spawn_subagent 两次派发（subagent_8a914288b69f、subagent_b0d3955e3bc3）所有 execute_command 均返回 unauthorized，探针子代理拿到原文错误"effect authority 丢失（run lease fenced）"。修复提交 47773fff5（2026-10-14 17:19）自述：spawn worker 经 copy_context 继承父 run generation，子会话在 run_generation_authority 查无登记→拒绝所有 effect 工具；自 2026-10-12 起 26 个生产子会话 0 次 execute_command 成功。白名单声明/参数调整均无效，唯一解是运行时换新代码（重启承载本会话的进程）。另叠加既有教训 METHOD-LEARNING-20261012-002：父模型结束回合→子代理 cancelled_on_model_final，长审核任务不应依赖子代理跨回合。当日成功路径：dsh_task（隔离进程、独立模型）+ /tmp 临时 worktree 边界，完成 18 分支全量审核（50 步/80 工具调用/turn end=completed，零副作用自检通过）。