---
title: claim 层：过期不等于失权，用 generation 做唯一 fencing 判据
scenario: "给 append-only 任务账本加执行权（claim）层时，需要决定\"租约过期\"与\"失权\"的关系：过期是否应直接拒绝写入"
root_cause: ""
solution: |
  把过期当作派生态而非失权态。唯一的安全失效判据是 fencing generation（claim_id + generation）：1) token 的 generation 落后/claim_id 已换（被接管）→ 拒绝 claim_generation_stale；2) state ∈ released/revoked → 拒绝；3) 仅过期但 generation 仍匹配 → 放行写入并顺带续期，回执标 claim_expired_renewed / renewed_after_expiry。理由：时间不承担安全职责，僵尸问题已由 generation 挡住；若把过期当失权，长任务跨过一次 TTL 的正常写入会无故失败。配套：续期用 max(now, last_renewed) 做单调化，避免时钟回拨把租约截短。
  
  当前性验证：跑 `pytest tests/test_task_claim.py -q -k "expired or stale or released"` 应得 4 passed；再 `grep -n "claim_generation_stale" src/llm_loop/introspection/task_claim.py` 确认判据仍在 _check 内（若已改名为其他 code，以当前实现为准重新核对）。
evidence: "tests/test_task_claim.py::test_expired_but_not_taken_over_write_succeeds_and_renews（过期+generation 匹配 → 写入成功并续期）、::test_stale_token_is_refused_after_takeover（接管后旧 token → claim_generation_stale）、::test_write_after_release_is_refused（released → claim_released）；本轮 31+3+3 条测试实测通过"
tags: [claim, fencing, lease, 过期语义, append-only]
source: {}
status: invalid
record_kind: experience
verification_state: verified
created_at: "2026-11-03T21:08:41.366407+08:00"
updated_at: "2026-11-03T21:08:58.137807+08:00"
---