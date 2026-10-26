---
title: 文稿独立审查闭环：每修订一轮就换 SHA，PASS 回执必须重新覆盖当前产物
scenario: "交付 PPT/文章等文稿，需要在放行前拿到覆盖\"当前产物\"的独立审查 PASS 回执（RULE-AI-28 文稿闸精神），且审查者与执行者必须分离。"
root_cause: ""
solution: 三轮独立审查闭环：每轮审查者给出 P0/P1/P2 → 执行者只改被点名项并重新生成 → SHA 变化 → 再发一轮覆盖新产物的审查 → 直到 PASS 并把回执落盘（含实测 SHA256+时间+逐条结论）。
evidence: "本次三轮实测：第一轮 VERDICT=REVISE（2×P0、7×P1、7×P2），抓到 P0-2「对股东而言回购的『成本』远低于同额现金分红」为源文没有的越界断言、P1-2 bullet 与标题合并进同一段落的渲染缺陷；第二轮 REVISE（2 项文字级）；第三轮 PASS。最终回执 work/cashout-ppt/review_receipt.md（第三版 8618B，SHA256 bc385f1b0da799956afd31619ec5be660f37769b801b2ba02364bcd8c2860ae5）。中间一次 agent_followup 因 fleet lease 过期被拒（\"lease 权威已失效\"），改为 spawn 新审查者解决。"
tags: [RULE-AI-28, 独立审查, 子代理, 文稿放行, 诚实性]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-26T08:47:28.961891+08:00"
updated_at: "2026-10-26T08:47:28.961891+08:00"
---

对文稿类交付物做 RULE-AI-28 独立审查的可复用做法：① 审查者与执行者分离：spawn_subagent 指定不同模型（glm/glm-5.3）+ requires.fs/execute_command/read_file + network=false，任务书只给"被审产物绝对路径 + 事实来源文件 + 检查维度 + 回执落盘路径"，明确"不得修改产物，只写回执"；② 回执必须含被审产物实测 SHA256、复核时间、verdict、逐条结论、覆盖范围与局限声明——sha 变了旧回执即失效；③ 审查者最该抓的两类真问题（本次实测）：渲染缺陷类（bullet_block 把首条 bullet 与上一段标题合并进同一段落，肉眼像丢换行，脚本自检查不出，必须渲染看图）、诚实性类（PPT 文案里出现源文没有的推演句/越界断言，如"对所有股东是净增益""回购成本远低于现金分红"）；④ 修订一轮就换 SHA → 必须再发一轮审查拿覆盖当前产物的 PASS，不能拿旧回执放行；⑤ 子代理 fleet lease 会过期，agent_followup 可能被拒（"fleet lease 权威已失效"），此时直接 spawn 新审查者，并把上一轮回执作为输入清单；⑥ 执行者不要替审查者下结论，也不要因"整体不错"提前放行。