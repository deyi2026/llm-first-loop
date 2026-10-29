---
title: 委派审查子代理必须限制输出体量，否则子会话触发上下文预检失败且无回执
scenario: 给子代理下审查任务书时若允许它自由回显大输出（全量 diff、整文件 cat、536 行 porcelain），MiniMax 子会话会在收尾时触发上下文预检失败（子代理回答为「模型输入接近实际窗口…拒绝静默截断」），rounds/tools 已消耗但没有 verdict、没有回执文件，等于白跑。
root_cause: ""
solution: 任务书里直接写死输出纪律：每条命令输出回显 ≤30 行，超出用 head/tail/wc -l 截断或重定向到 scratch 文件只统计行数；禁止 cat 整个 diff/文件/commit body，一律用 --stat/--numstat/--name-only/--oneline；工具调用总数上限 ~25。第二次委派加上这些约束后，同类 7 项审查在 20 rounds/30 tools 内正常完成并落盘 PASS 回执（P0=0/P1=0/P2=4）。另：任务书要显式写「只读、禁止 git push/commit/add/reset/rebase」和「只有回执文件允许写」。
evidence: 第一次 spawn subagent_73a502edff43：rounds=15 tools=28，child_state=failed，回答为上下文预检拒绝截断，无回执落盘（find 无 push-20261028* 文件）；第二次 subagent_382a7796707d 加输出纪律：rounds=20 tools=30，child_state=completed，verdict PASS P0=0 P1=0 P2=4，回执 /Users/yyj/lfl-workspace/receipts/push-20261028-dgui-to-github-main.json
tags: [subagent, context_budget, review_gate, delegation]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-28T15:25:39.925032+08:00"
updated_at: "2026-10-28T15:25:39.925032+08:00"
supersedes: [EXPERIENCE-20261026-独立审查子代理必须预先限定读取面-否则上下文预检失败且无-verdict]
---