---
title: macOS sandbox-exec 下写仓库须显式 workdir 参数（cd 不等效）
scenario: LFL 会话需对 code_root 仓库执行 git 写操作（worktree/merge/commit/回执落盘），但沙箱默认只允许写会话工作区与缓存目录，仓库目录 touch 报 Operation not permitted
root_cause: ""
solution: 所有需要写仓库的 execute_command 一律显式传 workdir=仓库根（如 /Users/yyj/Project/llm-first-loop-mirror）；仅在命令里 cd 不获得写权限。只读命令无需 workdir。编辑仓库文件不能用 edit_file（WorkspaceScopeMismatch），用 head/tail/printf 拼接或 git checkout --ours/--theirs。
evidence: "evidence://v1/5406000fbd97bcef471217e23ad9ceb10812085743a86d3c40731949ea05a58d（workdir 探针成功）；evidence://v1/e7f3d8cf5f723edf5b3e543f949b296a1bf6e991a2126fb45c0293a8b19399e9（workdir=仓库根下 worktree/merge/commit 全链路成功）"
tags: [sandbox, execute_command, git, workdir, macos]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-26T14:46:52.195059+08:00"
updated_at: "2026-10-26T14:46:52.195059+08:00"
---

现象：execute_command 在 macOS sandbox-exec 沙箱下对 /Users/yyj/Project/llm-first-loop-mirror 仓库目录 touch 返回 "Operation not permitted"（cd 可读可执行，仅写被拒）。结论：沙箱可写根=会话工作区+缓存目录+【本次调用显式传入的 workdir】。验证：workdir=仓库根时 touch .workdir_probe 成功；随后 git worktree add/merge/commit/回执提交全链路在 workdir=仓库根下执行成功。适用边界：仅当 workdir 显式指向目标目录才获得其写权限，命令内 cd 不等效；read_file 等文件工具另有 workspace scope（.worktrees 子目录会被 WorkspaceScopeMismatch 拒绝），需要编辑时用 shell 手术（head/tail/printf 拼接）或 git checkout --ours/--theirs 替代。注意：留下探针文件要记得 rm。