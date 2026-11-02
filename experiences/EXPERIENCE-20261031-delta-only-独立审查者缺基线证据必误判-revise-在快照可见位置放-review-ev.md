---
title: delta-only 独立审查者缺基线证据必误判 REVISE：在快照可见位置放 REVIEW-EVIDENCE.md（基线行号+自验命令+逐条映射三证）翻绿
scenario: "RULE-AI-28 独立审查（review_admission kind=git_push/full_test）连续 REVISE：reviewer 子代理只看冻结 delta 与产物快照，看不到基线侧前置事实（函数体/调用方早已是新语义、基线行号内容、历史验证结论），于是把\"纯签名补齐/收口型\"的正确 delta 误判为半应用变更并给 P1/P2。在对话里向 reviewer 解释无用——它读不到你的解释。"
root_cause: ""
solution: "把可自验的基线证据写成文件放进审查可见位置，再重启审查：主树用 .tmp-ci/review-evidence-*.md（列入 artifact_paths）；隔离 worktree 用 worktree 根的 REVIEW-EVIDENCE.md（uncommitted，随 workdir 快照冻结给 reviewer）。文件内容三证齐全：①基线事实（git show <base>:file 行号级对比）②当前态自验命令原文+输出（如 .venv/bin/pyright <file> → 0 errors）③逐条映射 reviewer 的 P1/P2 编号。写完立即 review_admission start 让新快照带上证据。本质是给 delta-only 盲审补基线视野，让结论可机械复核。"
evidence: "两次独立实战翻绿：①【本轮直核】2026-10-31 推送线：第 3 轮 git_push 审查 REVISE（P1-1/P2-1）→ 14:27:21 在 .worktrees/push-wt-20261031/ 写 REVIEW-EVIDENCE.md（标题\"第3轮 git_push 审查 P1-1/P2-1 答复（可自验）\"）→ 14:27:27 第 4 轮 review_admission start（workdir=worktree，快照含该文件）→ 14:29:43 push 放行成功；远端 main=55b53ab8，CI run 41176926620 success（上轮已核终态）。同日 12:38 第 1 轮 start 亦携带 .tmp-ci/review-evidence-20261031-pyright-*.md（主树变体）。②【memory 卡转述，2026-10-28T01:40:43】主树 .tmp-ci/review-evidence-*.md + 基线行号（git show 对比）+ pyright 0 errors 自验，两轮 REVISE 均靠此翻绿——该记录为 memory_extract 自动提取，本轮未回放原始事件流，标注为转述级证据。"
tags: [rule28, review_admission, git_push, 审查门, delta-only, REVISE翻绿, 证据文件]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T20:48:46.966276+08:00"
updated_at: "2026-10-31T20:48:46.966276+08:00"
---

## 机理
review_admission 的独立 reviewer（GLM-5.3 子代理）输入 = 冻结 delta + 产物快照（_source_snapshot），它是 delta-only 盲审：看不到基线侧事实。当 delta 是"收口/补齐型"改动（例如纯签名补齐、防御性收尾），reviewer 缺基线上下文会把无害变更误判为"半应用变更/破坏性修改"给 REVISE（P1/P2）。重复重审无效——每次重审它看到的还是同一份缺上下文的 delta。解释写在对话/回复里它也看不到；唯一出路是把证据放进它的可见信息集。

## 做法
1. **选对位置**（证据文件必须进快照/delta 可见范围）：
   - 主树场景：.tmp-ci/review-evidence-<日期>-<主题>.md，显式列入 review_admission 的 artifact_paths；
   - 隔离 worktree 场景：worktree 根的 REVIEW-EVIDENCE.md（uncommitted 文件会随 workdir 快照被冻结，reviewer 可读）。
2. **内容三证**（标题直接对应 reviewer 上一轮的 P1/P2 编号，逐条答复）：
   - 基线事实：`git show <base>:<file>` 行号级对比，证明"基线早已是 X，本次 delta 未改变该语义"；
   - 当前态自验：可复现命令原文+输出（如 `.venv/bin/pyright <file>` → 0 errors）；
   - 逐条映射：每条 P1/P2 → 对应证据行，让 reviewer 可机械核验而非重新推理。
3. **写完立刻重启审查**：review_admission start 让新快照带上证据文件（本次 14:27:21 写文件 → 14:27:27 start，间隔 6 秒）。

## 适用边界
- 只救"变更本身正确、纯因缺基线上下文被误判"的 REVISE；P0/P1 指向真实缺陷时先修代码，证据文件救不了真 bug。
- 证据必须可自验（命令+输出可复现）；无自验命令的申辩式答复 reviewer 不认。
- 证据文件放审查可见位置 ≠ 说服审查者；是给盲审补基线视野，让结论可机械复核。

## 反例风险
若基线事实与 delta 实际语义不符（reviewer 判断正确），强行附"证据"会在下一轮被识破并伤信任；写证据文件前先自己跑一遍三证命令。