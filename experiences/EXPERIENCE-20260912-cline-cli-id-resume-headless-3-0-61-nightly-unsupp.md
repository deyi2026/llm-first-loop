---
title: cline CLI --id resume 无 headless 形态（3.0.61/nightly 已排除）——自动化评测中应标 UNSUPPORTED 而非 adapter 缺陷
scenario: AgentPilot t12 Session Continuity 评测需要在 headless（CI/确定性 benchmark）环境下恢复 cline 会话；v0 三次 resume 均以 CLI 参数/TTY 错误 1s 内失败，需判定根因是 adapter 调用缺陷还是 CLI 能力边界。
root_cause: ""
solution: 不猜，做系统化 smoke qualification：同一 conv_* 会话 + 同一 ws 上排除全部调用形态（--json 位置参数/管道 stdin/--storage-id/无 json/--auto-approve/--yolo/--yolo+json/--zen 共 8 种），全部被 CLI 守卫拒绝；grep 二进制确认守卫字符串；装隔离前缀复测当日 nightly 确认未修；PTY(script+管道) 探针确认 TUI 不提交 turn、会话文件不增长。结论定性为 CLI 能力边界 → 引入 UNSUPPORTED(headless) 状态与 ADAPTER_INVALID 区分，v1 矩阵不烧无效 run，runner 保留守卫消息分类分支以便上游修复后自动恢复。
evidence: "evidence://v1/81896eadb0f91dc7bfdad25568b2f03bc60f67b4b8dc9b88eaeeca27f43bc569 (nightly 同错); evidence://v1/f88e79147479861993b21186979834a4e33dfc7bcaf273179e4caacf37df8cd3 (PTY 会话文件未增长+进程残留); evals/pilot/REPORT.md §4.2 (artifact://v1/5a8f0e6975a04ded85046cdc899ce51c, 8 形态表)"
tags: [cline, session-resume, headless, benchmark, agentpilot, cli-capability-boundary]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-12T15:58:29.097969+08:00"
updated_at: "2026-09-12T15:58:29.097969+08:00"
---

cline CLI 3.0.61 与当日 nightly 的 --id 会话恢复只能走交互 TTY：--id 与 --json 组合守卫直接拒绝；无 --json 时非交互 shell 触发 "interactive mode requires a TTY"；--auto-approve/--yolo/--zen 均绕不过；PTY(script)+管道 stdin 只渲染 TUI、turn 不提交、会话文件不增长且挂起。判定依据为同一 conv_* 会话上的 8 形态系统排除 + 二进制守卫字符串 + nightly 复测。评测/自动化场景应将 cline resume 标记 UNSUPPORTED(headless) 而非 adapter 缺陷，等待上游提供 headless resume 后重测。