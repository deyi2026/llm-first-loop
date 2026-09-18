---
title: codeartsdoer specs/ SDD 流水线全景与恢复锚点
scenario: 会话中断/压缩后恢复 llm-first-loop-mirror 的 spec-driven 开发任务时，需快速定位哪些 SDD 在流水线哪个阶段
root_cause: ""
solution: "先读 specs/ 各目录 mtime + tasks.md 的 [x]/[ ] 计数（一条 bash 命令覆盖全部），再按 mtime 深读最新目录三件套"
evidence: ""
tags: [spec-driven-development, sdd-pipeline, cache-capability, ev_recov, resume-context]
source: {}
status: active
created_at: "2026-08-27T01:24:50.501292+08:00"
updated_at: "2026-08-27T01:24:50.501292+08:00"
---

specs/ 目录 SDD 流水线状态（2026-08-27 实测）：cache-capability（08-27 最新，35 任务 0 执行，4 开放问题待用户确认：P3-1 实验验收口径/P3-2 预算放宽目标/P2-1 强弱模型清单/P0-2 节奏边界）；ev_recov（08-26，spec+design+r9/r12 两对增补，无 tasks.md，阶段 3 未完成，承载 P0-2）；cache_hit_fix 是唯一大规模执行过的 SDD（79/121 完成）；truncation_optimization 102 任务全未执行；其余 24 目录为 8 月中旬历史 spec。依赖链：P1-1/P2/P3 依赖 P0-1（REASONING_TAIL 裁剪重审，bug-fix-agent 执行）先合并；P0-2 由 ev_recov SDD 独立负责。