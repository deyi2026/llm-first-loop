---
title: SIGKILL mid-turn 时 CLI stdout 无 sid：LFL resume 必须从持久 session store 取 id，并用 resume 前缀==phase1 sid 断言 continuity
scenario: AgentPilot t12 中断-恢复 runner：对 LFL 子进程定时 SIGKILL 后需取 phase1 会话 id 以 `--session` 续接。v0 从 800 字符尾部日志提取 sid 恒为空；修复为传全量 phase1_full 后复测发现 stdout 仍可能无 sid。
root_cause: ""
solution: "sid 提取必须双通道：stdout 找不到 `[会话 …]` 行时，从隔离 DATA_DIR 的 sessions/ store 直接解析（SIGKILL 后、resume 前 store 内只有 phase1 会话，无歧义）；并加机械断言 resume 报告的 session 前缀 == phase1 sid 前缀（session_continuity 布尔 + resume_semantics 枚举）。验证：3/3 正式复测 + interrupt_s=8 强制 mid-kill 1/1，均 session-resume、sid 匹配；store 解析函数在真实被杀 store 上单元验证通过。"
evidence: "evals/pilot/data/results_v01_t12_midkill.jsonl（interrupted=true, phase1_sid=9b9b1c76, resume_session=9b9b1c76…, continuity=True）；results_v01_t12_retest.jsonl（3/3）；run_pilot.py _lfl_newest_session_sid；REPORT.md §3.2-P0-1"
tags: [session-resume, sigkill, durable-session-store, agentpilot, mechanical-assertion]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-12T16:10:49.851011+08:00"
updated_at: "2026-09-12T16:10:49.851011+08:00"
---

LFL CLI 的 `[会话 <sid>]` 行只在会话进程退出/输出 flush 时可见；`killpg(SIGKILL)` 命中 turn 执行中时该行从未打印。任何"从进程 stdout 提取 sid"的 resume 协议在该场景必然得到空串，即使给全量日志也一样。可靠协议是双通道：stdout 提取失败时直接从 per-run 隔离 DATA_DIR 的 sessions/ store 解析（kill 后、resume 前 store 内仅含被杀会话，取最新 mtime 即无歧义），并以 `resume_session[:8] == phase1_sid[:8]` 机械断言 continuity，同时在数据行保留 phase1_sid 与 resume_semantics 枚举。另注意：固定秒数中断窗口对"是否真杀到 turn 中间"是时序敏感的（25s 窗口下 phase1 有时自然完成），确定性 mid-kill 需把窗口降到首 turn 中位时长以下。