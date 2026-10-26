---
title: 知识打分闭环需要周期巡检与结算触发双通道
scenario: 知识打分器只有手动 CLI 入口时，use ledger 持续累积但打分明细长期不增长（本次停在 11 条）；单靠页面读取 ledger 不会触发补分。
root_cause: 缺少常驻调度：Web 启动时不补 backlog、运行中无周期巡检；结算提交后也没有触发补分。打分动作与使用回执的产生路径完全解耦。
solution: "1) Web 进程启动时先补 backlog，随后每 120s 巡检 pending；2) 结算提交成功后异步 spawn 一轮补分，周期巡检兜底；3) CLI 与调度器共用跨进程文件锁，避免重复打分；4) 单卡超时、连续失败熔断、失败冷却与指数退避；5) 管理 API/UI 暴露 pending、最近自动打分、连续失败与下次重试时间；6) 健康检查失败时跳过本轮而非空转。当前性验证：跑 `PYTHONPATH=src .venv/bin/python -c \"from llm_loop.knowledge_score.pending import scan_pending; print(len(scan_pending('.')))\"` 记下 pending 数，再跑 `scripts/knowledge_score.py --all-pending --limit 1`，预期 pending 减少、ledger 增加、runner_state.last_run_at 更新。"
evidence: 全量 ci_gate 9447 passed / 137 skipped；独立复审两轮 PASS（P0=0/P1=0）；tests/test_knowledge_score_runner.py 覆盖周期、结算触发、锁、熔断、退避与状态字段；提交 ba8122db1。
tags: [knowledge_score, scheduler, closed_loop, settlement]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-17T22:56:07.486122+08:00"
updated_at: "2026-10-17T22:56:07.486122+08:00"
---

闭环判据不是“有打分脚本”，而是“新回执能自动变成分数且状态可见”。当前性验证：先运行 `PYTHONPATH=src .venv/bin/python -c "from llm_loop.knowledge_score.pending import scan_pending; print(len(scan_pending('.')))"` 得到 pending 数；再运行 `scripts/knowledge_score.py --all-pending --limit 1`，预期该数下降且 ledger.jsonl 行数增加、runner_state.json 的 last_run_at 更新。周期线程是否存活看 runner_state.json 的 updated_at 是否按 interval 推进；若长期不推进，先查 Web 进程启动时间是否早于 runner 代码提交，再查 /api/v1/knowledge/scores 的 runner 字段。