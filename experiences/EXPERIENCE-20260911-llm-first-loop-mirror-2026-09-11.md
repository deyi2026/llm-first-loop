---
title: "[已验证事实] llm-first-loop-mirror 是当前本地主仓（2026-09-11 核验）"
scenario: 在 last_verified_at 对应核验窗口内，会话需要在本机操作 llm-first-loop 仓库：找主仓、fetch/push、gc、prune、删除目录、恢复备份，或看到 mainrepo/lfl/origin remote 时。
root_cause: 原主仓目录被移除后，镜像仓吸收了主仓角色并挂载了全部 worktree，但 mainrepo remote 仍指死路径，导致跨会话容易误判拓扑（以为镜像是可删副本）。
solution: |
  事实声明（2026-09-11 核验；后续高影响操作须重新核当前 git/runtime）：
  1. /Users/yyj/Project/llm-first-loop-mirror 是唯一的本地主仓与 master object store（.git 在此）。
  2. 原 /Users/yyj/Project/llm-first-loop 已不存在。所有仓库/工作目录中的 mainrepo remote 原指向该死路径，已于 2026-09-11 统一修正为镜像自身（共享 config，一处生效）。
  3. 其余全部"看起来像克隆"的目录都是镜像的 git worktree，对象库共享 mirror/.git：
     - /Users/yyj/Project/{lfl-method-learning-v1, lfl-model-protocol-continuity, lfl-r9-refactor, lfl-tool-working-set-wip}
     - /Users/yyj/Project/research/{integration-s1-truncation-continuity, research-truncation-continuity, s1-producer-research}
     - mirror/.worktrees/*（含 cache-contract-fix、ci-rg-fallback-20260910、convergence-disposition-revision-20260910 等）
     - /private/tmp/lfl-* 及大量 detached 调试 worktree（部分 prunable）
  4. 远端语义：lfl = 正式远端 github.com/deyi2026/llm-first-loop（push 认证在 LFL shell 环境可用，2026-09-11 已实测 push 成功）；origin = legacy 仓，勿推。
  5. 推论与禁令：在当前拓扑仍成立时不可删除/移动/重命名 llm-first-loop-mirror（删它=删全部 worktree 的对象库）；执行高影响操作前须重新核 git worktree list/remotes；对 mirror/.git 做 gc/prune 前必须先核对 git worktree list；/Users/yyj/Project/backups/lfl-salvage 是私有恢复证据，永不入仓/上传。
evidence: 2026-09-11 实测：git worktree list（mirror 为主，60+ worktree）；lfl-method-learning-v1/.git 为文件指向 mirror/.git/worktrees/*；ls /Users/yyj/Project/llm-first-loop → No such file or directory；git remote set-url mainrepo 后 worktree 侧 get-url 已返回镜像路径；push lfl docs/convergence-disposition-revision-20260910@31f9c81 成功且 ls-remote 精确匹配。
tags: [declaration, repo-topology, llm-first-loop, main-repo, git-worktree, critical, do-not-delete, remotes]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-11T02:18:25.096916+08:00"
updated_at: "2026-09-11T19:33:32.133104+08:00"
last_verified_at: "2026-09-11T19:33:32.133104+08:00"
---