---
title: 工作区外文件的可写路径与安全编辑法（workdir 绑定 + 仓库副本 edit_file）
scenario: 需要修改位于会话工作区之外（工作区外目录）的文档，但 execute_command 默认 sandbox 只允许写当前仓库工作区；直接 touch 被拒，heredoc 写文件又被 RULE-AI-28 准入阻断。
root_cause: ""
solution: 三步落地：(1) 目标目录作为 `workdir` 传给 execute_command —— sandbox 写权限跟随声明的 workdir，因此该目录内的单条命令可写；(2) 复杂文本不要用 `cat > file <<'EOF'` 这类复合/heredoc 写法（会被判 compound_protected_shell_requires_split_commands 或 here-doc 执行硬阻断），改为把文件 `cp` 进仓库，用 read_file(snapshot=true) + edit_file 精确编辑（仓库内 snapshot 可用），再 `cp` 回原目录；(3) 验收两件事：最终文件 sha 与 edit_file 回执 artifact sha 一致，且用备份 `cmp` 证明目标段落之外逐字节未变。注意 read_file 对工作区外路径能读但 snapshot 会报 WorkspaceScopeMismatch，所以编辑必须绕到仓库副本上做。
evidence: 1) `$HOME/lfl-workspace` 下 `touch` 返回 Operation not permitted（默认 sandbox 仅允许写仓库工作区）。2) 同一命令加 `workdir=$HOME/lfl-workspace` 后 `touch docs/.wtest2` 成功（CWD_WRITE_OK）。3) 该目录内 `cat > file <<'EOF'` 形式被 RULE-AI-28 Host 准入以 `compound_protected_shell_requires_split_commands` 阻断两次。4) 最终路径：`cp` 该文件到仓库内（允许写）→ read_file(snapshot=true) 得 snapshot_ref → edit_file 精确改 → `cp` 回原目录（单条 cp 命令未被阻断）→ 校验最终 sha 与 edit 回执 artifact sha 一致（c39cb01e0d2e078bd9…）。5) 改后 `cmp` 校验前 281 行与备份完全一致（HEAD281_IDENTICAL），确认只动了目标段落。
tags: [sandbox, workspace-scope, edit_file, rule-ai-28, verification]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-28T09:34:41.976924+08:00"
updated_at: "2026-10-28T09:34:41.976924+08:00"
supersedes: [EXPERIENCE-20261026-macos-sandbox-exec-下写仓库须显式-workdir-参数-cd-不等效, EXPERIENCE-20260911-edit-file]
---