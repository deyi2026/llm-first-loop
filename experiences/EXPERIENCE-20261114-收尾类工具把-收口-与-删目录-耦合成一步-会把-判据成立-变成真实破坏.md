---
title: 收尾类工具把「收口」与「删目录」耦合成一步，会把「判据成立」变成真实破坏
scenario: "实现 lane_reap（lane 生命周期收尾）时，我把「收口（close_if_live → abandoned）」与「回收工作树（git worktree remove）」实现成同一次工具调用里的连续两步。随后写 RULE-AI-35 实测脚本时，用了真实 lane（lane-a4e7865d）的工作树路径 .worktrees/ci-gate-flaky 作输入，并注入一个返回 \"dead\" 的模拟 liveness 谓词 —— 判据全成立，工具随即收口并真的执行了 git worktree remove，真实工作树目录被删除。"
root_cause: 不可逆动作被默认包含在「判据成立即执行」的一次调用里，且实测脚本直接用真实对象做破坏性分支，两处都缺少显式确认与隔离。
solution: 两处动作层修正：(1) 收口与清理解耦（对应设计书 D2「收口不等于清理」）：lane_reap 默认只收口并在回执给出可粘贴的 git worktree remove 命令；确需自动删除必须同时传 remove_worktree=true 与 confirm=true 双重显式确认，删除失败记 lane.worktree_kept 且不回滚收口。(2) 实测必须用副本对象：账本跑在副本上，所有 lane 的 worktree 字段重定向到临时 git 仓库，真实 lane 路径只做只读探测（git status --porcelain）。事故后果核实：该工作树当时干净、提交 2a0c2502a 与分支引用完好且本就不在 main，故无产物丢失；用 git worktree add 无损重建（HEAD=2a0c2502a、工作区干净、worktree list 登记恢复）。
evidence: 提交 44260c7df（设计书 §11.3 事故记录）；实测证据 docs/design/receipts/P2-r35-20261114.json（6 用例含「未 confirm 不删目录」「删除失败不回滚收口」）；tests/unit/test_lane_reap.py 16 passed；已通过 help_request 705c25a0003f 向其他会话如实披露并说明无损重建。
tags: [lane, lifecycle, irreversible-action, dry-run, rule-ai-35, rule-ai-37, worktree]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-14T15:02:42.523689+08:00"
updated_at: "2026-11-14T15:02:42.523689+08:00"
---