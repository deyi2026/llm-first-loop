---
title: 删分支前必读治理分组登记 + 检查 worktree 活进程
scenario: "删除分支前需要识别\"不应删除\"的分支：治理文档登记保留组、含活进程的 worktree 分支"
root_cause: ""
solution: 删前读治理文档分组登记建白名单 + 检查 worktree 活进程占用 + 用 patch-id 口径 + 先打 bundle
evidence: "docs/governance/branch-triage-20261017.md 明确登记 feat/harmonyos-native-agent-poc-20261011 属 D 组保留；该分支误删后从 patch-merged-25-branches.bundle 恢复，local SHA f5a7913525efe9141d806ce0887d58753d3cf6e7 与 bundle list-heads 一致。活进程证据：lsof -p 18323 显示 cwd 仍指向 .worktrees/cli-t08-terminal-closure-20261019；归档 runtime-data/feat__cli-t08-terminal-closure-20261019.tar.gz 与 fix__cli-ime-explicit-send-20261019.tar.gz 各 11M，条目 30/19。evidence://v1/c3d10bed3abd7837487e422945576f6bae87e49573345d880acd3b4ae6959250, evidence://v1/26927481c4da5675dca8cf5ebc2241a0394dda7a1f42a4e1f3, evidence://v1/3b140af4314711fb9486b840e2c1acd0f1bbff6cd716100d2af43b5c6ffb711e, evidence://v1/69ee4884ec342f3f4c2d6d6d3abb9f7de526f65d36e59b4606264c8de32d1"
tags: [git, branch-cleanup, governance, worktree, lesson]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-21T22:54:08.101591+08:00"
updated_at: "2026-10-21T22:54:08.101591+08:00"
---

问题：删分支时"已合入"的口径只看 git branch --merged 会误删。删除前必须读仓库治理文档的分组登记。
本次实例：docs/governance/branch-triage-20261017.md 把 feat/harmonyos-native-agent-poc-20261011 登记为 D 组「长期实验现场，保留」，
但它拓扑上已合入 main，被机械口径判为可删 → 误删。已从 bundle 恢复。

另一类误删来源：worktree 中有活进程的分支。
本次实例：feat/cli-t08-terminal-closure-20261019（探针进程仍在跑）、fix/cli-ime-explicit-send-20261019（用户交互 shell cwd 在其中），
其 worktree 目录被删但分支内容既不在 main 也不在 bundle。事后判定：两分支的未提交内容已由 runtime-data tar 保全，
且 patch 所含改动经逐行比对确认已在 main（仅类型标注写法差异），故无真实损失——但这是运气，不是流程保证。

正确流程：
1. 删之前先读 docs/governance/ 与 triage/ 文档，提取所有「保留/长期实验/勿删」分组，列入白名单。
2. `git worktree list --porcelain` + `lsof` 检查是否有活进程占用 worktree；有活进程的分支一律不删，或先停进程。
3. 判定口径用 patch-id（git cherry），不只用拓扑。
4. 删除前对全部待删集打 bundle 并 `git bundle verify`。