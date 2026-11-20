---
title: 只读调查子代理读大文件触发上下文耗尽被守门拒收：续话可回收结论，派发须限窗
scenario: 多子代理只读调查时，子代理读大文件导致上下文耗尽、结果被守门拒收
root_cause: ""
solution: 派发时限定读取窗口/禁止整文件读取；失败后用 agent_followup 无工具续话回收已读结论，输出≤40行压缩结论并显式标注未覆盖项
evidence: 子代理失败回执：subagent_0be41bf41e2a tokens_in=208611/rounds=14；subagent_653499683ee9 tokens_in=298877/rounds=17；subagent_a8bc25db9a72 tokens_in=350315/rounds=18，均 child_outcome=failed 且“已保留完整会话”；agent_followup 续话后三份压缩结论成功回收（父会话续话计数 2/4）
tags: [subagent, context-exhaustion, agent_followup, read-only-investigation, review-loop]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-16T10:08:03.563222+08:00"
updated_at: "2026-11-16T10:08:03.563222+08:00"
---

场景：并行只读调查子代理（MiniMax M3.1 Flash）查宿主审查链/报表/S1 三块事实，三个子代理全部在 14–18 rounds、tokens_in 208k–350k 时触发「子代理上下文预检：模型输入接近实际窗口，但当前子代理没有可调用的 search_archive 或持久 ArchiveStore；已保留完整会话，拒绝静默截断」而 failed，无结论交付。
根因：子代理用 read_file 整读大文件（review_host_admission.py 5654 行、review_report.py、lane_gate.py）并反复 search_files，累积输入远超其窗口；宿主守门选择 fail-closed 拒绝截断（宁可失败也不静默产出半截审查）。
有效处置：对已终止 child 用 agent_followup 续话（同会话保留上下文），指令明确「不要再调用任何工具，直接基于已读内容输出压缩结论，未查到的写未覆盖、不要臆造行号」，三个子代理均在 1 round 内回收了带 file:line 的可用结论（父会话续话额度：每 child ≤2、每父会话 ≤4/15 分钟窗口）。
派发纪律（下次预防）：调查类子代理任务书须写明按章节行号窗口读取、禁止整文件 read_file、要求 ≤40 行压缩输出；先约定「未覆盖」口径，避免子代理为补齐而继续读大文件。