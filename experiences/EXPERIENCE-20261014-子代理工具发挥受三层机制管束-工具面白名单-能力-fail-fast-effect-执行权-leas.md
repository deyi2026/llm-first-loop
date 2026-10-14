---
title: 子代理工具发挥受三层机制管束：工具面白名单→能力 fail-fast→effect 执行权 lease fence；诊断分层、spawn 前列全
scenario: spawn 子代理后发现工具调不动（unauthorized/fenced/拒绝），需要判断是工具面没给、能力缺口还是执行权被栅栏；或想让子代理充分发挥能力设计 spawn 参数
root_cause: ""
solution: 按三层定位：工具面（requires.tools 白名单/继承父域）→ 能力（network/fs fail-fast）→ 执行权（lease fence sticky fail closed）。spawn 时工具列全+能力声明；审查型保持只读；执行型防 lease 断并备父接管。
evidence: "src/llm_loop/tools/builtin/spawn_subagent.py:24-32,67-99（白名单+能力声明）；src/llm_loop/subagent/runner.py:791-824,2315（lease fence probe 构造与 heartbeat 失败即 fence）；src/llm_loop/core/tool_execution_journal.py:416-461（提交窗口探测+sticky fenced）；RULE-AI-28 规则正文（审查子代理 E4 只读面设计）。核实时间 2026-10-14。"
tags: [spawn_subagent, requires-tools-whitelist, lease-fence, effect-authority, 子代理, 工具面, RULE-AI-28]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T16:46:04.144963+08:00"
updated_at: "2026-10-14T16:46:04.144963+08:00"
---

核实结论（读 spawn_subagent.py / runner.py / tool_execution_journal.py）：子代理工具发挥受三层机制管束，诊断"工具不可用"先分层——(1) 工具面层：requires.tools 是程序级强制白名单，声明即截断发现面+执行面，声明外调用确定性拒绝；不声明则继承父执行域（spawn_subagent 除外防递归，CHILD_SPAWN_GRANT 才授予分层舰队，depth≤3）。授权只降不升。(2) 能力声明层：requires.network/fs/session_continuity 在 child 启动前比对能力矩阵，缺口即拒绝（fail-fast，好于跑到一半失败）。(3) 执行权层：effect 类工具（execute_command/edit_file/dsh_task/workflow/codearts_dispatch）每个物理提交窗口过 lease_fence 探测（runner.py:799 probe：lease 仍在 runner + coordinator 在 + 磁盘 lease_is_current，任一失守→revoke+sticky fence）；heartbeat 续约失败也直接 mark_effect_fence_lost（runner.py:797），sticky 后 fail closed 不再探测磁盘。上轮审查子代理 8 次 unauthorized 报"run lease fenced"而非白名单拒绝，说明工具面可见、卡在第 3 层。实操：spawn 前把任务真正需要的工具在 requires.tools 列全+能力声明补齐；审查闸子代理按 RULE-AI-28 设计就是只读面（E4），不硬塞 shell，测试由父补跑；执行型子代理须防 lease 断（任务切小、以 subagent_result 为准、fenced 后父接管）。