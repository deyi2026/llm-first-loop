---
title: 独立审查子代理必须预先限定读取面，否则上下文预检失败且无 VERDICT
scenario: "对一份 15+ 页中文 PPT 做交付前独立审查（RULE-AI-28 类要求）：把 build_ppt.py 全文、source_analysis.md 全文、16 张预览图都交给子代理自行决定读什么。子代理连续 12 轮、16 次工具调用、tokens_in 284552 后触发\"模型输入接近实际窗口\"预检失败，保留会话、拒绝静默截断，最终 child_state=failed，零审查结论可用（等效于白跑一轮审查）。"
root_cause: ""
solution: "先由父代理算好被审对象的精确行号/行段，把 context 写成\"受限读取清单\"：(1) 只允许 execute_command 执行指定 sed -n '278,306p;462,492p;683,712p' 这类定点取行，禁止 read_file 整个源码/源文档；(2) 只允许 read_image 指定 N 张改动页 PNG，不许通读全部页面；(3) 在 context 里显式写\"最多 N 次工具调用、不得运行 build_ppt.py\"；(4) 把要核对的数字清单与\"已核验/粗算/单一来源\"标注等级直接写进 context，避免子代理自己去检索通道找来源。改造后同一份产物，子代理在 12 次工具调用内产出 VERDICT: PASS 并给出 P0/P1/P2 分档。"
evidence: "失败样本：子代理 6775833848ce，child_outcome=failed，rounds=12，tools=16，tokens_in=284552，错误文案\"模型输入接近实际窗口，但当前子代理没有可调用的 search_archive 或持久 ArchiveStore；已保留完整会话，拒绝静默截断\"。成功样本：子代理 1f4121d1df05 按受限读取清单执行，产出 VERDICT: PASS（0 个 P0，3 个 P1 均为标注/表述级），实际调用 11 次。另注：同一父会话对单个 child 的 agent_followup 续话预算是 4 次，全局 6 次会耗尽（回执\"父会话续话总预算已用尽: 6/4\"），故复核轮次要预留新建 child 而不是指望续话。"
tags: [subagent, independent-review, context-budget, ppt-delivery, routing]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-26T09:36:48.622008+08:00"
updated_at: "2026-10-26T09:36:48.622008+08:00"
supersedes: [EXPERIENCE-20261025-独立文稿审查子代理必须先给上下文纪律-否则窗口溢出失败]
---