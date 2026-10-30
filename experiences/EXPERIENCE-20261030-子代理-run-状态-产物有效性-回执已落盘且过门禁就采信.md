---
title: 子代理 run 状态 ≠ 产物有效性：回执已落盘且过门禁就采信
scenario: 独立评审子代理在写完回执文件之后触发上下文预检，以 failed 收尾；是否要重试？
root_cause: ""
solution: 以产物真值判定，不以 run 状态判定：先跑 harness verdict 看 problems，再把落库回执与 harness 调用清单逐字回验（note/evidence_refs/四字段）；两者都通过 ⇒ 采信产物、照常落库流转。**不得重试评审**：重试会产出同卡第二份回执，门禁以 duplicate_verdict_for_ref 拒收合并，且两版结论可能不一致。run 状态只是过程信号。
evidence: Round 4 C 批（child_id subagent_43dbb308916b）：child_state=failed、child_outcome=failed，失败信息为「模型输入接近实际窗口…拒绝静默截断」；但其 4 条回执文件已落盘，harness verdict problems=0、call_count=4，逐字回验 note/evidence_refs/verdict/promotion 全等且无重复行，随后 4 张正常流转（1 张 qualify）。
tags: [子代理, 独立评审, 回执, 双写]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T13:18:54.837477+08:00"
updated_at: "2026-10-30T13:18:54.837477+08:00"
---