---
title: Subject-binding 线退役裁决：eval 效能未达标且生产痛点审计为零证据，预置 stop rule 触发
scenario: Subject-binding cue（在 save_experience 工具描述追加 subject 判别提示）研究线：v2 dev PASS（构造 holdout 上 C0 错误率 73%），v3 confirmatory 92-cell 双模型 net_flip=2/17 均未过门槛（EFFICACY_NOT_QUALIFIED）；随后零成本生产价值审计发现 323 条生产 experiences、634 episodes、docs、usage registry 中 0 起 subject 误绑事故、0 可量化损失，可观测决策流 n=9 全 positive，guard 条款 278/631 为蒸馏期第一性书写。
root_cause: 机制研究从构造性难题出发而非生产痛点；且生产 record_use 遥测缺失（n=9/7864 次检索），效能提升在生产中既无法证实也无法度量。
solution: 按预先声明的规则执行：痛点证据不足 → 直接 retire 研究线（≥6 个月），不再烧 v4。教训两条：①机制类研究在进入 confirmatory 前必须先做生产痛点审计（0 provider 成本即可完成），构造性证据（人为 holdout 的 C0 错误率）不能代理生产价值；②reopen 前置条件必须是生产遥测先行（record_use 纳入真实 closeout 回路，目标 n≥100 自然决策 + ≥3 起有量化损失的事故记录），否则即使 eval PASS 也无法证明生产价值。资产冻结于 worktree method-binding-efficacy-v3-20261006（commit 5f0b794f9）。
evidence: "evidence://v1/72a841af5a42496cb50343c911ebb467e7d280b1034459c481e4476529a8e656（92/92+disposition）；审计命令 receipts 15:33-15:35（事故扫描 n=0、decision n=9）；commit 5f0b794f9。"
tags: [method-efficacy, subject-binding, retire-decision, production-value-audit, stop-rule]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-06T15:37:11.350196+08:00"
updated_at: "2026-10-06T15:37:11.350196+08:00"
---

当前性验证：`ls /Users/yyj/Project/llm-first-loop-mirror/.worktrees/method-binding-efficacy-v3-20261006/evals/method_binding_efficacy_v3/confirmatory_provider_v1/status | wc -l` 应得 92；`git -C <worktree> log --oneline -1` 应含 5f0b794f9；若 reopen 提案出现，先核对 PRODUCTION-VALUE-AUDIT.md 的三个前置条件是否满足。