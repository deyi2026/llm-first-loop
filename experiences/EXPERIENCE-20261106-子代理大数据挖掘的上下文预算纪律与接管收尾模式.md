---
title: 子代理大数据挖掘的上下文预算纪律与接管收尾模式
scenario: 委派子代理做需要扫描大型数据文件（百 MB 级 JSONL）的分析/实现任务
root_cause: ""
solution: 主会话先脚本化蒸馏大文件→子代理消费蒸馏产物；僵死判定用 diff 行数非文件名
evidence: subagent_3d2ecdeaf87c 失败回执（75 rounds/5.29M tokens/拒绝静默截断）+ 其工作树 +342/-29 diff 经接管后 82 项 scoped 全绿并合并 main（042a8ac57）；对照 F 子代理（数据量小）23 分钟正常完成。
tags: [subagent-delegation, context-budget, data-mining, FR-SAFE-01, loss-salvage]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-06T00:41:25.338002+08:00"
updated_at: "2026-11-06T00:41:25.338002+08:00"
---

把重数据挖掘（如 327MB 的 declaration_check.jsonl 逐行审计）交给 spawn_subagent 会烧穿其上下文（75 轮 5.29M tokens 失败，失败信息只有"模型输入接近实际窗口"）。正确姿势：主会话先写提取脚本落盘（RULE-AI-36 姿势：脚本写文件再 python3 -I 执行，绝不管道直连解释器——FR-SAFE-01 一晚拦了我 3 次）把大文件蒸馏成 KB 级样本文件，子代理只消费蒸馏产物。子代理疑似僵死时先看 worktree diff --stat 行数变化（文件名快照看不出进展，我差点误杀一个 +342 行进行中的实现）；child_id 必须用 spawn 回执的完整原文，不可凭前缀补全（我拼错过 3 个）。接管失败子代理的遗产：其工作树未提交 diff 通常有价值，diff 导出到文件逐段审读后接管收尾，commit 信息如实双署名。