---
title: 死 owner 会话的 goal 收口：跨会话死锁的审计脚本迁移模式（真实 verifier 验证字段）
scenario: 需要收口属于已死亡会话的 goal（owner 数十天未活动，任务图有 open task 且部分 evidence_required=True）
root_cause: ""
solution: scripts/oneoff/supersede_learning_cluster_tasks_20261105_v2.py 模式 + 正规 cross_session goal 门收尾
evidence: 台账对账 active 76→63 / complete 161→174（D 9 个 + unclear 4 个全部落账）；verifier 实测 verified digest 44672323…；备份 .tmp-ci/ledger-backup-20261105-late/ 9 份；审计脚本 commit 7397ce4fa + 1ed1d9339；失败反例：claim_task 同样拒绝、goal 门对 open task 拒绝（in_progress=1）、doc 路径作 evidence_refs 报 unsupported_ref。
tags: [goal-lifecycle, cross-session, evidence-verification, ledger-migration]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-06T00:41:23.920494+08:00"
updated_at: "2026-11-06T00:41:23.920494+08:00"
---

死 owner 会话的 goal 收口：先测通道（task_update/claim_task 会被 cross_session_write_denied 拒；goal 门要求任务图先收口且对 cancelled+evidence_required 同样要求 evidence_verification_status=="verified"，而该字段仅 →done 时由 TaskStore 置位）→ 确认死锁后走受控迁移：备份台账 → 落盘一次性脚本 → 脚本内 import 运行时 TaskEvidenceVerifier 真实验证（owner 从 evidence ledger 的 ref_index/<sha[:2]>/<sha>.json → owner_key → owners/<key>/owner.json 解出；勿全库 rglob——evidence ledger 很大会超时）→ 把验证器报告的 status/checked_at/refs_digest 原样写进终态记录（cancelled + evidence_required=True 时必须带这三个字段，缺一不可）→ goal 用 update_goal(cross_session=true, evidence_refs=[合法 evidence:// ref]) 正规关。evidence ref 必须逐字符精确（抄错一位 → unresolved_or_not_authorized）。data/audit/ 是 gitignored 运行态无需提交；审计脚本与 receipt 应提交留痕。