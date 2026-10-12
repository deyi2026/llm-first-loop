---
title: hev0 评测 harness 三连坑与判别力预检先行法
scenario: LFL compaction 锚点 A/B 评测（evals/harness_evolution_v0）：pilot 双臂 reward 全 1.0，仅机制信号有差异，面临是否放 48 行全量（~亿级 tokens）的决策。
root_cause: ""
solution: "先花小成本做判别力预检（2 压力行×双臂=4 行，~1.3M tokens）：结果双臂仍全 1.0，按预定决策规则放弃全量，转生产遥测。预检过程修掉 3 个 harness 缺陷：1) 事件捕获读不存在的 engine.session.event_store.tail() 且匹配字段 \"event\"（实际字段 \"type\"），须直接读 HEV_ROW_DATA/event_logs 落盘 jsonl；2) event_logs 平面文件 10MB 后轮转为 <sid>/N.jsonl 目录，glob 须 **/*.jsonl 递归；3) LoopResult 终答字段是 final_answer 不是 content，取错会回退 str(res) repr，oracle 正则从 repr 抓出垃圾判 0 分——答案可从事件日志最后一条非空 assistant 消息零成本重建并离线重判。"
evidence: "evals/harness_evolution_v0/results/hev0-freeze-20260916T121349Z/{rows.jsonl,regrade-annotations.md}；修正后积分板 6 行双臂全 1.0；机制信号 candidate pin_user=2 vs baseline=0；t3 成本 268k vs 315k tokens_in 无上浮。"
tags: [eval, hev0, compaction, anchor-pinning, harness-bug, event-store, 判别力预检]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-16T20:54:06.647140+08:00"
updated_at: "2026-09-16T20:54:06.647140+08:00"
---