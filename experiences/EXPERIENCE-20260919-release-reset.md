---
title: 外部 release reset 抹掉未提交工作区：恢复方法与防御
scenario: 长任务在共享工作区落地大量未提交 src+tests 改动（R0 reclaim authority gate + R1 effect fence，测试全绿）；外部 release 流程（merge PR 后 git reset to lfl/main）在同一秒回滚全部 tracked 文件，未提交改动全部丢失，测试文件因新建（untracked）部分幸存
root_cause: "外部 release 流程对共享工作区做 git reset --hard，与模型工作流的\"完成不落盘即不持久\"假设冲突；且 reset 前无任何通知或 stash"
solution: "1) 幸存的测试文件即完整规格：按断言逐条重建实现（\"测试即规格\"恢复法）；2) 每个绿色里程碑立即 git stash push + stash apply 钉住副本（stash 不受 reset 影响）；3) 恢复后用 sha256 对照编辑回执确认内容一致，再跑定向+全量回归"
evidence: "git reflog HEAD@{0}=14:27:10 reset to lfl/main；store.py mtime 14:26:34 与回滚同秒；tests/unit/test_fleet_reclaim_authority_gate.py 重跑 13/14 FAILED 复现丢失；恢复后 50 项全绿（test_fleet_reclaim_gate + authority_gate + race_and_ttl + effect_fence + renew_and_tool）；stash@{0} 含全部恢复成果"
tags: [workspace-hygiene, external-reset, recovery, fleet, r1-effect-fence]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-19T14:38:41.544814+08:00"
updated_at: "2026-09-19T14:38:41.544814+08:00"
---

时间线：14:26:34 外部 release 流程 `git reset --hard to lfl/main`（reflog: 14:27:10 PR #41 merge）把全部未提交 tracked 文件回滚——R0（上午落地、报告全绿）与 R1（本会话 14:18-14:25 刚完成、测试全绿）同时消失。恢复：R0 store 层实现按 `test_fleet_reclaim_authority_gate.py` 14 项断言逐条重建（rolling renew、expiry fence、force_reclaim 双 CAS+justification 落盘、settle 分层 fence）；R1 的 journal/runner/工具编辑由另一外部进程重放（sha 与编辑回执一致），store 层由本会话手工重建。防御：`git stash push` 留副本后 `git stash apply` 恢复工作区。教训：(1) 该工作区的"不 commit"惯例在 release reset 下必然周期性丢工作，长任务必须在每个绿色里程碑立即 stash/commit；(2) 编辑回执中的 sha256+old/new 文本是唯一可靠恢复源，工具回执即备份。