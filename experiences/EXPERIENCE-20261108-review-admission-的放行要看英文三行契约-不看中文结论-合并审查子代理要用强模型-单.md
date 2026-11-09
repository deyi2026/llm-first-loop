---
title: review_admission 的放行要看英文三行契约，不看中文结论；合并审查子代理要用强模型+单命令取证
scenario: "用 review_admission 发起 full_test 审查，审查员正文结论明明是\"通过 P0=0 P1=0\"，但 status 返回 qualification=REVISE（review_verdict_incomplete_or_not_pass），无法放行；另外用 spawn_subagent 做长 diff 合并审查时，子代理多次撞 max_rounds 被截断。"
root_cause: "review_admission 的放行资格由程序解析回执末尾的契约行（VERDICT/P0-P1-P2/FINGERPRINT），不认自然语言结论；中文\"结论：通过\"虽然语义正确，但解析器不识别，于是判 REVISE。同时审查子代理在长 diff 上容易无边界探索，小模型会耗尽轮次而不产出结论。"
solution: |
  1) 拿到 REVISE 先看 review_report_path 正文：若是格式问题，用 review_admission(action=start, previous_child_id=<上次child>) 重发窄复审，并在 target_name 里点明"请给规范三行契约"。2) 契约三行必须是英文：`VERDICT: PASS` / `P0=<n> P1=<n> P2=<n>` / `FINGERPRINT: <candidate 指纹前缀>`；中文"通过"不算。3) 合并审查用 spawn_subagent 时：指定 model=glm-5.3、max_rounds 给足，且把取证压成"一条 shell 命令 + 5 个是/否问题"，不要让子代理自由探索；deepseek-v4-flash 在长 diff 上会反复 read_evidence 耗尽轮次。4) 若仍截断，换更强模型重开，不要复用已耗尽 followup 预算的 child。
  当前性验证：`grep -rn "review_verdict_incomplete_or_not_pass" --include=*.py src/` 应命中 review_host_admission.py 且附近有 PASS 契约解析；`review_admission(action=status, child_id=<id>)` 的 qualification 字段应为 PASS 才可提交。
evidence: "第一轮审查报告正文写\"结论：通过 P0=0 P1=0 P2=5\" → host 返回 qualification=REVISE / reason=review_verdict_incomplete_or_not_pass；重发并输出 \"VERDICT: PASS / P0=0 P1=0 P2=5 / FINGERPRINT: b1a9...\" 后 status 返回 qualification=PASS。审查实现内有 _qualifying_pass_p2 逻辑与\"localized labels INVALID\"说明。"
tags: [review-admission, merge-gate, subagent, contract-format]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-08T21:29:31.227505+08:00"
updated_at: "2026-11-08T21:29:31.227505+08:00"
supersedes: [EXPERIENCE-20261105-review-admission-判-revise-但评审员正文写-pass-先逐字符核-candi]
---