---
title: 并发会话共享检树：amend 污染他人提交的识别与无损还原
scenario: 共享 git 检树被并发会话切换分支时提交/amend
root_cause: ""
solution: 提交前必查 git branch --show-current 与 git reflog；发现 amend 落到他人提交时，用 reset --soft <对方原提交> + restore 恢复对方分支与工作树，自己的改动改在独立 worktree 的自有分支上提交
evidence: "git reflog（21:29:17 checkout 到 fix/rules-version-wheel-install-20261028，21:29:20 其提交 19758ec79，21:37 本会话 amend 产生 81d14404e）；修复后 `git branch -v` 该分支=19758ec79、本会话分支=3fbd11271→84fcee554"
tags: [git, 并发会话, worktree, commit-amend, 事故修复]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-28T22:22:04.307447+08:00"
updated_at: "2026-10-28T22:22:04.307447+08:00"
---

场景：多会话共用同一检树 /Users/<user>/Project/llm-first-loop-mirror（本会话在 feat/web-model-admin-ship-20261028 上工作，另一会话同时在主编检树切到 fix/rules-version-wheel-install-20261028 并提交）。
事故：本会话未核对 HEAD 分支即执行 `git commit --amend`，把本会话的 provider_routes.py 改动并进了另一会话的提交 19758ec79（amend 后 81d14404e），跨任务污染。
发现：出问题时不要把 HEAD 上的改动再 amend/reset 当作"修自己"，要先看 `git branch --show-current` + `git reflog`，确认提交归属。
修复（可复现）：
1) `git log/reflog` 定位对方原始提交 19758ec79；
2) 先把本会话待提交文件的最终内容另存到工作区临时路径（.tmp-ci/xxx）避免丢失；
3) `git reset --soft <对方原始提交>` + `git restore --source=<对方原始提交> --staged --worktree <被污染文件>`，把对方分支指针与工作树都还原，保留对方未提交的其它改动；
4) 本会话改用独立 worktree（`git worktree add .worktrees/ship-fix feat/...`）在自有分支上 amend，永不在共享检树上 amend；
5) 门禁/部署同样在独立 worktree 里跑与 publish（`service_control publish code_root=<clean worktree>`）。
验证：对方分支 `git branch -v` 回到 19758ec79、`git status` 只剩对方自己的 docs/api.md；本会话分支 tip 为自己的提交且 diff 仅含本任务文件。
适用边界：同一 git 仓库被多个会话/代理并行使用时；单会话独立检树时无效。