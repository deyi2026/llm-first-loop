---
title: 多 contextvar 挂载 + 多提前返回路径：set 之后的所有 return 必须经 finally
scenario: "函数在当前线程挂载多个 contextvar/资源（scope token、worktree lease、fleet 拓扑），且存在多条\"机械边界拒绝→提前 return refused\"路径（白名单越域、prepare 失败、lease 失败）"
root_cause: 资源挂载点与提前返回点数量不匹配：N 个 contextvar/资源 × M 条提前返回路径，手工保证配对在改动中极易遗漏；单测又只覆盖成功路径的恢复断言
solution: "写代码时先把\"挂起点之后的一切\"包进单一 try/finally，finally 里统一 reset/释放/幂等清理，再往 try 内填业务逻辑；测试必须为每条提前返回路径断言 contextvar/资源复位（成功路径的复位断言不够）。R28 独立审查对此类缺陷有效，值得在涉及 contextvar 的 PR 上常规启用"
evidence: R28 审查记录 P1-1/P2-3（child subagent_f71a5618000f，verdict REVISE）；修复后全量门禁 PASS（candidate_sha256=d679a2596fb807a7de2708a61bf566b666d15d675e74ac8ccc5520f469789a03）；回归测试 test_run_sync_scope_not_leaked_on_prepare_refusal / test_run_sync_scope_not_leaked_on_fleet_refusal（commit fef342164）
tags: [contextvar, resource-lifecycle, early-return, code-review, subagent-runner]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-16T21:10:24.778346+08:00"
updated_at: "2026-10-16T21:10:24.778346+08:00"
---

在 SubAgentRunner.run() 同步路径接入 fs_isolation 时，把 current_tool_discovery_scope.set() 放在 prepare_worktree/fleet lease 检查之前，而这两处拒绝分支直接 return——独立审查（R28）抓到 P1：父线程 scope 被永久污染（后续工具发现收窄、伪"超出父执行域"拒绝）。同类问题：prepare 只捕 WorktreeIsolationError，OSError 逃逸导致 _finalize_child 不执行、sid 泄漏在拓扑。修复：_reserve_child 之后全部主体收进单一 try/finally，finally 统一做 contextvar reset + worktree 兜底释放 + 幂等 finalize；机械准备段 except Exception 也转 refused。

当前性验证：grep -n "杜绝拒绝路径的 scope 泄漏" src/llm_loop/subagent/runner.py 应命中 run() 注释段；grep -n "test_run_sync_scope_not_leaked_on_prepare_refusal" tests/unit/test_worktree_isolation.py 应命中；python3 -m pytest tests/unit/test_worktree_isolation.py -q 应全绿。若 run() 主体已重构（如拆分 helper），以 grep 确认拒绝路径仍经统一 finally，否则本卡仅作历史参考。