---
title: 独立文稿审查子代理必须先给上下文纪律，否则窗口溢出失败
scenario: "让独立子代理审查一篇 311 行的中文长文稿（需核对 arXiv 论文全文 + 5 份仓库文档）。第一次 spawn（MiniMax-M3.1-Flash）跑了 20 轮 31 次工具后，在最终答复阶段触发\"模型输入接近实际窗口\"而 failed，证据全部丢失、零回执落盘；第二次换 glm-5.3 并在任务书里加了\"上下文纪律\"节（禁止整文件读入、只许 grep -n | head -N、每取得一类证据立即追加写入回执、标注待核项允许写\"未核验\"）后一次跑通。"
root_cause: ""
solution: "spawn 审查类子代理时，任务书里必须前置\"上下文纪律\"节：①禁止 cat/整读大文件与大网页，一律定向 grep -n | head -N 或 sed -n 'a,bp'；②每拿到一类证据就落盘到回执（verdict 先填 IN_PROGRESS），让失败也不丢证据；③明确\"允许写未核验，不许为补全而扩读\"；④指定收敛轮数（如 2-3 轮内给最终回复）。窄复审轮次用同一模型的新会话，并把待核销项与旧表述清除关键词列成可直接 grep 的清单。"
evidence: "子代理 subagent_09c5027344ba（MiniMax）failed：子代理回答\"子代理上下文预检: 模型输入接近实际窗口…拒绝静默截断\"，回执未落盘；改用 glm-5.3 + 上下文纪律后 subagent_ee2ad8d5bfb1 / subagent_ed021145779f / subagent_e547627b5375 / subagent_3929e068b95f 四轮均成功，回执 verdict=PASS 并绑定 sha256 ab52dc04bfd86f27f65a660306c6daeff5c8960e5eeb32add570c68e28cd0552"
tags: [subagent, review, context-budget, RULE-AI-28, article-review-gate]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-25T11:29:07.449226+08:00"
updated_at: "2026-10-25T11:29:07.449226+08:00"
---