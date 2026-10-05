---
title: 孤儿/settle-loss 对账扫描必须避开在途 attempt（竞态误报）
scenario: 对 event_logs 做 transport 孤儿/settle-loss 对账扫描（如 scripts/evidence/mark_orphaned_transport_attempts.py --dry-run 或等价自写扫描），在系统存在活跃 LLM 回合时执行。
root_cause: "历史对账扫描（构建 settled 集合 → 找 opened 未 settled 的 attempt）与正在流式输出中的在途 attempt 存在结构性竞态；in-flight attempt 恰好满足\"opened 且未 settled\"，被误计为孤儿候选。"
solution: 扫描前确认无在途 run；或对候选加时间过滤（opened_at < now − 10min）。定性 settle-loss 前必读会话日志尾部、确认文件不再增长、检查同会话是否有后续 settled/error。先 --dry-run 观察，再决定是否真标记。
evidence: "evidence://v1/47dcc48cbf9bf36180b9ad0e430e8d031e286053186558ef6121db0ba61c7584; evidence://v1/89aa79e38822a7055c26aad46de1711f8946d0d2a41b3c4fa6f43a398c225fea; evidence://v1/8a47578c43b0fe9a2c7d9b69a4f968485c9b6a53245d71c2c829256cf88cae31"
tags: [durability, orphan-scan, race, verification, event_logs]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-05T21:02:08.284633+08:00"
updated_at: "2026-10-05T21:02:08.284633+08:00"
---

现象：2026-10-05 对 data/event_logs 做 provider.transport opened-without-settled 全局扫描时，报告 1 个"新孤儿候选"（pattempt:dd31ee40，session 7bab3a29），初判为 settle-loss 复发并准备执行标记脚本。核查该会话日志尾部后发现：该 attempt 属于一个仍在执行中的探测回合（qwen3.8-flash-next 对 ~46KB 提示思考 55 秒+，llm.partial_checkpoint 的 text_tail 全空属 thinking 阶段正常形态），随后正常 settle。定性：扫描与在途 attempt 竞态，误报。修正动作：放弃标记，改在无在途 run 的静默期重扫。通用结论：(1) 对账/孤儿类历史扫描在构建 settled 集合时天然与在途 attempt 竞态，必须先确认无活跃 run，或仅统计 opened_at 早于 now−10min 的 attempt；(2) 定性 settle-loss 前必须先读会话日志尾部并确认文件不再增长；(3) scripts/evidence/mark_orphaned_transport_attempts.py 的 --dry-run 是必要前置步骤，且其 candidate 计数在有任何活跃 run 时不可直接当作 settle-loss 证据。