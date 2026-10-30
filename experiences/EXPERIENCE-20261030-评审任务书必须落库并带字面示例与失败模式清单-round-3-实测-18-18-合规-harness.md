---
title: 评审任务书必须落库并带字面示例与失败模式清单：Round 3 实测 18/18 合规、harness problems=0
scenario: 独立子代理批量评审（method candidate qualification 通道），一轮 18 张卡、9 个子代理，评审结论由子代理出、父会话落库。任务书若不落库，每轮重建稿未经验证，首波代理大面积格式违约。
root_cause: ""
solution: 1) 先把评审任务书落库（docs/governance/qualification-reviewer-taskbook.md），内含字面 JSON 示例 + 五值枚举值域（pass|fail|mixed|insufficient|not_evaluated）+ 一致性红线 + 取证预算与禁区；2) 每轮开跑先读它，重试从它改，不从零重建；3) 放行纪律：先放 2 个试点代理 → 用 harness 机械校验回执（枚举合法 + 红线无违反，problems=0）→ 再一次性放行剩余批次；4) 评审员工具面只给 execute_command + read_file（不给 search_files，避免诱发全库 grep），总调用预算 ≤6 次（2 卡/代理）；5) 任务书必须写死三条硬坑：禁止 heredoc 交解释器（E6_CATASTROPHIC_HARD 硬阻断，整条命令作废）、禁止 && 串联复合命令（compound_protected_shell_requires_split_commands）、第 6-9 次调用会撞上下文预检（取证够了就写文件收尾，别再查）；6) 父会话落库时 task_ref/qualification_episode_ref 由运行时绑定当次真人回合 episode（method_manage 无 task_ref 参数），并须与卡的 source_episode_refs 独立。
evidence: docs/governance/qualification-reviewer-taskbook.md（117 行，本轮新增落库）；docs/governance/card-lifecycle.md「评审任务书必须落库（2026-10-30 Round 3 补）」段；本轮 git commit 785e5a2e5（20 文件，18 份回执 + 任务书 + card-lifecycle 修改）；harness 校验 /tmp/r3_calls_final.json 18 calls / 0 problems；子代理失败轨迹 3 例（subagent_43d5f73c4434 tools=6 第 6 次 blocked；subagent_a6a0e7b3026c tools=9 含 2 次 blocked；subagent_b76609ba021f tools=7 含 1 次 blocked）
tags: [subagent, review, qualification, taskbook, context-budget, hard-block]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T12:09:16.873069+08:00"
updated_at: "2026-10-30T12:09:16.873069+08:00"
supersedes: [EXPERIENCE-20261030-子代理上下文耗尽-任务书必须同时约束-读什么-与-读多少, EXPERIENCE-20261028-委派审查子代理必须限制输出体量-否则子会话触发上下文预检失败且无回执]
---