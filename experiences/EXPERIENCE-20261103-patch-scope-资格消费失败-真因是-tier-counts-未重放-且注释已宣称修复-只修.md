---
title: patch-scope 资格消费失败：真因是 tier_counts 未重放，且注释已宣称修复（只修了一半）
scenario: 排查「review_admission 发出的 PASS 资格无法被 check_shell 消费」类缺陷时：代码注释已标注 EVO-20261102-scope-consume 修复（重放 scope_paths），容易据此认为问题已解决。实际消费侧只重放了 scope_paths，未重放冻结时的 tier_counts（切片外绑定计数），该值参与 identity sha。
root_cause: ""
solution: |
  诊断次序（可复用）：
  1) 不要只看注释声称的修复范围，直接对比「冻结侧写入的全部 identity 输入」与「消费侧重放的输入」两张清单，差集即可疑点。
  2) 用最小探针做单变量归因：同一 repo/切片，仅切换可疑入参（tier_counts=None vs 冻结值），比对 _target 产出的 sha 是否等于签发的 candidate_sha256。等于→钉死因果。
  3) 同时跑对照组（该输入为 0 的情形），确认缺陷只在特定条件下触发，避免把「条件性误拒」误报为「恒不可用」——本轮即由此修正了先前表述。
  4) 检查既有回归测试是否只覆盖了「输入为 0」的分支（本例两个 consumable 测试都恰好切片外=0）。
  修复方向：消费侧返回并重放 row.bound_unreviewed_tracked/untracked（_scope_header_fields 已把 None 与 (0,0) 视同，故 tree scope 不受影响）。
  
  当前性验证（在仓库根执行）：
  1) `grep -n '_pending_scopes' src/llm_loop/tools/review_host_admission.py` —— 若其返回项仍为二元组 (scope_paths, out_scope_digest)、且 check_shell 的 `_target(...)` 调用没有 `tier_counts=` 参数，则缺陷仍在；
  2) 复现：按本卡构造「切片外 untracked=1 + paths=['example.py'] + start→PASS→check_shell」，若 allowed=False 即复现。
evidence: |
  实测探针（HEAD 6665c1a4f，uv run）：
  - 切片外=0：start(PASS)→check_shell allowed=True
  - 切片外=1 untracked：start(PASS)→check_shell allowed=False
  - 归因（同 repo/切片）：_target tier=None → 3ffa88ba…（≠签发 f7bd5ebb…）；tier=(0,1) → f7bd5ebb…（==签发）
  代码：_freeze_record 写 bound_unreviewed_tracked/untracked（约 3409-3410）；check_shell 重算未传 tier_counts（约 4399-4403）；_pending_scopes 不返回 tier（约 4438-4461）。
  演进建议：EVO-20261103-0de3bd57
tags: [review_admission, scope=patch, identity-sha, 冻结输入重放, 最小复现归因, 条件性缺陷]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-03T16:02:58.290197+08:00"
updated_at: "2026-11-03T16:02:58.290197+08:00"
---