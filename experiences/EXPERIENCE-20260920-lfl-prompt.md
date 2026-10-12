---
title: LFL prompt 前缀缓存失效的三层改写源定位（函数级）
scenario: 排查 provider 前缀缓存逐轮失效：窗口均值高但双峰（每轮首笔全冷、轮内第二笔起热），需定位 prompt 在哪一层被改写。
root_cause: ""
solution: "按层定位：头部查 core/history.py 压缩与 cache_protected_prefix 覆盖范围；中段查 episode_history 的 working_set 折叠及 ingress_resolution 调用点；尾部查 recent_continuity 是否 pop/重排 user 之前消息；再核 projection_gate 是整幅 hash 校验而非前缀单调校验。诊断结论：改写全部发生在 runtime prompt 管线且各自\"合法\"。"
evidence: "代码核验 file:line 如上（2026-09-20 当日读源）；运行态证据：cache_monitor 窗口 token 收缩轨迹、tool_working_set raw_tool_chars 波动、recent_continuity 逐轮 rehydrated 抖动（本会话归档）。"
tags: [prompt-cache, prefix-stability, prompt_build, token-cost]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-20T14:51:37.424301+08:00"
updated_at: "2026-09-20T14:51:37.424301+08:00"
supersedes: [EXPERIENCE-20260816-llm-ttl]
---

三个 prompt 改写源（均经读源核验，非推测）：
1) 头部：build_history_messages（core/history.py:818）预算触发压缩——194K→54.5K→25.3K token 收缩即此路径；cache_protected_prefix（history.py:853-854）只护压缩路径。
2) 中段：project_active_tool_working_set_with_stats（core/episode_history.py:745，调用点 stages/ingress_resolution.py:307）grace 队列逐轮折出旧工具组，字节逐轮变化（实测 raw_tool_chars 17,340→24,242→17,340→36,063）。
3) 尾部：apply_recent_continuity_suffix（core/recent_continuity.py:260，调用点 stages/tail_assembly.py:113）会从当前 user 之前区域 pop 相邻 assistant（recent_continuity.py:360-368）并重排，触发条件逐轮抖动。
根因缺口：projection_gate（stages/projection_gate.py:60,90）用 ver+seq+built_hash 校验整幅视图，ver 含 budget/anchor 等合法变化项，不校验前缀单调性——三轮改写各自合法通过门禁，缓存整体失效。
已提交 EVO-20260920-3fb8aa0a（pending_review）：A 先加 prefix-stability checker 让打破点可归因；B once-emitted-bytes-frozen 不变式；C 压缩事件显式化。修复未实施，等人工审阅。