---
title: Rule28 git_push 准入被拒的三个真实原因：gate 副作用脏 worktree、并行会话打陈旧产物快照、验证应在一次性干净 worktree 完成
scenario: "push 前按 RULE-AI-28 发起 git_push 准入，连续被拒：先 review_artifact_exceeds_192kb（单提交 54KB 也超），后\"不存在覆盖当前产物的有效资格\"（status 显示 PASS 但执行层不认）。根因有两个：ci_gate 全量段的 WebUI 构建会重写 reports/phase3/m0/*.json 等已跟踪文件，把一次性验证 worktree 弄脏 ~323KB，_source_snapshot 把 uncommitted_delta 计入审查产物超 192KB；主工作区有并行会话在准入冻结后继续改文件（web/__init__.py 等），产物快照随之失效。"
root_cause: ""
solution: "在一次性 /tmp worktree（git worktree add /tmp/lfl-verify-evo-20261021 <SHA>）完成准入与 push：checkout 目标提交 → git restore . 清掉 gate 副作用 → admission start（workdir 指向该 worktree）→ PASS 后立即同命令 push。产物公式下干净 worktree 的 committed delta = diff(merge-base(HEAD,main), HEAD)，HEAD 即 main 时为 0，不受 push 里程（remote..HEAD）大小影响，126 个积压提交也能一次 fast-forward 推送。"
evidence: "admission 拒收回执（review_artifact_exceeds_192kb，两次）+ /tmp worktree git diff --binary HEAD 实测 323,275 字节（reports/phase3/m0/*.json 被测试重写）+ restore 后 admission accepted（subagent_b6241fa58e42 PASS）+ push 回执 9dc08579d..bfe949a53 exit 0 + ls-remote 确认 lfl/main=bfe949a53"
tags: [rule28, review-admission, git-push, worktree, ci-gate, 192kb-cap, concurrent-session]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-21T07:26:45.335096+08:00"
updated_at: "2026-10-21T07:26:45.335096+08:00"
---

> **当前适用性（2026-10-28 复核）**：审查材料上限已是 **2.5M 字符**（超限码 `review_artifact_exceeds_cap`），“单提交 54KB 也超 192KB”不再是有效理由；本例 323KB 的 gate 副作用脏树现在也远在限内。仍然成立、且与上限无关的两条更重要：① 准入资格绑定“当前产物”快照，并行会话写入会让资格失效；② 一次性干净 worktree + PASS 后立即同命令 push 仍是最稳做法（避免竞争，不是为了压体积）；③ ci_gate 重写 reports/ 的副作用仍需在验证 worktree 里 restore。

Rule28 git_push/full_test 准入产物 = _source_snapshot(workdir)：merge-base(HEAD, 本地main)..HEAD 的 committed diff + 未提交 tracked 改动 + untracked 全文（≤40 个文件），合计硬上限 192KB。三个坑：① ci_gate 全量段会用测试重写已跟踪文件（reports/phase3/m0/*.json），在验证 worktree 里留下 ~320KB 脏改动，直接顶爆 git_push 准入；② 主工作区有并行会话持续写入时，准入冻结的产物快照会被对方新改动打陈旧（内存资格对"当前产物"绑定，status 仍显 PASS 但执行层拒绝）；③ 纯净一次性 worktree（git worktree add /tmp/xxx <SHA>）产物≈0 且无人竞争，是发起准入与执行 push 的首选位置。流程：checkout 目标提交→restore . 清副作用→admission start→PASS 后立刻 push（资格一次性）。另：ruff I001 要求注释块+import 前留空行成组。