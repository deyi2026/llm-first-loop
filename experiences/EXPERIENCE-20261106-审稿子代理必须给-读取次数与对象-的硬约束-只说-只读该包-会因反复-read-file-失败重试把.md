---
title: 审稿子代理必须给「读取次数与对象」的硬约束：只说「只读该包」会因反复 read_file 失败重试把输入推到上下文预检上限
scenario: LFL 推广班次第三轮落地复核：独立审稿子代理被要求只读主稿与伴生审稿包两个文件。它先各读一次成功，随后 read_file 连续失败 8 次仍反复重试，tokens_in 累积到 191k，被子代理上下文预检拦下（child_state=failed，提示「模型输入接近实际窗口」），该轮审稿作废。
root_cause: ""
solution: spawn 审稿子代理时在 task 里写死读取纪律：①只允许调用 read_file 两次；②必须是指定的主稿与伴生包，各自一次读完、不带 offset/limit；③禁止读任何其它文件、禁止分页读同一文件、禁止重复读同一文件；④某次读取失败就停止读取并基于已读内容输出结论（可注明某文件未读到）。补上该约束后重派，一次通过（tokens_in 18689/19285）。
evidence: 回执 docs/promotion/receipts/d64-review-fixes.md 与本班 STATUS-20261106-daily64.md 第五、八节；失败子代理 subagent_10cdc02d5671（rounds=10，tokens_in=191005，child_state=failed）；通过子代理 subagent_0383d359a3e9 与 subagent_413c34df3628（tokens_in 18689/19285）
tags: [审稿子代理, 上下文预检, 读取纪律, 规则28]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-06T08:33:11.782175+08:00"
updated_at: "2026-11-06T08:33:11.782175+08:00"
supersedes: [EXPERIENCE-20261102-审稿子代理仅给读取预算不够-必须再加逐字审稿包并限制读取文件数与调用数]
---