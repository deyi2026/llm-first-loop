# GOAL-20261016-cf563b27 交付报告：P2 批次一「settlement 口径与幂等」

- 交付日期：2026-10-16 10:5x
- 目标：批次一 P-SET-1..7（7 项 P2）+ 顺手项 r1N1，走完 编码→独立审查闸→全量门→推送 全链路
- 规格载体：docs/tasks/P2-pool-knowledge-feedback.md（批次一表 + 验收行）

## 交付物

- commit 1ddcfff77 @ lfl/main（已推送，ls-remote SHA 一致）：11 文件 +1019/−44
  - 产品：settlement.py / experiences/store.py / methods/store.py / factory.py / registry_experience.py
  - 测试：test_settlement_receipts.py / test_settlement_tools.py / test_use_ledger_contract.py
  - 文档：P2 池 + 编码自报告 + 审查回执

## 逐项状态

| ID | 状态 | 锚点 |
|---|---|---|
| P-SET-1 投影去重键补 slot_id | fixed | T2 回执逐项复检 + 碰撞测试 |
| P-SET-2 降级窗口空 session 不抵扣 | fixed | 同上 |
| P-SET-3 experience 回执收集过滤对齐 | fixed | 同上 |
| P-SET-4 method 统计行级 integrity | fixed | 同上 |
| P-SET-5 规则 ref 归一 + supersedes 显式 | fixed | 同上 |
| P-SET-6 ledger 回执按 session 过滤 | fixed | 探针 A6 回归 |
| P-SET-7 跨会话规则查重投影 | fixed | 同上 |
| r1N1 索引修正 [-1]→[0] | fixed | 随批次一 |

## 流水线证据链

1. T1 编码：subagent_c4f24a5a331c（docs/reports/GOAL-20261016-cf563b27-b1-settlement-p2-selfreport.md）
2. T2 独立审查闸：subagent_191c6b090506 PASS，回执 docs/governance/receipts/20261016-cf563b27-b1-settlement-p2-code-review.json（sha256 8ccb2a8c…）
3. T3 全量门：full_test 准入 PASS（candidate 85a33047…）→ scripts/ci_gate.sh exit 0（2026-10-16 09:31；ruff/env-pin/pyright new=0 + tier0 + 全量 pytest；此后工作树未变——staged 文件 mtime ≤09:10，index 与工作树零差异，全量门覆盖即推送产物）
4. T3 推送：git_push 准入 PASS（subagent_b16c415d125f，candidate a3093c33…，冻结指纹=推送内容）→ 推送 lfl main（f7c081282..1ddcfff77）→ ls-remote = 本地 main（字节一致）
5. T4 收口：池状态更新引用具体提交（本文件 + 池 63 行）

## 遗留披露（非本 goal 义务）

- P2 池后续：批次二 6 项（+P-LED-6，P-SET-8 候补）、批次三 3 项、挂账 5 项（P-DEF-4 待用户定夺）
- 工作树存在 untracked src/llm_loop/workspace/worktree_isolation.py（EVO-20261016-ac47e850 他线施工，无引用接线）——不属本批次，未动
- git stash 12 条历史 WIP，与本次交付无关
