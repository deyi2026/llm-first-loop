---
title: "RULE-AI-28 push 闸的\"同一目标\"约束：复合命令必被拒，逐字单命令放行"
scenario: RULE-AI-28 门禁下的 git push：已取得 review_admission git_push PASS 资格后，执行时把 push 与后续核验命令拼成复合命令
root_cause: ""
solution: execute_command 必须逐字使用与 review_admission 审查目标完全一致的单条命令；SHA 核验、ls-remote、gh pr create 等后续动作拆成独立命令执行。审查回执的 qualification=PASS（含 candidate_sha256 匹配）才是放行凭据；闸门行内 unverified_verdict_text 观测线索是通用告警，不作为结论。
evidence: "evidence://v1/bd9a08f40423d83071ffb05f4401747a083708b098bb3acdb8d1dc1ddb23fba4（拆分后逐字同命令 push 成功回执，21:18:41）；阻断回执（21:18:35 前后，[状态: blocked] compound_protected_shell_requires_split_commands，动作未执行）见本轮对话工具记录；随后同命令重试 success。两者对比构成 verified 因果链。"
tags: [rule-ai-28, git-push, review-admission, gate, command-fingerprint]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-22T21:21:28.120954+08:00"
updated_at: "2026-10-22T21:21:28.120954+08:00"
supersedes: [EXPERIENCE-20261021-rule-ai-28-审查门-192kb-材料上限下的拆分推送与结论格式雷-2026-10-21-实]
---

现象：execute_command 执行 git push 时报 [RULE-AI-28 Host准入阻断] compound_protected_shell_requires_split_commands。根因：闸门把命令整体哈希绑定到审查目标；在已通过审查的 "git push lfl <branch>" 后用 && 拼接 ls-remote 核验，命令字符串不再与 review_admission 冻结的 command 逐字一致，被判为不同目标。修复：核验/后续动作拆独立命令，execute 逐字复用审查通过的那条命令（21:18:41 拆分后同命令成功放行）。另一噪音：闸门回执中 unverified_verdict_text=REVISE 是对历史文本线索的通用未核验告警，不代表本次审查结论；有效凭据只能是 review_admission(action=status) 回执的 qualification=PASS + candidate_sha256 一致。适用：任何走 RULE-AI-28（full_test/git_push/article_publish）门禁的执行；测试副产物（reports/*.json）push 前建议 git checkout -- . 恢复干净树再冻结审查。