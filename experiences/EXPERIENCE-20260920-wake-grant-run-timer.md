---
title: "wake 失联真实机制：条目持久、grant 随进程死、救援=退避窗口内真人 run 重铸（修正\"timer 内存丢失\"误诊）"
scenario: "会话跑在被重启的常驻服务进程内（web/feishu/learning 任一），发起 service_control restart 前注册了 wake=true 定时核验（如\"4分钟后查重启终态\"）。重启完成后，wake 在退避窗口内未触发，核验静默丢失，直到真人下次交互才补查。容易误诊为\"timer 存内存被重启清掉\"——实际不是。"
root_cause: ""
solution: "操作约定（立即可用）：对爆炸半径内的服务做重启，核验一律不挂 wake——按回执语义\"下一轮任意交互读 status/action_id 终态\"，或依赖下一条真人消息时主动 status；wake 只用于 blast-radius 外的定时任务。系统级修复见演进建议：restart 动作自核验落 durable action 记录（主案）、降级 wake 可见化（小修）、pinned-wake 跨重启重铸（备选，需安全评审）。"
evidence: "src/llm_loop/core/scheduler.py L469-524 rearm_wake_grants；src/llm_loop/core/trace_leak/ingress_token.py delegate_ingress docstring；本会话 event_stream prefix_mismatch 10 条（04:03-05:16 UTC）；12:50-13:09 会话事件流零记录；service_control restart 回执\"下一轮查终态\"语义"
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-20T13:20:14.675575+08:00"
updated_at: "2026-09-20T13:20:14.675575+08:00"
supersedes: [EXPERIENCE-20260919-restart-schedule-wake-wake, EXPERIENCE-20260912-schedule-wake-workdir-v3, EXPERIENCE-20260919-capability-re-mint]
---

真实机制（代码级，2026-09-20 实证修正）：1) schedule 条目持久化于 data/schedule.json（文件锁+跨进程 claim/lease），重启不丢；2) 随进程死亡的是 wake grant（delegate_ingress 产物，设计上"只驻留进程内、不写 schedule.json"，防重启进程自铸续跑授权）；3) 设计救援 rearm_wake_grants(EVO-20260919-f119847d)：同会话下一次真人 run（非委派 ingress）满足 条目存活+未消费未降级+wake_started_at==0+owner pid 已死 时重铸一次。12:49 注册 wake→12:50 gen54 全量重启 grant 死→~12:55 到点新进程持条目无 grant 有界退避→真人 run 13:09 才来（超窗口）→条目已降级为 output-side notify（无人消费）→核验轮从未发生。修正：先前"timer 存内存被重启清掉"是错误诊断——条目在盘上，丢的是 grant，且救援存在但被退避窗口+无真人 run 组合击穿。另发现伴生慢性 bug：run.interruption_recovery repair_failed reason=prefix_mismatch 本会话每条真人消息触发一次（12:03 起 ≥7 次，event_messages==memory_messages 前缀不匹配，prompt_chars=0），独立于重启，待排查。